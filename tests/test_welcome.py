import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from zavod import welcome
from zavod.storage import Storage


class FakeResp:
    def __init__(self, status, data=None, content=b""):
        self.status_code, self._data, self.content, self.text = status, data or {}, content, ""

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeHttp:
    def __init__(self, fail=False):
        self.posts, self.fail = 0, fail

    async def post(self, url, json=None, headers=None):
        self.posts += 1
        return FakeResp(400 if self.fail else 200, {"id": f"job{self.posts}"})

    async def get(self, url, headers=None, follow_redirects=False):
        if url.endswith("/content"):
            return FakeResp(200, content=b"video")
        return FakeResp(200, {"status": "completed", "usage": {"cost": 0.4}})


class WelcomeBudget(unittest.TestCase):
    def setUp(self):
        self.db = Storage(os.path.join(tempfile.mkdtemp(), "t.db"))
        asyncio.run(self.db.init())

    def test_job_saved_and_not_reordered(self):
        async def go():
            http = FakeHttp()
            self.assertEqual(await welcome.clip(self.db, http, "code", "k"), b"video")
            self.assertEqual(await self.db.kv_get("welcome:job:code"), "job1")
            await welcome.clip(self.db, http, "code", "k")  # перезапуск: тот же номер, новой оплаты нет
            self.assertEqual(http.posts, 1)
            self.assertAlmostEqual(await welcome._spent(self.db), 0.4, places=3)
        asyncio.run(go())

    def test_ceiling_blocks_order(self):
        async def go():
            await self.db.kv_set("welcome:spent", "1.20")
            http = FakeHttp()
            self.assertIsNone(await welcome.clip(self.db, http, "angel", "k"))  # 0,84 не влезает
            self.assertEqual(http.posts, 0)
        asyncio.run(go())

    def test_failed_order_not_repeated(self):
        async def go():
            http = FakeHttp(fail=True)
            with self.assertRaises(RuntimeError):
                await welcome.clip(self.db, http, "code", "k")
            self.assertIsNone(await welcome.clip(self.db, http, "code", "k"))
            self.assertEqual(http.posts, 1)
        asyncio.run(go())

    def test_publish_order_and_gap(self):
        async def go():
            await self.db.kv_set("welcome:urls", '{"angel_ru": "u1", "code_ru": "u2", "angel_en": "e1"}')
            sent, now = [], datetime(2026, 10, 30, 14, 0)

            async def pub(key, url):
                sent.append((key, url))
                return "ok"

            async def note(t):
                pass
            await welcome.publish_due(self.db, None, now, "ru", pub, note)
            await welcome.publish_due(self.db, None, now + timedelta(hours=1), "ru", pub, note)
            await welcome.publish_due(self.db, None, now + timedelta(hours=3), "ru", pub, note)
            await welcome.publish_due(self.db, None, now + timedelta(hours=7), "ru", pub, note)
            self.assertEqual(sent, [("angel", "u1"), ("code", "u2")])
        asyncio.run(go())

    def test_languages_not_mixed(self):
        from zavod import lang
        for spec in welcome.CLIPS.values():
            for _, _, t in spec["lines"]["en"]:
                self.assertFalse(lang.has_cyrillic(t))
            self.assertFalse(lang.has_cyrillic(spec["post"]["en"]))
            self.assertRegex(" ".join(t for _, _, t in spec["lines"]["ru"]), "[а-я]")

    def test_lines_never_overlap(self):
        spec = welcome.CLIPS["code"]
        rows, total = welcome.timeline(spec["lines"]["ru"], [2.2, 1.0, 6.5, 2.6], 15)
        for i in range(1, len(rows)):
            self.assertGreaterEqual(rows[i][0], rows[i - 1][1])  # надпись после надписи
        self.assertGreaterEqual(rows[3][2], rows[2][2] + 6.5)  # фраза после фразы
        self.assertGreaterEqual(total, rows[3][2] + 2.6)


if __name__ == "__main__":
    unittest.main()
