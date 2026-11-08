import unittest
from zavod import autopost

class T(unittest.TestCase):
    def test_zodiac_text_goes_to_astrology_even_with_other_rubric(self):
        self.assertEqual(autopost.topic_tag_for("text_free", "Скорпион и Телец: кто кого проверяет"), "Astrology Threads")
        self.assertEqual(autopost.topic_tag_for("text_baza", "Число 7 любит тишину"), "Нумерология")
        self.assertEqual(autopost.topic_tag_for("text_matrix"), "Матрица судьбы")
        print("OK")

if __name__ == "__main__":
    unittest.main()
