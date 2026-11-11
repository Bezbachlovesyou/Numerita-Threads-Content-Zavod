import unittest
from datetime import datetime, timedelta, timezone

from zavod import bot as B


class OpsAfter(unittest.IsolatedAsyncioTestCase):
    """Отложенная команда пульта ждёт своего времени и не выходит наугад."""

    async def test_waits_until_time_then_goes(self):
        later = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        earlier = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.assertFalse(await B.op_ready({"id": "a", "action": "tell", "after": later}, None, None))
        self.assertTrue(await B.op_ready({"id": "b", "action": "tell", "after": earlier}, None, None))
        self.assertFalse(await B.op_ready({"id": "c", "action": "tell", "after": "вечером"}, None, None))
        self.assertFalse(await B.op_ready({"id": "d", "action": "tell", "after": "2099-11-12T18:30:00"}, None, None))  # без пояса — не выпускаем


if __name__ == "__main__":
    unittest.main()
