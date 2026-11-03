import json
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zavod import autopost, fromcomments, rework
from zavod.storage import Storage

NOW = datetime.now(timezone.utc)


class HitsAndComments(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def post(self, rubric, views, comments=0, likes=0, hours=10):
        ident = await self.db.add_draft("t", f"Текст {rubric} {views}", rubric)
        await self.db.set_threads_id(ident, f"r{ident}")
        await self.db.mark_published(ident)
        await self.db._execute("UPDATE posts SET published_at = ? WHERE id = ?", ((NOW - timedelta(hours=hours)).isoformat(), ident))
        await self.db.kv_set(f"performance:{ident}:latest", json.dumps({"views": views, "comments": comments, "likes": likes}))
        return ident

    async def test_hit_is_found_queued_once_and_limited(self):
        for v in (50, 60, 70, 80, 90):
            await self.post("text_free", v)
        hit = await self.post("text_fears", 900, comments=20)
        grid = await self.post("grid", 6000, comments=700)  # матрицы не переписываем
        self.assertEqual(await rework.scan_hits(self.db, NOW), 1)
        self.assertEqual(await rework.scan_hits(self.db, NOW + timedelta(minutes=5)), 0)  # не чаще раза в 30 минут
        cand = await rework.next_hit(self.db, NOW)
        self.assertEqual((cand["id"], cand["rubric"], cand["hit"]), (hit, "text_fears", True))
        await rework.mark_hit_done(self.db, hit, NOW)
        self.assertIsNone(await rework.next_hit(self.db, NOW + timedelta(hours=4)))  # один раз на пост
        self.assertNotEqual(cand["id"], grid)

    async def test_ordinary_posts_are_not_hits(self):
        for v in (50, 60, 70, 80):
            await self.post("text_free", v)
        self.assertEqual(await rework.scan_hits(self.db, NOW), 0)

    async def test_comments_become_topics_without_names_links_or_sensitive_words(self):
        ident = await self.post("text_free", 100)
        for i, text in enumerate(["А почему у шестёрок вечно ссоры из-за денег? https://x.y", "Расскажите про числа совместимости пары, интересно очень", "26.06.57",
                                  "Моя мама умерла в мае, что говорят числа?", "Что значит, если в дате много девяток подряд?", "@vasya а у вас как?",
                                  "Как понять, какое число ведёт именно меня?"]):
            await self.db.record_comment(f"c{i}", ident, f"user{i}", text, "ответ", "replied")
        items = await fromcomments.sample(self.db, NOW)
        self.assertEqual(len(items), 4)
        joined = " ".join(items)
        for bad in ("https", "умерла", "@vasya", "26.06.57", "user"):
            self.assertNotIn(bad, joined)

    async def test_too_few_comments_means_rubric_not_due_and_once_a_day(self):
        self.assertFalse(await fromcomments.due(self.db, NOW.replace(hour=12)))
        ident = await self.post("text_free", 100)
        for i in range(3):
            await self.db.record_comment(f"d{i}", ident, "u", f"Интересно, а что значит число {i} в дате рождения?", "ответ", "replied")
        self.assertTrue(await fromcomments.due(self.db, NOW.replace(hour=12)))
        await fromcomments.take(self.db, NOW.replace(hour=12))
        self.assertFalse(await fromcomments.due(self.db, NOW.replace(hour=13)))
        self.assertFalse(await fromcomments.due(self.db, NOW.replace(hour=3)))

    def test_rubric_exists_and_is_never_random(self):
        rubrics = autopost.load_rubrics(Path("prompts/content_plan.md"))
        self.assertIn("text_from_comments", {r.key for r in rubrics})
        plan = autopost.ContentPlan(rubrics)
        keys = {plan.choose([], random.Random(i)).key for i in range(500)}
        self.assertNotIn("text_from_comments", keys)


if __name__ == "__main__":
    unittest.main()
