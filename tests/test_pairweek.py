import random
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from zavod import attribution as A, autopost, pairweek as PW
from zavod.storage import Storage

NOON = datetime(2026, 11, 5, 13, 0, tzinfo=timezone.utc)  # четверг


class PairWeek(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_numbers_and_signs_match_the_bot_branch_example(self):
        lennon_ono = PW.pairs()[1]
        text = PW.block(lennon_ono, False)
        for part in ("Джон Леннон: душа 9 (Марс), судьба 6 (Венера), Солнце — Весы", "Йоко Оно: душа 9 (Марс), судьба 9 (Марс), Солнце — Водолей", "одна стихия (воздух)"):
            self.assertIn(part, text)
        self.assertIn("совместимость в процентах не измерить", text)

    def test_data_is_clean_no_politics_no_percent_and_en_has_no_cyrillic(self):
        names = " ".join(p["a"]["ru"] + p["b"]["ru"] for p in PW.pairs())
        self.assertNotIn("Обама", names)
        self.assertNotIn("Кало", names)
        for p in PW.pairs():
            for en_text in (PW.block(p, True),):
                self.assertIsNone(re.search("[А-Яа-яЁё]", en_text), p["a"]["en"])
            self.assertNotRegex(PW.block(p, False), r"\d+\s?%")

    def test_sun_sign_boundaries(self):
        self.assertEqual(PW.sun_sign(date(1980, 1, 19))[2], "Козерог")
        self.assertEqual(PW.sun_sign(date(1980, 1, 20))[2], "Водолей")
        self.assertEqual(PW.sun_sign(date(1980, 3, 20))[2], "Рыбы")
        self.assertEqual(PW.sun_sign(date(1980, 3, 21))[2], "Овен")

    async def test_due_once_a_week_in_the_day_window_and_rotates(self):
        self.assertTrue(await PW.due(self.db, NOON))
        self.assertFalse(await PW.due(self.db, NOON.replace(hour=3)))  # ночью не выходит
        first = await PW.take(self.db, NOON, False)
        self.assertFalse(await PW.due(self.db, NOON + timedelta(days=3)))
        self.assertTrue(await PW.due(self.db, NOON + timedelta(days=7)))
        second = await PW.take(self.db, NOON + timedelta(days=7), False)
        self.assertNotEqual(first["a"]["ru"], second["a"]["ru"])

    async def test_english_takes_global_names_only(self):
        for i in range(10):
            pair = await PW.take(self.db, NOON + timedelta(days=7 * i), True)
            self.assertEqual(pair["audience"], "both")

    def test_rubric_exists_is_never_random_and_link_label_parses(self):
        rubrics = autopost.load_rubrics(Path("prompts/content_plan.md"))
        plan = autopost.ContentPlan(rubrics)
        keys = {plan.choose([], random.Random(i)).key for i in range(400)}
        self.assertNotIn("text_pair_week", keys)
        self.assertIn("text_pair_week", {r.key for r in rubrics})
        slot = plan.render(next(r for r in rubrics if r.key == "text_pair_week"), NOON, random.Random(1))
        self.assertIn("[[PAIR]]", slot.topic)
        for label in ("ad_th_pair", "ad_en_th_pair"):
            p = A.parse(label)
            self.assertEqual((p["kind"], p["name"], p["platform"]), ("static", "pair", "th"))


if __name__ == "__main__":
    unittest.main()
