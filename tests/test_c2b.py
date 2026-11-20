import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from zavod import c2b, digest
from zavod.storage import Storage

TZ = ZoneInfo("Europe/Moscow")


class C2B(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Storage(os.path.join(tempfile.mkdtemp(), "t.db"))
        await self.db.init()
        rows = [("c1", "anna", "replied", "Твоё число — 7 ✨"), ("c2", "anna", "replied", "Разбор тут t.me/Numeritabot?start=ad_th_r5_le"),
                ("c3", "boris", "skipped", ""), ("c4", "numerita.ai", "skipped", ""), ("c5", "vera", "replied", "t.me/Numeritabot?start=ad_th_r5_on"),
                ("c6", "gleb", "replied", "Спасибо!")]
        for cid, author, status, reply in rows:
            await self.db.record_comment(cid, 5, author, "коммент", reply, status)

    async def test_rate_counts_people_not_comments(self):
        data = {"labels": [{"label": "th_r5_le", "came": 1, "paid": 0}, {"label": "th_r5_on", "came": 1, "paid": 1},
                           {"label": "th_text_roles1_2011", "came": 3}]}
        now = datetime.now(TZ)
        m = await c2b.measure(self.db, now, data)
        self.assertEqual((m["people"], m["linked"], m["came"], m["paid"]), (4, 2, 2, 1))  # свой аккаунт не считается
        self.assertEqual(m["rate"], 50.0)
        self.assertEqual(m["by_group"], {"лестница": 1, "прежний": 1})
        self.assertEqual(m["by_style"], {"живой": 1, "обычный": 1})
        await c2b.record(self.db, now, m)
        line = c2b.line(m, {"rate": 40.0})
        self.assertTrue(line.startswith("📈") and "50,0%" in line and "▲" in line)
        self.assertEqual(digest.headline(line), line[:digest.LINE_LIMIT] if len(line) <= digest.LINE_LIMIT else digest.headline(line))

    async def test_no_bot_data_is_said_plainly(self):
        m = await c2b.measure(self.db, datetime.now(TZ), None)
        self.assertIn("нет данных бота", c2b.line(m))

    def test_metric_goes_first_in_digest(self):
        text = digest.build(["⚠️ Пост не вышел", "✅ Канал", "📈 Из комментариев в бота: 5,0%"])
        self.assertTrue(text.splitlines()[1].startswith("📈"))


if __name__ == "__main__":
    unittest.main()
