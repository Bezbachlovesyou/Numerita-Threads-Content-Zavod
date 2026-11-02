import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from zavod import bot as B
from zavod.storage import Storage

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


class Banned(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_banned_first_lines(self):
        for text in ("Объяснительная от шестёрки\nЯ не виновата", "  Жалоба от тройки: ...", "Explanatory note from a Six\nI did not do it"):
            self.assertTrue(B.banned_format(text), text)
        for text in ("Родился 6-го? Это про тебя", "В объяснительной нет ничего смешного\nна самом деле", "", "Complaint-free Sixes\nare rare"):
            self.assertFalse(B.banned_format(text), text)

    def test_daily_notes_are_off(self):
        self.assertFalse(B.NOTES_ENABLED)

    async def published(self, text, hours=5):
        ident = await self.db.add_draft("t", text, "text_free")
        await self.db.set_threads_id(ident, f"r{ident}")
        await self.db.mark_published(ident)
        await self.db._execute("UPDATE posts SET published_at = ? WHERE id = ?", ((NOW - timedelta(hours=hours)).isoformat(), ident))
        return ident

    def threads(self, likes=0, comments=0, final="cancelled"):
        t = MagicMock()
        t.account_id = "ours"
        t.post_stats = AsyncMock(return_value={"platformAnalytics": [{"platform": "threads", "syncStatus": "synced",
                                    "analytics": {"likes": likes, "comments": 0, "lastUpdated": NOW.isoformat()}}]})
        t._request = AsyncMock(return_value=(200, {"comments": [{"id": "x"}] * comments}))
        t.unpublish = AsyncMock()
        t.post_status = AsyncMock(return_value=(final, None, None))
        return t

    async def test_retires_zero_reaction_banned_post_and_reports_by_receipt(self):
        bad = await self.published("Объяснительная от шестёрки\nЯ не виновата")
        ok = await self.published("Родился 6-го? Это про тебя")
        t, notes = self.threads(), []
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, text: notes.append(text))):
            await B.retire_banned(self.db, t, MagicMock(), MagicMock(), NOW)
        t.unpublish.assert_awaited_once_with(f"r{bad}")
        self.assertEqual((await self.db.get(bad)).status, "deleted")
        self.assertEqual((await self.db.get(ok)).status, "published")
        self.assertTrue(notes and "Снят пост" in notes[0])

    async def test_post_with_reaction_or_unconfirmed_removal_is_kept(self):
        liked = await self.published("Жалоба от тройки")
        t = self.threads(likes=5)
        with patch.object(B, "notify_admins", AsyncMock()):
            await B.retire_banned(self.db, t, MagicMock(), MagicMock(), NOW)
        t.unpublish.assert_not_awaited()
        t = self.threads(final="published")  # площадка всё ещё показывает пост — «снят» не пишем
        notes = []
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, text: notes.append(text))):
            await B.retire_banned(self.db, t, MagicMock(), MagicMock(), NOW)
        self.assertEqual((await self.db.get(liked)).status, "published")
        self.assertTrue(notes and "не снялся" in notes[0])


if __name__ == "__main__":
    unittest.main()
