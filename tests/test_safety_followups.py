import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zavod.storage import Storage, PgStorage
from zavod import brandvideo, instagram, autoreply


class SafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        dsn = os.getenv('DELIVERY_TEST_DSN')
        self.db = PgStorage(dsn) if dsn else Storage(self.temp.name + '/safety.sqlite')
        await self.db.init()
        if dsn:
            await self.db.pool.execute('TRUNCATE posts, kv, autopost_slots RESTART IDENTITY')

    async def asyncTearDown(self):
        if isinstance(self.db, PgStorage):
            await self.db.pool.close()
        self.temp.cleanup()

    async def test_brand_generation_claim_is_atomic_and_persistent(self):
        speak = AsyncMock(return_value=(bytes(48000), 0))
        send = AsyncMock()
        with patch.object(brandvideo, 'speak', speak), \
             patch.object(brandvideo, 'assemble', return_value=Path('/tmp/synthetic-not-written')):
            await asyncio.gather(*(brandvideo.run_once(self.db, 'synthetic-key', send) for _ in range(3)))
            await brandvideo.run_once(self.db, 'synthetic-key', send)
        self.assertEqual(speak.await_count, len(brandvideo.LINES))
        send.assert_awaited_once()

    async def test_cancelled_paid_attempt_is_not_automatically_retried(self):
        speak = AsyncMock(side_effect=asyncio.CancelledError())
        with patch.object(brandvideo, 'speak', speak):
            with self.assertRaises(asyncio.CancelledError):
                await brandvideo.run_once(self.db, 'synthetic-key', AsyncMock())
            await brandvideo.run_once(self.db, 'synthetic-key', AsyncMock())
        self.assertEqual(speak.await_count, 1)

    async def test_legacy_account_cache_is_not_trusted_and_target_is_verified(self):
        await self.db.kv_set('ig:account', 'OTHER')
        client = AsyncMock()
        client._request.return_value = (200, {'accounts': [
            {'_id': 'OTHER', 'platform': 'instagram', 'username': 'another_profile'},
            {'_id': 'NUMERITA', 'platform': 'instagram', 'username': '@numerita.ai'}]})
        with patch.dict(os.environ, {'ZERNIO_INSTAGRAM_ACCOUNT_ID': ''}):
            self.assertEqual(await instagram.account_id(self.db, client), 'NUMERITA')
        self.assertEqual(await self.db.kv_get('ig:account:verified'), 'NUMERITA')

    async def test_ambiguous_account_list_is_rejected(self):
        client = AsyncMock()
        client._request.return_value = (200, {'accounts': [
            {'_id': 'A', 'platform': 'instagram', 'username': 'numerita.ai'},
            {'_id': 'B', 'platform': 'instagram', 'username': 'numerita.ai'}]})
        with patch.dict(os.environ, {'ZERNIO_INSTAGRAM_ACCOUNT_ID': ''}):
            self.assertIsNone(await instagram.account_id(self.db, client))

    async def test_redo_stops_before_generation_when_daily_budget_exhausted(self):
        rows = [{'reply': 'template', 'comment_id': 'test', 'post_id': None, 'comment': 'question', 'author': 'test'}]
        generator = AsyncMock()
        with patch.object(autoreply.reply_cooldown, 'blocked', AsyncMock(return_value=False)), \
             patch.object(self.db, 'replied_since', AsyncMock(return_value=rows)), \
             patch.object(self.db, 'reply_target', AsyncMock(return_value='target')), \
             patch.object(autoreply, 'is_code_reply', return_value=True), \
             patch.object(autoreply, 'spent_on_replies', AsyncMock(return_value=999)):
            await autoreply.redo_code_replies(self.db, AsyncMock(), generator, 90, 1)
        generator.write_reply.assert_not_awaited()

    async def test_redo_rechecks_budget_between_each_generation(self):
        rows = [{'reply': 'template', 'comment_id': str(i), 'post_id': None, 'comment': 'question', 'author': 'test'} for i in range(2)]
        generator = AsyncMock(); generator.write_reply.return_value = 'SKIP'
        with patch.object(autoreply.reply_cooldown, 'blocked', AsyncMock(return_value=False)), \
             patch.object(self.db, 'replied_since', AsyncMock(return_value=rows)), \
             patch.object(self.db, 'reply_target', AsyncMock(return_value='target')), \
             patch.object(autoreply, 'is_code_reply', return_value=True), \
             patch.object(autoreply, 'spent_on_replies', AsyncMock(side_effect=[0, 999])):
            await autoreply.redo_code_replies(self.db, AsyncMock(), generator, 90, 1)
        self.assertEqual(generator.write_reply.await_count, 1)
