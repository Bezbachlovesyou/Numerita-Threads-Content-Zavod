import asyncio
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from zavod import attribution as A, autopost, pdfpost
from zavod.lang import EN_SKIP_RUBRICS


class KV:
    def __init__(self):
        self.d = {}

    async def kv_get(self, k):
        return self.d.get(k)

    async def kv_set(self, k, v):
        self.d[k] = v


async def _rows(rows):
    return rows


class PdfPost(unittest.TestCase):
    def test_best_days_come_from_history(self):
        from datetime import timezone
        rows = []
        base = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)  # пн 19:00 МСК
        for week in range(4):
            for wd in range(7):
                t = base + timedelta(days=7 * week + wd)
                hit = wd in (2, 6)  # ср и вс — сильные дни
                rows.append({"published_at": t.isoformat(), "comments": 9 if hit else 1, "likes": 30 if hit else 3, "views": 2000 if hit else 200})
        db = KV()
        db.engagement = lambda since: _rows(rows)
        now = datetime(2026, 11, 29, 16, 30, tzinfo=timezone.utc)  # вс 19:30 МСК
        slots = asyncio.run(pdfpost.best_slots(db, now))
        self.assertTrue(slots["enough"])
        self.assertEqual(sorted(slots["weekdays"]), [2, 6])
        self.assertEqual(slots["part"], "evening")
        self.assertIn("ср", pdfpost.describe(slots))
        self.assertTrue(asyncio.run(pdfpost.due(db, now)))
        self.assertFalse(asyncio.run(pdfpost.due(db, now - timedelta(days=1))))  # суббота — не лучший день
        self.assertFalse(asyncio.run(pdfpost.due(db, now.replace(hour=8))))  # утро — не то окно


    def test_rubric_rules_and_weekly_gate(self):
        rubrics = {r.key: r for r in autopost.load_rubrics(Path("prompts/content_plan.md"))}
        text = rubrics["text_pdf"].text
        for part in ("больше 100 страниц", "Цену, скидки", "не диагноз", "Ссылку не пиши", "ХУК", "ЗАВЯЗКА", "РАЗВЯЗКА", "ИСКРОМЁТНАЯ", "пример страниц"):
            self.assertIn(part, text)
        self.assertIn("text_pdf", EN_SKIP_RUBRICS)
        label = A.parse(autopost.BOT_LINK + "pdf")
        self.assertEqual((label["kind"], label["name"]), ("static", "pdf"))
        db, now = KV(), datetime(2026, 11, 18, 13)
        db.engagement = lambda since: _rows([])  # данных мало — любой день, 12–22

        async def run():
            self.assertFalse(await pdfpost.due(db, now.replace(hour=9)))
            self.assertTrue(await pdfpost.due(db, now))
            await pdfpost.mark(db, now)
            self.assertFalse(await pdfpost.due(db, now + timedelta(days=6)))
            self.assertTrue(await pdfpost.due(db, now + timedelta(days=7)))
        asyncio.run(run())
        # обычный выбор рубрик никогда не берёт text_pdf сам
        import random
        plan = autopost.ContentPlan(list(rubrics.values()))
        picks = {plan.choose([], random.Random(i)).key for i in range(400)}
        self.assertNotIn("text_pdf", picks)

    def test_real_publish_path_sends_preview_in_text_mode(self):
        import os, tempfile
        from unittest.mock import AsyncMock, patch
        from zavod.bot import publish
        from zavod.storage import Storage
        from zavod.threads_api import ThreadsClient

        async def run():
            with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"THREADS_TEXT_ONLY": "1", "THREADS_GRID_EXCEPTION": "1"}):
                db = Storage(root + "/t.sqlite"); await db.init()
                ident = await db.add_draft("Тема", "Сто страниц о вас — и в каждой главе первая строка: что делать сегодня.", "text_pdf")
                api = ThreadsClient("fake", "fake")
                api._request = AsyncMock(return_value=(200, {"post": {"_id": str(ident)}}))
                api.upload_image = AsyncMock(return_value="https://cdn/pdf.jpg")
                with patch("zavod.pdfpost.hero_bytes", AsyncMock(return_value=b"jpg")):
                    result = await publish(await db.get(ident), db, api, None, "", cards=False)
                self.assertEqual(result.status, "published")
                body = api._request.call_args.kwargs["json"]
                self.assertEqual(body.get("mediaItems"), [{"type": "image", "url": "https://cdn/pdf.jpg"}])
                # превью не скачалось — пост всё равно выходит, текстом
                ident2 = await db.add_draft("Тема", "Книга о вас.", "text_pdf")
                with patch("zavod.pdfpost.hero_bytes", AsyncMock(side_effect=OSError("net"))):
                    result2 = await publish(await db.get(ident2), db, api, None, "", cards=False)
                self.assertEqual(result2.status, "published")
                self.assertNotIn("mediaItems", api._request.call_args.kwargs["json"])
        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
