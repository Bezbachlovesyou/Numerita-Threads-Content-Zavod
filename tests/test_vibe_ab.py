import unittest
from zavod import autoreply, generator

class T(unittest.TestCase):
    def test_arm_is_stable_and_splits_both_ways(self):
        arms = [autoreply.vibe_arm(f"user{i}") for i in range(400)]
        self.assertEqual(arms, [autoreply.vibe_arm(f"user{i}") for i in range(400)])
        share = arms.count("e") / 400
        self.assertTrue(0.4 < share < 0.6, share)

    def test_rule_mentions_only_elegant_set_and_sensitive_exception(self):
        self.assertIn("🤍", generator.VIBE_RULE)
        self.assertIn("без юмора и без эмодзи", generator.VIBE_RULE)

    def test_label_still_parses(self):
        from zavod import attribution
        for suffix in ("ae", "an", "ce", "cn"):
            self.assertTrue(attribution.REPLY.match(f"r12_a{suffix}"), suffix)
        print("OK")

if __name__ == "__main__":
    unittest.main()
