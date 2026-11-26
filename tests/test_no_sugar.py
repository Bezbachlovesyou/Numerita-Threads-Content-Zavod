import random
import unittest
from datetime import datetime
from pathlib import Path
from zavod import autopost

class NoSugar(unittest.TestCase):
    def test_approved_rubric_is_renderable_and_attributed(self):
        plan=autopost.ContentPlan(autopost.load_rubrics(Path('prompts/content_plan.md')))
        rubric=next(r for r in plan.all_rubrics() if r.key=='text_no_sugar')
        slot=plan.render(rubric,datetime(2026,11,26,15),random.Random(1))
        self.assertTrue(slot.tag.startswith('fail'))
        self.assertNotIn('{arcana}',slot.topic)
        self.assertIn('не вычисленный сегодняшний',slot.topic)
        self.assertEqual(autopost.topic_tag_for(rubric.key),'Astrology Threads')
