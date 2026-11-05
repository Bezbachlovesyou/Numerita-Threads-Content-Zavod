import random
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from zavod import autopost, gitaqualities as G
from zavod.storage import Storage

NOON = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


class Gita(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_exactly_twenty_six_complete_entries_and_clean_languages(self):
        data = G.qualities()
        self.assertEqual(len(data), 26)
        self.assertEqual([x["n"] for x in data], list(range(1, 27)))
        for x in data:
            for k in ("ru", "en", "sa", "sa_ru", "mean_ru", "mean_en"):
                self.assertTrue(x[k].strip(), (x["n"], k))
            for k in ("en", "sa", "mean_en"):
                self.assertIsNone(re.search("[А-Яа-яЁё]", x[k]), (x["n"], k))
            self.assertIsNone(re.search("[a-zA-Z]", x["sa_ru"]), x["n"])
        self.assertIn("Бесстрашие", [x["ru"] for x in data][:1])

    async def test_one_per_day_in_the_day_window_in_order_and_cycles(self):
        self.assertTrue(await G.due(self.db, NOON))
        self.assertFalse(await G.due(self.db, NOON.replace(hour=3)))
        first = await G.take(self.db, NOON)
        self.assertEqual(first["n"], 1)
        self.assertFalse(await G.due(self.db, NOON.replace(hour=18)))
        self.assertTrue(await G.due(self.db, NOON.replace(day=7)))
        for i in range(1, 26):
            await G.take(self.db, NOON.replace(day=7))
        self.assertEqual((await G.take(self.db, NOON.replace(day=8)))["n"], 1)  # после 26-го — круг сначала

    def test_block_is_tradition_not_science_no_cyrillic_in_english_and_rubric_is_not_random(self):
        item = G.qualities()[0]
        self.assertIn("ТРАДИЦИЕЙ", G.block(item, False))
        en = G.block(item, True)
        self.assertIsNone(re.search("[А-Яа-яЁё]", en))
        self.assertIn("not as science", en)
        rubrics = autopost.load_rubrics(Path("prompts/content_plan.md"))
        self.assertIn("text_qualities", {r.key for r in rubrics})
        plan = autopost.ContentPlan(rubrics)
        self.assertNotIn("text_qualities", {plan.choose([], random.Random(i)).key for i in range(500)})


if __name__ == "__main__":
    unittest.main()
