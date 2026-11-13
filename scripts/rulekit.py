"""Shadowrocket 规则解析、去重与优先级处理。

这个模块只依赖 Python 标准库，GitHub Actions 上不需要安装任何第三方包。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

# Shadowrocket / Surge 常见策略名，统一成三种内置策略。
POLICY_ALIASES = {
    "proxy": "Proxy",
    "reject": "Reject",
    "direct": "DIRECT",
}

DOMAIN_TYPES = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"}
IP_TYPES = {"IP-CIDR", "IP-CIDR6", "IP-ASN", "GEOIP", "GEOIP6"}
# 上游里出现、但本项目不需要的规则类型。
UNSUPPORTED_TYPES = {"RULE-SET", "DOMAIN-WILDCARD"}

# 这些“域名关键字”过于宽泛，会把正常网站误判，构建时删除。
DROP_DOMAIN_KEYWORDS = {"gle"}


def normalize_policy(raw: str) -> str:
    """把 direct / DIRECT / Proxy / REJECT 统一成规范写法。"""
    value = raw.strip()
    alias = POLICY_ALIASES.get(value.lower())
    if alias:
        return alias
    # 保留自定义策略名（例如某个代理组），只做首字母大写兼容。
    if value.upper() in {"DIRECT", "REJECT", "PROXY"}:
        return value.title() if value.upper() == "PROXY" else value.upper()
    return value


def clean_domain(raw: str) -> str:
    """规范化域名：小写、去尾点、去 *. 前缀。"""
    value = raw.strip().lower().rstrip(".")
    if value.startswith("*."):
        value = value[2:]
    if not value:
        raise ValueError("空域名")
    if any(ch in value for ch in (" ", "/", ":", "\\", "\t")):
        raise ValueError(f"域名格式不正确: {raw!r}")
    if value == "localhost":
        return value
    if "." not in value and value not in {"local", "lan", "internal"}:
        # 单标签域名在 Shadowrocket 中也可能合法，但不作强制限制。
        return value
    return value


@dataclass(frozen=True)
class Rule:
    """一条 Shadowrocket 规则。"""

    type: str
    value: str
    policy: str
    options: tuple[str, ...] = ()

    @property
    def is_domain(self) -> bool:
        return self.type in DOMAIN_TYPES

    @property
    def domain(self) -> str | None:
        return self.value if self.is_domain else None

    def key(self) -> tuple[str, str, str, tuple[str, ...]]:
        return (self.type, self.value.lower(), self.policy.lower(), self.options)

    def value_key(self) -> tuple[str, str]:
        """用于判断“同一个域名/网段”是否有不同策略。"""
        return (self.type, self.value.lower())

    def render(self) -> str:
        if self.type == "FINAL":
            return f"FINAL,{self.policy}"
        parts = [self.type, self.value, self.policy, *self.options]
        return ",".join(parts)

    @classmethod
    def parse(cls, line: str) -> "Rule | None":
        text = line.strip()
        if not text or text.startswith("#") or text.startswith("//"):
            return None
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 2:
            raise ValueError(f"无法解析规则: {line!r}")

        rule_type = parts[0].upper()
        if rule_type == "FINAL":
            if len(parts) < 2 or not parts[1]:
                raise ValueError(f"FINAL 缺少策略: {line!r}")
            return cls("FINAL", "", normalize_policy(parts[1]))

        if len(parts) < 3:
            raise ValueError(f"规则少于 3 段: {line!r}")

        value = parts[1]
        policy = normalize_policy(parts[2])
        options = tuple(p.strip() for p in parts[3:] if p.strip())

        if rule_type in DOMAIN_TYPES:
            if rule_type == "DOMAIN-KEYWORD":
                value = value.lower()
                if not value:
                    raise ValueError(f"空关键字: {line!r}")
            else:
                value = clean_domain(value)
        elif rule_type in IP_TYPES:
            value = value.strip()
        else:
            value = value.strip()

        return cls(rule_type, value, policy, options)


def parse_rules(lines: Iterable[str]) -> tuple[list[Rule], list[str]]:
    """解析多行规则，返回 (规则列表, 错误列表)。"""
    rules: list[Rule] = []
    errors: list[str] = []
    for line in lines:
        try:
            rule = Rule.parse(line)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if rule is not None:
            rules.append(rule)
    return rules, errors


def domain_matches(domain: str, suffix: str) -> bool:
    """判断 domain 是否等于 suffix 或属于 suffix 的子域。"""
    d = domain.strip().lower().rstrip(".")
    s = suffix.strip().lower().rstrip(".")
    if not d or not s:
        return False
    return d == s or d.endswith("." + s)


def covered_by(domain: str, suffixes: Sequence[str]) -> bool:
    return any(domain_matches(domain, suffix) for suffix in suffixes)


def rule_matches_domain(rule: Rule, domain: str) -> bool:
    if rule.type == "DOMAIN":
        return domain.strip().lower().rstrip(".") == rule.value
    if rule.type == "DOMAIN-SUFFIX":
        return domain_matches(domain, rule.value)
    if rule.type == "DOMAIN-KEYWORD":
        return rule.value in domain.lower()
    return False


def first_match_policy(rules: Iterable[Rule], domain: str) -> str:
    """按顺序模拟 Shadowrocket 的域名匹配，返回命中的策略。"""
    for rule in rules:
        if rule.type == "FINAL":
            return rule.policy
        if rule.is_domain and rule_matches_domain(rule, domain):
            return rule.policy
    return "DIRECT"


def parent_domains(domain: str) -> Iterator[str]:
    """依次产出 example.com -> com，用于后缀包含判断。"""
    parts = domain.lower().strip(".").split(".")
    for index in range(1, len(parts)):
        yield ".".join(parts[index:])


@dataclass
class OptimizeStats:
    duplicates: int = 0
    subsumed: int = 0
    input: int = 0
    output: int = 0


def optimize_rules(rules: Iterable[Rule]) -> tuple[list[Rule], OptimizeStats]:
    """去重，并删除被前面同策略后缀规则完全覆盖的规则。

    只做“安全删除”：如果 later 规则已经被 earlier 的同策略更宽规则覆盖，
    它本来就永远不会命中，删掉不改变匹配结果。
    """
    stats = OptimizeStats()
    seen: set[tuple[str, str, str, tuple[str, ...]]] = set()
    suffix_by_policy: dict[str, set[str]] = defaultdict(set)
    exact_by_policy: dict[str, set[str]] = defaultdict(set)
    output: list[Rule] = []

    for rule in rules:
        stats.input += 1
        key = rule.key()
        if key in seen:
            stats.duplicates += 1
            continue
        seen.add(key)

        if rule.type == "DOMAIN-SUFFIX":
            if any(parent in suffix_by_policy[rule.policy] for parent in parent_domains(rule.value)):
                stats.subsumed += 1
                continue
            suffix_by_policy[rule.policy].add(rule.value)
        elif rule.type == "DOMAIN":
            if (
                rule.value in exact_by_policy[rule.policy]
                or rule.value in suffix_by_policy[rule.policy]
                or any(
                    parent in suffix_by_policy[rule.policy]
                    for parent in parent_domains(rule.value)
                )
            ):
                stats.subsumed += 1
                continue
            exact_by_policy[rule.policy].add(rule.value)

        output.append(rule)

    stats.output = len(output)
    return output, stats


@dataclass
class FilterStats:
    skipped_conflicts: int = 0
    skipped_whitelist: int = 0
    skipped_keywords: int = 0
    skipped_unsupported: int = 0


def filter_upstream(
    rules: Iterable[Rule],
    *,
    reserved: set[tuple[str, str]],
    ad_suffixes: Sequence[str],
    direct_suffixes: Sequence[str],
    whitelist: Sequence[str],
    drop_keywords: set[str] | None = None,
) -> tuple[list[Rule], FilterStats]:
    """过滤上游规则，保证微信直连/广告拦截的优先级不被覆盖。"""
    stats = FilterStats()
    keywords = {k.lower() for k in (drop_keywords or DROP_DOMAIN_KEYWORDS)}
    output: list[Rule] = []

    for rule in rules:
        if rule.type in UNSUPPORTED_TYPES:
            stats.skipped_unsupported += 1
            continue
        if rule.type == "FINAL":
            continue
        if rule.is_domain and rule.type == "DOMAIN-KEYWORD" and rule.value in keywords:
            stats.skipped_keywords += 1
            continue
        if rule.is_domain and rule.value_key() in reserved:
            stats.skipped_conflicts += 1
            continue

        if rule.is_domain:
            domain = rule.value
            if covered_by(domain, ad_suffixes):
                # 广告域名一律以本项目的小程序广告规则为准。
                stats.skipped_conflicts += 1
                continue
            if covered_by(domain, direct_suffixes):
                # 微信核心域名必须直连，上游的 Proxy/Reject 都不要。
                stats.skipped_conflicts += 1
                continue
            if rule.policy == "Reject":
                if rule.type == "DOMAIN-KEYWORD":
                    if any(rule.value in item for item in whitelist):
                        stats.skipped_whitelist += 1
                        continue
                elif covered_by(domain, whitelist):
                    stats.skipped_whitelist += 1
                    continue

        output.append(rule)

    return output, stats


def load_domain_list(path: Path) -> list[str]:
    """读取一行一个域名的白名单文件，忽略注释和空行。"""
    domains: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        domain = clean_domain(line)
        if domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def load_rules(path: Path) -> list[Rule]:
    """读取本项目 config/*.list（完整规则格式）。"""
    rules, errors = parse_rules(path.read_text(encoding="utf-8").splitlines())
    if errors:
        raise ValueError(f"{path} 有无法解析的规则:\n" + "\n".join(errors[:10]))
    return rules


def dedupe_rules(rules: Iterable[Rule]) -> list[Rule]:
    """仅去重，保持顺序。"""
    output: list[Rule] = []
    seen: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for rule in rules:
        key = rule.key()
        if key in seen:
            continue
        seen.add(key)
        output.append(rule)
    return output


def count_policies(rules: Iterable[Rule]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for rule in rules:
        counts[rule.policy] += 1
    return dict(counts)
