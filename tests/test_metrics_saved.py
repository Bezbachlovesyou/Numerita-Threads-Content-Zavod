import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from zavod import performance
from zavod.storage import Storage


class Threads:
    async def post_stats(self, threads_id):
        if threads_id == "t0":
            return None  # у старого поста площадка новых данных не дала — остаётся уже собранное
        return {"platformAnalytics": [{"platform": "threads", "analytics": {"likes": 52, "comments": 25, "views": 10100}}]}


class MetricsSaved(unittest.IsolatedAsyncioTestCase):
    async def test_collect_and_backfill_reach_engagement(self):
        db = Storage(os.path.join(tempfile.mkdtemp(), "t.db"))
        await db.init()
        old = await db.add_draft("x", "Старый пост", "text_roles")
        await db.set_threads_id(old, "t0")
        await db.mark_published(old)
        await db.kv_set(f"performance:{old}:latest", json.dumps({"likes": 7, "views": 900}))
        pid = await db.add_draft("x", "Пост", "text_roles")
        await db.set_threads_id(pid, "t1")
        await db.mark_published(pid)
        now = datetime.now(timezone.utc) + timedelta(hours=1, minutes=10)  # окно 1 часа
        await performance.collect(db, Threads(), now)
        rows = {r["id"]: r for r in await db.engagement(now - timedelta(days=7))}
        self.assertEqual((rows[pid]["likes"], rows[pid]["views"]), (52, 10100))
        self.assertEqual((rows[old]["likes"], rows[old]["views"]), (7, 900))
        print("OK")


if __name__ == "__main__":
    unittest.main()
