import unittest
from datetime import datetime
from zavod import autopost

class T(unittest.TestCase):
    def test_quiet_from_1_to_10(self):
        self.assertEqual(autopost.quiet_end(datetime(2026, 11, 10, 3, 30)), datetime(2026, 11, 10, 10, 0))
        self.assertIsNone(autopost.quiet_end(datetime(2026, 11, 10, 10, 0)))
        self.assertIsNone(autopost.quiet_end(datetime(2026, 11, 10, 0, 59)))
        self.assertEqual(autopost.quiet_end(datetime(2026, 11, 10, 1, 0)), datetime(2026, 11, 10, 10, 0))
        print("OK")

if __name__ == "__main__":
    unittest.main()
