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
