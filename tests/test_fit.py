import unittest
from zavod.autoreply import fit

class T(unittest.TestCase):
    def test_never_cuts_mid_word(self):
        text = "Первое предложение про число. " * 5 + "Полный разбор о тебе и о паре — в Нумерите в Telegram"
        for limit in range(60, len(text)):
            out = fit(text, limit)
            self.assertLessEqual(len(out), limit)
            self.assertFalse(out.endswith("Telegr"), out)
            self.assertTrue(out[-1] in ".!?…" or out == text[:len(out)] and text[len(out)] == " " or out.endswith("…"), out)
        self.assertEqual(fit("Коротко.", 50), "Коротко.")
        print("OK")

if __name__ == "__main__":
    unittest.main()
