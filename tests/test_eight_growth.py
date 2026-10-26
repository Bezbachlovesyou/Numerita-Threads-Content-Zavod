import unittest
from zavod.cards import eight_growth_carousel, carousel_json, carousel_from_json


class EightGrowthCarouselTest(unittest.TestCase):
    def test_six_slides_keep_order_and_palette(self):
        cards = eight_growth_carousel(2)
        self.assertEqual(len(cards), 6)
        self.assertTrue(all(c.palette == 2 and c.dates == "8 · 17 · 26" for c in cards))
        self.assertEqual(carousel_from_json(carousel_json(cards)), cards)
        self.assertIn("назвать цену", cards[-1].hook)

    def test_truth_boundary_and_action_precede_question(self):
        cards = eight_growth_carousel(0)
        self.assertIn("Не доказательство", cards[1].hook)
        self.assertIn("Запиши", cards[4].hook)
        self.assertTrue(all(len(c.hook) < 165 for c in cards))
        self.assertTrue(all("ХОЧУ" not in c.hook for c in cards))


if __name__ == "__main__":
    unittest.main()
