import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from zavod import bot as B
from zavod.storage import Storage


class OpsTell(unittest.IsolatedAsyncioTestCase):
    """Команда пульта tell: текст идёт только владельцу, Threads не трогается."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def run_tell(self, cmd):
        sent = []
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: sent.append(t))):
            await B.run_op(cmd, self.db, None, None, None)
        return sent

    async def test_text_goes_to_owner_without_threads(self):
        self.assertEqual(await self.run_tell({"id": "t1", "action": "tell", "text": "Привет"}), ["Привет"])

    async def test_file_outside_knowledge_is_refused(self):
        sent = await self.run_tell({"id": "t2", "action": "tell", "file": "zavod/config.py"})
        self.assertIn("нечего отправить", sent[0])
        sent = await self.run_tell({"id": "t3", "action": "tell", "file": "knowledge/../zavod/config.py"})
        self.assertIn("нечего отправить", sent[0])

    async def test_blocks_are_not_torn_apart(self):
        sep = "━━━━━━━━━━━━━━"
        blocks = [f"Группа {i}\n" + "я" * 900 for i in range(9)]
        parts = B.pack_blocks(f"\n{sep}\n".join(blocks))
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 3400 for p in parts))
        self.assertEqual(sum(p.count("Группа") for p in parts), 9)
        for p in parts:  # каждая часть начинается с заголовка группы
            self.assertTrue(p.startswith("Группа"))

    async def test_long_text_is_split_by_telegram_limit(self):
        text = "\n".join(f"День {i}: " + "а" * 300 for i in range(31))
        chunks = B.report_chunks(text)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks).replace("\n", ""), text.replace("\n", ""))
        self.assertTrue(all(len(c) <= 3500 for c in chunks))


if __name__ == "__main__":
    unittest.main()
