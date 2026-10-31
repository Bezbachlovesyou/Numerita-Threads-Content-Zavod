import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from zavod import bot as B
from zavod import ops
from zavod.storage import PgStorage, Storage


class OpsSpacing(unittest.IsolatedAsyncioTestCase):
    """Посты из пульта не идут пачкой: следующий ждёт обычной паузы после последнего поста."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()
        self.cfg = SimpleNamespace(timezone=ZoneInfo("Europe/Moscow"))
        ops._last = None

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def publish_now(self):
        pid = await self.db.add_draft("x", "Пост", "text_seed")
        await self.db.set_threads_id(pid, "z1")
        await self.db.mark_published(pid)

    async def test_empty_history_and_non_post_actions_are_not_held(self):
        self.assertTrue(await B.op_ready({"action": "post", "account": "ru"}, self.db, self.cfg))
        await self.publish_now()
        self.assertTrue(await B.op_ready({"action": "tell"}, self.db, self.cfg))
        self.assertTrue(await B.op_ready({"action": "post", "account": "tg"}, self.db, self.cfg))

    async def test_fresh_post_holds_the_next_one(self):
        await self.publish_now()
        self.assertFalse(await B.op_ready({"action": "post", "account": "ru"}, self.db, self.cfg))
        self.assertFalse(await B.op_ready({"action": "thread", "account": "ru"}, self.db, self.cfg))

    async def test_pile_of_commands_goes_one_per_gap_and_is_not_lost(self):
        cmds = [{"id": f"c{i}", "account": "ru", "action": "post", "text": "t"} for i in range(3)]
        ran = []

        async def run(c):
            ran.append(c["id"])
            await self.publish_now()

        async def ready(c):
            return await B.op_ready(c, self.db, self.cfg)

        with patch.object(ops, "fetch", AsyncMock(return_value=cmds)):
            await ops.tick(self.db, "ru", run, ready)
            self.assertEqual(ran, ["c0"])  # первая вышла, две ждут — но не потеряны
            self.assertTrue(await self.db.claim_slot("ops:c1"))  # ещё не заняты проходом


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "нужен TEST_POSTGRES_DSN")
class OpsSpacingPostgres(OpsSpacing):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PgStorage(os.environ["TEST_POSTGRES_DSN"])
        await self.db.init()
        for table in ("posts", "kv", "autopost_slots"):
            await self.db._execute(f"DELETE FROM {table}")
        self.cfg = SimpleNamespace(timezone=ZoneInfo("Europe/Moscow"))
        ops._last = None


if __name__ == "__main__":
    unittest.main()
