import asyncio
import os
import secrets
import tempfile
import unittest
from zavod.storage import Storage, PgStorage


class KvConcurrency(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_parallel_updates_never_remove_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Storage(tmp + '/test.sqlite')
            await db.init()
            await asyncio.gather(*(db.kv_set('api:next_request', str(i)) for i in range(20)))
            self.assertIn(await db.kv_get('api:next_request'), {str(i) for i in range(20)})

    async def test_postgres_parallel_updates_do_not_collide(self):
        url = os.getenv('TEST_LOCAL_DATABASE_URL', '')
        if not url:
            self.skipTest('Only a separate local test database')
        self.assertTrue('host=/tmp' in url or 'localhost' in url or '127.0.0.1' in url)
        schema = 'test_kv_' + secrets.token_hex(6)
        db = PgStorage(url, schema=schema)
        await db.init()
        try:
            await asyncio.gather(*(db.kv_set('api:next_request', str(i)) for i in range(100)))
            self.assertIn(await db.kv_get('api:next_request'), {str(i) for i in range(100)})
        finally:
            await db.pool.execute('DROP SCHEMA ' + schema + ' CASCADE')
            await db.pool.close()
