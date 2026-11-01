import random
import re
import unittest
from datetime import datetime
from pathlib import Path

from zavod import autopost, greatpeople as G


class Great(unittest.TestCase):
    def test_numbers_are_computed_by_code(self):
        n = G.numbers("1879-03-14")  # Эйнштейн: день 14 → 5; 1+4+0+3+1+8+7+9 = 33 → 6
        self.assertEqual((n["soul"], n["sum"], n["mission"]), (5, 33, 6))
        n = G.numbers("1452-04-15")  # день 15 → 6; 1+5+0+4+1+4+5+2 = 22 → 4
        self.assertEqual((n["soul"], n["sum"], n["mission"]), (6, 22, 4))

    def test_data_is_clean_and_complete(self):
        for p in G.people():
            self.assertTrue(re.fullmatch(r"\d{4}-\d{2}-\d{2}", p["born"]), p["ru"])
            self.assertIn(p["audience"], ("both", "ru"))
            for k in ("ru", "en", "field_ru", "field_en", "fact_ru", "fact_en"):
                self.assertTrue(p[k].strip(), (p["ru"], k))
            for k in ("en", "field_en", "fact_en"):
                self.assertIsNone(re.search("[А-Яа-яЁё]", p[k]), (p["en"], k))  # английская часть без кириллицы
            self.assertLess(len(p["fact_ru"]), 200)

    def test_english_block_has_no_cyrillic_and_uses_global_names_only(self):
        rng = random.Random(1)
        for _ in range(60):
            person = G.pick(rng, True)
            self.assertEqual(person["audience"], "both")
            self.assertIsNone(re.search("[А-Яа-яЁё]", G.block(person, True)))

    def test_no_immediate_repeats(self):
        G.RECENT.clear()
        rng = random.Random(2)
        names = [G.pick(rng, False)["ru"] for _ in range(14)]
        self.assertEqual(len(set(names)), 14)

    def test_rubric_renders_with_data(self):
        rubrics = {r.key: r for r in autopost.load_rubrics(Path("prompts/content_plan.md"))}
        self.assertIn("{great}", rubrics["text_celeb"].text)
        slot = autopost.ContentPlan(list(rubrics.values())).render(rubrics["text_celeb"], datetime(2026, 11, 1, 12), random.Random(4))
        self.assertNotIn("{", slot.topic)
        self.assertIn("Посчитано кодом", slot.topic)


if __name__ == "__main__":
    unittest.main()
