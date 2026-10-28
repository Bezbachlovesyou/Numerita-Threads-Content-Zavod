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
            self.assertTrue(first.text.startswith("Новость дня"))
            rows = await db._rows("SELECT COUNT(*) AS n FROM posts WHERE topic LIKE 'priority:%'")
            self.assertEqual(rows[0]["n"], 1)


class DnaKnowledge(unittest.TestCase):
    def test_dna_topics_get_rule_and_facts_others_do_not(self):
        from zavod.dna_genome import excerpt
        e = excerpt("Правда ли, что музыка 528 Гц чинит ДНК?")
        self.assertIn("не меняют", e["rule"])
        self.assertTrue(any("528" in f for f in e["facts"]))
        self.assertIsNone(excerpt("Шестёрки и любовь"))
