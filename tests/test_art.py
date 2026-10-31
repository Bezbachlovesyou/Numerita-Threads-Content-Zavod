import unittest
from unittest.mock import patch

from zavod import art, lang
from zavod import bot as B
from zavod import text_mode

GOOD = "ХУК: 9\nИНТРИГА: 8\nЮМОР: 9\nСОДЕРЖАНИЕ: 8\nЖИВОСТЬ: 9\nРИФМА: ДА\nШАБЛОН: НЕТ\nСЛАБОЕ: нет"
BLAND = "ХУК: 6\nИНТРИГА: 6\nЮМОР: 5\nСОДЕРЖАНИЕ: 7\nЖИВОСТЬ: 6\nРИФМА: НЕТ\nШАБЛОН: ДА\nСЛАБОЕ: общие слова, панч предсказуем"
TEMPLATE_BUT_HIGH = GOOD.replace("ШАБЛОН: НЕТ", "ШАБЛОН: ДА")


class Gen:
    reply_model = "cheap"
    system = "голос"

    def __init__(self, judges, elevations=(), judge_error=False):
        self.judges, self.elevations, self.judge_error = list(judges), list(elevations), judge_error
        self.calls = []

    async def improve(self, system, prompt, max_tokens=None, kind="other", model=None):
        self.calls.append(kind)
        if kind == "coherence":
            return "OK"
        if kind == "art":
            if self.judge_error:
                raise RuntimeError("нет связи")
            return self.judges.pop(0)
        if kind == "elevate":
            return self.elevations.pop(0)
        raise AssertionError(kind)


def reset():
    art._state["rejects"] = 0
    art.STATS.update(day=None, judged=0, passed_first=0, elevated=0, rejected=0, forced=0, rhyme=0, sum=0.0)


class Parse(unittest.TestCase):
    def test_parse_and_bar(self):
        good, bland = art.parse(GOOD), art.parse(BLAND)
        self.assertTrue(art.passed(good) and good["rhyme"])
        self.assertFalse(art.passed(bland))
        self.assertEqual(bland["weak"], "общие слова, панч предсказуем")
        self.assertIsNone(art.parse("ХУК: 9"))  # неполный ответ не разобран
        self.assertFalse(art.passed(art.parse(TEMPLATE_BUT_HIGH)))  # «шаблон» не пропускается даже с высокими баллами
        floor = art.parse(GOOD.replace("ЮМОР: 9", "ЮМОР: 3"))
        self.assertGreaterEqual(floor["total"], 8.0 - 1.3)
        self.assertFalse(art.passed(floor))  # одно провальное измерение — не пройдено


class Gate(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset()

    async def test_good_text_goes_unchanged_without_rewrites(self):
        gen = Gen([GOOD])
        self.assertEqual(await art.art_gate(gen, "Текст"), "Текст")
        self.assertEqual(gen.calls, ["art"])
        self.assertIn("с рифмой 1", art.stats_line())

    async def test_bland_text_is_elevated_once_and_passes(self):
        gen = Gen([BLAND, GOOD], ["Поднятый текст"])
        self.assertEqual(await art.art_gate(gen, "Скучный текст"), "Поднятый текст")
        self.assertEqual(gen.calls, ["art", "elevate", "art"])

    async def test_still_bland_after_two_lifts_is_not_published(self):
        gen = Gen([BLAND, BLAND, BLAND], ["Раз", "Два"])
        self.assertIsNone(await art.art_gate(gen, "Скучный текст"))
        self.assertEqual(art.STATS["rejected"], 1)

    async def test_feed_is_not_stopped_forever_after_repeated_rejections(self):
        for _ in range(art.FALLBACK_AFTER - 1):
            gen = Gen([BLAND] * 3, ["a", "b"])
            self.assertIsNone(await art.art_gate(gen, "Скучный текст"))
        gen = Gen([BLAND] * 3, ["лучше", "ещё лучше"])
        self.assertIsNotNone(await art.art_gate(gen, "Скучный текст"))  # запасное правило: выпускаем лучший вариант
        self.assertEqual(art.STATS["forced"], 1)

    async def test_judge_failure_never_blocks_a_post(self):
        gen = Gen([], judge_error=True)
        self.assertEqual(await art.art_gate(gen, "Текст"), "Текст")

    async def test_english_lift_with_russian_letters_is_rejected(self):
        gen = Gen([BLAND], ["Поднятый текст на русском"])
        self.assertIsNone(await art.art_gate(gen, "Plain text", english=True))

    async def test_too_long_lift_is_rejected(self):
        gen = Gen([BLAND], ["я" * (art.MAX_TEXT + 1)])
        self.assertIsNone(await art.art_gate(gen, "Скучный текст"))


class Integration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset()

    async def test_hook_gate_keeps_links_and_returns_none_when_bar_is_missed(self):
        link = "t.me/Numeritabot?start=ad_th_x1_3110"
        gen = Gen([GOOD])
        out = await B.hook_gate(gen, f"Хороший текст\n{link}")
        self.assertIn(link, out)
        reset()
        gen = Gen([BLAND, BLAND, BLAND], ["раз", "два"])
        self.assertIsNone(await B.hook_gate(gen, f"Скучный текст\n{link}"))

    async def test_antidupe_gate_passes_none_through(self):
        self.assertIsNone(await B.antidupe_gate(None, None, None, None))


class PrincipleIsWritten(unittest.TestCase):
    def test_principle_is_in_every_layer(self):
        self.assertIn("АРТ-ОБЪЕКТ", text_mode.STYLE)
        self.assertIn("рифм", text_mode.STYLE)
        self.assertNotIn("Цель 120–280 знаков", text_mode.STYLE)  # жанровый замок снят
        self.assertIn("elevate", lang.PUBLIC_KINDS)
        self.assertIn("rhyme", lang.EN_RULE)
        voice = open("prompts/brand_voice.md", encoding="utf-8").read()
        self.assertIn("КАЖДЫЙ ТЕКСТ — АРТ-ОБЪЕКТ", voice)
        self.assertIn("МИНИМАЛЬНО", B.COHERENCE_SYSTEM)
        self.assertIn("не сглаживай", B.COHERENCE_SYSTEM)


if __name__ == "__main__":
    unittest.main()
