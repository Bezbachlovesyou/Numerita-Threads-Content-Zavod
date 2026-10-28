import json
import os
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from zavod.storage import Storage, PgStorage
from zavod import tgchannel

TZ = ZoneInfo("Europe/Moscow")


class ChannelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        dsn = os.getenv('DELIVERY_TEST_DSN')
        self.db = PgStorage(dsn) if dsn else Storage(self.temp.name + '/t.sqlite')
        await self.db.init()
        if dsn:
            await self.db.pool.execute('TRUNCATE posts, kv RESTART IDENTITY')
        self.base = datetime.now(TZ).replace(hour=12, minute=0)
        self.now = self.base.astimezone(timezone.utc)
        self.bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=77)),
                                   send_photo=AsyncMock(return_value=SimpleNamespace(message_id=88)),
                                   delete_message=AsyncMock(), edit_message_text=AsyncMock())

    async def asyncTearDown(self):
        if isinstance(self.db, PgStorage):
            await self.db.pool.close()
        self.temp.cleanup()

    async def post(self, hours, likes, comments, text='Хук.\nНапиши число в комментариях.'):
        ident = await self.db.add_draft('t', text, 'humor')
        await self.db.set_threads_id(ident, f'r{ident}')
        await self.db.mark_published(ident)
        await self.db._execute('UPDATE posts SET published_at = ? WHERE id = ?',
                               ((self.now - timedelta(hours=hours)).isoformat(), ident))
        if likes is not None:
            await self.db.kv_set(f'performance:{ident}:latest', json.dumps({'likes': likes, 'comments': comments}))
        return ident

    def at(self, hour):
        fake = self.base + timedelta(hours=hour - 12)
        return patch('zavod.tgchannel.datetime', wraps=datetime, **{'now.return_value': fake})

    async def test_best_post_goes_with_link_and_limits(self):
        weak = await self.post(5, 1, 0)
        best = await self.post(6, 4, 2)
        await self.post(1, 50, 9)          # слишком свежий
        await self.post(5, None, None)     # нет замера — не ноль, ждём
        with self.at(12):
            self.assertIsNone(await tgchannel.tick(self.db, self.bot, "@ch", TZ, random.Random(1)))
        text = self.bot.send_message.await_args.args[1]
        self.assertIn(f'ad_th_tg{best}', text)
        self.assertIn('в комментариях к посту', text)
        self.assertEqual((await self.db.get(best)).tg_message_id, '77')
        with self.at(13):  # меньше 3 часов — ждём
            await tgchannel.tick(self.db, self.bot, '@ch', TZ)
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertIsNone((await self.db.get(weak)).tg_message_id)

    async def test_silent_without_reactions_or_at_night(self):
        await self.post(5, 0, 0)
        with self.at(12):
            await tgchannel.tick(self.db, self.bot, '@ch', TZ)
        await self.post(5, 10, 3)
        with self.at(2):
            await tgchannel.tick(self.db, self.bot, '@ch', TZ)
        self.bot.send_message.assert_not_awaited()
        self.assertIsNone(await tgchannel.tick(self.db, self.bot, '', TZ))

    async def test_grid_goes_with_picture_and_word_matrix(self):
        from zavod.cards import make_grid, grid_json
        ident = await self.post(5, 5, 2, text='Много единиц? Тогда эта сетка ждала тебя. Назови три числа.')
        await self.db._execute('UPDATE posts SET card = ?, tg_message_id = ? WHERE id = ?',
                               (grid_json(make_grid(random.Random(1)), 'Что видишь первым?', 0), '64', ident))
        await tgchannel.fix_grid_post(self.db, self.bot, '@ch', ident)
        self.bot.delete_message.assert_awaited_once_with('@ch', 64)
        caption = self.bot.send_photo.await_args.kwargs['caption']
        self.assertIn('эта матрица ждала', caption)
        self.assertNotIn('сетк', caption)
        self.assertEqual((await self.db.get(ident)).tg_message_id, '88')
        await tgchannel.fix_grid_post(self.db, self.bot, '@ch', ident)
        self.assertEqual(self.bot.send_photo.await_count, 1)

    def test_word_swap_keeps_case(self):
        self.assertEqual(tgchannel.no_grid_word('Сетка и в сетке'), 'Матрица и в матрице')


if __name__ == '__main__':
    unittest.main()
