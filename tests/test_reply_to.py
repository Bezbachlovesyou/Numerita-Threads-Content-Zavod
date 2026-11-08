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
        self.t.commented_posts = AsyncMock(return_value=[{"id": "zp1", "content": "наш пост"}])
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


class Diagnostics(ReplyTo):
    async def test_not_found_says_what_was_seen(self):
        await B.reply_to_comment(self.db, self.t, self.bot, self.cfg, "nobody", "жалпы", "Привет")
        self.assertTrue(any("постов: 1" in n and "вложенными ответами): 2" in n for n in self.notes))

    async def test_author_missing_in_zernio_answer_falls_back_to_unique_text(self):
        self.t.comments = AsyncMock(return_value=[{"id": "c9", "message": "Не дедің жалпы", "from": {}}])
        await B.reply_to_comment(self.db, self.t, self.bot, self.cfg, "abdrakhman1414", "жалпы", "Давайте проще")
        self.t.reply.assert_awaited_once_with("zp1", "c9", "Давайте проще")


class Nested(ReplyTo):
    async def test_comment_nested_in_a_thread_is_found(self):
        self.t.comments = AsyncMock(return_value=[
            {"id": "top", "message": "Интересно", "from": {"username": "someone"},
             "replies": [{"id": "deep", "message": "Не дедің жалпы", "from": {"username": "abdrakhman1414"}}]}])
        await B.reply_to_comment(self.db, self.t, self.bot, self.cfg, "abdrakhman1414", "жалпы", "Давайте проще")
        self.t.reply.assert_awaited_once_with("zp1", "deep", "Давайте проще")

    async def test_posts_from_our_database_are_searched_even_if_zernio_list_omits_them(self):
        ident = await self.db.add_draft("t", "Свой пост", "text_free")
        await self.db.set_threads_id(ident, "zp2")
        await self.db.mark_published(ident)
        self.t.commented_posts = AsyncMock(return_value=[])
        async def comments(target, max_pages=3):
            return [{"id": "c7", "message": "Не дедің жалпы", "from": {"username": "abdrakhman1414"}}] if target == "zp2" else []
        self.t.comments = comments
        await B.reply_to_comment(self.db, self.t, self.bot, self.cfg, "abdrakhman1414", "жалпы", "Давайте проще")
        self.t.reply.assert_awaited_once_with("zp2", "c7", "Давайте проще")


class SkippedBefore(ReplyTo):
    async def test_comment_the_bot_skipped_earlier_still_gets_the_owners_reply(self):
        await self.db.record_comment("c1", 0, "abdrakhman1414", "Не дедің жалпы", "skip:model", "skipped")
        await B.reply_to_comment(self.db, self.t, self.bot, self.cfg, "abdrakhman1414", "жалпы", "Қарапайым түсіндірейін")
        self.t.reply.assert_awaited_once_with("zp1", "c1", "Қарапайым түсіндірейін")
        self.assertTrue(any("✅" in n for n in self.notes))


class Fallback(ReplyTo):
    async def test_unreachable_nested_comment_falls_back_to_its_parent(self):
        from zavod.threads_api import ThreadsError
        self.t.comments = AsyncMock(return_value=[
            {"id": "top", "message": "Looks like numbers are missing", "from": {"username": "jess"},
             "replies": [{"id": "deep", "message": "8. 17, 26", "from": {"username": "jess"}}]}])
        self.t.reply = AsyncMock(side_effect=[ThreadsError("Object with ID 'deep' does not exist, cannot be loaded due to missing permissions"), None])
        await B.reply_to_comment(self.db, self.t, self.bot, self.cfg, "jess", "17, 26", "Here are the days")
        self.assertEqual([c.args[1] for c in self.t.reply.await_args_list], ["deep", "top"])
        print("OK")
