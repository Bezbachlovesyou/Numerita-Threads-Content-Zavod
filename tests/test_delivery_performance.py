import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from zavod.storage import Storage, PgStorage
from zavod import performance, approved_post
from zavod.optimizer import post_score


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        dsn = os.getenv('DELIVERY_TEST_DSN')
        self.db = PgStorage(dsn) if dsn else Storage(self.temp.name+'/test.sqlite')
        await self.db.init()
        if dsn:
            if '/deliverytest?' not in dsn:
                raise RuntimeError('Only the dedicated deliverytest database is allowed')
            await self.db.pool.execute('TRUNCATE posts, kv, autopost_slots, comment_replies, post_metrics RESTART IDENTITY')
        self.now = datetime.now(timezone.utc)

    async def asyncTearDown(self):
        if isinstance(self.db, PgStorage):
            await self.db.pool.close()
        self.temp.cleanup()

    async def published(self, hours=24.5):
        ident = await self.db.add_draft('topic','actual hook and text','humor')
        await self.db.set_threads_id(ident, 'remote-'+str(ident))
        await self.db.mark_published(ident)
        await self.db._execute('UPDATE posts SET published_at = ? WHERE id = ?',
                              ((self.now-timedelta(hours=hours)).isoformat(), ident))
        return ident

    async def test_platform_counts_not_local_handled_messages(self):
        ident = await self.published()
        await self.db.record_comment('local', ident, 'someone', 'question', 'answer', 'replied')
        api = AsyncMock()
        api.post_stats.return_value = {'analytics': {'likes':12,'comments':8,'views':300}}
        await performance.collect(self.db, api, self.now)
        rows = await performance.comparable(self.db, self.now-timedelta(days=7))
        self.assertEqual([(r['comments'],r['likes']) for r in rows],[(8,12)])
        self.assertEqual(post_score(rows[0]),10.4)
        await performance.collect(self.db, api, self.now)
        self.assertEqual(api.post_stats.await_count,1)

    async def test_missing_not_zero_and_old_posts_not_backfilled(self):
        ident = await self.published()
        await self.published(50)
        api = AsyncMock()
        api.post_stats.return_value = {'analytics':{'likes':0,'impressions':200}}
        await performance.collect(self.db,api,self.now)
        self.assertEqual(await performance.comparable(self.db,self.now-timedelta(days=7)),[])
        sample = json.loads(await self.db.kv_get(f'performance:{ident}:24'))
        self.assertIsNone(sample['comments'])
        self.assertIsNone(sample['views'])
        self.assertEqual(api.post_stats.await_count,1)

    async def test_stale_provider_sample_not_labelled_24h(self):
        ident = await self.published()
        api = AsyncMock()
        api.post_stats.return_value = {'analytics': {'likes':1,'comments':2,
            'lastUpdated':(self.now-timedelta(hours=4)).isoformat()}}
        await performance.collect(self.db,api,self.now)
        self.assertIsNone(await self.db.kv_get(f'performance:{ident}:24'))

    def test_platform_scope_and_pending(self):
        self.assertIsNone(performance.parse({'syncStatus':'pending'}))
        self.assertIsNone(performance.parse({'platformAnalytics':[{'platform':'twitter','analytics':{'likes':99}}]}))
        result = performance.parse({'analytics':{'likes':999},'platformAnalytics':[
            {'platform':'threads','analytics':{'likes':0,'comments':0}}]})
        self.assertEqual(result['likes'],0)

    async def test_approved_once_image_required_and_confirmed(self):
        api = AsyncMock()
        api.find_post.return_value = None
        api.upload_image.return_value = 'https://image.example/approved.png'
        api.publish_text.return_value = 'zernio-confirm'
        notes = AsyncMock()
        with patch.object(approved_post.ASSET.__class__, 'read_bytes',return_value=b'approved-art'):
            self.assertTrue(await approved_post.tick(self.db,api,self.now,notes))
        args = api.publish_text.call_args
        self.assertEqual(args.args,(approved_post.TEXT,))
        self.assertEqual(args.kwargs['image_urls'],['https://image.example/approved.png'])
        api._request.return_value = (200,{'post':{'status':'published','platforms':[
            {'platform':'threads','status':'published','platformPostUrl':'https://threads.com/@numerita.ai/post/example'}]}})
        self.assertFalse(await approved_post.tick(self.db,api,self.now+timedelta(minutes=6),notes))
        self.assertFalse(await approved_post.tick(self.db,api,self.now+timedelta(minutes=12),notes))
        self.assertEqual(api.publish_text.await_count,1)
        state = json.loads(await self.db.kv_get(approved_post.KEY))
        self.assertTrue(state['done'])
        self.assertEqual((await self.db.get(state['local'])).status,'published')

    async def test_ambiguous_submit_never_repeated(self):
        api = AsyncMock()
        api.find_post.return_value = None
        api.upload_image.return_value = 'https://image.example/approved.png'
        api.publish_text.side_effect = RuntimeError('connection dropped')
        notes = AsyncMock()
        with patch.object(approved_post.ASSET.__class__, 'read_bytes',return_value=b'art'):
            with self.assertRaises(RuntimeError):
                await approved_post.tick(self.db,api,self.now,notes)
        await approved_post.tick(self.db,api,self.now+timedelta(minutes=6),notes)
        self.assertEqual(api.publish_text.await_count,1)
        self.assertFalse(json.loads(await self.db.kv_get(approved_post.KEY)).get('done',False))

    async def test_no_image_means_no_publication(self):
        api = AsyncMock()
        with patch.object(approved_post.ASSET.__class__, 'read_bytes',side_effect=OSError('missing')):
            with self.assertRaises(Exception):
                await approved_post.tick(self.db,api,self.now,AsyncMock())
        api.publish_text.assert_not_called()


if __name__ == '__main__':
    unittest.main()
