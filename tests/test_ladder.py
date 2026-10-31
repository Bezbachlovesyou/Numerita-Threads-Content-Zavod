import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from zavod import chain, ladder
from zavod.autoreply import answer_comments
from zavod.storage import PgStorage, Storage


class Hint(unittest.TestCase):
    def test_day_only_names_every_next_step(self):
        h = ladder.hint("Я родилась 14")
        for part in ("полная дата с годом", "время и город", "имя", "дата близкого"):
            self.assertIn(part, h)

    def test_full_date_with_time_does_not_ask_for_what_is_given(self):
        h = ladder.hint("14.05.1985, родилась в 4:30 утра")
        self.assertNotIn("полная дата с годом", h)
        self.assertNotIn("время и город", h)
        self.assertIn("имя", h)

    def test_pair_of_dates_asks_for_time_and_names(self):
        h = ladder.hint("6 и 17")
        self.assertIn("две даты", h)
        self.assertIn("имена", h)

    def test_no_date_asks_for_the_first_step(self):
        self.assertIn("день рождения", ladder.hint("расскажи про число 7"))


class Variants(unittest.TestCase):
    def test_variant_is_deterministic_and_share_works(self):
        self.assertEqual(ladder.variant_for("c1", 0.5), ladder.variant_for("c1", 0.5))
        self.assertTrue(all(ladder.variant_for(f"c{i}", 0.0) == "base" for i in range(50)))
        self.assertTrue(all(ladder.variant_for(f"c{i}", 1.0) == "ladder" for i in range(50)))
        share = sum(ladder.variant_for(f"c{i}", 0.5) == "ladder" for i in range(1000)) / 1000
        self.assertTrue(0.4 < share < 0.6, share)

    def test_letters_and_note_scope(self):
        self.assertEqual([ladder.letter("offer", "base"), ladder.letter("offer", "ladder"),
                          ladder.letter("paywall", "base"), ladder.letter("paywall", "ladder")], ["o", "l", "w", "m"])
        self.assertEqual(ladder.note("plain", "14"), "")
        self.assertEqual(ladder.note("link", "14"), "")  # кто сам спросил про ссылку — без лестницы
        note = ladder.note("offer", "Я родилась 14")
        self.assertIn("ЛЕСТНИЦА ЛИЧНОГО", note)
        self.assertIn("не гарантия", note)
        self.assertIn("Без давления", note)


class FunnelCompare(unittest.TestCase):
    def test_reply_variants_are_compared_from_labels(self):
        data = {"labels": [
            {"label": "th_r12_o", "came": 12, "wow": 5, "paid": 0}, {"label": "th_r12_wpc", "came": 3, "wow": 1, "paid": 0},
            {"label": "th_r13_l", "came": 11, "wow": 8, "paid": 2}, {"label": "th_r14_mpi", "came": 4, "wow": 2, "paid": 1},
            {"label": "th_r15_a", "came": 9, "wow": 4, "paid": 1}, {"label": "th_bio", "came": 40, "wow": 10, "paid": 0}]}
        got = chain.by_reply_variant(data)
        self.assertEqual((got["old"]["came"], got["old"]["paid"]), (15, 0))
        self.assertEqual((got["ladder"]["came"], got["ladder"]["paid"]), (15, 3))
        self.assertEqual(got["link"]["paid"], 1)
        c = {"days": 7, "posts": 1, "views": 1000, "views_posts": 1, "people": 5, "replies": 2, "linked": 2, "rubrics": {},
             "variants": got, "bot": {"came": 15, "new": 10, "wow": 5, "returned": 2, "paid": 3, "stars": 297, "usd": 0.0, "rub": 0.0,
                                      "subs_new": None, "subs_active": None, "renewed": None, "refunds": None}}
        line = next(x for x in chain.lines(c) if x.startswith("приглашение в ответах"))
        self.assertIn("прежнее: пришли 15", line)
        self.assertIn("«лестница личного»: пришли 15, «вау» 10, оплатили 3", line)
        self.assertNotIn("мало данных", line)


def comment(key, text):
    return {"id": key, "message": text, "from": {"id": "reader", "username": "reader", "isOwner": False},
            "createdTime": datetime.now(timezone.utc).isoformat(), "replies": []}


class InReplies(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/test.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def run_one(self, share):
        await self.db.kv_set("ladder:share", str(share))
        seen = {}

        class Threads:
            sent = []
            async def comments(self, target):
                return [comment("c-7", "Я родилась 14")]
            async def reply(self, target, key, text):
                self.sent.append(text)

        class Model:
            async def write_reply(self, post, text, author, mode, model=None):
                seen["post"], seen["mode"] = post, mode
                return "Число души 5, Меркурий: быстрый ум и живая речь. Где это помогает тебе?"

        threads = Threads()
        with patch("zavod.autoreply.reply_targets", new=AsyncMock(return_value=[("p", None, "Пост")])), \
             patch("zavod.autoreply.focus", new=AsyncMock(return_value="")):
            await answer_comments(self.db, threads, Model(), 90, 10)
        return seen, threads.sent[0]

    async def test_ladder_variant_adds_the_note_and_marks_the_link(self):
        seen, sent = await self.run_one(1.0)
        self.assertEqual(seen["mode"], "offer")  # режим для генератора прежний
        self.assertIn("ЛЕСТНИЦА ЛИЧНОГО", seen["post"])
        self.assertIn("полная дата с годом", seen["post"])
        self.assertIn("ad_th_r0_l", sent)

    async def test_base_variant_is_exactly_as_before(self):
        seen, sent = await self.run_one(0.0)
        self.assertNotIn("ЛЕСТНИЦА ЛИЧНОГО", seen["post"])
        self.assertIn("ad_th_r0_o", sent)


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "нужен TEST_POSTGRES_DSN")
class InRepliesPostgres(InReplies):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PgStorage(os.environ["TEST_POSTGRES_DSN"])
        await self.db.init()
        for table in ("comment_replies", "dialogue_messages", "kv", "autopost_slots"):
            await self.db._execute(f"DELETE FROM {table}")


if __name__ == "__main__":
    unittest.main()
