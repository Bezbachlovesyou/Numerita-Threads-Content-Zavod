import random
import unittest
from datetime import datetime
from pathlib import Path

from zavod import autopost, bot as B


class Lessons(unittest.TestCase):
    def test_rubric_is_in_rotation_with_soft_wording_and_labels_parse(self):
        rubrics = {r.key: r for r in autopost.load_rubrics(Path("prompts/content_plan.md"))}
        self.assertIn("text_lessons", rubrics)
        self.assertIn("text_lessons", B.LIST_ROTATION)
        self.assertGreaterEqual(autopost.BOOST["text_lessons"], 3.0)
        text = rubrics["text_lessons"].text
        for part in ("КАПСОМ", "образ, не приговор", "не писать", "Какая дата твоя?", "рост"):
            self.assertIn(part, text)
        slot = autopost.ContentPlan(list(rubrics.values())).render(rubrics["text_lessons"], datetime(2026, 11, 3, 13), random.Random(2))
        self.assertNotIn("{", slot.topic)


if __name__ == "__main__":
    unittest.main()
