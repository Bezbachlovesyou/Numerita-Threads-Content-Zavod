import unittest
from datetime import datetime
from zavod import autopost

class T(unittest.TestCase):
    def test_quiet_from_1_to_10(self):
        self.assertEqual(autopost.quiet_end(datetime(2026, 11, 10, 3, 30)), datetime(2026, 11, 10, 10, 0))
        self.assertIsNone(autopost.quiet_end(datetime(2026, 11, 10, 10, 0)))
        self.assertIsNone(autopost.quiet_end(datetime(2026, 11, 10, 1, 59)))
        self.assertEqual(autopost.quiet_end(datetime(2026, 11, 10, 2, 0)), datetime(2026, 11, 10, 10, 0))
        from unittest.mock import patch
        from zoneinfo import ZoneInfo
        msk = ZoneInfo("Europe/Moscow")
        with patch.object(autopost, "_is_en", lambda: True):
            # 10:00 МСК = 02:00 Нью-Йорк: тишина до 10:00 по Нью-Йорку = 18:00 МСК
            end = autopost.quiet_end(datetime(2026, 11, 10, 10, 0, tzinfo=msk))
            self.assertEqual(end.astimezone(msk), datetime(2026, 11, 10, 18, 0, tzinfo=msk))
            self.assertIsNone(autopost.quiet_end(datetime(2026, 11, 10, 19, 0, tzinfo=msk)))
        print("OK")

if __name__ == "__main__":
    unittest.main()
