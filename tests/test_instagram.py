import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from zavod.storage import Storage, PgStorage
from zavod import instagram

TZ = ZoneInfo("Europe/Moscow")


class FakeZernio:
    def __init__(self, accounts):
        self.accounts, self.posts, self.uploads = accounts, [], []

    async def _request(self, method, path, **kw):
        if path == "/accounts":
            return 200, {"accounts": self.accounts}
        self.posts.append(kw["json"])
        return 200, {"post": {"_id": "ig1", "status": "published"}}

    async def upload_image(self, data, name):
        self.uploads.append(len(data))
        return "https://cdn/x.jpg"


class InstagramTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        dsn = os.getenv('DELIVERY_TEST_DSN')
        self.db = PgStorage(dsn) if dsn else Storage(self.temp.name + '/t.sqlite')
        await self.db.init()
        if dsn:
            await self.db.pool.execute('TRUNCATE posts, kv, autopost_slots RESTART IDENTITY')
        self.base = datetime.now(TZ).replace(hour=12, minute=0)
        self.notes = []

    async def asyncTearDown(self):
        if isinstance(self.db, PgStorage):
            await self.db.pool.close()
        self.temp.cleanup()

    async def note(self, text):
        self.notes.append(text)

    async def post(self, hours, likes, comments):
        ident = await self.db.add_draft('t', 'Шестёрки опаздывают красиво.\nНапиши своё число.', 'humor')
        await self.db.set_threads_id(ident, f'r{ident}')
        await self.db.mark_published(ident)
        await self.db._execute('UPDATE posts SET published_at = ? WHERE id = ?',
                               ((self.base - timedelta(hours=hours)).astimezone(timezone.utc).isoformat(), ident))
        await self.db.kv_set(f'performance:{ident}:latest', json.dumps({'likes': likes, 'comments': comments}))
        return ident

    def at(self, hour):
        return patch('zavod.instagram.datetime', wraps=datetime,
                     **{'now.return_value': self.base + timedelta(hours=hour - 12)})

    async def test_best_post_goes_to_instagram_with_card(self):
        await self.post(5, 1, 0)
        best = await self.post(6, 5, 2)
        z = FakeZernio([{"_id": "th", "platform": "threads"}, {"_id": "IG", "platform": "instagram", "username": "numerita.ai"}])
        with self.at(12):
            await instagram.tick(self.db, z, TZ, self.note)
        body = z.posts[0]
        self.assertEqual(body["platforms"][0], {"platform": "instagram", "accountId": "IG"})
        self.assertEqual(body["mediaItems"][0]["type"], "image")
        self.assertIn("ссылка в шапке", body["content"])
        self.assertTrue(z.uploads[0] > 1000)
        self.assertEqual(await self.db.kv_get(f"ig:posted:{best}"), "ig1")
        self.assertIn("ad_ig_bio", self.notes[0])
        with self.at(13):  # пауза 5 часов
            await instagram.tick(self.db, z, TZ, self.note)
        self.assertEqual(len(z.posts), 1)

    async def test_no_instagram_account_no_posts(self):
        await self.post(6, 5, 2)
        z = FakeZernio([{"_id": "th", "platform": "threads"}])
        with self.at(12):
            await instagram.tick(self.db, z, TZ, self.note)
        self.assertEqual(z.posts, [])


if __name__ == '__main__':
    unittest.main()
