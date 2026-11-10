import unittest
from zavod import autopost
from zavod.optimizer import post_score

class T(unittest.TestCase):
    def test_deficit_picks_missing_goal(self):
        self.assertEqual(autopost.goal_deficit(["text_sign", "text_sign_truth", "text_mercury", "text_asc"]), "shares")
        self.assertEqual(autopost.goal_deficit(["text_sign", "text_gotaway", "text_sign_truth", "text_mercury"]), "likes")
        self.assertEqual(autopost.goal_of("text_angel"), "likes")
        print("OK")

    def test_shares_and_reposts_outweigh_likes(self):
        base = {"comments": 1, "likes": 10}
        self.assertGreater(post_score({**base, "shares": 2, "reposts": 1}), post_score({**base, "likes": 40}))

if __name__ == "__main__":
    unittest.main()
