import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rulekit import (  # noqa: E402
    Rule,
    covered_by,
    domain_matches,
    filter_upstream,
    first_match_policy,
    optimize_rules,
    parse_rules,
)


class RuleParsingTests(unittest.TestCase):
    def test_domain_suffix_is_lowercased(self):
        rule = Rule.parse("DOMAIN-SUFFIX,Weixin.QQ.com,DIRECT")
        self.assertEqual(rule.type, "DOMAIN-SUFFIX")
        self.assertEqual(rule.value, "weixin.qq.com")
        self.assertEqual(rule.policy, "DIRECT")
        self.assertEqual(rule.render(), "DOMAIN-SUFFIX,weixin.qq.com,DIRECT")

    def test_wildcard_prefix_is_removed(self):
        rule = Rule.parse("DOMAIN-SUFFIX,*.example.com,Reject")
        self.assertEqual(rule.value, "example.com")

    def test_final(self):
        rule = Rule.parse("FINAL,direct")
        self.assertEqual(rule.render(), "FINAL,DIRECT")

    def test_ip_rule_options(self):
        rule = Rule.parse("IP-CIDR,1.2.3.0/24,Proxy,no-resolve")
        self.assertEqual(rule.render(), "IP-CIDR,1.2.3.0/24,Proxy,no-resolve")

    def test_ip_asn_rule(self):
        rule = Rule.parse("IP-ASN,132203,DIRECT,no-resolve")
        self.assertEqual(rule.type, "IP-ASN")
        self.assertEqual(rule.value, "132203")
        self.assertEqual(rule.render(), "IP-ASN,132203,DIRECT,no-resolve")

    def test_comments_are_ignored(self):
        rules, errors = parse_rules(["# comment", "", "DOMAIN,a.com,Reject"])
        self.assertEqual(len(rules), 1)
        self.assertEqual(errors, [])

    def test_bad_domain(self):
        with self.assertRaises(ValueError):
            Rule.parse("DOMAIN-SUFFIX,http://example.com,Reject")


class MatchingTests(unittest.TestCase):
    def test_suffix(self):
        self.assertTrue(domain_matches("mp.weixin.qq.com", "weixin.qq.com"))
        self.assertTrue(domain_matches("weixin.qq.com", "weixin.qq.com"))
        self.assertFalse(domain_matches("notweixin.qq.com", "weixin.qq.com"))

    def test_covered_by(self):
        self.assertTrue(covered_by("a.gdt.qq.com", ["gdt.qq.com"]))
        self.assertFalse(covered_by("a.gdt.qq.com", ["dt.qq.com"]))

    def test_first_match_policy_respects_order(self):
        rules = [
            Rule.parse("DOMAIN-SUFFIX,wxs.qq.com,Reject"),
            Rule.parse("DOMAIN-SUFFIX,weixin.qq.com,DIRECT"),
            Rule.parse("DOMAIN-SUFFIX,qq.com,Proxy"),
            Rule.parse("FINAL,DIRECT"),
        ]
        self.assertEqual(first_match_policy(rules, "wxs.qq.com"), "Reject")
        self.assertEqual(first_match_policy(rules, "mp.weixin.qq.com"), "DIRECT")
        self.assertEqual(first_match_policy(rules, "other.qq.com"), "Proxy")
        self.assertEqual(first_match_policy(rules, "example.com"), "DIRECT")


class OptimizeTests(unittest.TestCase):
    def test_duplicate_removed(self):
        rules = [Rule.parse("DOMAIN,a.com,Reject")] * 2
        output, stats = optimize_rules(rules)
        self.assertEqual(len(output), 1)
        self.assertEqual(stats.duplicates, 1)

    def test_same_policy_parent_subsumes_child(self):
        rules = [
            Rule.parse("DOMAIN-SUFFIX,example.com,Reject"),
            Rule.parse("DOMAIN-SUFFIX,ads.example.com,Reject"),
            Rule.parse("DOMAIN,x.ads.example.com,Reject"),
        ]
        output, stats = optimize_rules(rules)
        self.assertEqual([r.value for r in output], ["example.com"])
        self.assertEqual(stats.subsumed, 2)

    def test_different_policy_is_not_removed(self):
        rules = [
            Rule.parse("DOMAIN-SUFFIX,example.com,Proxy"),
            Rule.parse("DOMAIN-SUFFIX,ads.example.com,Reject"),
        ]
        output, _ = optimize_rules(rules)
        self.assertEqual(len(output), 2)


class FilterTests(unittest.TestCase):
    def test_upstream_wechat_conflicts_removed(self):
        rules = [
            Rule.parse("DOMAIN-SUFFIX,weixin.qq.com,Reject"),
            Rule.parse("DOMAIN-SUFFIX,mp.weixin.qq.com,Proxy"),
            Rule.parse("DOMAIN-SUFFIX,wxs.qq.com,Proxy"),
            Rule.parse("DOMAIN-SUFFIX,google.com,Proxy"),
        ]
        output, stats = filter_upstream(
            rules,
            reserved=set(),
            ad_suffixes=["wxs.qq.com"],
            direct_suffixes=["weixin.qq.com"],
            whitelist=["weixin.qq.com"],
        )
        self.assertEqual([r.value for r in output], ["google.com"])
        self.assertEqual(stats.skipped_conflicts, 3)

    def test_whitelist_only_applies_to_reject(self):
        rules = [
            Rule.parse("DOMAIN-SUFFIX,pay.example.com,Reject"),
            Rule.parse("DOMAIN-SUFFIX,pay.example.com,Proxy"),
        ]
        output, stats = filter_upstream(
            rules,
            reserved=set(),
            ad_suffixes=[],
            direct_suffixes=[],
            whitelist=["example.com"],
        )
        # Reject 被白名单删除；Proxy 保留（是否走代理由上游决定）。
        self.assertEqual([r.policy for r in output], ["Proxy"])
        self.assertEqual(stats.skipped_whitelist, 1)


if __name__ == "__main__":
    unittest.main()
