import json
import tempfile
import unittest
from datetime import datetime, timezone

from zavod import costs
from zavod.storage import Storage

TZ = timezone.utc


class PostGuard(unittest.IsolatedAsyncioTestCase):
    """Ответы людям не съедают долю постов: в потолке постов их запас учтён заранее и целиком."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_replies_do_not_stop_posts_but_post_spend_does(self):
        key = costs.day_key(datetime.now(TZ))
        guard = costs.make_guard(self.db, TZ)
        await self.db.kv_set(key, json.dumps({"reply·haiku": [900, 0.45, 1, 1, 0], "summary": [9, 0.05, 1, 1, 0], "post": [2, 0.16, 1, 1, 0]}))
        self.assertLess(await guard(), costs.HARD_USD)          # 0.30 + 0.16 = 0.46: посты идут, хотя всего потрачено 0.66
        await self.db.kv_set(key, json.dumps({"reply·haiku": [10, 0.01, 1, 1, 0], "post": [4, 0.26, 1, 1, 0]}))
        self.assertGreaterEqual(await guard(), costs.HARD_USD)  # 0.30 + 0.26 = 0.56: доля постов исчерпана


if __name__ == "__main__":
    unittest.main()
