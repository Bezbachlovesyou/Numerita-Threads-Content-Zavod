import json
import tempfile
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from zavod import costs
from zavod.storage import Storage

TZ = ZoneInfo("Europe/Moscow")


class Days(unittest.IsolatedAsyncioTestCase):
    async def test_breakdown_by_article_and_day(self):
        tmp = tempfile.TemporaryDirectory()
        db = Storage(tmp.name + "/t.sqlite")
        await db.init()
        today = datetime.now(TZ).date().isoformat()
        await db.kv_set(f"cost:{today}", json.dumps({"post": [4, 0.40, 1, 1, 0], "reply·haiku": [10, 0.10, 1, 1, 0], "art": [2, 0.20, 1, 1, 0]}))
        state = {"key": {"usage_daily": 0.7, "usage_weekly": 10.31}, "credits": {"total_credits": 30, "total_usage": 25}, "price": {}}
        gen = MagicMock(api_key="k", model="m")
        with patch.object(costs, "openrouter_state", AsyncMock(return_value=state)):
            text = await costs.report_days(db, gen, TZ, 3)
        self.assertIn("Баланс счёта сейчас: $5.00", text)
        self.assertIn("за неделю $10.31", text)
        self.assertIn("$0.70", text)
        self.assertIn("учёта нет", text)  # дни без записей честно названы
        self.assertIn("в OpenRouter → Activity", text)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()


class OpenRouterReport(unittest.IsolatedAsyncioTestCase):
    async def test_without_management_key_it_explains_the_one_step(self):
        text = await costs.openrouter_report("")
        self.assertIn("Management Keys", text)
        self.assertIn("OPENROUTER_MANAGEMENT_KEY", text)

    async def test_report_shows_keys_models_and_days(self):
        import httpx

        class Fake:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, params=None):
                req = httpx.Request("GET", url)
                if url.endswith("/keys"):
                    return httpx.Response(200, request=req, json={"data": [
                        {"name": "Numerita bot", "usage_daily": 0.3, "usage_weekly": 1.29, "usage_monthly": 1.88},
                        {"name": "dev", "usage_daily": 0, "usage_weekly": 32.0, "usage_monthly": 33.0, "disabled": False}]})
                return httpx.Response(200, request=req, json={"data": [
                    {"model": "anthropic/claude-sonnet-5-5", "usage": 2.0}, {"model": "anthropic/claude-haiku-5-5", "usage": 0.5}]})
        with patch("httpx.AsyncClient", Fake):
            text = await costs.openrouter_report("mk", 2)
        self.assertIn("dev: $0.00 / $32.00 / $33.00", text)
        self.assertIn("claude-sonnet-5-5: $4.00 (80%)", text)  # два дня по $2.00
        self.assertIn("По дням (UTC)", text)


class PostCost(unittest.IsolatedAsyncioTestCase):
    async def test_weighted_average_over_all_created_and_alive_posts(self):
        tmp = tempfile.TemporaryDirectory()
        db = Storage(tmp.name + "/t.sqlite")
        await db.init()
        today = datetime.now(TZ).date().isoformat()
        await db.kv_set(f"cost:{today}", json.dumps({"post": [4, 1.0, 1, 1, 0], "art": [4, 0.2, 1, 1, 0]}))
        for i in range(4):
            ident = await db.add_draft("t", f"post {i}", "text_free")
            if i < 2:
                await db.set_threads_id(ident, f"r{i}")
                await db.mark_published(ident)
            else:
                await db.delete(ident)
        line = await costs.post_cost_line(db, TZ, 3)
        self.assertIn("$1.20 ÷ 4 созданных = $0.30", line)
        self.assertIn("на один оставшийся живым (2) = $0.60", line)
        tmp.cleanup()
