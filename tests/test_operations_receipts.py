import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from zavod import constraint, zero_cleanup
from zavod.storage import Storage, PgStorage
from zavod.threads_api import ThreadsError


class OperationsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        dsn = os.getenv('DELIVERY_TEST_DSN')
        self.db = PgStorage(dsn) if dsn else Storage(self.temp.name+'/test.sqlite')
        await self.db.init()
        if dsn:
            await self.db.pool.execute('TRUNCATE posts, kv, autopost_slots RESTART IDENTITY')
        self.now = datetime(2026,10,29,11,0,tzinfo=timezone.utc)

    async def asyncTearDown(self):
        if isinstance(self.db, PgStorage):
            await self.db.pool.close()
        self.temp.cleanup()

    async def test_review_failure_retries_then_records_success_once(self):
        # Legacy consumed slot cannot prevent a real completed review.
        await self.db.claim_slot('toc 2026-10-29 11')
        run = AsyncMock(side_effect=[None, 'Обход, 29.10 11:15\nУзкое звено: оплата'])
        with patch('zavod.constraint.review', run):
            await constraint.run_due(self.db, None, self.now, timezone.utc)
            await constraint.run_due(self.db, None, self.now+timedelta(minutes=5), timezone.utc)
            self.assertEqual(run.await_count,1)
            await constraint.run_due(self.db, None, self.now+timedelta(minutes=15), timezone.utc)
            await constraint.run_due(self.db, None, self.now+timedelta(minutes=30), timezone.utc)
        self.assertEqual(run.await_count,2)
        state = json.loads(await self.db.kv_get('toc_run:2026-10-29:11'))
        self.assertEqual(state['status'],'success')
        self.assertIn('выполнен', await constraint.report(self.db,self.now))
        self.assertEqual(len(json.loads(await self.db.kv_get('toc_log:2026-10-29'))),1)

    async def test_review_attempts_are_bounded_and_no_restart_burst(self):
        run = AsyncMock(side_effect=RuntimeError('fake failure'))
        with patch('zavod.constraint.review',run):
            for minute in (0,15,30,45,60):
                await constraint.run_due(self.db,None,self.now+timedelta(minutes=minute),timezone.utc)
            await constraint.run_due(self.db,None,self.now.replace(hour=23),timezone.utc)
        self.assertEqual(run.await_count,3)
        self.assertEqual(json.loads(await self.db.kv_get('toc_run:2026-10-29:11'))['status'],'failed')

    async def test_review_recovers_a_claim_without_success_receipt(self):
        await self.db.claim_slot('toc_run:2026-10-29:11:attempt:1')
        run=AsyncMock(return_value='Обход, 29.10 11:15\nУзкое звено: оплата')
        with patch('zavod.constraint.review',run):
            await constraint.run_due(self.db,None,self.now,timezone.utc)
            run.assert_not_awaited()
            await constraint.run_due(self.db,None,self.now+timedelta(minutes=15),timezone.utc)
        run.assert_awaited_once()

    async def candidate(self):
        ident = await self.db.add_draft('test','Original valuable text','test')
        await self.db.set_threads_id(ident,'remote')
        await self.db.mark_published(ident)
        await self.db._execute('UPDATE posts SET published_at=? WHERE id=?',
                               ((self.now-timedelta(days=2)).isoformat(),ident))
        await self.db.kv_set(f'performance:{ident}:latest',json.dumps({'likes':0,'comments':0}))
        return ident

    def remote(self,status='published',account='ours',**extra):
        return {'post':{'status':status,'content':'Original valuable text',
                        'platforms':[{'platform':'threads','accountId':account,'status':status}],**extra}}

    def metrics(self,**extra):
        return {'platformAnalytics':[{'platform':'threads','syncStatus':'synced',
            'analytics':{'likes':0,'comments':0,'lastUpdated':self.now.isoformat(),**extra}}]}

    def client(self,**extra):
        c=AsyncMock();c.account_id='ours';c.post_stats.return_value=self.metrics()
        c._request.side_effect=[(200,self.remote()),(200,{'comments':[]}),(200,self.remote('cancelled'))]
        for k,v in extra.items():setattr(c,k,v)
        return c

    async def test_cleanup_backs_up_and_only_marks_deleted_after_readback(self):
        ident=await self.candidate();c=self.client()
        async def mutate(_):
            backup=json.loads(await self.db.kv_get(f'zero_cleanup:post:{ident}'))
            self.assertEqual(backup['status'],'attempting')
            self.assertEqual(backup['text'],'Original valuable text')
        c.unpublish.side_effect=mutate
        await zero_cleanup.tick(self.db,c,self.now)
        c.unpublish.assert_awaited_once_with('remote')
        self.assertEqual((await self.db.get(ident)).status,'deleted')
        self.assertIn('удаление подтверждено',await zero_cleanup.report(self.db,self.now))
        await zero_cleanup.tick(self.db,c,self.now+timedelta(hours=2))
        self.assertEqual(c.unpublish.await_count,1)

    async def test_cleanup_unknown_post_outcome_reconciles_without_repeat(self):
        ident=await self.candidate();c=self.client()
        c.unpublish.side_effect=ThreadsError('timeout')
        await zero_cleanup.tick(self.db,c,self.now)
        self.assertEqual((await self.db.get(ident)).status,'published')
        c._request.side_effect=[(200,self.remote('cancelled'))]
        await zero_cleanup.tick(self.db,c,self.now+timedelta(hours=1))
        self.assertEqual(c.unpublish.await_count,1)
        self.assertEqual((await self.db.get(ident)).status,'deleted')

    async def test_cleanup_preserves_unknown_stale_reacting_and_foreign_posts(self):
        ident=await self.candidate()
        for payload in (None, self.metrics(likes=1),self.metrics(likes=.2),
                        self.metrics(lastUpdated=(self.now-timedelta(hours=2)).isoformat())):
            await self.db.kv_set('zero_cleanup:last_scan','')
            c=self.client();c.post_stats.return_value=payload
            await zero_cleanup.tick(self.db,c,self.now)
            c.unpublish.assert_not_awaited()
        for payload in (self.remote(account='someone_else'), self.remote(threadedContent=['another post'])):
            await self.db.kv_set('zero_cleanup:last_scan','')
            c=self.client();c._request.side_effect=[(200,payload)]
            await zero_cleanup.tick(self.db,c,self.now)
            c.unpublish.assert_not_awaited()
        self.assertEqual((await self.db.get(ident)).status,'published')

    async def test_cleanup_preserves_new_comments_and_bounded_daily_mutations(self):
        await self.candidate();c=self.client()
        c._request.side_effect=[(200,self.remote()),(200,{'comments':[{'id':'new'}]})]
        await zero_cleanup.tick(self.db,c,self.now)
        c.unpublish.assert_not_awaited()
        await self.db.kv_set('zero_cleanup:last_scan','')
        await self.db.kv_set('zero_cleanup:day:2026-10-29','3')
        c=self.client();await zero_cleanup.tick(self.db,c,self.now)
        c._request.assert_not_awaited()
