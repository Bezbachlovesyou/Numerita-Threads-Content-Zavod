import unittest

from zavod import funnel, stories


class Stories(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_without_key(self):
        funnel.KEY = ""
        self.assertIsNone(await stories.fetch())

    def test_numbers_line_has_no_dates(self):
        line = stories.numbers_line({"people": [{"role": "она", "soul": 6, "destiny": 3},
                                                {"role": "он", "soul": 8}]})
        self.assertEqual(line, "она: soul 6, destiny 3; он: soul 8")
        self.assertIn("никаких имён", stories.STORY_RULES)
