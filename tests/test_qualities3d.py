import random
import unittest

from zavod import qualities3d as Q


class T(unittest.TestCase):
    def test_words_base(self):
        w = Q.load_qualities()
        self.assertEqual(sorted(w), list(range(1, 10)))
        self.assertGreaterEqual(sum(len(v) for v in w.values()), 100)
        self.assertTrue(all(len(v) >= 12 for v in w.values()))
        allwords = [x for v in w.values() for x in v]
        self.assertEqual(len(allwords), len(set(allwords)), "слово не должно быть у двух чисел")

    def test_every_shape_pairs_words(self):
        words = Q.load_qualities()[1][:12]
        for shape, fn in Q.POINTS.items():
            pts = fn(Q.WORDS_ON_SHAPE, 0.0)
            self.assertEqual(len(pts), Q.WORDS_ON_SHAPE, shape)
            labels = Q._pair_up(pts, words)
            self.assertTrue(all(labels), shape)
            self.assertTrue(all(labels.count(x) == 2 for x in set(labels)), shape)
            self.assertTrue(Q.CURVES[shape](0.0), shape)

    def test_options_and_post(self):
        for digit in range(1, 10):
            opts = Q.make_options(digit, random.Random(digit))
            self.assertEqual(len(set(opts)), 4)
            self.assertIn(digit, opts)
            self.assertEqual(opts, sorted(opts))
        text = Q.post_text(1, Q.load_qualities()[1], [1, 3, 5, 7])
        self.assertNotIn("Это 1", text)
        self.assertLessEqual(len(text), 500)
        self.assertIn("1 · 10 · 19 · 28", Q.answer_text(1))

    def test_frame_renders(self):
        frame = next(Q.frames("heart", 1, [1, 3, 5, 7], "t", 2))
        self.assertEqual(len(frame), 1080 * 1350 * 3)
        print("OK")


if __name__ == "__main__":
    unittest.main()
