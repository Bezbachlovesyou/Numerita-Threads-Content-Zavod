import os
import tempfile
import unittest

from zavod import hottopics, lang
from zavod.autopost import topic_tag_for
from zavod.storage import Storage


class HotTopics(unittest.IsolatedAsyncioTestCase):
    def test_texts_are_short_honest_and_clean(self):
        for t in hottopics.TOPICS:
            ru, en = hottopics.compose(t, False), hottopics.compose(t, True)
            self.assertLessEqual(len(ru), 470)
            self.assertFalse(lang.has_cyrillic(en))
            self.assertIn("нумеролог", ru.lower())  # традиция названа
            self.assertNotRegex(ru.lower(), r"сейчас|придут|гарант")  # без прогнозов и обещаний
            self.assertEqual(len(set(t[3])), 3)

    async def test_money_is_frequent_and_order_cycles(self):
        db = Storage(os.path.join(tempfile.mkdtemp(), "t.db"))
        await db.init()
        keys = [(await hottopics.take(db))[0] for _ in range(len(hottopics.TOPICS) + 1)]
        self.assertEqual(keys[0], keys[-1])
        self.assertGreaterEqual(sum(k.startswith("money") for k in keys[:9]), 3)
        self.assertEqual(topic_tag_for("text_three", ""), hottopics.TOPICS[0][6])

    def test_alternates_with_deep_series(self):
        self.assertTrue(hottopics.turn(["text_deep"]))
        self.assertFalse(hottopics.turn(["text_three", "text_deep"]))


if __name__ == "__main__":
    unittest.main()
