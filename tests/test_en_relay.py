import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from zavod import bot as B
from zavod.storage import Storage


class Relay(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.en = Storage(self.tmp.name + "/en.sqlite")
        await self.en.init()
        self.cfg = MagicMock(cards=False, timezone=ZoneInfo("Europe/Moscow"), tts_auto=False)
        self.bot = MagicMock()
        self.bot.send_message = AsyncMock()
        self.bot.edit_message_text = AsyncMock()
        self.generator = MagicMock()
        self.generator.write_post = AsyncMock(return_value="Done is better than perfect. Which number is yours?")

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_language_detection(self):
        self.assertTrue(B.is_english_text("done"))
        self.assertTrue(B.is_english_text("Gratitude and numbers"))
        self.assertFalse(B.is_english_text("сделал"))
        self.assertFalse(B.is_english_text("done сделал"))
        self.assertFalse(B.is_english_text("12345"))

    async def test_owner_word_becomes_english_post_with_english_buttons(self):
        await B.en_queue_push(self.en, "owner:inbox", {"topic": "done", "chat_id": 77})
        with patch.object(B, "post_card", lambda post, cfg: f"card {post.id}"):
            await B.en_owner_tick(self.bot, self.cfg, self.en, None, self.generator)
        self.generator.write_post.assert_awaited_once_with("done")
        chat, text = self.bot.send_message.await_args.args[:2]
        self.assertEqual((chat, text), (77, "[EN] card 1"))
        kb = self.bot.send_message.await_args.kwargs["reply_markup"]
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertTrue(all(d.startswith("enpost:") for d in datas))
        self.assertTrue(any(d.startswith("enpost:publish:") for d in datas))
        self.assertEqual(json.loads(await self.en.kv_get("owner:inbox")), [])

    async def test_publish_button_is_executed_by_the_english_factory_and_reported(self):
        post_id = await self.en.add_draft("done", "An English post. Which number is yours?")
        await B.en_queue_push(self.en, "owner:actions", {"action": "publish", "post_id": post_id, "chat_id": 77, "message_id": 5})
        async def fake_publish(post, db, threads, bot, channel, cards=True):
            await db.set_threads_id(post.id, "remote")
            await db.mark_published(post.id)
            return await db.get(post.id)
        with patch.object(B, "publish", fake_publish), patch.object(B, "post_card", lambda post, cfg: f"status {post.status}"):
            await B.en_owner_tick(self.bot, self.cfg, self.en, None, self.generator)
        self.assertEqual((await self.en.get(post_id)).status, "published")
        self.assertIn("status published", self.bot.edit_message_text.await_args.args[0])

    async def test_delete_and_missing_post(self):
        post_id = await self.en.add_draft("x", "Text")
        await B.en_queue_push(self.en, "owner:actions", {"action": "delete", "post_id": post_id, "chat_id": 77, "message_id": 5})
        await B.en_queue_push(self.en, "owner:actions", {"action": "publish", "post_id": 999, "chat_id": 77, "message_id": 6})
        with patch.object(B, "post_card", lambda post, cfg: "c"):
            await B.en_owner_tick(self.bot, self.cfg, self.en, None, self.generator)
        self.assertEqual((await self.en.get(post_id)).status, "deleted")
        self.assertTrue(any("не найден" in c.args[1] for c in self.bot.send_message.await_args_list))


if __name__ == "__main__":
    unittest.main()
