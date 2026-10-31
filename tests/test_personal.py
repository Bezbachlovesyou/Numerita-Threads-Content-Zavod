import random
import re
import unittest
from datetime import datetime
from pathlib import Path

from zavod import autopost, personal

PLAN = autopost.ContentPlan(autopost.load_rubrics(Path("prompts/content_plan.md")))


class Arithmetic(unittest.TestCase):
    def test_destiny_matches_the_knowledge_base_example(self):
        self.assertEqual(personal.destiny(6, 11, 1985), 4)  # база: 06.11.1985 → 31 → 4

    def test_year_example_is_correct_and_the_numbers_differ(self):
        for seed in range(200):
            text = personal.year_example(random.Random(seed))
            dates = re.findall(r"(\d\d)\.(\d\d)\.(\d{4}) → сумма цифр (\d+) → число судьбы (\d)", text)
            self.assertEqual(len(dates), 2, text)
            nums = []
            for d, m, y, total, n in dates:
                self.assertEqual(sum(int(c) for c in d + m + y), int(total))
                self.assertEqual(personal.destiny(int(d), int(m), int(y)), int(n))
                nums.append(n)
            self.assertNotEqual(nums[0], nums[1])  # смысл примера: тот же день, разные судьбы
            self.assertEqual(dates[0][:2], dates[1][:2])  # день и месяц одинаковы, разный только год


class Rubrics(unittest.TestCase):
    def test_third_mechanism_rubrics_exist_render_cleanly_and_use_the_example(self):
        keys = {r.key: r for r in PLAN.all_rubrics()}
        for key in personal.PERSONAL:
            self.assertIn(key, keys, key)
        for key in ("text_year", "text_pair", "text_unknown"):
            for seed in range(8):
                slot = PLAN.render(keys[key], datetime(2026, 10, 31, 20), random.Random(seed))
                self.assertNotIn("{", slot.topic)
                self.assertEqual(keys[key].cta, "reply")
        year = PLAN.render(keys["text_year"], datetime(2026, 10, 31, 20), random.Random(3)).topic
        self.assertIn("→ число судьбы", year)
        self.assertIn("Полную дату публично не проси", year)
        self.assertIn("ссылка в шапке профиля", year)

    def test_weights_are_high(self):
        for key in ("text_year", "text_pair", "text_sunrise", "text_seek"):
            self.assertGreaterEqual(autopost.BOOST[key], 4.0)


class Frequency(unittest.TestCase):
    def share(self, param, n=3000):
        old = personal.PERSONAL_SHARE
        personal.PERSONAL_SHARE = param
        try:
            rng, recent, hit = random.Random(11), [], 0
            for _ in range(n):
                r = PLAN.choose(recent, rng)
                recent = [r.key] + recent[:9]
                hit += r.key in personal.PERSONAL
            return hit / n
        finally:
            personal.PERSONAL_SHARE = old

    def test_guarantee_raises_the_share_but_does_not_flood_the_feed(self):
        base, boosted = self.share(0.0), self.share(0.35)
        self.assertGreater(boosted, base + 0.05)
        self.assertLess(boosted, 0.40)  # максимум — не больше двух из пяти постов

    def test_no_back_to_back_repeats(self):
        rng, recent = random.Random(5), []
        for _ in range(500):
            r = PLAN.choose(recent, rng)
            self.assertNotEqual(r.key, recent[0] if recent else None)
            recent = [r.key] + recent[:9]


if __name__ == "__main__":
    unittest.main()
