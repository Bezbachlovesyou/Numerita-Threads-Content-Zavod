import os
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zavod import text_mode
from zavod.autopost import ContentPlan,load_rubrics
from zavod.generator import Generator
from zavod.knowledge import KnowledgeBase
from zavod.threads_api import ThreadsClient,ThreadsError
from zavod.storage import Storage

class TextModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_queue_is_idempotent_and_legacy_drafts_are_preserved(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'THREADS_TEXT_ONLY':'1'}):
            db=Storage(root+'/test.sqlite');await db.init()
            old=await db.add_draft('legacy','Посмотри на картинке','grid',card='{}');await db.queue_post(old)
            await text_mode.seed(db);await text_mode.seed(db)
            rows=await db._rows("SELECT id FROM posts WHERE rubric='text_seed'")
            self.assertEqual(len(rows),6)
            self.assertEqual((await db.get(old)).status,'queued')
            self.assertEqual((await text_mode.next_seed(db)).text,text_mode.SAMPLES[0])

    def test_seed_texts_are_short_and_standalone(self):
        for text in text_mode.SAMPLES:
            self.assertLessEqual(len(text),280)
            self.assertFalse(text_mode.needs_visual(text))
    async def test_last_boundary_strips_both_video_and_images_from_legacy_draft(self):
        api=ThreadsClient('fake','fake');api._request=AsyncMock(return_value=(200,{'post':{'_id':'confirmed'}}))
        with patch.dict(os.environ,{'THREADS_TEXT_ONLY':'1'}):
            await api.publish_text('Самостоятельный текст.',image_urls=['https://example/image.png'],video_url='https://example/video.mp4')
        body=api._request.call_args.kwargs['json']
        self.assertNotIn('mediaItems',body)
        self.assertEqual(body['content'],'Самостоятельный текст.')

    async def test_experiment_can_be_reversed_explicitly(self):
        api=ThreadsClient('fake','fake');api._request=AsyncMock(return_value=(200,{'post':{'_id':'confirmed'}}))
        with patch.dict(os.environ,{'THREADS_TEXT_ONLY':'0'}):
            await api.publish_text('Текст',image_urls=['https://example/image.png'])
        self.assertEqual(len(api._request.call_args.kwargs['json']['mediaItems']),1)

    async def test_image_dependent_caption_cannot_be_published_without_image(self):
        api=ThreadsClient('fake','fake');api._request=AsyncMock()
        with patch.dict(os.environ,{'THREADS_TEXT_ONLY':'1'}):
            with self.assertRaises(ThreadsError):await api.publish_text('Найди число на картинке!')
        api._request.assert_not_awaited()

    async def test_all_post_rewrites_get_short_humorous_text_instruction(self):
        with patch.dict(os.environ,{'THREADS_TEXT_ONLY':'1'}):
            generator=Generator('fake','fake',Path('prompts/brand_voice.md'),KnowledgeBase(''))
            generator._complete=AsyncMock(return_value='Готово.')
            await generator.write_post('Сценка про шестёрку')
            self.assertIn(text_mode.STYLE,generator._complete.call_args.args[1])
            await generator.sharpen('Длинная старая заготовка')
            self.assertIn(text_mode.STYLE,generator._complete.call_args.args[1])

    def test_plan_uses_text_formats_and_excludes_visual_tasks(self):
        plan=ContentPlan(load_rubrics(Path('prompts/content_plan.md')))
        with patch.dict(os.environ,{'THREADS_TEXT_ONLY':'1'}):
            for i in range(100):
                rubric=plan.choose([],random.Random(i))
                self.assertTrue(rubric.key.startswith('text_') or rubric.key=='number_mirror')
                self.assertTrue(text_mode.allowed(rubric))
