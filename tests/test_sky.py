import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from zavod import bot as B
from zavod.skyevents import upcoming
from zavod.storage import Storage


class Sky(unittest.IsolatedAsyncioTestCase):
    def test_venus_turns_direct_on_14_november_2026(self):
        lines = upcoming(datetime(2026, 11, 12, tzinfo=timezone.utc), 4)
        self.assertTrue(any("Венера разворачивается вперёд" in l and "14.11" in l for l in lines))

    async def test_venus_post_reports_only_confirmed_link(self):
        tmp = tempfile.TemporaryDirectory()
        db = Storage(tmp.name + "/t.db")
        await db.init()
        threads = AsyncMock()
        threads.upload_image.return_value = "https://v/venus.mp4"
        threads.publish_text.return_value = "z7"
        threads.post_status.side_effect = [("publishing", None, None), ("published", "https://threads.net/p/v", None)]
        sent = []
        with patch("zavod.venusrose.render_video", return_value=b"mp4"), \
             patch("zavod.bot.asyncio.sleep", AsyncMock()), \
             patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: sent.append(t))):
            await B.venus_post(db, threads, None, None)
        self.assertEqual(threads.publish_text.await_args.kwargs["media_kind"], "sky_video")
        self.assertIn("https://threads.net/p/v", sent[0])
        tmp.cleanup()
