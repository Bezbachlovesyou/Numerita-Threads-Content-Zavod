import asyncio
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from zavod import bot as B
from zavod import chain, optimizer, reminders, welcome
from zavod.storage import PgStorage, Storage

TZ = ZoneInfo("Europe/Moscow")
MORNING = datetime(2026, 11, 1, 10, 30, tzinfo=TZ)


class Reminders(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_civilization_every_three_days_in_the_morning_only(self):
        first = await reminders.run_due(self.db, MORNING, TZ)
        self.assertTrue(first and first[0].startswith("🌍 Масштаб"))
        self.assertEqual(await reminders.run_due(self.db, MORNING + timedelta(hours=1), TZ), [])  # тот же день — без повтора
        self.assertEqual([m for m in await reminders.run_due(self.db, MORNING + timedelta(days=2), TZ) if not m.startswith('📘')], [])
        third = await reminders.run_due(self.db, MORNING + timedelta(days=3), TZ)
        self.assertTrue(third and third[0] != first[0])  # формулировки идут по кругу
        evening = MORNING.replace(hour=21) + timedelta(days=9)
        self.assertEqual(await reminders.run_due(self.db, evening, TZ), [])  # вечером не беспокоим

    async def test_ideas_are_remembered_and_reminded_weekly(self):
        self.assertTrue(await reminders.add_idea(self.db, "twin", "Цифровой двойник близкого", MORNING))
        self.assertFalse(await reminders.add_idea(self.db, "twin", "Цифровой двойник близкого", MORNING))  # повтор не плодит
        first = await reminders.run_due(self.db, MORNING, TZ)
        self.assertTrue(any("Цифровой двойник близкого" in m for m in first))
        later = await reminders.run_due(self.db, MORNING + timedelta(days=3), TZ)
        self.assertFalse(any("💡" in m for m in later))
        week = await reminders.run_due(self.db, MORNING + timedelta(days=7), TZ)
        self.assertTrue(any("💡" in m for m in week))
        self.assertTrue(await reminders.close_idea(self.db, "twin"))
        self.assertFalse(any("💡" in m for m in await reminders.run_due(self.db, MORNING + timedelta(days=14), TZ)))

    async def test_pult_idea_saves_title_and_sends_full_text(self):
        sent = []
        cfg = SimpleNamespace(timezone=TZ, admin_ids=[1])
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: sent.append(t))):
            await B.run_op({"id": "i1", "action": "idea", "title": "Двойник", "text": "Подробности идеи"}, self.db, None, None, cfg)
            await B.run_op({"id": "i1", "action": "idea", "title": "Двойник", "text": "Подробности идеи"}, self.db, None, None, cfg)
            await B.run_op({"id": "i2", "action": "idea", "text": "без названия"}, self.db, None, None, cfg)
        self.assertIn("записана: Двойник", sent[0])
        self.assertIn("Подробности идеи", sent[0])
        self.assertIn("уже была записана", sent[1])
        self.assertIn("без названия", sent[2])
        self.assertEqual(len(await reminders.ideas(self.db)), 1)


class ResendClips(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()
        self.cfg = SimpleNamespace(timezone=TZ, admin_ids=[7])

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_four_clips_with_captions_and_instructions(self):
        urls = {f"{k}_{c}": f"https://cdn.example/{k}_{c}.mp4" for k in ("angel", "code") for c in ("ru", "en")}
        await self.db.kv_set("welcome:urls", json.dumps(urls))
        bot, notified = MagicMock(), []
        bot.send_message, bot.send_video = AsyncMock(), AsyncMock()

        class Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url): return SimpleNamespace(status_code=200, content=b"x" * 60_000)

        with patch("httpx.AsyncClient", Client), \
             patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: notified.append(t))):
            await B.resend_clips(bot, self.cfg, self.db, "")
        self.assertIn("Instagram", notified[0])
        self.assertIn("Языки не мешать", notified[0])
        self.assertEqual(bot.send_video.await_count, 4)
        captions = [c.args[1] for c in bot.send_message.await_args_list if c.args[1].startswith("<pre>")]
        self.assertEqual(len(captions), 4)  # подпись — отдельным сообщением для копирования, с хэштегами
        self.assertTrue(all("#" in c for c in captions))
        for cap in captions:
            self.assertNotIn("t.me/", cap)  # в подписи Instagram ссылки нет
        en = [c for c in captions if "Your birthday" in c or "Born on" in c]
        self.assertTrue(en and all(not re.search("[А-Яа-яЁё]", c) for c in en))  # английская подпись без русских букв
        ru = [c for c in captions if re.search("[А-Яа-яЁё]", c)]
        self.assertTrue(all("шапке профиля" in c for c in ru))
        heads = [c.args[1] for c in bot.send_message.await_args_list]
        self.assertTrue(any("numerita.love" in h for h in heads) and any("numerita.ai" in h for h in heads))

    async def test_no_clips_in_base_says_so_instead_of_paying_again(self):
        bot, notified = MagicMock(), []
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: notified.append(t))):
            await B.resend_clips(bot, self.cfg, self.db, "")
        self.assertIn("нужна смета", notified[0])


