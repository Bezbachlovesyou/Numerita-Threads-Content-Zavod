import io
import re
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from PIL import Image

from zavod import bot as B
from zavod import igcarousel as C
from zavod.storage import Storage

CYR = re.compile("[А-Яа-яЁё]")
BANNED = re.compile(r"(?i)отметь|перешли|сохрани|тегни|tag a friend|tag someone|save this|share this|giveaway|розыгрыш")


def strings(t: dict):
    for k, v in t.items():
        yield from (v if isinstance(v, list) else [v])


class Content(unittest.TestCase):
    def test_groups_cover_every_day_once(self):
        days = [int(x) for g in C.GROUPS for x in g.split(" · ")]
        self.assertEqual(sorted(days), list(range(1, 32)))

    def test_every_set_has_nine_scenes_in_both_languages_without_mixing(self):
        self.assertGreaterEqual(len(C.SETS), 3)
        for key, data in C.SETS.items():
            for lang in ("ru", "en"):
                t = data[lang]
                self.assertEqual(len(t["lines"]), 9, (key, lang))
                has_cyr = any(CYR.search(x) for x in strings(t))
                self.assertEqual(has_cyr, lang == "ru", (key, lang))
                if lang == "en":
                    self.assertFalse(any(CYR.search(x) for x in strings(t)), key)

    def test_captions_ask_for_a_comment_and_lead_to_the_bot_without_banned_calls(self):
        for key, data in C.SETS.items():
            for lang, bio in (("ru", "ссылка в шапке профиля"), ("en", "link in bio")):
                cap = data[lang]["caption"]
                self.assertLessEqual(len(cap), 2200)
                self.assertIn(bio, cap)
                self.assertRegex(cap, r"(?i)день рождения числом|birth day as a number")
                self.assertIsNone(BANNED.search(cap), (key, lang))
                self.assertIsNone(BANNED.search(" ".join(strings(data[lang]))), (key, lang))

    def test_every_set_states_it_is_symbolism_not_a_diagnosis(self):
        for data in C.SETS.values():
            self.assertRegex(data["ru"]["note"], "не диагноз")
            self.assertIn("not a diagnosis", data["en"]["note"])

    def test_no_promises_of_results(self):
        for data in C.SETS.values():
            for lang in ("ru", "en"):
                self.assertIsNone(re.search(r"(?i)гарантир|обещаем|разбогатеешь|guarantee|you will be rich", " ".join(strings(data[lang]))))


class Render(unittest.TestCase):
    def test_every_set_renders_five_instagram_slides(self):
        for key in C.SETS:
            for lang in ("ru", "en"):
                slides = C.render_set(key, lang)
                self.assertEqual(len(slides), 5)
                for b in slides:
                    im = Image.open(io.BytesIO(b))
                    self.assertEqual(im.size, (1080, 1350))  # один формат на всю карусель
                    self.assertLess(len(b), 1_500_000)

    def test_text_never_collides_with_the_footer_or_the_next_block(self):
        probe = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(Image.new("RGBA", (1080, 1350)))
        for data in C.SETS.values():
            for lang in ("ru", "en"):
                for text in data[lang]["lines"]:
                    font, lines, size = C._fit(probe, text, "PlayfairDisplay.ttf", "SemiBold", (60, 56, 52, 48, 44, 40, 36), 1080 - 210, 4, max_h=226)
                    self.assertGreaterEqual(size, 36, text)
                    self.assertLessEqual(len(lines) * int(size * 1.22), 226, text)
                cover = data[lang]["cover"]
                _, lines, size = C._fit(probe, cover, "PlayfairDisplay.ttf", "Bold", (84, 76, 68, 60, 54, 48), 1080 - 150, 4, lh=1.18)
                self.assertLessEqual(len(lines), 4, cover)


class Pult(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()
        self.cfg = SimpleNamespace(timezone=ZoneInfo("Europe/Moscow"), admin_ids=[7])

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_preview_goes_only_to_the_owner_and_publishes_nothing(self):
        bot = MagicMock()
        bot.send_media_group = AsyncMock()
        bot.send_message = AsyncMock()
        threads = MagicMock()
        threads.upload_image = AsyncMock()
        await B.ig_carousel(bot, self.cfg, self.db, threads, "quarrel", False, "")
        media = bot.send_media_group.await_args.args[1]
        self.assertEqual(len(media), 5)
        self.assertIn("нигде не выложено", media[0].caption)
        self.assertIsNone(media[1].caption)
        threads.upload_image.assert_not_awaited()

    async def test_publish_needs_a_receipt_and_never_doubles(self):
        notified = []
        threads = MagicMock()
        threads.upload_image = AsyncMock(side_effect=lambda b, n: f"https://cdn/{n}")
        threads._request = AsyncMock(return_value=(200, {"post": {"_id": "p1", "status": "pending"}}))
        with patch("zavod.instagram.account_id", AsyncMock(return_value="acc")), \
             patch("zavod.instagram.post_images", AsyncMock(return_value=("published", "https://instagram.com/p/x"))) as post, \
             patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: notified.append(t))):
            await B.ig_carousel(None, self.cfg, self.db, threads, "ok", True, "")
            await B.ig_carousel(None, self.cfg, self.db, threads, "ok", True, "")
        self.assertEqual(post.await_count, 1)  # второй раз не выкладывает
        self.assertEqual(len(post.await_args.args[2]), 5)
        self.assertIn("https://instagram.com/p/x", notified[0])
        self.assertIn("уже публиковалась", notified[1])

    async def test_not_published_status_is_not_reported_as_done(self):
        notified = []
        threads = MagicMock()
        threads.upload_image = AsyncMock(return_value="https://cdn/x")
        with patch("zavod.instagram.account_id", AsyncMock(return_value="acc")), \
             patch("zavod.instagram.post_images", AsyncMock(return_value=("pending", None))), \
             patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: notified.append(t))):
            await B.ig_carousel(None, self.cfg, self.db, threads, "love", True, "")
        self.assertIn("не считаю её вышедшей", notified[0])

    async def test_unknown_set_is_reported(self):
        notified = []
        with patch.object(B, "notify_admins", AsyncMock(side_effect=lambda b, c, t: notified.append(t))):
            await B.ig_carousel(None, self.cfg, self.db, None, "nope", False, "")
        self.assertIn("Нет такой карусели", notified[0])

    async def test_english_instance_renders_english_slides(self):
        bot = MagicMock()
        bot.send_media_group = AsyncMock()
        bot.send_message = AsyncMock()
        with patch("zavod.lang.is_en", return_value=True):
            await B.ig_carousel(bot, self.cfg, self.db, None, "quarrel", False, "[EN] ")
        caption = bot.send_media_group.await_args.args[1][0].caption
        self.assertIn("HOW YOU ARGUE".lower(), caption.lower().replace("how you argue, by birth day", "how you argue"))
        self.assertFalse(CYR.search(C.caption("quarrel", "en")))


if __name__ == "__main__":
    unittest.main()


class ReelCaption(unittest.TestCase):
    def test_caption_is_copy_ready_with_hashtags_and_no_link(self):
        from zavod import instagram
        ru = instagram.reel_caption("Привет\n\nt.me/Numeritabot?start=ad_th_code", "ru")
        en = instagram.reel_caption("Hello\n\nt.me/Numeritabot?start=ad_en_th_code", "en")
        self.assertNotIn("t.me", ru + en)
        self.assertIn("#нумерология", ru)
        self.assertIn("#numerology", en)
        self.assertFalse(re.search("[А-Яа-яЁё]", en))
        self.assertEqual(ru, ru.strip())
