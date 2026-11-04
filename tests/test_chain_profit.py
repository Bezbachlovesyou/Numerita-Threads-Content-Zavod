import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from zavod import bot as B
from zavod import chain, constraint, profit
from zavod.storage import PgStorage, Storage

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 31, 19, 5, tzinfo=TZ)


def funnel_data(came=100, new=60, wow=30, returned=10, paid=1, stars=99, **extra):
    return {"days": 7, "labels": [{"label": "th_x", "came": came, "new": new, "wow": wow, "returned": returned,
                                   "paid": paid, "stars": stars, **extra}]}


def cdata(**kw):
    base = {"days": 7, "posts": 10, "views": 5000, "views_posts": 10, "people": 40, "replies": 30, "linked": 6,
            "bot": {"came": 100, "new": 60, "wow": 30, "returned": 10, "paid": 1, "stars": 99, "usd": 0.0, "rub": 0.0}}
    base.update(kw)
    return base


class ChainLogic(unittest.TestCase):
    def test_weakest_is_lowest_rate_with_enough_sample(self):
        w = chain.weakest(cdata())  # доли 0,8% / 2% / 60% / 50% / 33% / 10% против ориентиров: хуже всех «пришли → новые» (0,75)
        self.assertEqual(w["kind"], "rate")
        self.assertIn("пришли → новые", w["link"])
        zero_pay = cdata(bot={"came": 100, "new": 90, "wow": 50, "returned": 20, "paid": 0, "stars": 0, "usd": 0.0, "rub": 0.0})
        self.assertIn("вернулись → оплатили", chain.weakest(zero_pay)["link"])  # 0 оплат при выборке 20 — это и есть узкое звено

    def test_top_of_funnel_small_share_is_not_mistaken_for_a_bottleneck(self):
        healthy = cdata(views=10000, people=80, bot={"came": 20, "new": 18, "wow": 12, "returned": 5, "paid": 1, "stars": 99, "usd": 0.0, "rub": 0.0})
        self.assertNotIn("просмотры", chain.weakest(healthy)["link"])

    def test_small_sample_is_not_zero_and_not_the_bottleneck(self):
        c = cdata(views=100, bot={"came": 3, "new": 1, "wow": 0, "returned": 0, "paid": 0, "stars": 0, "usd": 0.0, "rub": 0.0})
        w = chain.weakest(c)
        self.assertEqual(w["kind"], "sample")
        self.assertTrue(any("мало данных" in line for line in chain.lines(c)))

    def test_no_bot_data_means_measurement_is_the_bottleneck(self):
        w = chain.weakest(cdata(bot=None))
        self.assertEqual(w["kind"], "data")
        self.assertTrue(any("нет данных" in line for line in chain.lines(cdata(bot=None))))

    def test_value_per_touch_line_shows_link_share(self):
        self.assertTrue(any("ответов со ссылкой 20%" in line for line in chain.lines(cdata())))


class ValueGuard(unittest.TestCase):
    def test_pressure_is_rejected_value_is_kept(self):
        for bad in ("Ставь ссылку в каждом ответе", "Пиши: только сегодня скидка", "Добавь последний шанс", "Чаще ссылки"):
            self.assertTrue(constraint.PRESSURE.search(bad), bad)
        for good in ("Сначала назови число человека и дай одну точную фразу, потом спокойно предложи разбор",
                     "Больше юмора в первой строке"):
            self.assertFalse(constraint.PRESSURE.search(good), good)


