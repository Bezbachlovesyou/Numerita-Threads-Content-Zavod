import json
import random
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from zavod import bot as B
from zavod.cards import grid_json, make_grid
from zavod.storage import Storage


class Remote:
    """Подставной Zernio: пост с заглушкой в базе, настоящий номер знает только Zernio."""
    def __init__(self, status="published"):
        self.state = {"z1": status}
        self.unpublished = []

    async def find_posts(self, fragment, since):
        return [{"_id": "z1", "content": "Протокол проверки бизнес-идеи: ..."}]

    async def post_status(self, pid):
        return self.state[pid], "https://threads.net/p/x", "video rejected" if self.state[pid] == "failed" else None

    async def unpublish(self, pid):
        self.unpublished.append(pid)
        self.state[pid] = "cancelled"


class UnpublishAndConfirm(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_placeholder_id_is_resolved_through_zernio_and_verified(self):
        pid = await self.db.add_draft("x", "Протокол проверки бизнес-идеи: кнопка", "text_seed")
        await self.db.set_threads_id(pid, "published")
        await self.db.mark_published(pid)
        remote = Remote()
        lines = await B.unpublish_matching(self.db, remote, ["Протокол проверки бизнес-идеи"])
        self.assertEqual(remote.unpublished, ["z1"])
        self.assertIn("Снят", lines[0])
        self.assertEqual(await B.unpublish_matching(self.db, remote, ["Протокол проверки бизнес-идеи"]), [])

    async def test_owner_hears_only_confirmed_status_and_video_falls_back_to_image(self):
        card = json.dumps({**json.loads(grid_json(make_grid(random.Random(3), style="heart"), "?", 2)), "anim": True})
        pid = await self.db.add_draft("heart", "В этом сердце 120 цифр.", "grid", None, card)
        await self.db.set_threads_id(pid, "z1")
        await self.db.kv_set("heart:post", str(pid))
        remote = Remote("failed")
        sent = []
        async def publish(post, *a, **k):
            await self.db.set_threads_id(post.id, "z1")
            remote.state["z1"] = "published"
            return await self.db.get(post.id)
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: sent.append(t))), \
             patch.object(B, "publish", publish):
            await B.confirm_heart(self.db, remote, None, None)  # ДНК ещё не вышла — сердце ждёт
            self.assertEqual(sent, [])
            dna = json.dumps({**json.loads(grid_json(make_grid(random.Random(4), style="dna"), "?", 3)), "anim": True})
            did = await self.db.add_draft("dna", "ДНК", "grid", None, dna)
            await self.db.set_threads_id(did, "z2")
            await self.db.mark_published(did)
            await B.confirm_heart(self.db, remote, None, None)
            await B.confirm_heart(self.db, remote, None, None)
        self.assertIn("не принял видео", sent[0])
        self.assertIn("https://threads.net/p/x", sent[1])
