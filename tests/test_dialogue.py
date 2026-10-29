import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from zavod.autoreply import answer_comments, reply_candidates
from zavod.dialogue import archive_comments, conversation_context, fair_queue
from zavod.generator import GenerationError
from zavod.storage import Storage, PgStorage


def message(key, text, owner=False, replies=None, author="reader"):
    return {"id": key, "message": text, "from": {"id": author, "username": author, "isOwner": owner},
            "createdTime": (datetime(2026, 10, 24, tzinfo=timezone.utc)
                            + timedelta(seconds=int(''.join(filter(str.isdigit, key)) or 0))).isoformat(),
            "replies": replies or []}


class Model:
    reply_model = 'test-model'
    def __init__(self):
        self.calls = 0
        self.summaries = 0
        self.fail_summary = False

    async def write_reply(self, post, comment, author, mode, model=None):
        self.calls += 1
        ideas = ["сюжет держится на выборе героя", "автор прячет главное в паузах", "финал спорит с началом",
                 "второстепенный персонаж ведёт историю", "язык меняется вместе с героем", "время в книге течёт иначе",
                 "мотив дороги повторяется трижды", "ирония спасает трагедию", "письма раскрывают характер",
                 "город звучит как отдельный голос", "детская память решает всё", "последняя глава переворачивает первую"]
        return f"{ideas[(self.calls - 1) % len(ideas)].capitalize()} — {comment}? Ответ {self.calls}"

    async def improve(self, system, prompt, max_tokens=None, kind=None, model=None):
        self.summaries += 1
        if self.fail_summary:
            raise GenerationError("test")
        return "@reader обсуждает книги; уже рекомендована книга. Не повторять."


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/test.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_archive_restart_summary_and_scope(self):
        await self.exercise_archive(self.db)
        restarted = Storage(self.db.path)
        await restarted.init()
        self.assertEqual(len(await restarted.dialogue_history("p", "m0")), 30)

    async def exercise_archive(self, db):
        for i in range(30):
            await archive_comments(db, "p", [message("m"+str(i), "book " + str(i))])
            # Flat API ancestry is known when we save it ourselves.
            await db._execute("UPDATE dialogue_messages SET root_id=?,parent_id=? WHERE message_id=?",
                              ("m0", "m"+str(i-1) if i else None, "m"+str(i)))
        await archive_comments(db, "other", [message("secret", "OTHER POST SECRET")])
        model = Model()
        text = await conversation_context(db, model, "p", "m29")
        self.assertIn("Сводка", text)
        self.assertIn("book 28", text)
        self.assertNotIn("OTHER POST SECRET", text)
        self.assertLess(len(text), 18000)
        self.assertEqual(len(await db.dialogue_history("p", "m0")), 30)
        # Repeated retrieval preserves original timestamps and does not duplicate.
        await archive_comments(db, "p", [message("m29", "book 29")])
        self.assertEqual(len(await db.dialogue_history("p", "m0")), 30)
        await conversation_context(db, model, "p", "m29")
        count = model.summaries
        await conversation_context(db, model, "p", "m29")
        self.assertEqual(model.summaries, count)

    async def test_ten_turns_and_no_duplicate(self):
        await self.exercise_ten_turns(self.db)

    async def exercise_ten_turns(self, db):
        # Память длинного диалога; стену бесплатных ответов (28.10.2026) проверяет test_conversation_first.
        patcher = patch("zavod.autoreply.FREE_PER_DAY", 100)
        patcher.start()
        self.addCleanup(patcher.stop)
        model = Model()
        class Threads:
            def __init__(self):
                self.comments_data = []
                self.sent = []
            async def commented_posts(self, since):
                return [{"id": "ten", "content": "Обсуждаем книги"}]
            async def comments(self, target):
                return self.comments_data
            async def reply(self, target, comment_id, text):
                self.sent.append(comment_id)
        threads = Threads()
        root = None
        for i in range(10):
            current = message("t"+str(i*2), "Обсудим книгу " + str(i))
            if root is None:
                root = current
                threads.comments_data = [root]
            else:
                cursor["replies"] = [current]
            # One pending message per run; no sleep/network/generation service.
            self.assertEqual(await answer_comments(db, threads, model, 30, 5), 1)
            owner = message("t"+str(i*2+1), "Предыдущий ответ.", True, author="numerita")
            current["replies"] = [owner]
            cursor = owner
        self.assertEqual(len(threads.sent), 10)
        self.assertEqual(await answer_comments(db, threads, model, 30, 5), 0)
        self.assertEqual(await db.replies_since(datetime.now(timezone.utc)-timedelta(days=1)), 10)

    async def test_summary_failure_retains_archive(self):
        await self.exercise_archive(self.db)
        await self.db._execute("DELETE FROM kv WHERE key LIKE 'dialogue_summary:%'")
        model = Model()
        model.fail_summary = True
        text = await conversation_context(self.db, model, "p", "m29")
        self.assertIn("Выдержки", text)
        self.assertEqual(len(await self.db.dialogue_history("p", "m0")), 30)

    def test_nested_candidates_and_fairness(self):
        leaf = message("n3", "new")
        tree = message("n1", "root", replies=[message("n2", "answer", True, [leaf])])
        self.assertEqual([x[0]["id"] for x in reply_candidates([tree])], ["n3"])
        entries = [("p", None, "", message(str(i), "x", author=a))
                   for i,a in enumerate(["a","a","a","b","c"])]
        self.assertEqual([x[3]["from"]["id"] for x in fair_queue(entries)], ["a","b","c","a","a"])


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "set isolated TEST_POSTGRES_DSN")
class PostgresTests(MemoryTests):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PgStorage(os.environ["TEST_POSTGRES_DSN"])
        await self.db.init()
        await self.db.pool.execute("TRUNCATE posts, post_metrics, autopost_slots, dialogue_messages, comment_replies, kv")

    async def asyncTearDown(self):
        await self.db.pool.close()
        self.tmp.cleanup()

    async def test_archive_restart_summary_and_scope(self):
        await self.exercise_archive(self.db)
        reopened = PgStorage(os.environ["TEST_POSTGRES_DSN"])
        await reopened.init()
        try:
            self.assertEqual(len(await reopened.dialogue_history("p", "m0")), 30)
        finally:
            await reopened.pool.close()


if __name__ == "__main__":
    unittest.main()
