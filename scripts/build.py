#!/usr/bin/env python3
"""构建 Shadowrocket 配置。

数据流：
  1. 下载 Johnshall 的 sr_top500_banlist_ad.conf（黑名单 + 去广告 + top500 方向）；
  2. 把“微信小程序/微信广告拦截”规则插到最前面；
  3. 把“微信核心域名直连”规则插到广告规则后面；
  4. 上游规则全部后移，并删掉会覆盖微信直连/广告拦截的冲突项；
  5. 去重、做安全的后缀合并，生成 dist/ 下的文件。

只使用 Python 标准库。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from rulekit import (  # noqa: E402
    Rule,
    count_policies,
    covered_by,
    dedupe_rules,
    filter_upstream,
    load_domain_list,
    load_rules,
    optimize_rules,
    parse_rules,
)

UPSTREAM_REPO = "Johnshall/Shadowrocket-ADBlock-Rules-Forever"
UPSTREAM_BRANCH = "release"
UPSTREAM_FILE = "sr_top500_banlist_ad.conf"
UPSTREAM_URLS = [
    f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/{UPSTREAM_BRANCH}/{UPSTREAM_FILE}",
    f"https://cdn.jsdelivr.net/gh/{UPSTREAM_REPO}@{UPSTREAM_BRANCH}/{UPSTREAM_FILE}",
    f"https://johnshall.github.io/Shadowrocket-ADBlock-Rules-Forever/{UPSTREAM_FILE}",
]

CST = timezone(timedelta(hours=8))
CACHE_FILE = ROOT / ".cache" / "upstream.conf"
MIN_UPSTREAM_BYTES = 500_000


class BuildError(RuntimeError):
    pass


def now_cst() -> datetime:
    return datetime.now(tz=CST)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def log(message: str) -> None:
    print(message, flush=True)


def fetch_url(url: str, timeout: int = 90) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "shadowrocket-wechat-rules/1.0 (+https://github.com/)",
            "Accept": "text/plain,*/*",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    text = data.decode("utf-8-sig", errors="replace")
    if len(data) < MIN_UPSTREAM_BYTES:
        raise BuildError(f"下载内容过小（{len(data)} 字节）: {url}")
    if "[Rule]" not in text or "FINAL" not in text:
        raise BuildError(f"下载内容不像 Shadowrocket 配置: {url}")
    return text


def read_upstream_source(source: str | None, *, allow_stale: bool) -> tuple[str, str]:
    """返回 (配置文本, 来源说明)。"""
    if source:
        path = Path(source).expanduser()
        if path.exists():
            text = path.read_text(encoding="utf-8-sig")
            if len(text.encode("utf-8")) < MIN_UPSTREAM_BYTES:
                raise BuildError(f"本地上游文件过小: {path}")
            return text, f"local:{path}"
        if not source.startswith(("http://", "https://")):
            raise BuildError(f"本地上游文件不存在: {source}")

    urls = [source] if source and source.startswith(("http://", "https://")) else UPSTREAM_URLS
    errors: list[str] = []
    for url in urls:
        for attempt in range(1, 4):
            try:
                log(f"  下载上游（第 {attempt} 次）: {url}")
                text = fetch_url(url)
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                CACHE_FILE.write_text(text, encoding="utf-8")
                return text, url
            except Exception as exc:  # noqa: BLE001 - 需要把所有网络异常汇总后重试
                errors.append(f"{url} -> {exc}")
                if attempt < 3:
                    time.sleep(2 * attempt)

    if allow_stale and CACHE_FILE.exists():
        text = CACHE_FILE.read_text(encoding="utf-8")
        log("  ! 所有上游地址都失败，使用本地缓存（--allow-stale）")
        return text, f"cache:{CACHE_FILE}"

    raise BuildError("无法下载上游规则：\n" + "\n".join(errors[-6:]))


def extract_section(text: str, section: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip().lower() == f"[{section.lower()}]":
            start = index + 1
            break
    if start is None:
        raise BuildError(f"上游配置缺少 [{section}]")

    output: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            break
        output.append(line.rstrip())
    return output


def extract_build_time(text: str) -> str:
    match = re.search(r"^#\s*build time:\s*(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else "unknown"


def parse_upstream_rules(text: str, min_rules: int = 50_000) -> list[Rule]:
    lines = extract_section(text, "Rule")
    rules, errors = parse_rules(lines)
    if errors:
        preview = "\n".join(errors[:8])
        raise BuildError(f"上游有 {len(errors)} 条规则无法解析：\n{preview}")
    if len(rules) < min_rules:
        raise BuildError(f"上游规则数量异常（{len(rules)} 条），拒绝生成")
    return rules


def prepare_injected() -> tuple[list[Rule], list[Rule], list[str]]:
    ad_path = ROOT / "config" / "wechat-ad.list"
    direct_path = ROOT / "config" / "wechat-direct.list"
    whitelist_path = ROOT / "config" / "whitelist.list"

    ad_rules = dedupe_rules(load_rules(ad_path))
    direct_rules = dedupe_rules(load_rules(direct_path))
    whitelist = load_domain_list(whitelist_path)

    for rule in ad_rules:
        if not rule.is_domain:
            raise BuildError(f"广告规则只允许域名类型: {rule.render()}")
        if rule.policy != "Reject":
            raise BuildError(f"广告规则策略必须是 Reject: {rule.render()}")
    for rule in direct_rules:
        if not rule.is_domain and rule.type not in {"IP-ASN", "IP-CIDR", "IP-CIDR6"}:
            raise BuildError(f"直连规则只允许域名或 IP 类型: {rule.render()}")
        if rule.policy != "DIRECT":
            raise BuildError(f"直连规则策略必须是 DIRECT: {rule.render()}")

    ad_suffixes = [r.value for r in ad_rules if r.type in {"DOMAIN", "DOMAIN-SUFFIX"}]
    filtered_direct: list[Rule] = []
    for rule in direct_rules:
        if rule.type in {"DOMAIN", "DOMAIN-SUFFIX"} and covered_by(rule.value, ad_suffixes):
            log(f"  ! 直连规则与广告规则冲突，已按“广告优先”移除: {rule.render()}")
            continue
        filtered_direct.append(rule)

    if not ad_rules:
        raise BuildError("config/wechat-ad.list 为空")
    if not filtered_direct:
        raise BuildError("config/wechat-direct.list 为空")
    return ad_rules, filtered_direct, whitelist


def build_rules(
    *,
    upstream_text: str,
    ad_rules: Sequence[Rule],
    direct_rules: Sequence[Rule],
    whitelist: Sequence[str],
    min_upstream_rules: int = 50_000,
) -> tuple[list[Rule], dict[str, int]]:
    upstream_rules = parse_upstream_rules(upstream_text, min_rules=min_upstream_rules)

    injected = list(ad_rules) + list(direct_rules)
    reserved = {rule.value_key() for rule in injected}
    ad_suffixes = [r.value for r in ad_rules if r.type in {"DOMAIN", "DOMAIN-SUFFIX"}]
    direct_suffixes = [r.value for r in direct_rules if r.type in {"DOMAIN", "DOMAIN-SUFFIX"}]

    filtered, filter_stats = filter_upstream(
        upstream_rules,
        reserved=reserved,
        ad_suffixes=ad_suffixes,
        direct_suffixes=direct_suffixes,
        whitelist=whitelist,
    )

    combined = injected + filtered
    optimized, optimize_stats = optimize_rules(combined)

    stats = {
        "upstream_rules": len(upstream_rules),
        "injected_ad": len(ad_rules),
        "injected_direct": len(direct_rules),
        "skipped_conflicts": filter_stats.skipped_conflicts,
        "skipped_whitelist": filter_stats.skipped_whitelist,
        "skipped_keywords": filter_stats.skipped_keywords,
        "skipped_unsupported": filter_stats.skipped_unsupported,
        "duplicates_removed": optimize_stats.duplicates,
        "subsumed_removed": optimize_stats.subsumed,
        "final_rules": len(optimized),
        "total_lines": len(optimized) + 1,
    }
    return optimized, stats


def render_config(
    *,
    general_lines: Sequence[str],
    ad_rules: Sequence[Rule],
    direct_rules: Sequence[Rule],
    all_rules: Sequence[Rule],
    build_time: str,
    upstream_source: str,
    generated_at: datetime,
    stats: dict[str, int],
) -> str:
    ad_keys = {rule.value_key() for rule in ad_rules}
    direct_keys = {rule.value_key() for rule in direct_rules}
    ad_kept = [r for r in all_rules if r.value_key() in ad_keys]
    direct_kept = [r for r in all_rules if r.value_key() in direct_keys]
    rest = [r for r in all_rules if r.value_key() not in ad_keys and r.value_key() not in direct_keys]

    lines: list[str] = []
    lines.extend(
        [
            "# ============================================================",
            "# Shadowrocket 规则：Top500 Banlist + 去广告 + 微信直连",
            "# 生成时间： " + generated_at.strftime("%Y-%m-%d %H:%M:%S %z"),
            "# 上游：     " + upstream_source,
            "# 上游构建： " + build_time,
            "# 规则数量： " + str(stats["total_lines"]) + "（含 FINAL）",
            "# 许可：    规则部分改编自 Johnshall（CC BY-SA 4.0），详见 NOTICE.txt",
            "#",
            "# 关键顺序：",
            "#   1. 微信小程序/微信广告域名 -> Reject",
            "#   2. 微信/微信支付/小程序基础服务 -> DIRECT",
            "#   3. 上游 Top500 banlist + 广告规则",
            "#   4. 其余未知流量 -> DIRECT",
            "#",
            "# 本配置不含节点，使用 Shadowrocket 当前选中的节点作为 Proxy 策略。",
            "# 标准版不含 MITM/证书，不需要安装证书。",
            "# ============================================================",
            "",
            "[General]",
        ]
    )
    lines.extend(general_lines)
    lines.extend(["", "[Rule]", ""])

    lines.append("# ── 1. 微信小程序 / 微信广告拦截（必须排在最前）──")
    lines.extend(rule.render() for rule in ad_kept)
    lines.append("")

    lines.append("# ── 2. 微信 / 微信支付 / 小程序基础服务：国内直连 ──")
    lines.extend(rule.render() for rule in direct_kept)
    lines.append("")

    lines.append("# ── 3. Top500 Banlist + 全局去广告（上游规则，已优化）──")
    lines.extend(rule.render() for rule in rest)
    lines.append("")
    lines.append("# ── 4. 其余未知流量直连 ──")
    lines.append("FINAL,DIRECT")
    lines.append("")
    return "\n".join(lines)


def render_list(title: str, rules: Iterable[Rule], generated_at: datetime, note: str) -> str:
    lines = [
        f"# {title}",
        f"# 生成时间：{generated_at.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"# {note}",
        "",
    ]
    lines.extend(rule.render() for rule in rules)
    lines.append("")
    return "\n".join(lines)


def render_module(ad_rules: Sequence[Rule], generated_at: datetime) -> str:
    lines = [
        "#!name=微信小程序 / 微信广告拦截",
        "#!desc=拦截微信广告投放域与广点通 GDT 广告素材；纯域名规则，无需证书。请确保它排在宽泛的 qq.com 直连规则之前。",
        "#!author=shadowrocket-wechat-rules",
        "#!category=去广告",
        f"#!date={generated_at.strftime('%Y-%m-%d')}",
        "",
        "[Rule]",
        "",
    ]
    lines.extend(rule.render() for rule in ad_rules)
    lines.append("")
    return "\n".join(lines)


def render_report(
    *,
    generated_at: datetime,
    upstream_source: str,
    build_time: str,
    stats: dict[str, int],
    policy_counts: dict[str, int],
    ad_rules: Sequence[Rule],
    direct_rules: Sequence[Rule],
) -> str:
    lines = [
        "Shadowrocket 规则构建报告",
        "=" * 40,
        f"生成时间： {generated_at.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"上游来源： {upstream_source}",
        f"上游构建： {build_time}",
        "",
        "规则统计",
        "-" * 40,
        f"上游规则数：       {stats['upstream_rules']}",
        f"注入广告规则：     {stats['injected_ad']}",
        f"注入微信直连规则： {stats['injected_direct']}",
        f"因冲突跳过：       {stats['skipped_conflicts']}",
        f"因白名单跳过：     {stats['skipped_whitelist']}",
        f"删除宽泛关键字：   {stats['skipped_keywords']}",
        f"删除不支持类型：   {stats['skipped_unsupported']}",
        f"删除重复规则：     {stats['duplicates_removed']}",
        f"删除被覆盖规则：   {stats['subsumed_removed']}",
        f"最终规则数：       {stats['total_lines']}（含 FINAL）",
        "",
        "策略分布（不含 FINAL）",
        "-" * 40,
        *[f"{policy}: {count}" for policy, count in sorted(policy_counts.items())],
        "",
        "微信广告拦截规则",
        "-" * 40,
        *[rule.render() for rule in ad_rules],
        "",
        "微信直连规则",
        "-" * 40,
        *[rule.render() for rule in direct_rules],
        "",
    ]
    return "\n".join(lines)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=path.parent
    ) as handle:
        handle.write(text)
        temp_name = handle.name
    os.chmod(temp_name, 0o644)
    Path(temp_name).replace(path)


def publish_outputs(
    *,
    out_dir: Path,
    config_text: str,
    ad_rules: Sequence[Rule],
    direct_rules: Sequence[Rule],
    generated_at: datetime,
    manifest: dict,
    report: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_text(out_dir / "shadowrocket-wechat.conf", config_text)
    write_text(
        out_dir / "wechat-direct.list",
        render_list(
            "微信 / 微信支付 / 小程序基础服务：国内直连",
            direct_rules,
            generated_at,
            "这些规则必须排在宽泛的 qq.com 直连规则之前；本文件用于查看和二次使用。",
        ),
    )
    write_text(
        out_dir / "wechat-ad.list",
        render_list(
            "微信小程序 / 微信广告拦截域名",
            ad_rules,
            generated_at,
            "这些规则必须排在微信直连规则之前；删除某行即可放行对应域名。",
        ),
    )
    write_text(out_dir / "wechat-ad.sgmodule", render_module(ad_rules, generated_at))
    write_text(
        out_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    write_text(out_dir / "build-report.txt", report)
    notice_path = ROOT / "NOTICE.md"
    if notice_path.exists():
        write_text(out_dir / "NOTICE.txt", notice_path.read_text(encoding="utf-8"))
    write_text(out_dir / ".nojekyll", "")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 Shadowrocket 微信直连 + 去广告配置")
    parser.add_argument("--out", default=str(ROOT / "dist"), help="输出目录（默认 dist/）")
    parser.add_argument(
        "--upstream",
        default=None,
        help="指定上游配置文件路径或 URL；不填则自动下载",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="下载失败时允许使用 .cache/upstream.conf（日常构建不建议开启）",
    )
    args = parser.parse_args(argv)

    generated_at = now_cst()
    log("==> 准备规则")
    ad_rules, direct_rules, whitelist = prepare_injected()
    log(f"  微信广告规则 {len(ad_rules)} 条，微信直连规则 {len(direct_rules)} 条，白名单 {len(whitelist)} 条")

    log("==> 获取上游")
    upstream_text, upstream_source = read_upstream_source(
        args.upstream, allow_stale=args.allow_stale
    )
    build_time = extract_build_time(upstream_text)
    general_lines = extract_section(upstream_text, "General")

    log("==> 合并与优化")
    all_rules, stats = build_rules(
        upstream_text=upstream_text,
        ad_rules=ad_rules,
        direct_rules=direct_rules,
        whitelist=whitelist,
    )
    if not all_rules:
        raise BuildError("内部错误：没有生成任何规则")
    if any(rule.type == "FINAL" for rule in all_rules):
        raise BuildError("内部错误：FINAL 不应出现在规则列表中")

    config_text = render_config(
        general_lines=general_lines,
        ad_rules=ad_rules,
        direct_rules=direct_rules,
        all_rules=all_rules,
        build_time=build_time,
        upstream_source=upstream_source,
        generated_at=generated_at,
        stats=stats,
    )

    policy_counts = count_policies(all_rules)
    report = render_report(
        generated_at=generated_at,
        upstream_source=upstream_source,
        build_time=build_time,
        stats=stats,
        policy_counts=policy_counts,
        ad_rules=ad_rules,
        direct_rules=direct_rules,
    )

    manifest = {
        "generated_at": generated_at.isoformat(),
        "timezone": "Asia/Shanghai",
        "upstream": {
            "repo": UPSTREAM_REPO,
            "branch": UPSTREAM_BRANCH,
            "file": UPSTREAM_FILE,
            "source": upstream_source,
            "build_time": build_time,
            "sha256": sha256_text(upstream_text),
        },
        "counts": {
            "total_lines_including_final": stats["total_lines"],
            "rules_excluding_final": stats["final_rules"],
            "policies": policy_counts,
        },
        "injected": {
            "wechat_ad_rules": len(ad_rules),
            "wechat_direct_rules": len(direct_rules),
        },
        "optimization": {
            key: stats[key]
            for key in (
                "upstream_rules",
                "skipped_conflicts",
                "skipped_whitelist",
                "skipped_keywords",
                "skipped_unsupported",
                "duplicates_removed",
                "subsumed_removed",
            )
        },
        "files": [
            "shadowrocket-wechat.conf",
            "wechat-direct.list",
            "wechat-ad.list",
            "wechat-ad.sgmodule",
            "manifest.json",
            "build-report.txt",
            "NOTICE.txt",
        ],
    }

    log("==> 写出文件")
    publish_outputs(
        out_dir=Path(args.out),
        config_text=config_text,
        ad_rules=ad_rules,
        direct_rules=direct_rules,
        generated_at=generated_at,
        manifest=manifest,
        report=report,
    )
    log(report)
    log(f"==> 完成：{Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as exc:
        print(f"构建失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        raise SystemExit(130)
