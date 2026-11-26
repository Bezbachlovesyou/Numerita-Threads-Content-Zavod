import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zavod.storage import Storage, PgStorage
from zavod import reply_closure as job
from zavod.threads_api import ThreadsClient, ThreadsError

class Counts(unittest.TestCase):
    def test_real_links_not_hints_or_other_bots(self):
        rows=[{'reply':s} for s in ['https://t.me/Numeritabot?start=ru https://t.me/numeritabot/app',
            '@Numeritabot — ссылка в шапке', 'link in bio', 'https://t.me/otherbot', 'https://example.org/app']]
        self.assertEqual(job.count_links(rows),dict(confirmed_answers=5,answers_with_url=1,url_occurrences=2,mentions_without_url=1,profile_hints=2))

class Closure(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Storage(self.tmp.name+'/test.db');await self.db.init()
        self.client=SimpleNamespace(commented_posts=AsyncMock(return_value=[{'id':'p','content':'post'}]),comments=AsyncMock(return_value=[{'id':'c','message':'Question?','from':{'username':'reader'},'canReply':True}]))
        self.mirror=AsyncMock();self.bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)))
        self.cfg=SimpleNamespace(admin_ids={1})
        self.env=patch.dict(os.environ,COMMENTS_CLOSURE_JOB='test');self.env.start()
    async def asyncTearDown(self):self.env.stop();self.tmp.cleanup()
    async def run_tick(self):
        with patch('zavod.reply_closure.reply_cooldown.blocked',AsyncMock(return_value=False)):
            await job.tick(self.db,self.client,self.bot,self.cfg,self.mirror)
    async def test_pending_survives_restart_then_confirmed_send_clears(self):
        await self.run_tick();state=await job.load(self.db)
        self.assertEqual(state['pending'],1);self.assertFalse(state['complete']);self.bot.send_message.assert_not_called()
        self.assertEqual(len(await job.extra_targets(self.db)),1)
        restarted=Storage(self.db.path);await restarted.init();self.db=restarted
        await self.db.record_comment('c',None,'reader','Question?','Answer','replied')
        state['next']=0;await job.save(self.db,state);await self.run_tick()
        state=await job.load(self.db);self.assertTrue(state['complete']);self.assertEqual(state['sent_during_job'],1)
    async def test_error_never_becomes_empty_queue(self):
        self.client.comments.side_effect=ThreadsError('failed',http_status=429)
        with patch('zavod.reply_closure.reply_cooldown.defer',AsyncMock()):await self.run_tick()
        state=await job.load(self.db);self.assertFalse(state['complete']);self.assertIn('error',state)
        self.bot.send_message.assert_not_called()
    async def test_notice_reserved_before_api_and_no_blind_retry(self):
        state={};self.bot.send_message.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):await job.notify_once(self.db,state,self.bot,self.cfg,'done')
        self.assertEqual((await job.load(self.db))['notice'],'reserved')
        await job.notify_once(self.db,state,self.bot,self.cfg,'done')
        self.assertEqual(self.bot.send_message.call_count,1)

class Pagination(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_requires_all_pages(self):
        c=ThreadsClient('fake','fake');c._request=AsyncMock(side_effect=[(200,{'data':[{'id':'a'}],'pagination':{'hasMore':True,'cursor':'next'}}),(200,{'data':[{'id':'b'}],'pagination':{'hasMore':False}})])
        self.assertEqual(len(await c.commented_posts(datetime.now(timezone.utc),all_pages=True)),2)
    async def test_comments_truncation_is_not_success(self):
        c=ThreadsClient('fake','fake');c._request=AsyncMock(return_value=(200,{'comments':[{'id':'a'}],'pagination':{'hasMore':True,'cursor':'next'}}))
        with self.assertRaises(ThreadsError):await c.comments('p',max_pages=1)

if __name__=='__main__':unittest.main()

class PostgresClosure(Closure):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        import asyncpg, uuid
        self.schema='closure_'+uuid.uuid4().hex[:12]
        self.dsn='postgresql://postgres@localhost:5433/postgres'
        self.db=PgStorage(self.dsn,schema=self.schema)
        await self.db.init()
    async def asyncTearDown(self):
        import asyncpg
        await self.db.pool.close()
        conn=await asyncpg.connect(self.dsn)
        await conn.execute('DROP SCHEMA '+self.schema+' CASCADE')
        await conn.close()
        await super().asyncTearDown()
    async def test_pending_survives_restart_then_confirmed_send_clears(self):
        # Production persistence survives creating a new storage object.
        await self.run_tick();state=await job.load(self.db)
        self.assertEqual(state['pending'],1)
        await self.db.pool.close()
        self.db=PgStorage(self.dsn,schema=self.schema);await self.db.init()
        await self.db.record_comment('c',None,'reader','Question?','Answer','replied')
        state['next']=0;await job.save(self.db,state);await self.run_tick()
        state=await job.load(self.db);self.assertTrue(state['complete']);self.assertEqual(state['sent_during_job'],1)

class Combined(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_both_then_reports_once(self):
        state={'job':'same','complete':'now','targets':[], 'sent_during_job':2,'skipped_during_job':1,'links72h':job.count_links([{'reply':'https://t.me/numeritabot'}])}
        db=SimpleNamespace(pool=SimpleNamespace(fetchval=AsyncMock(return_value=json.dumps({'job':'same','complete':False}))),kv_set=AsyncMock())
        bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=42)))
        cfg=SimpleNamespace(admin_ids={1});mirror=AsyncMock()
        with patch('zavod.reply_closure.lang.is_en',return_value=False):
            await job.combined_report(db,state,bot,cfg,mirror);bot.send_message.assert_not_called()
            db.pool.fetchval.return_value=json.dumps(state)
            await job.combined_report(db,state,bot,cfg,mirror)
            await job.combined_report(db,state,bot,cfg,mirror)
        self.assertEqual(bot.send_message.call_count,1)
        self.assertIn('2 прямых ссылок',bot.send_message.call_args.args[1])
