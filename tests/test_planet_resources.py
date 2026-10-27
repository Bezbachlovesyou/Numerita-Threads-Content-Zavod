import unittest,json
from zavod.planet_resources import data,excerpt
from zavod.knowledge import KnowledgeBase
from zavod.autopost import ContentPlan
from pathlib import Path
class PlanetTests(unittest.IsolatedAsyncioTestCase):
 async def test_knowledge_without_remote_kb(self):
  result=json.loads(await KnowledgeBase('').excerpt('planet_resources — сильные планеты'))
  self.assertEqual(len(result['planet_resources']['items']),6)
  self.assertIn('Не выводить силу',result['planet_resources']['rule'])
 async def test_ordinary_topic_has_no_extra_context(self):
  self.assertIsNone(excerpt('обычный вопрос о книге'))
 def test_posts_fit_and_no_false_strength_result(self):
  for text in data()['posts']:
   self.assertLessEqual(len(text),500)
   self.assertNotIn('У вас сильн',text)
  self.assertEqual(data()['paid']['state'],'specification_not_live_in_core_bot')
