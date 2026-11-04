import random
import unittest
from datetime import datetime
from pathlib import Path

from zavod import attribution as A, autopost, bot as B
from zavod.optimizer import short_name


class Flags(unittest.TestCase):
    def test_rubric_is_wired_soft_and_labels_parse(self):
        rubrics = {r.key: r for r in autopost.load_rubrics(Path("prompts/content_plan.md"))}
        self.assertIn("text_flags", rubrics)
        self.assertIn("text_flags", B.LIST_ROTATION)
        self.assertIn("text_flags", autopost.CORE)
        self.assertEqual(autopost.topic_tag_for("text_flags"), "Dating Threads")
        self.assertEqual(short_name("text_flags"), "красные и зелёные флаги")
        text = rubrics["text_flags"].text
        for part in ("не диагноз", "зона роста", "не подходите", "без процентов", "Напишите два числа"):
            self.assertIn(part, text)
        slot = autopost.ContentPlan(list(rubrics.values())).render(rubrics["text_flags"], datetime(2026, 11, 5, 19), random.Random(3))
        self.assertNotIn("{", slot.topic)
        p = A.parse(autopost.BOT_LINK + slot.tag + "_lc")
        self.assertEqual(p["rubric"], "text_flags")


if __name__ == "__main__":
    unittest.main()


class GameLabel(unittest.TestCase):
    def test_game_label_is_registered_for_both_languages(self):
        for label in ("ad_th_game_redflag", "ad_en_th_game_redflag"):
            p = A.parse(label)
            self.assertEqual((p["kind"], p["name"], p["platform"]), ("static", "game_redflag", "th"), label)
