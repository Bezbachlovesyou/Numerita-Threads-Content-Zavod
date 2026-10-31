import json
import os
import random
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from zavod import game, text_mode
from zavod.autoreply import answer_comments
from zavod.cards import grid_json, make_grid
from zavod.storage import PgStorage, Storage

HIDDEN = ["111", "222", "777", "1234"]


class Check(unittest.TestCase):
    def test_tokens_and_check(self):
        self.assertEqual(game.tokens("нашла 111 и 777, 111 снова! И ещё 12345"), ["111", "777"])  # 5 цифр — не число игры
        c = game.check("111 и 777", HIDDEN, egg="2828")
        self.assertEqual((c["found"], c["left"], c["total"], c["egg"], c["first"]), (["111", "777"], 2, 4, False, "111"))
        c = game.check("1234, 2828 и 999", HIDDEN, egg="2828")
        self.assertEqual((c["found"], c["egg"], c["outside"]), (["1234"], True, ["999"]))
        self.assertEqual(game.check("ничего не вижу", HIDDEN)["tokens"], [])

    def test_reading_is_computed_by_code(self):
        self.assertIn("цифра 7 (Кету) повторена 3 раза; сумма 21 → 3 (Юпитер)", game.reading("777"))
        self.assertIn("сумма 10 → 1 (Солнце)", game.reading("1234"))
        self.assertIn("сумма 8 → 8 (Сатурн)", game.reading("2222"))

    def test_note_never_spoils_what_is_left(self):
        n = game.note(game.check("нашла 111", HIDDEN), None)
        self.assertIn("найдено 1 из 4", n)
        self.assertIn("ещё осталось 3 (какие — не называй)", n)
        for hidden_left in ("222", "777", "1234"):
            self.assertNotIn(hidden_left, n)  # оставшиеся не названы
        self.assertIn("игра-образ", n)
        self.assertIn("день рождения", n)
        self.assertIn("не выдумывай", n.lower())

    def test_note_for_egg_and_for_empty_answer(self):
        n = game.note(game.check("1234 и 2828", HIDDEN, egg="2828"), "2828")
        self.assertIn("пасхалку без подсветки он нашёл", n)
        empty = game.note(game.check("не нашёл", HIDDEN), None)
        self.assertIn("подбодри", empty)
        for h in HIDDEN:
            self.assertNotIn(h, empty)

    def test_mirror_promise_in_grid_caption_rules(self):
        self.assertIn("игру-зеркало", text_mode.GRID_STYLE)
        self.assertIn("не тест", text_mode.GRID_STYLE)


class WithDb(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def grid_post(self, rubric="grid"):
        grid = make_grid(random.Random(3), style="spiral", egg="2828")
        pid = await self.db.add_draft("g", "Угадай число · выпуск 5", rubric, None, grid_json(grid, "Какое число вынырнет?", 0))
        await self.db.set_threads_id(pid, "z")
        await self.db.mark_published(pid)
        return pid, grid

    async def test_grid_of_returns_hidden_only_for_grids(self):
        pid, grid = await self.grid_post()
        got = await game.grid_of(self.db, pid)
        self.assertEqual(got["hidden"], grid["hidden"])
        other, _ = await self.grid_post("text_seek")
        self.assertIsNone(await game.grid_of(self.db, other))
        self.assertIsNone(await game.grid_of(self.db, None))

    async def test_record_is_idempotent_and_results_line_summarises(self):
        pid, grid = await self.grid_post()
        hidden = grid["hidden"]
        a, b = hidden[0], hidden[1]
        for cid, text in (("c1", f"{a} и {b}"), ("c2", a), ("c3", "2828")):
            await game.record(self.db, pid, cid, game.check(text, hidden, "2828"))
        await game.record(self.db, pid, "c1", game.check(f"{a} и {b}", hidden, "2828"))  # повтор не считается
        data = await game.results(self.db, pid)
        self.assertEqual((data["n"], data["found"][a], data["found"][b], data["egg"]), (3, 2, 1, 1))
        line = game.results_line(data)
        self.assertIn("играло 3", line)
        self.assertIn(f"{a} (2)", line)
        self.assertIn("пасхалку нашли 1", line)
        self.assertEqual(game.results_line(None), "ответов пока нет")

    async def test_replies_under_a_grid_get_the_mirror_note_and_are_recorded(self):
        pid, grid = await self.grid_post()
        a = grid["hidden"][0]
        seen = {}

        class Threads:
            sent = []
            async def comments(self, target):
                return [{"id": "c-1", "message": f"Нашла {a}!", "from": {"id": "r", "username": "reader", "isOwner": False},
                         "createdTime": datetime.now(timezone.utc).isoformat(), "replies": []}]
            async def reply(self, target, key, text):
                self.sent.append(text)

        class Model:
            async def write_reply(self, post, text, author, mode, model=None):
                seen["post"] = post
                return "Ура, нашла! Цифры этого числа в языке чисел говорят о тонкой интуиции. А день рождения скажешь?"

        with patch("zavod.autoreply.reply_targets", new=AsyncMock(return_value=[("p", pid, "Угадай число")])), \
             patch("zavod.autoreply.focus", new=AsyncMock(return_value="")):
            await answer_comments(self.db, Threads(), Model(), 90, 10)
        self.assertIn("ИГРА «УГАДАЙ ЧИСЛО»", seen["post"])
        self.assertIn(f"найдено 1 из {len(grid['hidden'])}", seen["post"])
        self.assertIn(f"{a}:", seen["post"])  # расчёт кода по найденному
        self.assertEqual((await game.results(self.db, pid))["n"], 1)

    async def test_ordinary_posts_are_untouched(self):
        pid, _ = await self.grid_post("text_seek")
        seen = {}

        class Threads:
            sent = []
            async def comments(self, target):
                return [{"id": "c-2", "message": "Привет, 111", "from": {"id": "r", "username": "reader2", "isOwner": False},
                         "createdTime": datetime.now(timezone.utc).isoformat(), "replies": []}]
            async def reply(self, target, key, text):
                self.sent.append(text)

        class Model:
            async def write_reply(self, post, text, author, mode, model=None):
                seen["post"] = post
                return "Привет! Красивое число. Расскажешь, что для тебя оно значит?"

        with patch("zavod.autoreply.reply_targets", new=AsyncMock(return_value=[("p", pid, "Пост")])), \
             patch("zavod.autoreply.focus", new=AsyncMock(return_value="")):
            await answer_comments(self.db, Threads(), Model(), 90, 10)
        self.assertNotIn("ИГРА «УГАДАЙ ЧИСЛО»", seen["post"])
        self.assertIsNone(await game.results(self.db, pid))


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "нужен TEST_POSTGRES_DSN")
class WithPostgres(WithDb):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PgStorage(os.environ["TEST_POSTGRES_DSN"])
        await self.db.init()
        for table in ("comment_replies", "dialogue_messages", "post_metrics", "posts", "kv", "autopost_slots"):
            await self.db._execute(f"DELETE FROM {table}")


if __name__ == "__main__":
    unittest.main()
