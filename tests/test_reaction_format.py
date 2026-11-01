import random
import unittest
from datetime import datetime
from pathlib import Path

from zavod import attribution as A, autopost, bot as B


class ReactionFormat(unittest.TestCase):
    def test_rubric_in_rotation_and_labels_parse(self):
        rubrics = {r.key: r for r in autopost.load_rubrics(Path("prompts/content_plan.md"))}
        self.assertIn("text_reaction", rubrics)
        self.assertIn("text_reaction", B.LIST_ROTATION)
        self.assertGreaterEqual(autopost.BOOST["text_reaction"], 3.0)
        for part in ("не диагноз", "КАПСОМ", "Напиши день рождения числом"):
            self.assertIn(part, rubrics["text_reaction"].text)
        plan = autopost.ContentPlan(list(rubrics.values()))
        slot = plan.render(rubrics["text_reaction"], datetime(2026, 11, 1, 12), random.Random(3))
        self.assertNotIn("{", slot.topic)
        p = A.parse(autopost.BOT_LINK + slot.tag + "_lc")
        self.assertEqual(p["rubric"], "text_reaction")


if __name__ == "__main__":
    unittest.main()
