import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from zavod import bot as B
from zavod.storage import Storage


class ReplyTo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()
        self.cfg, self.bot = MagicMock(admin_ids=[1]), MagicMock()
        self.notes = []
        self.patch = patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t, *a: self.notes.append(t)))
        self.patch.start()
        self.t = MagicMock()
        self.t.commented_posts = AsyncMock(return_value=[{"id": "zp1"}])
        self.t.comments = AsyncMock(return_value=[
            {"id": "c0", "message": "Спасибо", "from": {"username": "someone"}},
            {"id": "c1", "message": "Не дедің жалпы", "from": {"username": "abdrakhman1414"}}])
        self.t.reply = AsyncMock()

    async def asyncTearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    async def test_finds_the_comment_replies_once_and_records_it(self):
        await B.reply_to_comment(self.db, self.t, self.bot, self.cfg, "@abdrakhman1414", "жалпы", "Давайте проще")
        self.t.reply.assert_awaited_once_with("zp1", "c1", "Давайте проще")
        self.assertIn("c1", await self.db.handled_comments(["c1"]))
        self.assertTrue(any("✅" in n for n in self.notes))
        await B.reply_to_comment(self.db, self.t, self.bot, self.cfg, "abdrakhman1414", "жалпы", "Давайте проще")
        self.assertEqual(self.t.reply.await_count, 1)  # второй раз не отвечаем

    async def test_not_found_is_reported_not_claimed_as_sent(self):
        await B.reply_to_comment(self.db, self.t, self.bot, self.cfg, "nobody", "жалпы", "Привет")
        self.t.reply.assert_not_awaited()
        self.assertTrue(any("не найден" in n for n in self.notes))


if __name__ == "__main__":
    unittest.main()