class ProfitController(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def ledger(self, usd):
        await self.db.kv_set(f"cost:{NOW.date().isoformat()}", json.dumps({"post": [3, usd, 0, 0, 0]}))

    async def test_collect_reads_views_and_bot_totals(self):
        pid = await self.db.add_draft("x", "Пост", "text_seed")
        await self.db.set_threads_id(pid, "z")
        await self.db.mark_published(pid)
        await self.db.save_metrics(pid, 2, 1200)
        with patch.object(chain.funnel, "fetch", AsyncMock(return_value=funnel_data())):
            c = await chain.collect(self.db, datetime.now(TZ))
        self.assertEqual((c["posts"], c["views"], c["bot"]["came"], c["bot"]["stars"]), (1, 1200, 100, 99))

    async def test_unknown_revenue_closes_new_experiments(self):
        await self.ledger(1.0)
        with patch.object(chain.funnel, "fetch", AsyncMock(return_value=None)):
            st = await profit.state(self.db, NOW)
            ok, why = await profit.allow(self.db, "video", 0.5, NOW)
        self.assertEqual(st["status"], "unknown")
        self.assertFalse(ok)
        self.assertIn("выручка неизвестна", why)

    async def test_owner_yes_opens_exactly_that_sum_and_records_spend(self):
        await self.ledger(1.0)
        await profit.authorize(self.db, "video", 1.0)
        with patch.object(chain.funnel, "fetch", AsyncMock(return_value=None)):
            self.assertTrue((await profit.allow(self.db, "video", 0.6, NOW))[0])
            self.assertFalse((await profit.allow(self.db, "video", 0.6, NOW))[0])  # осталось $0,40
            self.assertTrue((await profit.allow(self.db, "video", 0.4, NOW))[0])
        self.assertAlmostEqual((await profit.costs(self.db, NOW))["experiments"], 1.0, places=2)

    async def test_plus_week_allows_a_share_of_revenue(self):
        await self.ledger(0.5)
        # 1000 ⭐ ≈ $13 выручки при расходах $0,5 → плюс; на опыты 30% = $3,9
        with patch.object(chain.funnel, "fetch", AsyncMock(return_value=funnel_data(stars=1000, paid=10))):
            st = await profit.state(self.db, NOW)
            self.assertEqual(st["status"], "plus")
            self.assertTrue((await profit.allow(self.db, "ads", 3.0, NOW))[0])
            self.assertFalse((await profit.allow(self.db, "ads", 3.0, NOW))[0])  # доля выручки уже потрачена

    async def test_minus_alarm_once_per_three_days_and_receipt_per_slot(self):
        await self.ledger(5.0)
        with patch.object(chain.funnel, "fetch", AsyncMock(return_value=funnel_data(stars=99, paid=1))):
            first = await profit.run_due(self.db, NOW, TZ)
            self.assertTrue(first and first[0].startswith("‼️ Контролёр прибыли"))
            self.assertEqual(await profit.run_due(self.db, NOW, TZ), [])  # тот же слот — не повторять
            later = NOW.replace(hour=11) + timedelta(days=1)  # другой слот, но алярм не чаще раза в 3 дня
            self.assertEqual([n for n in await profit.run_due(self.db, later, TZ) if n.startswith("‼️")], [])
            much_later = NOW.replace(hour=11) + timedelta(days=4)
            await self.db.kv_set(f"cost:{much_later.date().isoformat()}", json.dumps({"post": [1, 5.0, 0, 0, 0]}))
            again = await profit.run_due(self.db, much_later, TZ)
            self.assertTrue(again and again[0].startswith("‼️"))

    async def test_loss_budget_keeps_small_minus_quiet(self):
        await self.ledger(2.0)
        await self.db.kv_set("profit:loss_budget", "5.00")
        with patch.object(chain.funnel, "fetch", AsyncMock(return_value=funnel_data(stars=0, paid=0))):
            st = await profit.state(self.db, NOW)
            self.assertEqual(st["status"], "minus_in_budget")
            notices = await profit.run_due(self.db, NOW, TZ)
        self.assertFalse(any(n.startswith("‼️") for n in notices))

    async def test_snapshot_history_is_stored(self):
        with patch.object(chain.funnel, "fetch", AsyncMock(return_value=funnel_data())):
            await profit.run_due(self.db, NOW, TZ)
        self.assertIsNotNone(await self.db.kv_get(f"chain:{NOW.date().isoformat()}:{NOW.hour}"))

    async def test_pult_approve_spend_authorizes_and_sets_budget(self):
        sent = []
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: sent.append(t))):
            await B.run_op({"id": "a1", "action": "approve_spend", "label": "video", "usd": 1.5, "loss_budget": 3},
                           self.db, None, None, None)
        self.assertEqual(await self.db.kv_get("profit:auth:video"), "1.5000")
        self.assertEqual(await self.db.kv_get("profit:loss_budget"), "3.00")
        self.assertIn("разрешено $1.50", sent[0])


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "нужен TEST_POSTGRES_DSN")
class ProfitControllerPostgres(ProfitController):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PgStorage(os.environ["TEST_POSTGRES_DSN"])
        await self.db.init()
        for table in ("post_metrics", "posts", "kv", "autopost_slots"):
            await self.db._execute(f"DELETE FROM {table}")


if __name__ == "__main__":
    unittest.main()


class GamesLine(unittest.TestCase):
    def test_games_line_shows_k_and_is_silent_without_data(self):
        from zavod import funnel
        self.assertEqual(funnel.games_lines({"games": {"redflag": {"started": 0}}}), [])
        self.assertEqual(funnel.games_lines(None), [])
        line = funnel.games_lines({"games": {"redflag": {"started": 20, "finished_first": 12, "pressed_invite": 5, "friends_came": 4,
                                                          "friends_finished": 3, "k": 0.25}}})[0]
        self.assertIn("начали 20", line)
        self.assertIn("K=0.25", line)
