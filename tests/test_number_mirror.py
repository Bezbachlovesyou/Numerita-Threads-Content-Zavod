import json
import unittest
from pathlib import Path
from zavod.number_mirror import data, excerpt
from zavod.knowledge import KnowledgeBase
from zavod.autopost import load_rubrics

class MirrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_offline_context_has_selected_portrait(self):
        result = json.loads(await KnowledgeBase('').excerpt('number_mirror число души 6'))
        self.assertEqual(set(result['number_mirror']['portraits']), {'6'})
        self.assertEqual(result['number_mirror']['portraits']['6']['days'], [6,15,24])

    async def test_kindness_context_does_not_require_number_or_remote_kb(self):
        result = json.loads(await KnowledgeBase('').excerpt('Доброта — слабость?'))
        self.assertIn('не психологический закон', str(result))

    def test_all_days_once_and_examples_fit_threads(self):
        seen = []
        for key,item in data()['portraits'].items():
            seen += item['days']
            for day in item['days']:
                root = day
                while root > 9: root = sum(map(int,str(root)))
                self.assertEqual(root,int(key))
            self.assertLessEqual(len(item['post']),500)
            self.assertIn('нумеролог',item['post'].lower())
        self.assertEqual(sorted(seen),list(range(1,32)))

    def test_ordinary_topic_unchanged_and_rubric_registered(self):
        self.assertIsNone(excerpt('Как научиться играть на гитаре?'))
        rubrics = load_rubrics(Path('prompts/content_plan.md'))
        self.assertEqual(sum(r.key=='number_mirror' for r in rubrics),1)
