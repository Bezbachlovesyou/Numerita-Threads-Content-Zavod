import random
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from zavod import autopost, series
from zavod.storage import Storage

WED = datetime(2026, 11, 4, 19, 0, tzinfo=timezone.utc)   # среда 19:00
THU = datetime(2026, 11, 5, 19, 0, tzinfo=timezone.utc)
SUN = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)
MON = datetime(2026, 11, 2, 19, 0, tzinfo=timezone.utc)


class Series(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.sqlite")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_windows_once_per_window_and_only_in_hours(self):
        self.assertEqual((await series.due(self.db, THU))[2], "text_marriage")
        await series.mark(self.db, THU, "text_marriage")
        self.assertIsNone(await series.due(self.db, THU))
        self.assertEqual((await series.due(self.db, SUN))[2], "text_roles")
        self.assertIsNone(await series.due(self.db, MON))
        self.assertIsNone(await series.due(self.db, THU.replace(hour=12)))

    def test_label_added_last_and_respects_limit(self):
        text = series.with_label("Пост про любовь", "text_marriage", False)
        self.assertTrue(text.endswith("«Дата рождения и любовь»"))
        self.assertEqual(series.with_label("x" * 490, "text_marriage", False), "x" * 490)  # не влезло — без метки
        en = series.with_label("A post about love", "text_marriage", True)
        self.assertNotRegex(en, "[А-Яа-яЁё]")
        self.assertTrue(series.with_label("t", "text_pair_week", True).endswith("\"Couple of the week\""))
        self.assertEqual(series.with_label("t", "text_other", False), "t")

    def test_grid_window_boosts_the_matrix_on_wednesday_evening_only(self):
        plan = autopost.ContentPlan(autopost.load_rubrics(Path("prompts/content_plan.md")))
        def share(now):
            return sum(plan.choose(["text_x", "text_y", "text_z"], random.Random(i), now).key == "grid" for i in range(600)) / 600
        self.assertGreater(share(WED), share(MON) * 2.5)

    def test_topic_tags_follow_audience_interests_and_en_has_no_cyrillic(self):
        self.assertEqual(autopost.topic_tag_for("text_loves"), "Dating Threads")
        self.assertEqual(autopost.topic_tag_for("text_fears"), "психология")
        self.assertEqual(autopost.topic_tag_for("text_baza"), "Нумерология")


if __name__ == "__main__":
    unittest.main()


class Suppressed(unittest.TestCase):
    def test_failing_formats_are_almost_gone_and_genres_removed(self):
        from zavod import postmatrix as P
        rng = random.Random(5)
        genres = {P.sample(rng, "ru", "text_free", [], {}, {})["genre"] for _ in range(400)}
        self.assertNotIn("scene", genres)
        self.assertNotIn("sitcom", genres)
        plan = autopost.ContentPlan(autopost.load_rubrics(Path("prompts/content_plan.md")))
        picks = [plan.choose([], random.Random(i)).key for i in range(1500)]
        suppressed = sum(k in autopost.SUPPRESSED for k in picks) / len(picks)
        self.assertLess(suppressed, 0.03)

    def test_evening_rhythm_is_sixty_to_seventy_five_minutes(self):
        self.assertEqual(autopost.PRIME_GAP, (60, 75))
