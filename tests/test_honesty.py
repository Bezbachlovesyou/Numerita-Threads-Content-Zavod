import unittest
from zavod.honesty import apply,runtime
class HonestyTests(unittest.TestCase):
    def test_policy_precedes_custom_prompt_and_is_not_duplicated(self):
        result=apply('Return JSON only')
        self.assertTrue(result.startswith(runtime()))
        self.assertTrue(result.endswith('Return JSON only'))
        self.assertEqual(apply(result),result)
        self.assertIn('не обещай безошибочность',result)
