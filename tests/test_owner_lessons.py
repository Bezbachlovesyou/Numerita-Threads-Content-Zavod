import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from zavod import owner_lessons as L, reminders
from zavod.storage import Storage

TZ = ZoneInfo("Europe/Moscow")


class Lessons(unittest.IsolatedAsyncioTestCase):
    def test_every_lesson_is_short_and_has_the_three_parts(self):
        for i in range(len(L.LESSONS)):
            text = L.lesson_text(i)
            self.assertLessEqual(len(text), 520, i)  # коротко: слово владельца про внимание
            self.assertIn("📘", text)
            self.assertIn("🧩 У нас:", text)
        titles = " ".join(t for t, *_ in L.LESSONS)
        for word in ("Голдратт", "Теории роста", "ТРИЗ"):
            self.assertIn(word, titles)

    async def test_one_lesson_a_day_in_order_and_cycles(self):
        tmp = tempfile.TemporaryDirectory()
        db = Storage(tmp.name + "/t.sqlite")
        await db.init()
        day = datetime(2026, 11, 6, 10, 30, tzinfo=TZ)
        first = [m for m in await reminders.run_due(db, day, TZ) if m.startswith("📘")]
        self.assertEqual(len(first), 1)
        self.assertIn("Урок 1 из", first[0])
        again = [m for m in await reminders.run_due(db, day + timedelta(minutes=30), TZ) if m.startswith("📘")]
        self.assertEqual(again, [])
        nxt = [m for m in await reminders.run_due(db, day + timedelta(days=1), TZ) if m.startswith("📘")]
        self.assertIn("Урок 2 из", nxt[0])
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
