#!/usr/bin/env python3
"""对生成的 Shadowrocket 配置做静态检查 + 关键域名匹配模拟。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from rulekit import count_policies, first_match_policy, parse_rules  # noqa: E402

# 这些是“核心承诺”，不满足就构建失败，避免发布坏规则。
CRITICAL = {
    # 小程序 / 微信广告：必须被拒
    "wxs.qq.com": "Reject",
    "wxsmsdy.video.qq.com": "Reject",
    "gdt.qq.com": "Reject",
    "mi.gdt.qq.com": "Reject",
    "pgdt.gtimg.cn": "Reject",
    "ad.qq.com": "Reject",
    # 微信核心：必须直连
    "weixin.qq.com": "DIRECT",
    "weixin.qq.com.cn": "DIRECT",
    "mp.weixin.qq.com": "DIRECT",
    "wechat.com": "DIRECT",
    "weixin.com": "DIRECT",
    "servicewechat.com": "DIRECT",
    "tenpay.com": "DIRECT",
    "wechatpay.com": "DIRECT",
    "wechatpay.cn": "DIRECT",
    "qpic.cn": "DIRECT",
    # 未知流量必须落到 FINAL,DIRECT
    "example.com": "DIRECT",
}

# 这些是上游行为，变化时只告警，不阻塞构建（避免上游小改动导致每天失败）。
INFORMATIONAL = {
    "google.com": "Proxy",
    "www.google.com": "Proxy",
    "baidu.com": "DIRECT",
}


class ValidationError(RuntimeError):
    pass


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "_preamble"
    sections[current] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].lower()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    if not text.startswith("#"):
        raise ValidationError("配置文件应以注释头开始")
    if "[General]" not in text or "[Rule]" not in text:
        raise ValidationError("缺少 [General] 或 [Rule]")

    sections = split_sections(text)
    forbidden = [name for name in ("mitm", "url rewrite", "script", "host") if name in sections]
    if forbidden:
        raise ValidationError(f"标准版不应包含这些段: {forbidden}")

    rules, errors = parse_rules(sections.get("rule", []))
    if errors:
        raise ValidationError("规则解析失败:\n" + "\n".join(errors[:10]))
    if len(rules) < 50_000:
        raise ValidationError(f"规则数量过少: {len(rules)}")
    if not rules or rules[-1].type != "FINAL":
        raise ValidationError("最后一条规则必须是 FINAL")
    if sum(1 for rule in rules if rule.type == "FINAL") != 1:
        raise ValidationError("FINAL 只能出现一次")
    if any(rule.type == "RULE-SET" for rule in rules):
        raise ValidationError("标准版不应依赖远程 RULE-SET")

    rendered = [rule.render() for rule in rules]
    if len(rendered) != len(set(rendered)):
        raise ValidationError("存在完全重复的规则")

    for domain, expected in CRITICAL.items():
        actual = first_match_policy(rules, domain)
        if actual != expected:
            raise ValidationError(f"{domain} 期望 {expected}，实际 {actual}")

    warnings: list[str] = []
    for domain, expected in INFORMATIONAL.items():
        actual = first_match_policy(rules, domain)
        if actual != expected:
            warnings.append(f"{domain} 期望 {expected}，实际 {actual}")

    # 广告规则必须排在微信直连之前
    ad_index = next(
        (
            index
            for index, rule in enumerate(rules)
            if rule.type == "DOMAIN-SUFFIX" and rule.value == "wxs.qq.com" and rule.policy == "Reject"
        ),
        None,
    )
    direct_index = next(
        (
            index
            for index, rule in enumerate(rules)
            if rule.type == "DOMAIN-SUFFIX" and rule.value == "weixin.qq.com" and rule.policy == "DIRECT"
        ),
        None,
    )
    if ad_index is None or direct_index is None:
        raise ValidationError("找不到 wxs.qq.com 拦截或 weixin.qq.com 直连规则")
    if ad_index >= direct_index:
        raise ValidationError("微信广告拦截规则没有排在微信直连之前")

    for token in ("IP-ASN,45090,DIRECT,no-resolve", "IP-ASN,132203,DIRECT,no-resolve"):
        if token not in text:
            raise ValidationError(f"缺少国外手机号 WeChat 的直连规则: {token}")

    # 微信核心域名不能被上游 Reject 误杀
    for domain in ("weixin.qq.com", "servicewechat.com", "tenpay.com", "qpic.cn"):
        if first_match_policy(rules, domain) == "Reject":
            raise ValidationError(f"微信核心域名被拦截: {domain}")

    if "CC BY-SA" not in text:
        raise ValidationError("配置头部缺少上游许可署名")

    notice_path = path.parent / "NOTICE.txt"
    if not notice_path.exists():
        raise ValidationError("缺少 NOTICE.txt")
    if "CC BY-SA" not in notice_path.read_text(encoding="utf-8"):
        raise ValidationError("NOTICE.txt 缺少 CC BY-SA 许可说明")

    general_text = "\n".join(sections.get("general", []))
    for key in ("dns-server", "skip-proxy", "bypass-tun"):
        if key not in general_text:
            raise ValidationError(f"[General] 缺少 {key}")

    size = path.stat().st_size
    if size < 1_000_000:
        raise ValidationError(f"配置文件过小: {size} 字节")
    if size > 10_000_000:
        raise ValidationError(f"配置文件过大: {size} 字节")

    counts = count_policies(rules)
    print(f"PASS: {path}")
    print(f"  大小: {size / 1024 / 1024:.2f} MiB")
    print(f"  规则: {len(rules)} 条")
    print("  策略: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for domain, expected in CRITICAL.items():
        print(f"  {domain:28} -> {expected}")
    for domain, expected in INFORMATIONAL.items():
        actual = first_match_policy(rules, domain)
        mark = "" if actual == expected else f" (WARN: 实际 {actual})"
        print(f"  {domain:28} -> {expected}{mark}")
    for warning in warnings:
        print(f"  WARN: {warning}")
    if warnings:
        print("  WARN: 上游分流行为发生变化，但不影响微信/广告核心规则")


def validate_module(path: Path, ad_list: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    sections = split_sections(text)
    if "mitm" in sections:
        raise ValidationError("去广告模块不应包含 MITM")
    rules, errors = parse_rules(sections.get("rule", []))
    if errors:
        raise ValidationError("模块规则解析失败:\n" + "\n".join(errors[:10]))
    expected_rules, _ = parse_rules(ad_list.read_text(encoding="utf-8-sig").splitlines())
    if [r.render() for r in rules] != [r.render() for r in expected_rules]:
        raise ValidationError("模块规则与 wechat-ad.list 不一致")
    print(f"PASS: {path} ({len(rules)} 条规则，无 MITM)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 Shadowrocket 配置")
    parser.add_argument("config", nargs="?", default=str(ROOT / "dist" / "shadowrocket-wechat.conf"))
    parser.add_argument("--module", default=str(ROOT / "dist" / "wechat-ad.sgmodule"))
    parser.add_argument("--ad-list", default=str(ROOT / "dist" / "wechat-ad.list"))
    args = parser.parse_args(argv)

    try:
        validate(Path(args.config))
        validate_module(Path(args.module), Path(args.ad_list))
    except ValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
