import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from zavod.autoreply import CRISIS_REPLY, answer_comments, risky_reply
from zavod.storage import PgStorage, Storage
from test_conversation_first import comment

BAD = ('Извиняться за «зае…» не нужно. Сейчас выматывает сильнее всего сама ситуация '
       'или то, что сил на неё уже почти не остаётся?')
GOOD = 'Злость тут понятна. Что сейчас сильнее всего мешает — сама задача или то, что её не с кем разделить?'


class SensitiveReply(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + '/test.db')
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def run_with(self, message, answers):
        sent, calls = [], []

        class Threads:
            async def comments(self, target):
                return [comment('new', message)]

            async def reply(self, target, key, text):
                sent.append(text)

        class Model:
            async def write_reply(self, post, text, author, mode, model=None, careful=False):
                calls.append(careful)
                return answers[min(len(calls) - 1, len(answers) - 1)]
        with patch('zavod.autoreply.reply_targets', new=AsyncMock(return_value=[('p', None, 'Терпение')])), \
             patch('zavod.autoreply.focus', new=AsyncMock(return_value='')), \
             patch('zavod.autoreply.asyncio.sleep', new=AsyncMock()):
            await answer_comments(self.db, Threads(), Model(), 90, 10)
        return sent, calls

    def test_patterns(self):
        self.assertTrue(risky_reply(BAD))
        for ok in [GOOD, 'Корабля и хлеба хватит', 'Заехать к маме — уже шаг', 'Бессмертные строки Пушкина']:
            self.assertFalse(risky_reply(ok), ok)

    async def test_risky_answer_is_rewritten_carefully(self):
        sent, calls = await self.run_with('Устала, всё зае…', [BAD, GOOD])
        self.assertEqual(calls, [False, True])
        self.assertEqual(sent, [GOOD])

    async def test_still_risky_is_skipped(self):
        sent, calls = await self.run_with('Устала, всё зае…', [BAD, BAD])
        self.assertEqual(sent, [])

    async def test_crisis_comment_gets_short_safe_reply(self):
        sent, calls = await self.run_with('Иногда не хочется жить', [GOOD])
        self.assertEqual(calls, [])
        self.assertEqual(sent, [CRISIS_REPLY])


@unittest.skipUnless(os.environ.get('TEST_POSTGRES_DSN'), 'requires isolated PostgreSQL')
class SensitiveReplyPostgres(SensitiveReply):
    async def asyncSetUp(self):
        self.db = PgStorage(os.environ['TEST_POSTGRES_DSN'])
        await self.db.init()
        await self.db.pool.execute('TRUNCATE dialogue_messages, comment_replies, kv')

    async def asyncTearDown(self):
        await self.db.pool.close()
