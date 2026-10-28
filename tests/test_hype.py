import unittest

from zavod.news import is_hype


class HypeFilter(unittest.TestCase):
    def test_media_people_pass_and_pain_or_power_is_cut(self):
        self.assertTrue(is_hype("Аня Чиповская перестала скрывать роман с коллегой"))
        self.assertTrue(is_hype("Меладзе заработает 90 миллионов рублей за концерт"))
        for bad in ("Певица задержана сотрудниками полиции после концерта",
                    "Блогер развелся с женой и платит алименты",
                    "«Состояние очень тяжелое»: подруга больной актрисы рассказала о прогнозах",
                    "Рэпер выступил перед военными на концерте в армии",
                    "Тиктокер похудел на 30 килограммов за полгода, вес шокировал"):
            self.assertFalse(is_hype(bad), bad)


class ApologyFirst(unittest.IsolatedAsyncioTestCase):
    async def test_apology_goes_before_other_seeds_once(self):
        import tempfile
        from zavod import text_mode
        from zavod.storage import Storage
        with tempfile.TemporaryDirectory() as d:
            db = Storage(d + "/t.sqlite")
            await db.init()
            await db.queue_post(await db.add_draft("x", "старый текст", "text_seed"))
            await text_mode.seed_apology(db)
            await text_mode.seed_apology(db)
            first = await text_mode.next_seed(db)
            self.assertTrue(first.text.startswith("Признаюсь"))
            rows = await db._rows("SELECT COUNT(*) AS n FROM posts WHERE topic LIKE 'apology-%'")
            self.assertEqual(rows[0]["n"], 1)
