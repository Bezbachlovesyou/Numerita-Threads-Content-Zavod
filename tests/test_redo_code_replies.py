import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from zavod import autoreply
from zavod.autoreply import is_code_reply, redo_code_replies
from zavod.storage import PgStorage, Storage

CODE = "Записала — смотри. Число души 6 — Венера: красота и забота. Узнаёшь себя?"
LIVE = "Шестёрка про заботу, а у тебя ещё и судьба 4 — опора семьи. Что сейчас строишь?"


class RedoBase:
    async def seed(self):
        now = datetime.now(timezone.utc).isoformat()
        for cid, reply in (("c1", CODE), ("c2", LIVE), ("c3", "Интересная пара! 6 → 6 и 8 → 8. Похоже на вас?")):
            await self.db.record_comment(cid, None, "user_" + cid, "15.06.1990", reply, "replied")
            await self.db.remember_message("zpost", cid, cid, None, "u", "user_" + cid, "user", "15.06.1990", now)
            await self.db.remember_message("zpost", cid, "local-reply:" + cid, cid, "numerita", "numerita.ai",
                                           "assistant", reply, now)

    async def test_redo_only_code_replies_once_with_apology(self):
        await self.seed()
        threads, gen = AsyncMock(), AsyncMock()
        gen.write_reply.return_value = "Тебе по дате выходит душа 6 — забота и вкус к красоте. Где это помогает?"
        with patch("zavod.autoreply.asyncio.sleep", AsyncMock()):
            self.assertEqual(await redo_code_replies(self.db, threads, gen, 30), 2)
            self.assertEqual(await redo_code_replies(self.db, threads, gen, 30), 0)
        targets = sorted(call.args[1] for call in threads.reply.await_args_list)
        self.assertEqual(targets, ["c1", "c3"])
        for call in threads.reply.await_args_list:
            self.assertEqual(call.args[0], "zpost")
            self.assertTrue(call.args[2].startswith("Прости"))
        self.assertTrue(is_code_reply(CODE))
        self.assertFalse(is_code_reply(LIVE))
        self.assertEqual(autoreply.CODE_SHARE, 0.0)


class SqliteRedo(RedoBase, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Storage(self.temp.name + "/t.sqlite")
        await self.db.init()

    async def asyncTearDown(self):
        self.temp.cleanup()


@unittest.skipUnless(os.getenv("DELIVERY_TEST_DSN"), "нет тестовой Postgres")
class PgRedo(RedoBase, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = PgStorage(os.environ["DELIVERY_TEST_DSN"])
        await self.db.init()
        await self.db._execute("TRUNCATE comment_replies, dialogue_messages, kv")

    async def asyncTearDown(self):
        await self.db.close() if hasattr(self.db, "close") else None
