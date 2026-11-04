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

    def test_labels_are_off_by_owner_word(self):
        self.assertEqual(series.with_label("Пост про любовь", "text_marriage", False), "Пост про любовь")

    def test_label_added_last_and_respects_limit(self):
        series.LABELS_ENABLED = True
        self.addCleanup(setattr, series, "LABELS_ENABLED", False)
        text = series.with_label("Пост про любовь", "text_marriage", False)
        self.assertTrue(text.endswith("«Дата рождения и любовь»"))
        self.assertEqual(series.with_label("x" * 490, "text_marriage", False), "x" * 490)  # не влезло — без метки
        en = series.with_label("A post about love", "text_marriage", True)
        self.assertNotRegex(en, "[А-Яа-яЁё]")
        self.assertTrue(series.with_label("t", "text_pair_week", True).endswith("\"Couple of the week\""))
        self.assertEqual(series.with_label("t", "text_other", False), "t")

    def test_grid_window_on_wednesday_evening_is_not_less_than_other_days(self):
        plan = autopost.ContentPlan(autopost.load_rubrics(Path("prompts/content_plan.md")))
        def share(now):
            return sum(plan.choose(["text_x", "text_y", "text_z"], random.Random(i), now).key == "grid" for i in range(600)) / 600
        self.assertGreaterEqual(share(WED), share(MON) * 0.9)  # матрицам и так гарантирована доля; вечер среды её не снижает

    def test_topic_tags_follow_audience_interests_and_en_has_no_cyrillic(self):
        self.assertEqual(autopost.topic_tag_for("text_loves"), "Dating Threads")
        self.assertNotEqual(autopost.topic_tag_for("text_seek"), "Dating Threads")  # продажа, не про отношения
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

    def test_evening_rhythm_is_two_to_two_and_a_half_hours(self):
        self.assertEqual(autopost.PRIME_GAP, (120, 150))


class Economy(unittest.IsolatedAsyncioTestCase):
    def test_posts_per_day_dropped_to_about_five(self):
        import datetime as dt
        plan = autopost.ContentPlan(autopost.load_rubrics(Path("prompts/content_plan.md")))
        rng = random.Random(1)
        now, end, count = dt.datetime(2026, 11, 5, 0, 0), dt.datetime(2026, 12, 5, 0, 0), 0
        while now < end:
            now += plan.next_gap(now, rng)
            count += 1
        self.assertLess(count / 30, 6.5)
        self.assertGreater(count / 30, 3.5)

    def test_core_rubrics_dominate_the_feed(self):
        plan = autopost.ContentPlan(autopost.load_rubrics(Path("prompts/content_plan.md")))
        picks = [plan.choose(["text_x", "text_y", "text_z"], random.Random(i)).key for i in range(2000)]
        core = sum(k in autopost.CORE for k in picks) / len(picks)
        self.assertGreater(core, 0.75)

    async def test_gates_use_the_cheap_model_and_posts_the_main_one(self):
        from unittest.mock import AsyncMock, MagicMock
        from zavod import generator as G
        g = G.Generator.__new__(G.Generator)
        g.api_key, g.model, g.reply_model, g.system = "k", "anthropic/claude-sonnet-5-5", "anthropic/claude-haiku-5-5", "s"
        used = {}
        class Fake:
            def __call__(self, *a, **k): return self
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, headers=None, json=None):
                used.setdefault("models", []).append(json["model"])
                import httpx
                return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}, request=httpx.Request("POST", url))
        from unittest.mock import patch
        async def noop(*a, **k): pass
        g._record_cost = noop
        with patch("httpx.AsyncClient", Fake()):
            await g._complete("s", "p", kind="coherence")
            await g._complete("s", "p", kind="post")
        self.assertEqual(used["models"], ["anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5"])


class GridShare(unittest.TestCase):
    def test_matrices_get_about_fifteen_percent_even_with_optimizer_weights(self):
        plan = autopost.ContentPlan(autopost.load_rubrics(Path("prompts/content_plan.md")))
        plan.weights = {"grid": 1.0, "text_marriage": 3.0}  # оптимизатор мог занизить матрицу — гарантия доли всё равно работает
        rec, rng, count = [], random.Random(7), 0
        for _ in range(4000):
            key = plan.choose(rec, rng).key
            count += key == "grid"
            rec = [key] + rec[:5]
        self.assertGreater(count / 4000, 0.12)
        self.assertLess(count / 4000, 0.20)
