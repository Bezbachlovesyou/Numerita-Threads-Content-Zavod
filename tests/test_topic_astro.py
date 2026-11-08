import unittest
from zavod import autopost

class T(unittest.TestCase):
    def test_sign_and_sky_go_to_astrology(self):
        self.assertEqual(autopost.topic_tag_for("text_sign"), "Astrology Threads")
        self.assertEqual(autopost.topic_tag_for("text_misread"), "Нумерология")
        print("OK")

if __name__ == "__main__":
    unittest.main()
