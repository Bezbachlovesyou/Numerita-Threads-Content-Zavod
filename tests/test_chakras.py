import unittest
from zavod import chakras as C

class T(unittest.TestCase):
    def test_notes_short_and_cycle(self):
        for i in range(len(C.NOTES) + 2):
            t = C.note_text(i)
            self.assertLess(len(t), 600)
            self.assertIn("Практика", t)
        self.assertEqual(C.note_text(0), C.note_text(len(C.NOTES)))
        print("OK")

if __name__ == "__main__":
    unittest.main()
