import tempfile, unittest
from datetime import datetime, timezone
from zavod import bot as B
from zavod.storage import Storage

class T(unittest.IsolatedAsyncioTestCase):
    async def test_refuses_near_copy_and_allows_different(self):
        tmp = tempfile.TemporaryDirectory(); db = Storage(tmp.name + "/t.sqlite"); await db.init()
        pid = await db.add_draft("a", "Хочу собрать живую вечеринку. Танцы, музыка, чаи и шампанское.", "text_free")
        await db.set_threads_id(pid, "t1"); await db.mark_published(pid)
        self.assertTrue(await B.similar_recent(db, "Хочу собрать живую вечеринку! Танцы, музыка, чаи и шампанское."))
        self.assertIsNone(await B.similar_recent(db, "Число 7 любит тишину и глубину."))
        print("OK")

if __name__ == "__main__":
    unittest.main()
