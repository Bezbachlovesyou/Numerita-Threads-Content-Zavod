import os
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zavod import text_mode
from zavod.autopost import ContentPlan,load_rubrics
from zavod.cards import make_grid,grid_json
from zavod.generator import Generator
from zavod.knowledge import KnowledgeBase
from zavod.threads_api import ThreadsClient
from zavod.storage import Storage
from zavod.bot import publish

class GridExceptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_publish_path_keeps_grid_with_cards_off_but_not_portraits(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'THREADS_TEXT_ONLY':'1','THREADS_GRID_EXCEPTION':'1'}):
            db=Storage(root+'/test.sqlite');await db.init()
            for rubric,card,expected in [('grid',grid_json(make_grid(random.Random(3)),'Числа',0),True),
                                         ('one_portrait','{}',False)]:
                ident=await db.add_draft('Тема','Игровая сценка.',rubric,card=card)
                api=ThreadsClient('fake','fake');api._request=AsyncMock(return_value=(200,{'post':{'_id':str(ident)}}))
                images=AsyncMock(return_value=['https://example/grid.jpg'])
                with patch('zavod.bot.ensure_images',images):
                    result=await publish(await db.get(ident),db,api,None,'',cards=False)
                self.assertEqual(result.status,'published')
                self.assertEqual('mediaItems' in api._request.call_args.kwargs['json'],expected)
                self.assertEqual(images.await_count,1 if expected else 0)
    async def test_only_explicit_single_grid_image_passes_final_boundary(self):
        api=ThreadsClient('fake','fake');api._request=AsyncMock(return_value=(200,{'post':{'_id':'published'}}))
        with patch.dict(os.environ,{'THREADS_TEXT_ONLY':'1','THREADS_GRID_EXCEPTION':'1'}):
            await api.publish_text('Какие числа на картинке заметили первыми?',image_urls=['https://example/grid.jpg'],media_kind='number_grid')
            self.assertEqual(api._request.call_args.kwargs['json']['mediaItems'],[{'type':'image','url':'https://example/grid.jpg'}])
            await api.publish_text('Самостоятельный текст.',image_urls=['https://example/portrait.jpg'])
            self.assertNotIn('mediaItems',api._request.call_args.kwargs['json'])
            await api.publish_text('Самостоятельный текст.',image_urls=['a','b'],media_kind='number_grid')
            self.assertNotIn('mediaItems',api._request.call_args.kwargs['json'])
            await api.publish_text('Самостоятельный текст.',image_urls=['a'],video_url='v',media_kind='number_grid')
            self.assertNotIn('mediaItems',api._request.call_args.kwargs['json'])

    def test_real_grid_required_before_ignoring_cards_off(self):
        with patch.dict(os.environ,{'THREADS_TEXT_ONLY':'1','THREADS_GRID_EXCEPTION':'1'}):
            post=SimpleNamespace(rubric='grid',card=grid_json(make_grid(random.Random(2)),'Числа',0))
            self.assertTrue(text_mode.grid_post(post))
            post.rubric='one_portrait';self.assertFalse(text_mode.grid_post(post))
            post.rubric='grid';post.card='{"grid":{"rows":["not a matrix"]}}'
            self.assertFalse(text_mode.grid_post(post))

    def test_plan_keeps_grid_but_never_carousels_and_spaces_grid_posts(self):
        plan=ContentPlan(load_rubrics(Path('prompts/content_plan.md')))
        with patch.dict(os.environ,{'THREADS_TEXT_ONLY':'1','THREADS_GRID_EXCEPTION':'1'}):
            selected={plan.choose([],random.Random(i)).key for i in range(200)}
            self.assertIn('grid',selected)
            self.assertFalse(selected & (text_mode.VISUAL_KEYS-{'grid'}))
            for i in range(100):self.assertNotEqual(plan.choose(['text_chat','grid'],random.Random(i)).key,'grid')

    async def test_grid_caption_uses_explicit_exception_not_text_only_instruction(self):
        with patch.dict(os.environ,{'THREADS_TEXT_ONLY':'1','THREADS_GRID_EXCEPTION':'1'}):
            generator=Generator('fake','fake',Path('prompts/brand_voice.md'),KnowledgeBase(''))
            generator._complete=AsyncMock(return_value='Какие три числа заметили первыми?')
            await generator.write_post(text_mode.GRID_MARKER+' Матрица с числами')
            system,prompt=generator._complete.call_args.args[:2]
            self.assertNotIn(text_mode.STYLE,system)
            self.assertIn(text_mode.GRID_STYLE,prompt)


class ShapeGrid(unittest.TestCase):
    def test_every_shape_renders_and_passes_single_image_check(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from zavod import text_mode
        from zavod.cards import GRID_STYLES, render_grid
        for style in GRID_STYLES:
            grid = make_grid(random.Random(5), style=style)
            self.assertEqual(len(grid["hidden"]), 7, style)
            if style != "classic":
                for seq in grid["hidden"]:
                    self.assertIn(seq, grid["digits"], style)
            self.assertGreater(len(render_grid(grid, "Вопрос?", 1, "t")), 50_000)
            post = SimpleNamespace(rubric="grid", card=grid_json(grid, "Вопрос?", 1))
            with patch.object(text_mode, "enabled", return_value=True), \
                 patch.object(text_mode, "grid_enabled", return_value=True):
                self.assertTrue(text_mode.grid_post(post), style)
