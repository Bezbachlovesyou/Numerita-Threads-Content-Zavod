import unittest

from zavod.textguard import garbage, post_problem, reply_problem, similarity

OLD = ("Пары, созданные на небесах. Честная версия\n1 + 2 — Солнце и Луна дружат. До «куда пойдём?» — «Куда хочешь».\n"
       "Напиши своё число и число партнёра — скажу, вы она или нет?")


class TextGuard(unittest.TestCase):
    def test_copy_is_caught(self):
        self.assertGreaterEqual(similarity(OLD, OLD.replace("Честная", "Правдивая")), 0.35)
        self.assertIsNotNone(post_problem(OLD + " Ещё строка.", [OLD]))

    def test_fresh_post_passes(self):
        new = "Кто вообще внушил шестёркам, что любовь к красивому — слабость?\n6, 15, 24 — напишите дату, расскажу?"
        self.assertIsNone(post_problem(new, [OLD]))

    def test_repeated_question_is_caught(self):
        new = ("Совсем другой пост про девятки: щедрость без счёта, помощь соседу, вечный ремонт чужих судеб, марафоны "
               "добрых дел и чай, который всегда остывает, пока девятка спасает мир.\n"
               "Напиши своё число и число партнёра — скажу, вы она или нет?")
        self.assertIn("вопрос", post_problem(new, [OLD]))

    def test_garbage(self):
        for bad in ["Загляни в ${addr}", "Число {digit} любит порядок", "**Важно**: число", "Ссылка: [адрес бота]"]:
            self.assertTrue(garbage(bad), bad)
        self.assertIsNone(garbage("6 + 8 = 14 → 5. Лёгкость и свобода!"))

    def test_reply_repeat(self):
        old = "Тройка в паре с шестёркой — красиво: один придумывает, другой делает уютно. Что вас сейчас радует?"
        self.assertIsNotNone(reply_problem(old, [old]))
        self.assertIsNone(reply_problem("Восьмёрка держит слово, а двойка чувствует настроение — хороший тандем.", [old]))
