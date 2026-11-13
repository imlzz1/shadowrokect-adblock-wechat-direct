import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build import build_rules, extract_section, render_config  # noqa: E402
from rulekit import Rule, first_match_policy  # noqa: E402

UPSTREAM = """# test upstream
# build time: UTC 2026-01-01 00:00:00

[General]
ipv6 = false
skip-proxy = localhost
bypass-tun = 10.0.0.0/8
dns-server = https://dns.alidns.com/dns-query
[Rule]
DOMAIN-SUFFIX,google.com,Proxy
DOMAIN-SUFFIX,ads.example.com,Reject
DOMAIN-SUFFIX,weixin.qq.com,Reject
DOMAIN-KEYWORD,gle,Proxy
DOMAIN-SUFFIX,ads.example.com,Reject
FINAL,direct
"""

AD = [
    "DOMAIN-SUFFIX,wxs.qq.com,Reject",
    "DOMAIN-SUFFIX,gdt.qq.com,Reject",
]
DIRECT = [
    "DOMAIN-SUFFIX,weixin.qq.com,DIRECT",
    "DOMAIN-SUFFIX,servicewechat.com,DIRECT",
]


class BuildTests(unittest.TestCase):
    def _build(self):
        ad_rules = [Rule.parse(line) for line in AD]
        direct_rules = [Rule.parse(line) for line in DIRECT]
        rules, stats = build_rules(
            upstream_text=UPSTREAM,
            ad_rules=ad_rules,
            direct_rules=direct_rules,
            whitelist=["weixin.qq.com"],
            min_upstream_rules=1,
        )
        text = render_config(
            general_lines=extract_section(UPSTREAM, "General"),
            ad_rules=ad_rules,
            direct_rules=direct_rules,
            all_rules=rules,
            build_time="UTC 2026-01-01 00:00:00",
            upstream_source="test",
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            stats=stats,
        )
        return text, rules, stats

    def test_conflicts_are_removed_and_priority_is_kept(self):
        text, rules, _ = self._build()
        self.assertNotIn("DOMAIN-SUFFIX,weixin.qq.com,Reject", text)
        self.assertNotIn("DOMAIN-KEYWORD,gle", text)
        self.assertLess(text.index("wxs.qq.com"), text.index("weixin.qq.com,DIRECT"))
        self.assertEqual(first_match_policy(rules, "wxs.qq.com"), "Reject")
        self.assertEqual(first_match_policy(rules, "mp.weixin.qq.com"), "DIRECT")
        self.assertEqual(first_match_policy(rules, "servicewechat.com"), "DIRECT")
        self.assertEqual(first_match_policy(rules, "google.com"), "Proxy")
        self.assertEqual(first_match_policy(rules, "example.com"), "DIRECT")

    def test_duplicate_upstream_rule_removed(self):
        _, rules, stats = self._build()
        self.assertEqual(stats["duplicates_removed"], 1)
        self.assertEqual(
            sum(1 for r in rules if r.type == "DOMAIN-SUFFIX" and r.value == "ads.example.com"),
            1,
        )

    def test_generated_config_has_final_and_general(self):
        text, _, _ = self._build()
        self.assertIn("[General]", text)
        self.assertIn("dns-server", text)
        self.assertTrue(text.rstrip().endswith("FINAL,DIRECT"))


if __name__ == "__main__":
    unittest.main()
