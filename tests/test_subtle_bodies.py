import json
import time
import unittest
from zavod.knowledge import KnowledgeBase
from zavod.subtle_bodies import data, excerpt


class SubtleBodiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_topic_without_remote_and_no_unrelated_injection(self):
        kb = KnowledgeBase('')
        self.assertEqual(await kb.excerpt('любовь и отношения'), '')
        answer = json.loads(await kb.excerpt('семь тонких тел и число 6'))
        self.assertIn('subtle_bodies', answer)
        self.assertIn('не научная анатомия', answer['subtle_bodies']['status'])

    async def test_boundaries_survive_reply_budget(self):
        kb = KnowledgeBase('https://unused.invalid')
        kb.data = {'usage': 'x' * 3000, 'numbers': {}}
        kb.loaded_at = time.monotonic()
        answer = await kb.excerpt('семь ракурсов заботы 6')
        self.assertIn('не научная анатомия', answer[:1500])
        self.assertIn('не указывает повреждение', answer[:1500])
        self.assertIn('не доказывают семь тел', answer[:1500])

    def test_topic_matching_and_complete_sources(self):
        for topic in ['Семь тонких тел', 'семи тонких тел', 'seven subtle bodies', 'пять кош']:
            self.assertTrue(excerpt(topic), topic)
        self.assertIsNone(excerpt('семь рублей'))
        self.assertEqual(len(data()['sources']), 25)
        self.assertEqual(set(data()['number_bridge']['focus']), set('123456789'))
