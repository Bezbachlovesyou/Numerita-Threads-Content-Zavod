import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zavod.bot import notify_admins, report_chunks


class ReportDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_unicode_report_keeps_every_character(self):
        text=('📊 Длинный отчёт\n'+'Факты и числа. '*500+'\n')*3
        bot=SimpleNamespace(send_message=AsyncMock())
        await notify_admins(bot,SimpleNamespace(admin_ids={1}),text)
        parts=[call.args[1] for call in bot.send_message.await_args_list]
        self.assertGreater(len(parts),1)
        self.assertEqual(''.join(parts),text)
        self.assertTrue(all(len(part.encode('utf-16-le'))//2 <= 3500 for part in parts))
        emoji='💗'*5000
        self.assertEqual(''.join(report_chunks(emoji)),emoji)
        self.assertTrue(all(len(part.encode('utf-16-le'))//2 <= 3500 for part in report_chunks(emoji)))

    async def test_post_buttons_only_follow_complete_report(self):
        bot=SimpleNamespace(send_message=AsyncMock())
        with patch('zavod.bot.post_keyboard',return_value='buttons'):
            await notify_admins(bot,SimpleNamespace(admin_ids={1}), 'x'*9000,post=object())
        calls=bot.send_message.await_args_list
        self.assertTrue(all(c.kwargs['reply_markup'] is None for c in calls[:-1]))
        self.assertEqual(calls[-1].kwargs['reply_markup'],'buttons')
