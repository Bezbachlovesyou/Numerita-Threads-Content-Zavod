import json
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from zavod import postmatrix as P, rework
from zavod.storage import Storage

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


class Rework(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def removed(self, ident, rubric="text_free", profile=None, age_h=10):
        await self.db.kv_set(f"pm:post:{ident}", json.dumps(profile or {"genre": "monolog", "hook": "nerve"}))
        await rework.record_removed(self.db, {"id": ident, "rubric": rubric, "local_text": f"текст {ident}",
                                              "published_at": (NOW - timedelta(hours=age_h)).isoformat()}, NOW)

    async def test_removed_post_is_logged_once_and_queued_for_one_rewrite(self):
        await self.removed(1)
        await self.removed(1)
        self.assertEqual(len(await rework.removed_rows(self.db, NOW - timedelta(days=3))), 1)
        cand = await rework.next_candidate(self.db, NOW)
        self.assertEqual((cand["id"], cand["rubric"], cand["profile"]["genre"]), (1, "text_free", "monolog"))
        await rework.mark_done(self.db, 1, NOW)
        self.assertIsNone(await rework.next_candidate(self.db, NOW + timedelta(hours=3)))  # один раз

    async def test_spacing_and_daily_cap_and_excluded_rubrics(self):
        await self.removed(1)
        await self.removed(2)
        await self.removed(3, rubric="grid")  # матрицы не переписываем
        await rework.mark_done(self.db, 1, NOW)
        self.assertIsNone(await rework.next_candidate(self.db, NOW + timedelta(minutes=30)))  # раз в 2 часа
        self.assertEqual((await rework.next_candidate(self.db, NOW + timedelta(hours=3)))["id"], 2)
        await self.db.kv_set(f"rework:day:{NOW.date().isoformat()}", str(rework.REWORK_DAILY))
        self.assertIsNone(await rework.next_candidate(self.db, NOW + timedelta(hours=3)))

    async def test_removed_posts_count_as_zero_reaction_in_learning_and_suppress_dead_styles(self):
        for i in range(1, 9):  # восемь снятых «монологов» с хуком «nerve»
            await self.removed(i, profile={"genre": "monolog", "hook": "nerve"}, age_h=24)
        for i in range(9, 17):  # восемь живых постов другого стиля
            ident = await self.db.add_draft("t", f"live {i}", "text_free")
            await self.db.set_threads_id(ident, f"r{i}")
            await self.db.mark_published(ident)
            await self.db.kv_set(f"pm:post:{ident}", json.dumps({"genre": "scene", "hook": "bold"}))
            for n in range(3):
                await self.db.record_comment(f"c{i}{n}", ident, "u", "q", "a", "replied")
        learned = await P.learn(self.db, datetime.now(timezone.utc))
        self.assertEqual(learned["genre:monolog"], 0.1)
        self.assertGreater(learned["genre:scene"], 1.0)

    def test_failed_profile_values_are_avoided_when_alternatives_exist(self):
        rng = random.Random(3)
        for _ in range(40):
            profile = P.sample(rng, "ru", "text_free", [], {}, {"avoid": {"genre": "monolog", "hook": "nerve"}})
            self.assertNotEqual(profile["genre"], "monolog")
            self.assertNotEqual(profile["hook"], "nerve")

    async def test_removed_rows_lower_rubric_scores(self):
        from zavod.optimizer import score_rubrics
        for i in range(1, 4):
            await self.removed(i, rubric="text_dead", age_h=5)
        rows = await rework.removed_rows(self.db, NOW - timedelta(days=1))
        self.assertEqual(score_rubrics(rows)["text_dead"], (3, 0.0))


if __name__ == "__main__":
    unittest.main()
