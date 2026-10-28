import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import httpx
from zavod import reply_cooldown
from zavod.autoreply import answer_comments
from zavod.bot import explain_autoreply_error, report_autoreply_error
from zavod.storage import Storage, PgStorage
from zavod.threads_api import ThreadsClient, ThreadsError

class CooldownTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Storage(self.temp.name+'/test.sqlite')
        await self.db.init()
        self.now = datetime.now(timezone.utc)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_403_80016_stops_pass_and_survives_restart(self):
        threads = AsyncMock()
        threads.comments.side_effect = ThreadsError('Platform error: 80016', http_status=403)
        with patch('zavod.autoreply.reply_targets', AsyncMock(return_value=[('a',None,''),('b',None,'')])):
            self.assertEqual(await answer_comments(self.db, threads, AsyncMock(),30,5),0)
        self.assertEqual(threads.comments.await_count,1)
        self.assertTrue(await reply_cooldown.blocked(self.db,self.now+timedelta(minutes=29)))
        await reply_cooldown.success(self.db,self.now+timedelta(minutes=31))
        await reply_cooldown.defer(self.db,ThreadsError('Platform error: 80016',http_status=403),self.now+timedelta(minutes=32))
        self.assertTrue(await reply_cooldown.blocked(self.db,self.now+timedelta(minutes=91)))
        self.assertFalse(await reply_cooldown.blocked(self.db,self.now+timedelta(minutes=93)))
        message = explain_autoreply_error('комментарии','Zernio HTTP 403: Platform error: 80016')
        self.assertIn('не подтверждение бана',message)

    async def test_unrelated_403_is_not_throttling(self):
        self.assertFalse(await reply_cooldown.defer(self.db,ThreadsError('permissions',http_status=403),self.now))

    async def test_http_status_and_retry_after_survive_api_error(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req:httpx.Response(429,json={'error':'Too many requests'},headers={'Retry-After':'900'})))
        with patch('zavod.threads_api.httpx.AsyncClient',return_value=client):
            with self.assertRaises(ThreadsError) as caught:
                await ThreadsClient('fake-key','fake-account')._request('GET','/inbox/comments')
        self.assertEqual(caught.exception.http_status,429)
        self.assertEqual(caught.exception.retry_after,'900')
        self.assertTrue(await reply_cooldown.defer(self.db,caught.exception,self.now))
        self.assertTrue(await reply_cooldown.blocked(self.db,self.now+timedelta(seconds=899)))
        self.assertFalse(await reply_cooldown.blocked(self.db,self.now+timedelta(seconds=901)))

    async def test_unknown_rate_text_is_not_proof_of_limit(self):
        self.assertFalse(await reply_cooldown.defer(self.db,ThreadsError('Generate failed'),self.now))
        text = explain_autoreply_error('ответ','Generate failed')
        self.assertNotIn('попросил отвечать реже',text)
        self.assertNotIn('Бот сам делает паузу',text)

    async def test_persisted_cooldown_prevents_any_requests(self):
        await reply_cooldown.defer(self.db,ThreadsError('limit',http_status=429),self.now)
        threads = AsyncMock()
        self.assertEqual(await answer_comments(self.db,threads,AsyncMock(),30,5),0)
        threads.comments.assert_not_awaited()
        threads.commented_posts.assert_not_awaited()
        threads.reply.assert_not_awaited()

    async def test_confirmed_limit_stops_remaining_targets(self):
        threads = AsyncMock()
        threads.comments.side_effect = ThreadsError('limit',http_status=429,retry_after='600')
        with patch('zavod.autoreply.reply_targets',AsyncMock(return_value=[('a',None,''),('b',None,'')])):
            self.assertEqual(await answer_comments(self.db,threads,AsyncMock(),30,5),0)
        self.assertEqual(threads.comments.await_count,1)
        threads.reply.assert_not_awaited()

    async def test_notice_deduplicates_and_recovery_requires_new_success(self):
        await reply_cooldown.success(self.db,self.now-timedelta(minutes=1))
        await reply_cooldown.defer(self.db,ThreadsError('limit',http_status=429),self.now)
        notify = AsyncMock()
        with patch('zavod.bot.notify_admins',notify):
            await report_autoreply_error(None,None,self.db)
            await reply_cooldown.defer(self.db,ThreadsError('again',http_status=429),self.now+timedelta(minutes=10))
            await report_autoreply_error(None,None,self.db)
            self.assertEqual(notify.await_count,1)
            self.assertIn('Источник внутри цепочки',notify.call_args.args[2])
            await self.db.kv_set('autoreply_error','')
            await report_autoreply_error(None,None,self.db)
            self.assertEqual(notify.await_count,1)
            await reply_cooldown.success(self.db,self.now+timedelta(minutes=11))
            await report_autoreply_error(None,None,self.db)
            self.assertEqual(notify.await_count,2)
            self.assertIn('успешная отправка нового ответа',notify.call_args.args[2])

@unittest.skipUnless(os.getenv('TEST_POSTGRES_DSN'),'requires isolated PostgreSQL')
class CooldownPostgres(CooldownTests):
    async def asyncSetUp(self):
        self.db=PgStorage(os.environ['TEST_POSTGRES_DSN']);await self.db.init()
        await self.db.pool.execute('TRUNCATE posts,post_metrics,autopost_slots,dialogue_messages,comment_replies,kv')
        self.now=datetime.now(timezone.utc)
    async def asyncTearDown(self):
        await self.db.pool.close()
