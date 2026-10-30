import importlib
import os
import unittest
from unittest import mock


class EnglishInstance(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("FACTORY_LANG", None)
        import zavod.lang, zavod.autopost
        importlib.reload(zavod.lang)
        importlib.reload(zavod.autopost)

    def test_en_links_and_rules(self):
        with mock.patch.dict(os.environ, {"FACTORY_LANG": "en"}):
            import zavod.lang, zavod.autopost
            importlib.reload(zavod.lang)
            importlib.reload(zavod.autopost)
            self.assertTrue(zavod.autopost.BOT_LINK.endswith("ad_en_th_"))
            self.assertIn("English", zavod.lang.public_rule("post"))
            self.assertEqual(zavod.lang.public_rule("optimizer"), "")  # отчёты владельцу — по-русски

    def test_ru_default(self):
        import zavod.lang
        importlib.reload(zavod.lang)
        self.assertEqual(zavod.lang.public_rule("post"), "")


class EnglishOffer(unittest.IsolatedAsyncioTestCase):
    async def test_date_gets_link_in_en(self):
        import tempfile
        from unittest.mock import AsyncMock, patch
        from zavod.autoreply import answer_comments
        from zavod.storage import Storage
        from datetime import datetime, timezone
        tmp = tempfile.TemporaryDirectory()
        db = Storage(tmp.name + "/t.db"); await db.init()
        sent, modes = [], []

        class Threads:
            async def comments(self, target):
                return [{'id': 'c1', 'message': 'My birthday is 12.05.1990', 'from': {'id': 'u', 'username': 'amy'},
                         'createdTime': datetime.now(timezone.utc).isoformat(), 'replies': []}]

            async def reply(self, target, key, text):
                sent.append(text)

        class Model:
            async def write_reply(self, post, text, author, mode, model=None, careful=False):
                modes.append(mode)
                return "Twelve reduces to three: Jupiter energy, generous and curious. Want the full picture?"
        with patch('zavod.autoreply.is_en', return_value=True), \
             patch('zavod.autoreply.reply_targets', new=AsyncMock(return_value=[('p', 1, 'Post')])), \
             patch('zavod.autoreply.focus', new=AsyncMock(return_value='')), \
             patch('zavod.autoreply.asyncio.sleep', new=AsyncMock()):
            await answer_comments(db, Threads(), Model(), 90, 10)
        self.assertEqual(modes, ['offer'])
        self.assertIn('t.me/', sent[0])
        self.assertTrue(sent[0].rstrip().endswith('_o') or '_o' in sent[0])
        tmp.cleanup()


class EnglishNoCyrillic(unittest.TestCase):
    def test_cyrillic_blocked_in_en(self):
        from unittest import mock
        from zavod import lang, textguard
        with mock.patch.object(lang, "LANG", "en"):
            self.assertTrue(textguard.post_problem("Born on the 9th? Привет", []))
            self.assertTrue(textguard.reply_problem("Lovely «date»", []))
            self.assertIsNone(textguard.reply_problem("Lovely date, a true 6.", []))
        with mock.patch.object(lang, "LANG", "ru"):
            self.assertIsNone(textguard.reply_problem("Привет, шестёрка", []))
