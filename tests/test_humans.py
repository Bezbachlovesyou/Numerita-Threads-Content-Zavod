import tempfile
import unittest
from datetime import datetime, timezone

from zavod import humans
from zavod.storage import Storage


class Humans(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_empty_base_is_stated(self):
        self.assertIn("нет комментариев", await humans.report(self.db, datetime.now(timezone.utc)))

    async def test_real_looking_comments_are_not_flagged_and_bot_patterns_are(self):
        for i, text in enumerate(["Мне 17, а что значит число?", "Родилась 12 июня, расскажите про судьбу", "Как понять, какое число ведёт меня?", "26.06.57"]):
            await self.db.record_comment(f"h{i}", 1, f"person{i}", text, "ответ", "replied")
        out = await humans.report(self.db, datetime.now(timezone.utc))
        self.assertIn("Похоже на людей", out)
        for i in range(4):
            await self.db.record_comment(f"b{i}", i + 1, f"spam{i}", "Check my profile, link in bio, earn money fast", "skip:promo", "skipped")
        out = await humans.report(self.db, datetime.now(timezone.utc))
        self.assertIn("Заметная доля похожа на ботов", out)
        self.assertIn("доказать нельзя", out)


if __name__ == "__main__":
    unittest.main()
