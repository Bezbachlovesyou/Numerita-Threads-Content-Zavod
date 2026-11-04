import random
import unittest
from datetime import datetime
from pathlib import Path

from zavod import autopost, bot as B
from zavod.optimizer import short_name


class NewThemes(unittest.TestCase):
    def setUp(self):
        self.rubrics = {r.key: r for r in autopost.load_rubrics(Path("prompts/content_plan.md"))}

    def test_rubrics_exist_with_honest_rules_and_no_living_names(self):
        for key in ("text_rita", "text_angel", "text_goals_story"):
            self.assertIn(key, self.rubrics)
            self.assertIn(key, autopost.CORE)
            self.assertFalse(short_name(key).startswith("text_"))
            slot = autopost.ContentPlan(list(self.rubrics.values())).render(self.rubrics[key], datetime(2026, 11, 5, 12), random.Random(2))
            self.assertNotIn("{", slot.topic)
        rita = self.rubrics["text_rita"].text
        for part in ("ТРАДИЦИЕЙ", "не прогноз", "Не называй живых авторов"):
            self.assertIn(part, rita)
        for banned in ("Торсунов", "Хакимов"):
            self.assertNotIn(banned, " ".join(r.text for r in self.rubrics.values() if r.key in ("text_rita", "text_angel", "text_goals_story")))

    def test_goals_never_invent_stories(self):
        text = self.rubrics["text_goals_story"].text
        for part in ("Только ПРАВДА", "не выдумывай историй", "Не обещай"):
            self.assertIn(part, text)
        slot = autopost.ContentPlan(list(self.rubrics.values())).render(self.rubrics["text_goals_story"], datetime(2026, 11, 5, 12), random.Random(2))
        self.assertIn("нет подтверждённых цифр", slot.topic)


if __name__ == "__main__":
    unittest.main()
