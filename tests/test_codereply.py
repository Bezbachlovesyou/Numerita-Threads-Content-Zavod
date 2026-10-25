import unittest

from zavod import codereply

KB = {"numbers": {str(n): {"name": f"Планета{n}", "qualities": f"качества {n}", "nature": f"Характер {n}. Ещё."}
                  for n in range(1, 10)}}


class CodeReplyTests(unittest.TestCase):
    def test_full_date_gives_soul_and_mission(self):
        text = codereply.reply("Моя дата 12.03.1990", KB, 1)
        self.assertIn("Число души 3", text)
        self.assertIn("миссия 7 (25 → 7)", text)

    def test_day_only_and_word_date(self):
        self.assertIn("Число души 6", codereply.reply("я 24-го", KB, 2))
        self.assertIn("миссия 4 (31 → 4)", codereply.reply("6 ноября 1985", KB, 3))

    def test_questions_ages_and_chat_go_to_ai(self):
        for m in ("А что значит 7?", "мне 30 лет", "люблю это", "уже 3 года жду"):
            self.assertIsNone(codereply.reply(m, KB, 4), m)

    def test_numbers_note_for_ai(self):
        self.assertIn("миссия (судьба) 7", codereply.numbers_note("12.03.1990 что скажешь?"))


if __name__ == "__main__":
    unittest.main()
