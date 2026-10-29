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
