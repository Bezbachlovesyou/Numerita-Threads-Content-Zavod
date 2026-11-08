import json, unittest
from datetime import datetime, timedelta, timezone
from zavod import dailypost
from zavod.storage import Storage

class T(unittest.IsolatedAsyncioTestCase):
    async def test_best_post_no_links_prompt_and_no_repeat(self):
        import tempfile; self.tmp = tempfile.TemporaryDirectory(); db = Storage(self.tmp.name + "/t.sqlite"); await db.init()
        now = datetime.now(timezone.utc)
        ids = []
        for i, (likes, com) in enumerate([(5, 0), (9, 4), (30, 0)]):
            pid = await db.add_draft(f"d{i}", f"ХУК номер {i}\nтекст t.me/Numeritabot?start=ad_x @Numeritabot", "text_sign")
            await db.set_threads_id(pid, f"th{i}"); await db.mark_published(pid)
            await db.kv_set(f"performance:{pid}:latest", json.dumps({"likes": likes, "comments": com}))
            ids.append(pid)
        # публикации «старше 12 часов»
        await db._execute("UPDATE posts SET published_at = ?", ((now - timedelta(hours=30)).isoformat(),))
        msgs = await dailypost.messages(db, now)
        self.assertTrue(msgs)
        if msgs:
            self.assertIn("30 лайков", msgs[0]); self.assertNotIn("t.me", msgs[1]); self.assertNotIn("@Numeritabot", msgs[1])
            self.assertIn("Промпт для Grok", msgs[2]); self.assertLessEqual(msgs[1].count("#"), 5)
            again = await dailypost.messages(db, now)
            self.assertIn("9 лайков", again[0])
        print("OK")

if __name__ == "__main__":
    unittest.main()
