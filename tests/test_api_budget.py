import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import httpx
from zavod.api_budget import RequestBudget, report
from zavod.autoreply import answer_comments
from zavod.storage import Storage, PgStorage
from zavod.threads_api import ThreadsClient

class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Storage(self.temp.name+'/test.sqlite');await self.db.init()
        self.time=1000.0
        async def sleep(delay): self.time+=delay
        self.sleep=sleep
    async def asyncTearDown(self):self.temp.cleanup()

    async def test_pacing_survives_new_client_and_keeps_reserve(self):
        a=RequestBudget(self.db,lambda:self.time,self.sleep)
        await a.before();self.assertEqual(self.time,1000)
        b=RequestBudget(self.db,lambda:self.time,self.sleep)
        await b.before();self.assertEqual(self.time,1003)
        await b.observe(httpx.Response(200,headers={'X-RateLimit-Limit':'60','X-RateLimit-Remaining':'10',
            'X-RateLimit-Reset':'1060'}),'GET','/inbox/comments/x')
        await a.before();self.assertEqual(self.time,1061)
        self.assertIn('10.0 из 60.0',await report(self.db,datetime.now(timezone.utc)))

    async def test_confirmed_provider_window_is_distinct_from_unknown_upstream(self):
        budget=RequestBudget(self.db,lambda:self.time,self.sleep)
        await budget.observe(httpx.Response(429,json={'details':{'currentCount':61,'limit':60}},
            headers={'Retry-After':'90'}),'GET','/inbox/comments/x')
        d=json.loads(await self.db.kv_get('api:last_429'))
        self.assertEqual(d['layer'],'zernio_request_window')
        self.assertEqual(d['kind'],'read_comments')
        await budget.before();self.assertEqual(self.time,1090)
        await budget.observe(httpx.Response(429,json={'code':'rate_limited','platform':'threads'}),
                             'POST','/inbox/comments/x')
        self.assertEqual(json.loads(await self.db.kv_get('api:last_429'))['layer'],'upstream_threads')

    async def test_invalid_body_still_records_429_without_inventing_source(self):
        b=RequestBudget(self.db,lambda:self.time,self.sleep)
        await b.observe(httpx.Response(429,json='unexpected'),'GET','/inbox/comments/x')
        self.assertEqual(json.loads(await self.db.kv_get('api:last_429'))['layer'],'unknown')

    async def test_scan_rotates_without_abandoning_old_posts(self):
        targets=[(str(i),None,'') for i in range(12)]
        threads=AsyncMock();threads.comments.return_value=[]
        with patch('zavod.autoreply.reply_targets',AsyncMock(return_value=targets)):
            await answer_comments(self.db,threads,AsyncMock(),30,5)
            self.assertEqual([c.args[0] for c in threads.comments.await_args_list],list(map(str,range(6))))
            threads.comments.reset_mock()
            await answer_comments(self.db,threads,AsyncMock(),30,5)
            self.assertEqual([c.args[0] for c in threads.comments.await_args_list],list(map(str,range(6,12))))

    async def test_paging_keeps_all_existing_pages_in_selected_thread(self):
        client=ThreadsClient('fake','a',self.db)
        client._request=AsyncMock(side_effect=[(200,{'comments':[{'id':'one'}],
            'pagination':{'hasMore':True,'cursor':'next-one'}}),(200,{'comments':[{'id':'two'}],
            'pagination':{'hasMore':True,'cursor':'next-two'}}),
            (200,{'comments':[{'id':'three'}],'pagination':{'hasMore':False}})])
        self.assertEqual([p['id'] for p in await client.comments('post')],['one','two','three'])
        self.assertEqual(client._request.call_args.kwargs['params']['cursor'],'next-two')

@unittest.skipUnless(os.getenv('TEST_POSTGRES_DSN'),'requires isolated PostgreSQL')
class BudgetPostgres(BudgetTests):
    async def asyncSetUp(self):
        self.db=PgStorage(os.environ['TEST_POSTGRES_DSN']);await self.db.init()
        await self.db.pool.execute('TRUNCATE posts,post_metrics,autopost_slots,dialogue_messages,comment_replies,kv')
        self.time=1000.0
        async def sleep(delay):self.time+=delay
        self.sleep=sleep
    async def asyncTearDown(self):await self.db.pool.close()
