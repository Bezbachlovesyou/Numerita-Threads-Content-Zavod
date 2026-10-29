import unittest

from zavod import note


class Note(unittest.TestCase):
    def test_parse_and_render(self):
        data = note.parse('```json\n{"genre": "Жалоба", "from": "от шестёрки", "body": "Переставила диван.\\nДважды.",'
                          ' "post": "Шестёрки, узнали себя?"}\n```')
        self.assertEqual(data["genre"], "Жалоба")
        self.assertTrue(note.render(data["genre"], data["from"], data["body"]).startswith(b"\xff\xd8"))
        self.assertIsNone(note.parse("не JSON"))
