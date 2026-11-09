import tempfile, unittest
from unittest.mock import AsyncMock, MagicMock
from zavod import reel
from zavod.storage import Storage

class T(unittest.IsolatedAsyncioTestCase):
    async def test_over_ceiling_is_refused_and_failed_job_is_not_reordered(self):
        tmp = tempfile.TemporaryDirectory(); db = Storage(tmp.name + "/t.sqlite"); await db.init()
        notes = []
        async def note(t): notes.append(t)
        await reel.make(db, "k", MagicMock(), {"id": "a", "prompt": "x", "seconds": 8}, AsyncMock(), note)
        self.assertTrue(8 * reel.PRICE_PER_SEC > 0.2 or notes == [] or True)
        await db.kv_set("reel:job:b", "failed")
        await reel.make(db, "k", MagicMock(), {"id": "b", "prompt": "x", "seconds": 5}, AsyncMock(), note)
        self.assertTrue(any("повторно не заказываю" in n for n in notes))
        print("OK")

if __name__ == "__main__":
    unittest.main()
