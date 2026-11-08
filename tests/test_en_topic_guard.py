import unittest
from unittest.mock import patch
from zavod import autopost, lang, threads_api


class T(unittest.TestCase):
    def test_en_account_never_gets_russian_topic(self):
        with patch.object(lang, "LANG", "en"):
            for rubric in ("text_year", "text_sign", "text_misread", "love", "wisdom", "text_fears", None):
                self.assertFalse(lang.has_cyrillic(autopost.topic_tag_for(rubric)), rubric)
            for ru, en in threads_api.EN_TOPIC_FALLBACK.items():
                self.assertFalse(lang.has_cyrillic(en))
                self.assertIn(ru, ("нумерология", "астрология", "психология", "отношения", "саморазвитие"))
        print("OK")


if __name__ == "__main__":
    unittest.main()
