import re, unittest
from zavod import astroschool as A

class T(unittest.TestCase):
    def test_lessons_fit_telegram_and_cycle(self):
        for i in range(len(A.LESSONS) + 1):
            text = A.lesson_html(i)
            self.assertLess(len(re.sub(r"<[^>]+>", "", text)), 1500)
            self.assertIn("ad_tg_school", text)
            self.assertIn("не наука", text)
        self.assertEqual(A.lesson_html(0), A.lesson_html(len(A.LESSONS)))
        print("OK")

if __name__ == "__main__":
    unittest.main()
