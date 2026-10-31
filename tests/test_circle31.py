import random
import unittest

import numpy as np

from zavod import circle31 as C


class Circle31(unittest.TestCase):
    def test_every_cell_exists_and_cells_differ_in_size(self):
        seeds = np.array([(C.R + 200 * np.cos(i), C.R + 200 * np.sin(i)) for i in range(C.CELLS)], np.float32)
        lab = C._labels(seeds, 2 * C.R)
        self.assertEqual(set(np.unique(lab)) - {-1}, set(range(C.CELLS)))
        self.assertEqual(lab[0, 0], -1)  # углы вне круга

    def test_one_turn_per_minute(self):
        self.assertEqual(360 / C.DEG_PER_SEC, 60)

    def test_disc_is_deterministic_and_fits_the_frame(self):
        a, b = C.build_disc("x"), C.build_disc("x")
        self.assertEqual(a.tobytes(), b.tobytes())
        self.assertEqual(a.size, (2 * C.R, 2 * C.R))
        cx, cy = C.CENTER
        self.assertGreaterEqual(cx - C.R, 0)
        self.assertLessEqual(cy + C.R + 140, C.H)  # под кругом место для полоски и значка Telegram

    def test_numbers_are_exactly_one_to_max_day(self):
        self.assertEqual(C.CELLS, 31)
        numbers = list(range(1, C.CELLS + 1))
        random.Random("x").shuffle(numbers)
        self.assertEqual(sorted(numbers), list(range(1, 32)))


if __name__ == "__main__":
    unittest.main()
