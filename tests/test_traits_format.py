import random
import unittest
from datetime import datetime
from pathlib import Path

from zavod import attribution as A, autopost, bot as B
from zavod.optimizer import short_name


class Traits(unittest.TestCase):
    def test_rubric_is_wired(self):
        rubrics = {r.key: r for r in autopost.load_rubrics(Path("prompts/content_plan.md"))}
        self.assertIn("text_traits", rubrics)
        self.assertNotIn("text_traits", B.LIST_ROTATION)  # своя частота, не 1/18 круга списков
        self.assertIn("text_traits", autopost.CORE)
        self.assertEqual(autopost.goal_of("text_traits"), "likes")
        self.assertEqual(short_name("text_traits"), "характер одной строкой")
        text = rubrics["text_traits"].text
        for part in ("все 9 групп", "не длиннее 8 слов", "не диагноз", "Какая строка про вас?"):
            self.assertIn(part, text)
        slot = autopost.ContentPlan(list(rubrics.values())).render(rubrics["text_traits"], datetime(2026, 11, 16, 19), random.Random(3))
        self.assertNotIn("{", slot.topic)
        self.assertEqual(A.parse(autopost.BOT_LINK + slot.tag + "_lc")["rubric"], "text_traits")

    def test_bydate_is_wired(self):
        rubrics = {r.key: r for r in autopost.load_rubrics(Path("prompts/content_plan.md"))}
        self.assertIn("text_bydate", rubrics)
        self.assertNotIn("text_bydate", B.LIST_ROTATION)
        self.assertIn("text_bydate", autopost.CORE)
        self.assertEqual(autopost.goal_of("text_bydate"), "shares")
        self.assertEqual(short_name("text_bydate"), "тема по дате рождения")
        text = rubrics["text_bydate"].text
        for part in ("ПО ДАТЕ РОЖДЕНИЯ", "все 31 день", "без приговоров", "не берём"):
            self.assertIn(part, text)
        slot = autopost.ContentPlan(list(rubrics.values())).render(rubrics["text_bydate"], datetime(2026, 11, 16, 19), random.Random(5))
        self.assertNotIn("{", slot.topic)
        self.assertEqual(A.parse(autopost.BOT_LINK + slot.tag + "_lc")["rubric"], "text_bydate")


if __name__ == "__main__":
    unittest.main()
