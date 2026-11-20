import json
import os
import tempfile
import unittest

from zavod import deepseries, lang
from zavod.autopost import topic_tag_for, load_rubrics, DAILY_POSTS_MAX
from zavod.storage import Storage
from pathlib import Path


class DeepSeries(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Storage(os.path.join(tempfile.mkdtemp(), "t.db"))
        await self.db.init()
        deepseries.CURRENT.clear()

    def test_dossier_is_clean(self):
        for s in deepseries.series():
            self.assertGreaterEqual(len(s["episodes"]), 5)
            for e in s["episodes"]:
                self.assertFalse(lang.has_cyrillic(e["en"]))
            self.assertFalse(lang.has_cyrillic(s["title_en"] + s["question_en"] + s["topic_en"]))

    async def test_episodes_go_in_order_and_wrap(self):
        all_s = deepseries.series()
        total = sum(len(s["episodes"]) for s in all_s)
        first = await deepseries.take(self.db)
        self.assertEqual((first["series"]["key"], first["n"]), (all_s[0]["key"], 1))
        for _ in range(total - 1):
            ep = await deepseries.take(self.db)
        self.assertEqual((ep["series"]["key"], ep["n"]), (all_s[-1]["key"], len(all_s[-1]["episodes"])))
        again = await deepseries.take(self.db)
        self.assertEqual((again["series"]["key"], again["n"]), (all_s[0]["key"], 1))

    async def test_label_topic_and_block(self):
        ep = await deepseries.take(self.db)
        text = deepseries.with_label("Пост", False)
        self.assertTrue(text.endswith(f"🔭 {ep['series']['title_ru']} · 1/{ep['total']}"))
        self.assertEqual(topic_tag_for("text_deep", "x"), ep["series"]["topic_ru"])
        self.assertFalse(lang.has_cyrillic(deepseries.block(ep, True)))
        self.assertIn("[[DEEP]]", next(r.text for r in load_rubrics(Path("prompts/content_plan.md")) if r.key == "text_deep"))

    def test_one_post_a_day(self):
        self.assertEqual(DAILY_POSTS_MAX, 1)


if __name__ == "__main__":
    unittest.main()
