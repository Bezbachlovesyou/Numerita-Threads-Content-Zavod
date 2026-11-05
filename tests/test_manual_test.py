import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from zavod import bot as B
from zavod.storage import Storage

EVENING = datetime(2026, 11, 4, 19, 0, tzinfo=timezone.utc)


class Manual(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()
        self.bot = MagicMock()
        self.bot.send_message = AsyncMock()
        self.cfg = MagicMock(admin_ids=[1])

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def draft(self, rubric="text_fears", text="Какой страх прячется\nв дате рождения?"):
        ident = await self.db.add_draft("t", text, rubric)
        return await self.db.get(ident)

    async def test_one_text_a_day_in_the_evening_goes_to_the_owner_and_is_not_published(self):
        post = await self.draft()
        self.assertTrue(await B.manual_test(self.db, self.bot, self.cfg, post, EVENING))
        self.assertEqual((await self.db.get(post.id)).status, "deleted")
        sent = self.bot.send_message.await_args.args[1]
        self.assertIn("<pre>", sent)
        self.assertIn("Какой страх", sent)
        self.assertEqual(json.loads(await self.db.kv_get("manual:log"))[0]["rubric"], "text_fears")
        second = await self.draft(text="Другой пост")
        self.assertFalse(await B.manual_test(self.db, self.bot, self.cfg, second, EVENING))  # один в сутки

    async def test_post_and_first_comment_arrive_as_separate_copyable_blocks(self):
        ident = await self.db.add_draft("t", "Текст поста\nвторая строка", "text_pair_week", "Проверь свою пару за минуту: t.me/Numeritabot?start=ad_th_pair")
        post = await self.db.get(ident)
        self.assertTrue(await B.manual_test(self.db, self.bot, self.cfg, post, EVENING))
        sent = [c.args[1] for c in self.bot.send_message.await_args_list]
        pres = [m for m in sent if m.startswith("<pre>")]
        self.assertEqual(len(pres), 2)  # пост и комментарий — отдельными блоками «нажал — скопировал»
        self.assertIn("Текст поста", pres[0])
        self.assertIn("t.me/Numeritabot?start=ad_th_pair", pres[1])
        self.assertNotIn("t.me", pres[0])

    async def test_not_in_the_morning_not_for_matrices_not_after_the_test_period(self):
        post = await self.draft()
        self.assertFalse(await B.manual_test(self.db, self.bot, self.cfg, post, EVENING.replace(hour=10)))
        grid = await self.draft("grid")
        self.assertFalse(await B.manual_test(self.db, self.bot, self.cfg, grid, EVENING))
        self.assertFalse(await B.manual_test(self.db, self.bot, self.cfg, post, datetime(2026, 11, 12, 19, 0, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
