import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import httpx

from zavod import bot as B, costs, generator as G
from zavod.storage import Storage

TZ = ZoneInfo("Europe/Moscow")


class Cap(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def spend(self, usd):
        await self.db.kv_set(costs.day_key(datetime.now(TZ)), json.dumps({"post": [1, usd, 1, 1, 0]}))

    def gen(self):
        g = G.Generator.__new__(G.Generator)
        g.api_key, g.model, g.reply_model, g.system = "k", "m", "h", "s"
        g.spend_guard = costs.make_guard(self.db, TZ)
        async def noop(*a, **k): pass
        g._record_cost = noop
        return g

    async def test_optional_steps_stop_after_soft_cap_but_writing_posts_continues(self):
        await self.spend(costs.SOFT_USD + 0.01)
        g = self.gen()
        with self.assertRaises(G.GenerationError):
            await g._complete("s", "p", kind="coherence")
        class Fake:
            def __call__(self, *a, **k): return self
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, headers=None, json=None):
                return httpx.Response(200, json={"choices": [{"message": {"content": "пост"}, "finish_reason": "stop"}], "usage": {}}, request=httpx.Request("POST", url))
        with patch("httpx.AsyncClient", Fake()):
            self.assertEqual(await g._complete("s", "p", kind="post"), "пост")  # сам пост ещё пишется до жёсткого потолка

    async def test_below_soft_cap_everything_runs(self):
        await self.spend(0.05)
        self.assertLess(await costs.today_total(self.db, TZ), costs.SOFT_USD)

    async def test_hard_cap_stops_new_posts_and_tells_once(self):
        await self.spend(costs.HARD_USD + 0.01)
        g = self.gen()
        notes = []
        bot, cfg = MagicMock(), MagicMock(timezone=TZ, admin_ids=[1])
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t, *a: notes.append(t))):
            await B.autopost_tick(bot, cfg, self.db, None, g, MagicMock(), MagicMock())
            await B.autopost_tick(bot, cfg, self.db, None, g, MagicMock(), MagicMock())
        self.assertEqual(len(notes), 1)
        self.assertIn("Дневной потолок", notes[0])


if __name__ == "__main__":
    unittest.main()
