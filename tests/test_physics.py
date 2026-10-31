import random
import re
import unittest
from datetime import datetime
from pathlib import Path

from zavod import autopost, physics


class PhysicsFacts(unittest.TestCase):
    def test_every_number_has_checked_facts_with_source_and_limit(self):
        for digit in range(1, 10):
            items = physics.data()[str(digit)]
            self.assertGreaterEqual(len(items), 2, digit)
            for f in items:
                self.assertTrue(f["fact"].strip() and f["source"].strip() and f["limit"].strip(), (digit, f))
                latin = set(re.findall(r"[A-Za-z]{4,}", f["fact"])) - {"Nature"}  # имена собственные допустимы
                self.assertFalse(latin, f"латиница в русском факте: {latin}")

    def test_fact_line_is_deterministic_and_carries_limit(self):
        a = physics.fact_for(8, random.Random(1))
        self.assertEqual(a, physics.fact_for(8, random.Random(1)))
        self.assertTrue(a.startswith("Проверенный факт:") and "Граница:" in a)
        self.assertEqual(physics.fact_for(0, random.Random(1)), "")

    def test_rubric_slot_gets_fact_for_its_number_and_has_no_open_braces(self):
        rubrics = autopost.load_rubrics(Path("prompts/content_plan.md"))
        rubric = next(r for r in rubrics if r.key == "text_physics")
        self.assertEqual(rubric.cta, "reply")
        plan = autopost.ContentPlan(rubrics)
        for seed in range(12):
            slot = plan.render(rubric, datetime(2026, 10, 31, 20, 0), random.Random(seed))
            self.assertIn("Проверенный факт:", slot.topic)
            self.assertNotIn("{", slot.topic)
            digit = int(slot.card_number)
            self.assertTrue(any(f["fact"] in slot.topic for f in physics.data()[str(digit)]), (seed, digit))
            self.assertTrue(slot.tag.startswith("text_physics"))

    def test_other_rubrics_do_not_consume_physics_random(self):
        rubrics = autopost.load_rubrics(Path("prompts/content_plan.md"))
        self.assertTrue(all("{physics}" not in r.text for r in rubrics if r.key != "text_physics"))


if __name__ == "__main__":
    unittest.main()
