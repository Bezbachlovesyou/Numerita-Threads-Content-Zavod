import os
import random
import tempfile
import unittest
from datetime import datetime, timezone

from zavod import postmatrix as P
from zavod import text_mode
from zavod.storage import PgStorage, Storage

NOW = datetime.now(timezone.utc)


class Catalog(unittest.TestCase):
    def test_at_least_a_hundred_parameters_with_unique_ids(self):
        self.assertGreaterEqual(P.total_values("ru"), 100)
        self.assertGreaterEqual(P.total_values("en"), 100)
        self.assertEqual(P.total_values("ru"), 128)
        for name in P.ORDER:
            ids = [e[0] for e in P.axis(name)]
            self.assertEqual(len(ids), len(set(ids)), name)
            self.assertTrue(all(len(e) == 3 and e[1] and e[2] for e in P.axis(name)), name)

    def test_voices_are_per_language_and_many_genres_exist(self):
        self.assertGreaterEqual(len(P.GENRES), 24)
        ru = {e[0] for e in P.axis("voice", "ru")}
        en = {e[0] for e in P.axis("voice", "en")}
        self.assertTrue({"zhvanetsky", "zadornov", "volya", "martirosyan"} <= ru)
        self.assertTrue({"seinfeld", "wilde", "twain", "wodehouse"} <= en)
        self.assertNotIn("seinfeld", ru)

    def test_catalog_doc_is_in_sync(self):
        self.assertEqual(open("docs/post-parameters.md", encoding="utf-8").read().strip(), P.catalog_md().strip())


class Sampling(unittest.TestCase):
    def draw(self, n=600, lang="ru", rubric=P.FREE, seed=1, flags=None):
        rng, recent, out = random.Random(seed), [], []
        for _ in range(n):
            pr = P.sample(rng, lang, rubric, recent, flags=flags)
            recent = [pr] + recent
            out.append(pr)
        return out

    def test_every_genre_voice_length_and_visual_appears(self):
        draws = self.draw()
        for name in ("genre", "voice", "length", "hook", "structure", "visual", "tone", "link", "ending", "theme", "truth", "narrator"):
            seen = {d[name] for d in draws}
            expected = {e[0] for e in P.axis(name)} - {x for (a, x) in P.REAL_ONLY if a == name}
            self.assertLessEqual(len(expected - seen), 2, f"{name}: не выпало {expected - seen}")  # чередуется почти всё

    def test_no_back_to_back_repeats_of_genre_or_voice(self):
        draws = self.draw()
        self.assertTrue(all(a["genre"] != b["genre"] for a, b in zip(draws, draws[1:])))
        self.assertTrue(all(a["voice"] != b["voice"] for a, b in zip(draws, draws[1:])))

    def test_incompatible_combinations_never_happen(self):
        for d in self.draw(2000, seed=5):
            if d["genre"] == "aphorisms":
                self.assertIn(d["length"], P.SHORT)
            if d["genre"] == "poem":
                self.assertEqual(d["visual"], "none")
            if d["genre"] in ("guess", "vote", "test"):
                self.assertIn(d["ending"], ("game_answer", "ask_number", "riddle", "say_by_date"))
            if d["genre"] == "sitcom":
                self.assertEqual(d["structure"], "dialogue")
            if d["genre"] == "fiction":
                self.assertNotEqual(d["narrator"], "real")

    def test_real_subscriber_stories_only_when_available(self):
        self.assertFalse(any(d["genre"] == "subscriber" or d["narrator"] == "real" for d in self.draw(1500, seed=7)))
        self.assertTrue(any(d["genre"] == "subscriber" for d in self.draw(1500, seed=7, flags={"real_story": True})))

    def test_rubrics_with_own_format_get_only_voice_and_tone_sometimes_visual(self):
        draws = self.draw(300, rubric="text_loves")
        self.assertTrue(all({"voice", "tone"} <= set(d) and set(d) <= {"voice", "tone", "visual"} for d in draws))
        self.assertTrue(all("genre" not in d for d in draws))

    def test_visuals_are_mostly_plain_text(self):
        draws = self.draw(1000)
        share = sum(d["visual"] == "none" for d in draws) / len(draws)
        self.assertTrue(0.3 < share < 0.65, share)

    def test_render_names_the_chosen_values_and_keeps_honesty_clause(self):
        pr = {"genre": "poem", "voice": "volya", "length": "s", "tone": "tender"}
        text = P.render(pr, "ru", "Проверенный факт: тест")
        self.assertIn("рифмованные строфы", text)
        self.assertIn("Приём Воли", text)
        self.assertIn("не отменяет честность", text)
        self.assertIn("Проверенный факт: тест", text)
        self.assertIn("ПРОФИЛЬ ГОЛОСА", P.render({"voice": "warm", "tone": "tender"}, "ru"))

    def test_style_no_longer_locks_a_single_genre(self):
        s = text_mode.STYLE
        self.assertNotIn("Одна бытовая сцена", s)
        self.assertNotIn("сатирический панч", s)
        self.assertNotIn("120–280", s)
        self.assertIn("НЕТ одного жанра", s)
        self.assertIn("ПРОФИЛЬ ПОСТА", s)
        self.assertIn("АРТ-ОБЪЕКТ", s)


class WithDb(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_pick_remembers_recent_and_avoids_repeats(self):
        rng = random.Random(3)
        profiles = [await P.pick(self.db, "ru", P.FREE, rng) for _ in range(30)]
        self.assertTrue(all(a["genre"] != b["genre"] for a, b in zip(profiles, profiles[1:])))
        self.assertEqual(len(await P.recent(self.db)), P.RECENT_KEEP)

    async def test_learning_boosts_what_gets_comments_and_stats_show_it(self):
        for i in range(12):
            good = i % 2 == 0
            pid = await self.db.add_draft("t", f"Пост {i}", "text_free")
            await self.db.set_threads_id(pid, "z")
            await self.db.mark_published(pid)
            for k in range(6 if good else 0):
                await self.db.record_comment(f"c{pid}_{k}", pid, f"u{k}", "к", "о", "replied")
            await P.record(self.db, pid, {"genre": "guess" if good else "monolog", "voice": "volya"})
        learned = await P.learn(self.db, NOW)
        self.assertGreater(learned["genre:guess"], 1.0)
        self.assertLess(learned["genre:monolog"], 1.0)
        self.assertTrue(0.5 <= learned["genre:monolog"] <= learned["genre:guess"] <= 2.0)
        lines = "\n".join(await P.stats_lines(self.db, NOW))
        self.assertIn("лучше: genre — угадай", lines)

    async def test_too_little_data_learns_nothing(self):
        self.assertEqual(await P.learn(self.db, NOW), {})


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "нужен TEST_POSTGRES_DSN")
class WithPostgres(WithDb):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PgStorage(os.environ["TEST_POSTGRES_DSN"])
        await self.db.init()
        for table in ("comment_replies", "post_metrics", "posts", "kv", "autopost_slots"):
            await self.db._execute(f"DELETE FROM {table}")


if __name__ == "__main__":
    unittest.main()
