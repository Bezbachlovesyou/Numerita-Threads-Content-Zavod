import json
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from zavod import funnel, giveaway
from zavod.storage import Storage

TZ = ZoneInfo("Europe/Moscow")


class Giveaway(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()
        funnel.KEY = "secret"

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_disabled_until_main_bot_ready(self):
        giveaway.ENABLED = False
        self.assertFalse(await giveaway.due_to_post(self.db, datetime(2026, 10, 30, 13, tzinfo=TZ)))

    async def test_draw_picks_commenter_with_date_and_sends_signed_link(self):
        pid = await self.db.add_draft("Разбор в подарок", "текст", "text_giveaway")
        await self.db.set_threads_id(pid, "th1")
        await self.db.record_comment("c1", pid, "anna", "Ура, 12.05.1990", "ответ", "replied")
        await self.db.record_comment("c2", pid, "numerita.ai", "24", "", "replied")
        await self.db.record_comment("c3", pid, "bob", "Классный пост", "ответ", "replied")
        now = datetime(2026, 10, 30, 20, 5, tzinfo=TZ)
        await self.db.kv_set("giveaway:state", json.dumps({"active": pid, "draw_at": (now - timedelta(minutes=5)).isoformat()}))
        sent = []

        class Threads:
            async def reply(self, post_id, comment_id, text):
                sent.append((post_id, comment_id, text))
        report = await giveaway.draw(self.db, Threads(), now)
        self.assertIn("1", report)
        self.assertEqual(sent[0][:2], ("th1", "c1"))
        code = sent[0][2].rsplit("ad_th_", 1)[1]
        nonce, sig = code[4:10], code[10:]
        self.assertEqual(giveaway.gift_code("secret", nonce), code)
        self.assertFalse(json.loads(await self.db.kv_get("giveaway:state")).get("active"))
