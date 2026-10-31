import json
import random
import re
import unittest
from datetime import datetime
from pathlib import Path

from zavod import autopost
from zavod import bot as B

GROUPS = ["1, 10, 19, 28", "2, 11, 20, 29", "3, 12, 21, 30", "4, 13, 22, 31", "5, 14, 23", "6, 15, 24", "7, 16, 25", "8, 17, 26", "9, 18, 27"]


class FearsFormat(unittest.TestCase):
    def chains(self):
        data = json.load(open("ops/commands.json", encoding="utf-8"))
        return {c["account"]: c for c in data if c["id"].startswith("fears-")}

    def test_both_chains_cover_each_group_once_and_fit_threads(self):
        chains = self.chains()
        self.assertEqual(set(chains), {"ru", "en"})
        for acc, c in chains.items():
            self.assertEqual(c["action"], "thread")
            self.assertEqual(c["rubric"], "text_fears")
            self.assertEqual(len(c["items"]), 3)
            self.assertTrue(all(len(x) <= 490 for x in c["items"]), [len(x) for x in c["items"]])
            body = "\n".join(c["items"][:2])
            for g in GROUPS:
                self.assertEqual(len(re.findall(rf"^{re.escape(g)}\b", body, re.M)), 1, (acc, g))

    def test_languages_are_not_mixed_and_honesty_is_stated(self):
        chains = self.chains()
        self.assertFalse(any(re.search("[А-Яа-яЁё]", x) for x in chains["en"]["items"]))
        self.assertTrue(all(re.search("[А-Яа-яЁё]", x) for x in chains["ru"]["items"]))
        self.assertIn("не диагноз", chains["ru"]["items"][0])
        self.assertIn("not a diagnosis", chains["en"]["items"][0])
        for c in chains.values():  # третья часть отдаёт любовь и закрывает петлю в личном чате
            self.assertIn("link in my profile" if c["account"] == "en" else "ссылка в шапке профиля", c["items"][2])

    def test_rubric_is_in_the_automatic_rotation_with_kb_shadows(self):
        rubrics = {r.key: r for r in autopost.load_rubrics(Path("prompts/content_plan.md"))}
        self.assertIn("text_fears", rubrics)
        self.assertIn("text_fears", B.LIST_ROTATION)
        self.assertGreaterEqual(autopost.BOOST["text_fears"], 3.0)
        text = rubrics["text_fears"].text
        for part in ("не диагноз", "образ числа", "критика", "самобичевание", "Заверши любовью"):
            self.assertIn(part, text)
        slot = autopost.ContentPlan(list(rubrics.values())).render(rubrics["text_fears"], datetime(2026, 10, 31, 20), random.Random(2))
        self.assertNotIn("{", slot.topic)


if __name__ == "__main__":
    unittest.main()
