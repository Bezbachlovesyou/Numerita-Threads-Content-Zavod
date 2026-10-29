import json
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from zavod import funnel, giveaway
from zavod.storage import Storage
from zavod.textguard import bait

TZ = ZoneInfo("Europe/Moscow")


class Surprise(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()
        funnel.KEY = "secret"

    async def asyncTearDown(self):
        giveaway.ENABLED = False
        self.tmp.cleanup()

    async def test_disabled_until_main_bot_ready(self):
        giveaway.ENABLED = False
        self.assertIsNone(await giveaway.surprise(self.db, None, datetime.now(TZ).replace(hour=20)))

    async def test_picks_commenter_with_date_and_sends_signed_link(self):
        giveaway.ENABLED = True
        pid = await self.db.add_draft("тема", "текст", "text_who_told")
        await self.db.set_threads_id(pid, "th1")
        await self.db.record_comment("c1", pid, "anna", "Моя дата 12.05.1990", "ответ", "replied")
        await self.db.record_comment("c2", pid, "numerita.ai", "24", "", "replied")
        await self.db.record_comment("c3", pid, "bob", "Классный пост", "ответ", "replied")
        sent = []

        class Threads:
            async def reply(self, post_id, comment_id, text):
                sent.append((post_id, comment_id, text))
        now = datetime.now(TZ).replace(hour=20)
        self.assertIn("из 1", await giveaway.surprise(self.db, Threads(), now))
        self.assertEqual(sent[0][:2], ("th1", "c1"))
        code = sent[0][2].rsplit("ad_th_", 1)[1]
        self.assertEqual(giveaway.gift_code("secret", code[4:10]), code)
        self.assertIn("anna", json.loads(await self.db.kv_get("giveaway:state"))["winners"])
        self.assertIsNone(await giveaway.surprise(self.db, Threads(), now))  # не чаще раза в 2 дня

    def test_bait_phrases(self):
        for t in ["Ставь лайк, если узнал себя", "Отметь подругу", "Розыгрыш разбора!", "Сделай репост"]:
            self.assertTrue(bait(t), t)
        self.assertIsNone(bait("Напиши дату — расскажу, какая звезда у вашей пары"))
