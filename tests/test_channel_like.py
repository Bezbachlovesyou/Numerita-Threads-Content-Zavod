import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from zavod import bot as B, tgchannel


class ChannelLike(unittest.TestCase):
    def _handler(self, channel):
        cfg = SimpleNamespace(admin_ids=[1], telegram_channel=channel)
        router = B.create_router(cfg, MagicMock())
        return router.channel_post.handlers[0].callback

    def _msg(self, chat_id, username, mid):
        return SimpleNamespace(message_id=mid, chat=SimpleNamespace(id=chat_id, username=username), bot=MagicMock())

    def test_likes_posts_of_our_channel_only_and_once(self):
        h = self._handler("@Numeritalovesyou")
        calls = AsyncMock(return_value=True)
        with patch.object(tgchannel, "react", calls):
            asyncio.run(h(self._msg(-100, "Numeritalovesyou", 5)))
            asyncio.run(h(self._msg(-200, "other", 6)))
        self.assertEqual(calls.await_count, 1)
        tgchannel.REACTED.append(7)
        with patch.object(tgchannel, "react", calls):
            asyncio.run(h(self._msg(-100, "Numeritalovesyou", 7)))
        self.assertEqual(calls.await_count, 1)  # свой пост уже с реакцией


if __name__ == "__main__":
    unittest.main()
