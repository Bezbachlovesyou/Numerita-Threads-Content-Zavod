import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from zavod.autoreply import answer_comments, asks_link
from zavod.storage import Storage, PgStorage


def comment(key, text, owner=False, replies=None):
    return {'id': key, 'message': text, 'from': {'id': 'owner' if owner else 'reader',
            'username': 'numerita.ai' if owner else 'reader', 'isOwner': owner},
            'createdTime': datetime.now(timezone.utc).isoformat(), 'replies': replies or []}


class ConversationFirst(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + '/test.db')
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def exercise(self, message, expected_mode, nested=False):
        leaf = comment('new', message)
        data = [comment('root', 'Вопрос о ремонте', replies=[
            comment('a1', 'Можно начать с одной небольшой задачи.', True, [comment('u2', 'Продолжение', replies=[
                comment('a2', 'Согласуйте, кто и чем может помочь.', True, [leaf])])])])] if nested else [leaf]
        class Threads:
            sent = []
            async def comments(self, target):
                return data
            async def reply(self, target, key, text):
                self.sent.append((key, text))
        class Model:
            modes = []
            async def write_reply(self, post, text, author, mode, model=None):
                self.modes.append(mode)
                return 'Тогда у тебя уже команда. Можно распределить конкретные задачи и оставить себе то, что нравится.'
        threads, model = Threads(), Model()
        with patch('zavod.autoreply.reply_targets', new=AsyncMock(return_value=[('p', None, 'Ремонт')])), \
             patch('zavod.autoreply.focus', new=AsyncMock(return_value='')):
            self.assertEqual(await answer_comments(self.db, threads, model, 90, 10), 1)
        self.assertEqual(model.modes, [expected_mode])
        self.assertEqual(threads.sent[0][0], 'new')
        if expected_mode == 'plain':
            self.assertNotIn('t.me/', threads.sent[0][1])
        else:
            self.assertIn('t.me/', threads.sent[0][1])

    async def test_short_new_detail_after_two_answers_is_not_skipped(self):
        await self.exercise('Обои ободраны, помощь есть', 'plain', nested=True)

    async def test_question_does_not_trigger_profile_invitation(self):
        await self.exercise('Как мне попросить помощи?', 'plain')

    async def test_requested_link_still_works(self):
        await self.exercise('Пришлите ссылку на бота', 'link')

    def test_link_intent(self):
        for text in ['Как посчитать число души?', 'Ваш сайт красивый', 'Не присылай мне ссылки', '18, ремонт делаю сама']:
            self.assertFalse(asks_link(text), text)
        for text in ['Есть ли у вас бот?', 'Где ваш сайт?', 'Как зайти в бот?', 'Пришлите ссылку']:
            self.assertTrue(asks_link(text), text)


@unittest.skipUnless(os.environ.get('TEST_POSTGRES_DSN'), 'requires isolated PostgreSQL')
class ConversationFirstPostgres(ConversationFirst):
    async def asyncSetUp(self):
        self.db = PgStorage(os.environ['TEST_POSTGRES_DSN'])
        await self.db.init()
        await self.db.pool.execute('TRUNCATE dialogue_messages, comment_replies, kv')

    async def asyncTearDown(self):
        await self.db.pool.close()


class FreeWall(ConversationFirst):
    async def given(self, n):
        for i in range(n):
            await self.db.record_comment(f'old{i}', None, 'reader', 'вопрос', 'ответ по сути', 'replied')

    async def test_last_free_answer_invites_to_bot(self):
        await self.given(5)
        await self.exercise('Как мне попросить помощи?', 'paywall')

    async def test_after_wall_no_more_answers_today(self):
        await self.given(6)
        threads = AsyncMock()
        threads.comments.return_value = [comment('new', 'Как мне попросить помощи?')]
        model = AsyncMock()
        with patch('zavod.autoreply.reply_targets', new=AsyncMock(return_value=[('p', None, 'Ремонт')])), \
             patch('zavod.autoreply.focus', new=AsyncMock(return_value='')):
            self.assertEqual(await answer_comments(self.db, threads, model, 90, 10), 0)
        threads.reply.assert_not_awaited()
        model.write_reply.assert_not_awaited()
