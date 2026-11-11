import re
import unittest

from zavod import momchild as M


class MomChild(unittest.TestCase):
    def test_three_posts_fit_threads_and_every_number_is_there(self):
        for lang in ("ru", "en"):
            for who in ("mom", "dad"):
                items = M.thread(lang, who)
                self.assertEqual(len(items), 3)
                text = "\n".join(items)
                self.assertTrue(all(len(i) <= M.LIMIT for i in items))
                for n in range(1, 10):
                    self.assertIn(f"{M.WORDS[lang][who]['who']} {n} (", text)

    def test_table_is_symmetric_like_the_base(self):
        for a in range(1, 10):
            for b in range(1, 10):
                self.assertEqual(b in M.GOOD[a], a in M.GOOD[b])
                self.assertEqual(b in M.HARD[a], a in M.HARD[b])
            self.assertFalse(set(M.GOOD[a]) & set(M.HARD[a]))

    def test_tones_reads_live_base(self):
        kb = {"pairs": {f"{a}-{b}": {"tone": "good" if b in M.GOOD[a] else "hard" if b in M.HARD[a] else "mixed"}
                        for a in range(1, 10) for b in range(a, 10)}}
        self.assertEqual(M.tones(kb), (M.GOOD, M.HARD))

    def test_tease_is_true_and_languages_do_not_mix(self):
        self.assertEqual(sum(1 for n in M.HARD if not M.HARD[n]), 2)   # «у двух ребёнка-учителя нет»
        self.assertEqual(max(len(v) for v in M.HARD.values()), 5)       # «у одного их пять»
        self.assertIsNone(re.search("[А-Яа-яЁё]", "\n".join(M.thread("en", "mom") + M.thread("en", "dad"))))
        ru = "\n".join(M.thread("ru"))
        self.assertIsNone(re.search(r"[A-Za-z]", ru))
        for bad in ("карм", "несовместим", "проклят"):
            self.assertNotIn(bad, ru.lower())


if __name__ == "__main__":
    unittest.main()
