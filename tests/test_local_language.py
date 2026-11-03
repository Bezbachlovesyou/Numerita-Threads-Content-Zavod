import unittest
from unittest.mock import AsyncMock, MagicMock

from zavod import generator as G, lang


class LocalLanguage(unittest.TestCase):
    def test_detects_kazakh_ukrainian_belarusian_and_leaves_russian_alone(self):
        self.assertEqual(lang.local_language("Не дедің жалпы"), "казахском")
        self.assertEqual(lang.local_language("Рахмет, өте қызық"), "казахском")
        self.assertEqual(lang.local_language("Дякую, дуже цікаво, я народилася 17-го"), "украинском")
        self.assertEqual(lang.local_language("Гэта вельмі цікава, дзякуй"), "белорусском")
        self.assertEqual(lang.local_language("Спасибо, очень интересно, мне 26"), None)
        self.assertEqual(lang.local_language("26.06.57"), None)
        self.assertEqual(lang.local_language(""), None)

    def test_rule_names_the_language_and_is_empty_for_russian(self):
        self.assertIn("на казахском языке", lang.local_language_rule("жалпы"))
        self.assertEqual(lang.local_language_rule("Привет, мне 12"), "")


class PromptCarriesTheRule(unittest.IsolatedAsyncioTestCase):
    async def test_write_reply_prompt_asks_for_the_commenters_language(self):
        g = G.Generator.__new__(G.Generator)
        g.reply_model, g.reply_system, g.knowledge = "m/x", "sys", MagicMock()
        g._with_knowledge = AsyncMock(side_effect=lambda prompt, *a, **k: prompt)
        captured = {}
        async def fake_complete(system, prompt, **kw):
            captured["prompt"] = prompt
            return "ok"
        g._complete = fake_complete
        await g.write_reply("пост", "Не дедің жалпы", "abdrakhman1414")
        self.assertIn("ответь ему на казахском языке", captured["prompt"])
        await g.write_reply("пост", "Мне 12 число", "vasya")
        self.assertNotIn("ЯЗЫК ОТВЕТА", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