class OutcomeOptimization(unittest.TestCase):
    def test_by_rubric_reads_post_tags_only(self):
        data = {"labels": [
            {"label": "th_text_seek4_3110", "came": 12, "new": 9, "paid": 1, "stars": 99},
            {"label": "th_text_seek4_3110_lt", "came": 3, "new": 2, "paid": 0, "stars": 0},
            {"label": "th_r123_a", "came": 5, "new": 5, "paid": 1, "stars": 99},  # ответ — не рубрика
            {"label": "th_bio", "came": 20, "new": 10, "paid": 0, "stars": 0}]}
        got = chain.by_rubric(data)
        self.assertEqual(set(got), {"text_seek"})
        self.assertEqual((got["text_seek"]["came"], got["text_seek"]["paid"]), (15, 1))

    def test_payment_boosts_rubric_but_small_samples_and_off_rubrics_are_left_alone(self):
        w = {"text_seek": 1.0, "text_loves": 0.0}
        out = optimizer.outcome_weights(w, {"text_seek": {"came": 15, "paid": 1}, "text_loves": {"came": 30, "paid": 2},
                                            "text_wealth": {"came": 5, "paid": 1}, "text_roles": {"came": 40, "paid": 0}})
        self.assertEqual(out["text_seek"], 1.3)
        self.assertEqual(out["text_loves"], 0.0)  # выключенную не включаем
        self.assertNotIn("text_wealth", out)  # мало пришедших — не сигнал
        self.assertNotIn("text_roles", out)  # без оплат ничего не меняем
        two = optimizer.outcome_weights({"text_seek": 2.5}, {"text_seek": {"came": 20, "paid": 2}})
        self.assertEqual(two["text_seek"], 3.0)  # потолок

    def test_subscription_fields_unknown_is_none_not_zero(self):
        c = {"days": 7, "posts": 1, "views": 1000, "views_posts": 1, "people": 5, "replies": 2, "linked": 0, "rubrics": {},
             "bot": {"came": 10, "new": 8, "wow": 4, "returned": 2, "paid": 1, "stars": 99, "usd": 0.0, "rub": 0.0,
                     "subs_new": None, "subs_active": None, "renewed": None, "refunds": None}}
        self.assertFalse(any("подписки:" in line for line in chain.lines(c)))
        c["bot"].update(subs_new=2, subs_active=5, renewed=1)
        self.assertTrue(any("подписки: новых 2, активных 5" in line for line in chain.lines(c)))


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "нужен TEST_POSTGRES_DSN")
class RemindersPostgres(Reminders):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PgStorage(os.environ["TEST_POSTGRES_DSN"])
        await self.db.init()
        for table in ("kv", "autopost_slots"):
            await self.db._execute(f"DELETE FROM {table}")


if __name__ == "__main__":
    unittest.main()


class SendAssets(unittest.IsolatedAsyncioTestCase):
    async def test_only_cover_files_are_sent_as_documents(self):
        cfg = SimpleNamespace(timezone=TZ, admin_ids=[7])
        bot, notified = MagicMock(), []
        bot.send_document, bot.send_message = AsyncMock(), AsyncMock()

        class Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, params=None): return SimpleNamespace(status_code=200, content=b"x" * 100)

        with patch("httpx.AsyncClient", Client), \
             patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: notified.append(t))):
            await B.send_assets(bot, cfg, ["assets/cover/a.jpg", "zavod/config.py", "assets/cover/../x"], "Инструкция", "")
        self.assertEqual(bot.send_document.await_count, 1)
        self.assertEqual(bot.send_document.await_args.args[1].filename, "a.jpg")
        self.assertEqual(notified[0], "Инструкция")
        self.assertEqual(sum("не из assets/cover" in n for n in notified), 2)

    async def test_accounts_check_reports_names_and_counts_only(self):
        cfg = SimpleNamespace(timezone=TZ, admin_ids=[7])
        notified = []
        threads = MagicMock()
        threads._request = AsyncMock(return_value=(200, {"accounts": [
            {"platform": "threads", "_id": "SECRET1"}, {"platform": "threads", "_id": "SECRET2"}, {"platform": "instagram", "_id": "SECRET3"}]}))
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: notified.append(t))):
            await B.accounts_check(None, cfg, threads, "")
        self.assertIn("instagram — 1", notified[0])
        self.assertIn("threads — 2", notified[0])
        self.assertIn("Facebook в Zernio НЕ подключён", notified[0])
        self.assertNotIn("SECRET", notified[0])
