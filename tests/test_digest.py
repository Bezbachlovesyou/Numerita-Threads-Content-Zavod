import asyncio
import os
import tempfile
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from zavod import bot as B, digest
from zavod.storage import Storage

TZ = ZoneInfo("Europe/Moscow")


class Digest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Storage(os.path.join(tempfile.mkdtemp(), "t.db"))
        await self.db.init()
        digest._buf = None
        B._DIGEST_DB["db"] = self.db
        self.out = []
        out = self.out

        class FakeBot:
            async def send_message(self, chat, text, **k):
                out.append(text)
        self.bot = FakeBot()
        self.cfg = types.SimpleNamespace(admin_ids=[1], timezone=TZ)
        self._mirror, B._mirror_log = B._mirror_log, self._nolog

    async def _nolog(self, text):
        pass

    async def asyncTearDown(self):
        B._mirror_log = self._mirror
        B._DIGEST_DB.clear()

    async def test_routine_waits_urgent_goes_now_and_digest_is_short(self):
        for t in ["✅ Канал: вышло", "ℹ️ Обход\nподробности", "⚠️ Пост не вышел", "ℹ️ Обход\nещё"] + [f"✅ {i}" for i in range(8)]:
            await B.notify_admins(self.bot, self.cfg, t)
        self.assertEqual(self.out, [])
        await B.notify_admins(self.bot, self.cfg, "‼️ Решите: минус сверх потолка")
        self.assertEqual(len(self.out), 1)
        self.assertIsNone(await digest.due(self.db, datetime(2026, 11, 20, 12, tzinfo=TZ)))
        digest._buf = None  # перезапуск: буфер из базы
        text = await digest.due(self.db, datetime(2026, 11, 20, 19, 31, tzinfo=TZ))
        lines = text.splitlines()
        self.assertTrue(lines[1].startswith("⚠️"))
        self.assertIn("(×2)", text)
        self.assertLessEqual(len(lines), digest.MAX_LINES + 2)
        self.assertIsNone(await digest.due(self.db, datetime(2026, 11, 20, 20, tzinfo=TZ)))

    async def test_live_mode_sends_at_once(self):
        await self.db.kv_set(digest.KV_MODE, "live")
        await B.notify_admins(self.bot, self.cfg, "✅ сразу")
        self.assertEqual(self.out, ["✅ сразу"])


if __name__ == "__main__":
    unittest.main()


class QuietDay(unittest.IsolatedAsyncioTestCase):
    async def test_calm_day_sends_nothing(self):
        db = Storage(os.path.join(tempfile.mkdtemp(), "q.db"))
        await db.init()
        digest._buf = None
        await digest.add(db, "✅ Пост вышел")
        await digest.add(db, "📈 Из комментариев в бота: 4,0%")
        self.assertIsNone(await digest.due(db, datetime(2026, 11, 21, 19, 31, tzinfo=TZ)))
        digest._buf = None
        self.assertEqual(await db.kv_get(digest.KV_BUF), "[]")
