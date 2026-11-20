import unittest
from datetime import datetime
from zavod import autopost

class T(unittest.TestCase):
    def test_windows(self):
        # 20.11.2026: одно окно — вечер 18–22
        self.assertIsNone(autopost.window_start(datetime(2026, 11, 11, 19, 0)))
        self.assertEqual(autopost.window_start(datetime(2026, 11, 11, 11, 0)), datetime(2026, 11, 11, 18, 0))
        self.assertEqual(autopost.window_start(datetime(2026, 11, 11, 14, 0)), datetime(2026, 11, 11, 18, 0))
        self.assertEqual(autopost.window_start(datetime(2026, 11, 11, 23, 0)), datetime(2026, 11, 12, 18, 0))
        self.assertEqual(autopost.window_start(datetime(2026, 11, 11, 4, 0)), datetime(2026, 11, 11, 18, 0))
        print("OK")

if __name__ == "__main__":
    unittest.main()
