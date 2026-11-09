import unittest
from zavod.reel import unstressed_words

class T(unittest.TestCase):
    def test_flags_missing_stress_and_accepts_marked(self):
        self.assertEqual(unstressed_words('She says "Скорпионы и стрельцы"'), ["Скорпионы", "стрельцы"])
        self.assertEqual(unstressed_words('She says "Скорпио\u0301ны и стрельцы\u0301, у вас о\u0301бщий секре\u0301т!"'), [])
        self.assertEqual(unstressed_words("no russian speech here"), [])
        print("OK")

if __name__ == "__main__":
    unittest.main()
