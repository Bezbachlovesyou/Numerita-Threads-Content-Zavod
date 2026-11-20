import unittest
from zavod.perfreport import conclusions


class Conclusions(unittest.TestCase):
    def test_owner_vs_auto_and_hits(self):
        posts = [{"rubric": "text_roles", "topic": "ops:x", "comments": 25, "likes": 52, "text": "a"},
                 {"rubric": "text_roles", "topic": "ops:y", "comments": 10, "likes": 20, "text": "b"},
                 {"rubric": "text_daily", "topic": "auto", "comments": 0, "likes": 1, "text": "c"},
                 {"rubric": "text_daily", "topic": "auto", "comments": 1, "likes": 3, "text": "d"}]
        text = "\n".join(conclusions(posts))
        self.assertIn("зашло (5+ комментариев или 10+ лайков): 2 из 4", text)
        self.assertIn("с участием владельца сильнее", text)
        self.assertIn("пустых (0 комментариев, до 2 лайков): 1", text)
        print("OK")


if __name__ == "__main__":
    unittest.main()
