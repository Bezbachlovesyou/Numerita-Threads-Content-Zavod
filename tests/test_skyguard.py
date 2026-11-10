import unittest
from zavod import skyguard

class T(unittest.TestCase):
    def test_claims_are_detected(self):
        self.assertEqual(skyguard.claims("Новолуние в Скорпионе сегодня"), ["new"])
        self.assertEqual(skyguard.claims("Ретроградный Меркурий и полнолуние"), ["full", "retro:меркур"])
        self.assertEqual(skyguard.claims("Число 7 любит тишину"), [])
        self.assertEqual(skyguard.verify("Число 7 любит тишину"), [])
        print("OK")

if __name__ == "__main__":
    unittest.main()
