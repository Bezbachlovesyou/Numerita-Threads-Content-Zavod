import unittest

from zavod.bot import POST_PREFIX, is_owner_question, owner_facts


class OwnerQuestion(unittest.TestCase):
    def test_questions_about_factory_are_answered(self):
        for t in ['А какой лимит ссылок в комментариях? Может увеличить его?', 'Сколько расходов сегодня?',
                  'Можешь выключить ответы ночью?']:
            self.assertTrue(is_owner_question(t), t)

    def test_topics_stay_posts(self):
        for t in ['Почему рождённые 8 любят порядок?', 'Любовь и числа', 'Число 6 и красота']:
            self.assertFalse(is_owner_question(t), t)
        self.assertTrue(POST_PREFIX.match('пост: какой лимит?'))

    def test_facts_name_real_limits(self):
        facts = owner_facts()
        self.assertIn('20 в сутки', facts)
        self.assertIn('25 в час', facts)
