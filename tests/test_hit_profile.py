import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from zavod.autoreply import hit_profile_mode, answer_comments
from zavod import reply_cooldown
from zavod.threads_api import ThreadsError
from zavod.generator import Generator
from zavod.storage import Storage

RU = 'Стрельца попросили не устраивать шоу. Он вызвал свидетелей.'
EN = 'A Sagittarius was told to stop making a scene. So they called witnesses.'

class HitProfileTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Storage(self.temp.name + '/test.sqlite')
        await self.db.init()
        self.now = datetime.now(timezone.utc)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_birthday_request_uses_profile_in_both_languages(self):
        for post in (RU, EN):
            self.assertEqual(await hit_profile_mode(self.db, post, '27', 'reader', self.now), 'bio_offer')

    async def test_invitation_is_not_repeated(self):
        await self.db.record_comment('first', None, 'reader', '27', 'Продолжить можно через ссылку в шапке профиля.', 'replied')
        self.assertEqual(await hit_profile_mode(self.db, RU, '27', 'reader', self.now), 'plain')

    async def test_unrelated_posts_and_simple_thanks_are_not_an_offer(self):
        self.assertIsNone(await hit_profile_mode(self.db, 'Другой пост', '27', 'reader', self.now))
        self.assertIsNone(await hit_profile_mode(self.db, RU, 'Спасибо!', 'reader', self.now))

    async def test_generator_keeps_bio_offer_mode(self):
        gen = Generator.__new__(Generator)
        gen.reply_system, gen.reply_model = 'test', 'fake'
        gen._with_knowledge = AsyncMock(side_effect=lambda text, *args: text)
        gen._complete = AsyncMock(return_value='Ответ по существу. Если захочешь продолжить — ссылка в шапке профиля.')
        await gen.write_reply(RU, '27', 'reader', 'bio_offer')
        prompt = gen._complete.call_args.args[1]
        self.assertIn('BIO_OFFER', prompt)
        self.assertIn('link in bio', prompt)
        self.assertNotIn('Про бота и профиль не пиши', prompt)

    def fixture(self, failing=False):
        comments = [{'id': str(i), 'message': '27', 'createdTime': self.now.isoformat(),
                     'from': {'username': 'reader' + str(i)}} for i in range(2)]
        threads = SimpleNamespace(comments=AsyncMock(return_value=comments), reply=AsyncMock())
        if failing:
            threads.reply.side_effect = ThreadsError('Platform error: 80016', http_status=403)
        gen = SimpleNamespace(knowledge=None, reply_model='fake', write_reply=AsyncMock(
            return_value='Двадцать седьмое сводится к девятке: образ решительности. Если захочешь продолжить — ссылка в шапке профиля.'))
        return threads, gen

    async def test_recovery_sends_only_one_and_clears_pause_only_after_success(self):
        await reply_cooldown.defer(self.db, ThreadsError('Platform error: 80016', http_status=403), self.now)
        threads, gen = self.fixture()
        with patch('zavod.autoreply.conversation_context', AsyncMock(return_value='')):
            n = await answer_comments(self.db, threads, gen, 30, 10, tz=timezone.utc,
                                      recovery_target=('target', None, RU))
        self.assertEqual(n, 1)
        self.assertEqual(threads.reply.await_count, 1)
        self.assertFalse(await reply_cooldown.blocked(self.db, self.now))

    async def test_recovery_denial_stops_after_one_attempt(self):
        threads, gen = self.fixture(failing=True)
        with patch('zavod.autoreply.conversation_context', AsyncMock(return_value='')):
            n = await answer_comments(self.db, threads, gen, 30, 10, tz=timezone.utc,
                                      recovery_target=('target', None, RU))
        self.assertEqual(n, 0)
        self.assertEqual(threads.reply.await_count, 1)
        self.assertTrue(await reply_cooldown.blocked(self.db, self.now))

    async def test_recovery_cannot_exceed_daily_budget(self):
        threads, gen = self.fixture()
        with patch('zavod.autoreply.spent_on_replies', AsyncMock(return_value=.31)):
            n = await answer_comments(self.db, threads, gen, 30, 1, daily_usd=.3, tz=timezone.utc,
                                      recovery_target=('target', None, RU))
        self.assertEqual(n, 0)
        threads.comments.assert_not_awaited()
        threads.reply.assert_not_awaited()

