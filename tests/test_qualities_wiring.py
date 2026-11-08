import json
import random
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from zavod import autopost, lang, qualities3d as Q, text_mode
from zavod import bot as B
from zavod.storage import Storage

PLAN = Path(__file__).resolve().parent.parent / "prompts" / "content_plan.md"


class Wiring(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()
        self.rubric = next(r for r in autopost.load_rubrics(PLAN) if r.key == "text_spin")
        self.slot = autopost.Slot("spin-test", datetime.now(timezone.utc), self.rubric, "тема", "spin")
        self.cfg = MagicMock(cards=False)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_rubric_is_known_and_ru_only(self):
        self.assertTrue(text_mode.allowed(self.rubric))
        self.assertIn("text_spin", lang.EN_SKIP_RUBRICS)
        self.assertIn("text_spin", autopost.CORE)

    def test_reply_notes(self):
        spin = {"digit": 1, "shape": "heart", "options": [1, 3, 5, 7]}
        self.assertIn("верно", Q.reply_note(spin, "Это 1!"))
        wrong = Q.reply_note(spin, "думаю 5")
        self.assertIn("не угадал", wrong)
        self.assertIn("1 · 10 · 19 · 28", wrong)
        self.assertIn("не нашёл", Q.reply_note(spin, "красиво"))
        self.assertIsNone(Q.guess_of("родилась 5 мая 1990", [1, 3, 5, 7]))   # дата — не ответ
        self.assertIsNone(Q.guess_of("15.05", [1, 3, 5, 7]))
        self.assertEqual(Q.guess_of("точно 7", [1, 3, 5, 7]), 7)
        self.assertIsNone(Q.guess_of("2", [1, 3, 5, 7]))                       # числа нет среди вариантов

    async def test_autopost_creates_rotating_posts(self):
        published = []

        async def fake_publish(post, *a, **k):
            published.append(post)
            return post
        with patch.object(B, "publish", side_effect=fake_publish), patch.object(B, "notify_admins", AsyncMock()):
            for _ in range(2):
                self.assertTrue(await B.spin_autopost(self.cfg, self.db, None, MagicMock(), self.slot, datetime.now(timezone.utc), random.Random(1)))
        self.assertEqual([p.rubric for p in published], ["text_spin", "text_spin"])
        first, second = (Q.spin_data(p.card) for p in published)
        self.assertEqual((first["digit"], first["shape"]), (1, "heart"))
        self.assertEqual((second["digit"], second["shape"]), (2, "sphere"))
        for p, spin in zip(published, (first, second)):
            self.assertIn(spin["digit"], spin["options"])
            self.assertFalse(lang.has_cyrillic(None))
            self.assertLessEqual(len(p.text), 500)
        found = await Q.spin_of(self.db, published[0].id)
        self.assertEqual(found["digit"], 1)
        await Q.record(self.db, published[0].id, "c1", found, "1")
        await Q.record(self.db, published[0].id, "c1", found, "1")           # повтор того же комментария не считаем
        await Q.record(self.db, published[0].id, "c2", found, "7")
        data = json.loads(await self.db.kv_get(f"spin:{published[0].id}"))
        self.assertEqual((data["n"], data["right"]), (2, 1))

    async def test_publish_sends_video_with_media_kind(self):
        post_id = await self.db.add_draft("t", "Эти слова кружатся…", "text_spin", None,
                                          json.dumps({"anim": True, "spin": {"digit": 1, "shape": "heart", "options": [1, 3, 5, 7], "seed": "s"}}))
        threads = MagicMock()
        threads.upload_image = AsyncMock(return_value="https://zernio/video.mp4")
        threads.publish_text = AsyncMock(return_value="th1")
        with patch.object(Q, "render_video", return_value=b"mp4"):
            post = await B.publish(await self.db.get(post_id), self.db, threads, MagicMock(), "", False)
        args, kwargs = threads.publish_text.call_args
        self.assertEqual(kwargs["media_kind"], "qualities_video")
        self.assertEqual(args[4], "https://zernio/video.mp4")
        self.assertEqual(post.threads_id, "th1")

    async def test_no_video_no_post(self):
        post_id = await self.db.add_draft("t", "Эти слова…", "text_spin", None,
                                          json.dumps({"anim": True, "spin": {"digit": 1, "shape": "heart", "options": [1, 3, 5, 7], "seed": "s"}}))
        threads = MagicMock()
        threads.upload_image = AsyncMock(side_effect=RuntimeError("нет сети"))
        threads.publish_text = AsyncMock(return_value="th1")
        with patch.object(Q, "render_video", return_value=b"mp4"), patch.object(B, "notify_admins", AsyncMock()):
            await B.publish(await self.db.get(post_id), self.db, threads, MagicMock(), "", False)
        threads.publish_text.assert_not_called()
        print("OK")


if __name__ == "__main__":
    unittest.main()
