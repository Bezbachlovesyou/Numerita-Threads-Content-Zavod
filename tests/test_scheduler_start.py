import asyncio
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from zavod import bot, ops, pairstar_ai, reels


class EarlyMorning(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 25, 2, 5, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class SchedulerStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_reaches_next_iteration_in_both_languages(self):
        for en in (False, True):
            with self.subTest(en=en), ExitStack() as stack:
                db = SimpleNamespace(claim_slot=AsyncMock(return_value=False), kv_get=AsyncMock(return_value="1"))
                config = SimpleNamespace(timezone=timezone.utc, telegram_channel="", admin_ids=(), autoreply=False)
                threads = SimpleNamespace(paused=True)
                sleep = AsyncMock(side_effect=asyncio.CancelledError)
                stack.enter_context(patch.object(bot, "datetime", EarlyMorning))
                stack.enter_context(patch.object(bot, "asyncio", SimpleNamespace(create_task=asyncio.create_task, sleep=sleep)))
                stack.enter_context(patch.object(bot, "_DIGEST_DB", {}))
                stack.enter_context(patch.object(bot.lang, "is_en", return_value=en))
                stack.enter_context(patch.object(bot.funnel, "KEY", "fixture"))
                for module, names in (
                    (bot, ("retire_banned", "en_owner_tick")),
                    (bot.zero_research, ("send_admin_report",)),
                    (bot.brandvideo, ("run_once",)),
                    (bot.sketch, ("run_trial",)),
                    (pairstar_ai, ("run_once",)),
                    (bot.tgchannel, ("run_backfill", "announce_once", "remove_posts", "publish_sent_jokes",
                                     "fix_grid_post", "restyle", "drop", "drop_matching", "tick")),
                    (bot.performance, ("collect",)),
                    (bot.zero_cleanup, ("tick",)),
                    (bot.rework, ("scan_hits",)),
                    (ops, ("tick",)),
                    (reels, ("tick",)),
                    (bot.instagram, ("tick",)),
                    (bot.digest, ("due",)),
                ):
                    for name in names:
                        stack.enter_context(patch.object(module, name, AsyncMock(return_value=None)))
                stack.enter_context(patch.object(bot, "unpublish_matching", AsyncMock(return_value=[])))
                for module in (bot.constraint, bot.reminders, bot.profit):
                    stack.enter_context(patch.object(module, "run_due", AsyncMock(return_value=[])))
                with self.assertNoLogs(bot.log, level="ERROR"), self.assertRaises(asyncio.CancelledError):
                    await bot.run_scheduler(AsyncMock(), config, db, threads, SimpleNamespace(api_key=""),
                                            SimpleNamespace(enabled=False))
                sleep.assert_awaited_once_with(30)
