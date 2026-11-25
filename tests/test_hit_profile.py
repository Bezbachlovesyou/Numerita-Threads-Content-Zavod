import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from zavod.autoreply import hit_profile_mode
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

