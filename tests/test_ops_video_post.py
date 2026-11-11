import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from zavod import bot as B
from zavod.storage import Storage


class FakeThreads:
    def __init__(self):
        self.uploaded, self.published = [], []

    async def upload_image(self, data, filename, content_type="image/jpeg"):
        self.uploaded.append((len(data), filename, content_type))
        return "https://cdn.example/video.mp4"

    async def publish_text(self, text, topic_tag=None, first_comment=None, image_urls=None, video_url=None, *, media_kind=None,
                           thread_items=None):
        self.published.append({"text": text, "topic": topic_tag, "video": video_url, "kind": media_kind, "items": thread_items})
        return "remote1"


class OpsVideoPost(unittest.IsolatedAsyncioTestCase):
    """Команда пульта video_post: готовый ролик из assets/ уходит в Threads с темой и продолжением ветки."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def run_cmd(self, cmd, threads):
        sent = []
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: sent.append(t))), \
                patch.object(B, "post_receipt", AsyncMock()):
            await B.run_op(cmd, self.db, threads, None, B.Config.__new__(B.Config) if False else _Cfg())
        return sent

    async def test_video_goes_out_with_astrology_topic_and_thread(self):
        th = FakeThreads()
        cmd = {"id": "v1", "action": "video_post", "media": "numerita_gas.mp4", "rubric": "video_zodiac_heart",
               "text": "Какой знак спрятан в сердце?", "items": ["Подсказка: стихии."]}
        sent = await self.run_cmd(cmd, th)
        self.assertEqual(sent, [])
        self.assertEqual(th.uploaded[0][2], "video/mp4")
        pub = th.published[0]
        self.assertEqual((pub["topic"], pub["video"], pub["kind"]), ("Astrology Threads", "https://cdn.example/video.mp4", "story_video"))
        self.assertEqual(pub["items"], ["Какой знак спрятан в сердце?", "Подсказка: стихии."])

    async def test_missing_or_outside_file_is_refused(self):
        th = FakeThreads()
        for media in ("channel/no_such.mp4", "../zavod/config.py"):
            sent = await self.run_cmd({"id": "v2" + media, "action": "video_post", "media": media, "text": "Текст"}, th)
            self.assertIn("не вышел", sent[0])
        self.assertEqual(th.published, [])


class LinkUnder(OpsVideoPost):
    async def test_link_goes_as_reply_to_our_own_thread_item(self):
        th = FakeThreads()
        await self.run_cmd({"id": "v1", "action": "video_post", "media": "numerita_gas.mp4", "text": "Какой знак спрятан в сердце?"}, th)
        th.replies, th.roots = [], []

        async def comments(target, max_pages=10):
            return [{"id": "c1", "from": {"isOwner": False}, "message": "Скорпион"}, {"id": "c2", "from": {"isOwner": True}, "message": "Подсказка"}]

        async def reply(target, comment_id, message):
            th.replies.append((target, comment_id, message))

        th.comments, th.reply = comments, reply
        sent = await self.run_cmd({"id": "l1", "action": "link_under", "fragment": "спрятан в сердце", "text": "t.me/Numeritabot?start=ad_th_zheart"}, th)
        self.assertEqual(th.replies, [("remote1", "c2", "t.me/Numeritabot?start=ad_th_zheart")])
        self.assertIn("поставлена", sent[0])

    async def test_static_label_is_registered(self):
        from zavod import attribution as A
        self.assertEqual(A.parse("ad_th_zheart")["kind"], "static")


class _Cfg:
    import zoneinfo
    timezone = zoneinfo.ZoneInfo("Europe/Moscow")


if __name__ == "__main__":
    unittest.main()
