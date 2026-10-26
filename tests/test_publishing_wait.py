import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from zavod.autoreply import answer_comments
from zavod.publishing_wait import defer_publishing, publication_ready
from zavod.storage import Storage, PgStorage
from zavod.threads_api import ThreadsError


class PendingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + '/test.db')
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_wait_escalate_restart_and_recovery(self):
        now = datetime.now(timezone.utc)
        error = ThreadsError('Zernio: Post waiting has no platform post ID yet (status: publishing).')
        await self.db.kv_set('autoreply_error', str(error))
        self.assertTrue(await defer_publishing(self.db, 'waiting', error, now))
        self.assertEqual(await self.db.kv_get('autoreply_error'), '')
        first = await self.db.kv_get('publishing_wait:waiting')
        await defer_publishing(self.db, 'waiting', error, now + timedelta(minutes=5))
        self.assertEqual(first, await self.db.kv_get('publishing_wait:waiting'))
        await defer_publishing(self.db, 'waiting', error, now + timedelta(minutes=31))
        self.assertIn('больше 30 минут', await self.db.kv_get('autoreply_error'))
        await publication_ready(self.db, 'waiting')
        self.assertEqual(await self.db.kv_get('autoreply_error'), '')
        self.assertEqual(await self.db.kv_get('publishing_wait:waiting'), '')

    async def test_other_errors_not_hidden(self):
        await self.db.kv_set('autoreply_error', 'rate limited')
        for text in ['status: failed', 'has no platform post ID yet (status: failed)', 'rate limited', '401 Unauthorized']:
            self.assertFalse(await defer_publishing(self.db, 'waiting', ThreadsError(text), datetime.now(timezone.utc)))
        await publication_ready(self.db, 'waiting')
        self.assertEqual(await self.db.kv_get('autoreply_error'), 'rate limited')

    async def test_pending_post_does_not_block_healthy_post(self):
        class Threads:
            def __init__(self):
                self.calls = []
            async def comments(self, target):
                self.calls.append(target)
                if target == 'waiting':
                    raise ThreadsError('Post waiting has no platform post ID yet (status: publishing).')
                return [{'id': 'owner-message', 'message': 'Existing reply',
                         'from': {'id': 'owner', 'username': 'owner', 'isOwner': True}}]
        threads = Threads()
        with patch('zavod.autoreply.reply_targets', new=AsyncMock(return_value=[
                ('waiting', None, 'pending'), ('ready', None, 'published')])):
            self.assertEqual(await answer_comments(self.db, threads, None, 60, 8), 0)
        self.assertEqual(threads.calls, ['waiting', 'ready'])
        self.assertIsNotNone(await self.db.dialogue_message('ready', 'owner-message'))
        self.assertFalse(await self.db.kv_get('autoreply_error'))


@unittest.skipUnless(os.environ.get('TEST_POSTGRES_DSN'), 'requires isolated test PostgreSQL')
class PendingPostgresTests(PendingTests):
    async def asyncSetUp(self):
        self.db = PgStorage(os.environ['TEST_POSTGRES_DSN'])
        await self.db.init()
        await self.db.pool.execute('TRUNCATE dialogue_messages, comment_replies, kv')

    async def asyncTearDown(self):
        await self.db.pool.close()
