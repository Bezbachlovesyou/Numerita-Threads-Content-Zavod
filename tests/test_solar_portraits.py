import io
import json
import os
import random
import tempfile
import unittest
from PIL import Image, ImageDraw
from zavod import solar_portraits as solar
from zavod.cards import carousel_from_json, carousel_json, render_card, _font, _wrap
from zavod.knowledge import KnowledgeBase
from zavod.storage import Storage, PgStorage


class SolarPortraitTests(unittest.IsolatedAsyncioTestCase):
    def test_every_deck_is_complete_readable_and_self_contained(self):
        for deck in solar.data()['decks']:
            self.assertLessEqual(len(deck['caption']), 450)
            self.assertNotIn('t.me/', deck['caption'])
            slides = solar.cards(deck, 1)
            self.assertEqual(len(slides), 6)
            self.assertEqual(carousel_from_json(carousel_json(slides)), slides)
            for slide in slides:
                self.assertEqual(slide.number, '1')
                self.assertEqual(slide.dates, '1 · 10 · 19 · 28')
                # Smallest font in production renderer must retain all text, not silently cut lines.
                draw = ImageDraw.Draw(Image.new('RGB', (1080, 1350)))
                self.assertLess(draw.textlength(' '.join(slide.label.upper()), font=_font('Montserrat.ttf', 34, 'SemiBold')), 1000)
                self.assertLessEqual(len(_wrap(draw, slide.hook, _font('PlayfairDisplay.ttf', 38, 'SemiBold'), 930)), 4)
                self.assertLess(draw.textlength(slide.cta_text, font=_font('Montserrat.ttf', 34, 'SemiBold')), 950)
            rendered = Image.open(io.BytesIO(render_card(slides[0], deck['id'])))
            self.assertEqual(rendered.size, (1080, 1350))

    async def test_local_knowledge_boundaries_survive_short_context(self):
        kb = KnowledgeBase('')
        context = await kb.excerpt('one_portrait женщина-единичка 28')
        self.assertIn('трактовки символические', context[:1500])
        self.assertIn('не доказывает характер', context[:1500])
        self.assertIn('Женщина не обязана руководить', context[:1500])
        self.assertEqual(await kb.excerpt('обычная тема без чисел'), '')

    def test_variants_keep_caption_and_card_topic_together(self):
        for seed in range(10):
            deck = solar.choose(random.Random(seed))
            topic = solar.topic(deck)
            self.assertIn(deck['caption'], topic)
            self.assertIn(deck['slides'][-1][0], topic)
            self.assertIn('1, 10, 19, 28', topic)

    async def test_carousel_roundtrip_on_database(self):
        dsn = os.getenv('SOLAR_TEST_DSN')
        if dsn:
            db = PgStorage(dsn)
        else:
            self.temp = tempfile.TemporaryDirectory()
            db = Storage(self.temp.name + '/solar.sqlite')
        await db.init()
        try:
            for deck in solar.data()['decks']:
                encoded = carousel_json(solar.cards(deck, 0))
                post_id = await db.add_draft(solar.topic(deck), deck['caption'], 'one_portrait', None, encoded)
                post = await db.get(post_id)
                self.assertEqual(post.rubric, 'one_portrait')
                self.assertEqual(post.text, deck['caption'])
                self.assertEqual(len(json.loads(post.card)['carousel']), 6)
                self.assertEqual(carousel_from_json(post.card)[-1].hook, deck['slides'][-1][0])
        finally:
            if dsn:
                await db.pool.close()
            else:
                self.temp.cleanup()


if __name__ == '__main__':
    unittest.main()
