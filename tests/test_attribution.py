import os
import random
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from zavod import attribution as A
from zavod import autopost, ladder, tgchannel
from zavod import bot as B
from zavod.storage import PgStorage, Storage

NOW = datetime.now(timezone.utc)


class Parse(unittest.TestCase):
    def test_every_kind_of_label_is_understood(self):
        cases = {
            "ad_th_text_seek4_3110_lc": ("post", "th", "ru", "text_seek", None, "comment"),
            "th_text_year3_3110": ("post", "th", "ru", "text_year", None, None),  # как в статистике завода, без ad_
            "ad_th_text_one_digit7_0111": ("post", "th", "ru", "text_one_digit", None, None),
            "ad_th_r123_lpi": ("reply", "th", "ru", None, 123, "ladder"),
            "ad_en_th_r5_o": ("reply", "th", "en", None, 5, "old"),
            "ad_th_r9_a": ("reply", "th", "ru", None, 9, "link"),
            "ad_th_tg77": ("channel", "tg", "ru", None, 77, None),
            "ad_th_tgnew": ("static", "tg", "ru", None, None, None),
            "ad_th_bio": ("bio", "th", "ru", None, None, None),
            "ad_ig_bio": ("bio", "ig", "ru", None, None, None),
            "ad_en_ig_bio": ("bio", "ig", "en", None, None, None),
            "ad_th_pin": ("pin", "th", "ru", None, None, None),
            "ad_th_gift12ab34cd": ("static", "th", "ru", None, None, None),
            "ad_th_story": ("static", "th", "ru", None, None, None),
        }
        for label, (kind, plat, lang, rubric, post_id, variant) in cases.items():
            p = A.parse(label)
            self.assertEqual((p["kind"], p["platform"], p["lang"], p["rubric"], p["post_id"], p["variant"]),
                             (kind, plat, lang, rubric, post_id, variant), label)

    def test_garbage_is_unknown(self):
        for label in ("", "hello", "ad_xx_bio", "ad_th_", "ad_th_unregistered"):
            self.assertEqual(A.parse(label)["kind"], "unknown", label)


class Contract(unittest.TestCase):
    """Незыблемый каркас: новая ссылка на бота с незарегистрированной меткой ломает тест."""

    def test_every_bot_link_in_the_code_has_a_registered_label(self):
        found = {}
        for path in Path("zavod").glob("*.py"):
            for lit in re.findall(r"start=(ad_[A-Za-z0-9_]+)(?![A-Za-z0-9_{])", path.read_text(encoding="utf-8")):
                if lit.endswith("_"):  # префикс: к нему код добавляет метку
                    continue
                found.setdefault(lit, path.name)
        self.assertGreater(len(found), 8)
        unknown = {lit: f for lit, f in found.items() if not A.known(lit)}
        self.assertEqual(unknown, {}, f"метка ссылки не зарегистрирована в attribution.STATIC: {unknown}")

    def test_every_platform_has_a_registered_bio_label(self):
        for plat in A.PLATFORMS:
            p = A.parse(A.PER_PLATFORM_BIO[plat])
            self.assertEqual((p["kind"], p["platform"]), ("bio", plat))

    def test_builders_produce_labels_that_parse_back(self):
        plan = autopost.ContentPlan(autopost.load_rubrics(Path("prompts/content_plan.md")))
        for key in ("text_year", "text_one_digit", "text_fears", "grid"):
            rubric = next(r for r in plan.all_rubrics() if r.key == key)
            slot = plan.render(rubric, datetime(2026, 10, 31, 20), random.Random(1))
            p = A.parse(autopost.BOT_LINK + slot.tag + "_lc")
            self.assertEqual((p["kind"], p["rubric"], p["variant"]), ("post", key, "comment"), slot.tag)
        for mode in ("offer", "paywall", "link"):
            for variant in ("base", "ladder"):
                p = A.parse(f"{autopost.BOT_LINK}r42_{ladder.letter(mode, variant)}pi")
                self.assertEqual((p["kind"], p["post_id"]), ("reply", 42))
        self.assertEqual(A.parse(tgchannel.link(5))["kind"], "channel")

    def test_first_comments_follow_the_account_language(self):
        slot = autopost.ContentPlan(autopost.load_rubrics(Path("prompts/content_plan.md")))
        rubric = next(r for r in slot.all_rubrics() if r.key == "text_year")
        s = slot.render(rubric, datetime(2026, 10, 31, 20), random.Random(1))
        ru = B.first_comment_for(s, s.tag + "_lc")
        self.assertTrue(re.search("[А-Яа-яЁё]", ru) and "t.me/" in ru)
        with patch("zavod.lang.is_en", return_value=True):
            en = B.first_comment_for(s, s.tag + "_lc")
        self.assertFalse(re.search("[А-Яа-яЁё]", en))
        self.assertIn("t.me/", en)


class WithDb(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(self.tmp.name + "/t.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def post(self, rubric, comments=0, first_comment=None, views=0, likes=0):
        pid = await self.db.add_draft("t", f"Пост {rubric}", rubric, first_comment)
        await self.db.set_threads_id(pid, "z")
        await self.db.mark_published(pid)
        if views or likes:
            await self.db.save_metrics(pid, likes, views)
        for i in range(comments):
            await self.db.record_comment(f"c{pid}_{i}", pid, f"u{i}", "комментарий", "ответ", "replied")
        return pid

    async def test_table_attributes_posts_replies_and_shows_unattributed(self):
        grid = await self.post("grid", comments=30, views=5000, likes=60)
        pairs = await self.post("text_heaven_pairs", comments=3, views=800, likes=10)
        for _ in range(3):
            await self.post("grid", comments=30)
        raw = {"labels": [
            {"label": f"ad_th_r{grid}_lpi", "came": 12, "new": 9, "wow": 6, "returned": 2, "paid": 1, "stars": 99},
            {"label": f"ad_th_r{pairs}_o", "came": 2, "new": 2, "wow": 1, "paid": 0},
            {"label": "ad_th_text_year3_3110_lc", "came": 3, "new": 3, "wow": 2, "paid": 0},
            {"label": "ad_th_bio", "came": 40, "new": 30, "wow": 10, "paid": 0},
            {"label": "ad_ig_bio", "came": 6, "new": 6, "wow": 1, "paid": 0}]}
        table = await A.rubric_table(self.db, NOW + timedelta(minutes=1), 7, raw)
        by = {(t["platform"], t["rubric"]): t for t in table}
        g = by[("th", "grid")]
        self.assertEqual((g["posts"], g["comments"], g["came"], g["via_reply"], g["paid"]), (4, 120, 12, 12, 1))
        self.assertAlmostEqual(g["comments_share"], 120 / 123, places=3)
        self.assertTrue(g["enough"])
        p = by[("th", "text_heaven_pairs")]
        self.assertEqual((p["posts"], p["comments"], p["came"]), (1, 3, 2))
        self.assertFalse(p["enough"])  # мало данных, и об этом сказано
        self.assertEqual(by[("th", "text_year")]["came"], 3)  # метка поста — прямо
        out = await A.outcomes(self.db, raw)
        self.assertEqual(out["total"]["came"], 63)
        self.assertAlmostEqual(A.share_attributed(out), 17 / 63, places=3)
        text = "\n".join(A.lines(table, out, {"grid": "Угадай число"}))
        self.assertIn("Угадай число (Threads) — 4 постов", text)
        self.assertIn("комментариев 120 из 123", text)
        self.assertIn("мало данных", text)
        self.assertIn("не привязано: Threads: шапка профиля — 40", text)
        self.assertIn("УЗКОЕ ЗВЕНО ИЗМЕРЕНИЯ", text)  # привязано меньше половины пришедших

    async def test_no_measurement_alarm_when_most_arrivals_are_attributed(self):
        grid = await self.post("grid", comments=4)
        raw = {"labels": [{"label": f"ad_th_r{grid}_l", "came": 20, "new": 10, "wow": 5, "paid": 0},
                          {"label": "ad_th_bio", "came": 5, "new": 5, "wow": 1, "paid": 0}]}
        out = await A.outcomes(self.db, raw)
        self.assertNotIn("УЗКОЕ ЗВЕНО ИЗМЕРЕНИЯ", "\n".join(A.lines(await A.rubric_table(self.db, NOW + timedelta(minutes=1), 7, raw), out)))

    async def test_needs_tracking_gives_each_rubric_a_measured_sample_without_flooding(self):
        link = "Посчитать своё число души: t.me/Numeritabot?start=ad_th_text_year3_3110_lc"
        later = NOW + timedelta(minutes=1)
        self.assertTrue(await A.needs_tracking(self.db, "text_year", NOW))  # постов нет — нужна выборка
        await self.post("text_year", first_comment=link)
        for _ in range(5):
            await self.post("text_other")
        self.assertTrue(await A.needs_tracking(self.db, "text_year", later))  # у рубрики 1 меченый из 2 нужных, доля меченых мала
        await self.post("text_year", first_comment=link)
        for _ in range(5):
            await self.post("text_other")
        self.assertFalse(await A.needs_tracking(self.db, "text_year", later))  # у рубрики уже 2 меченых
        self.assertTrue(await A.needs_tracking(self.db, "text_new_one", later))  # новой рубрике выборка нужна
        await self.post("text_x", first_comment=link)
        self.assertFalse(await A.needs_tracking(self.db, "text_new_one", later))  # два меченых подряд не ставим
        for _ in range(3):
            await self.post("text_y", first_comment=link)
        await self.post("text_z")
        self.assertFalse(await A.needs_tracking(self.db, "text_another", later))  # меченых и так слишком много (потолок доли)
        self.assertTrue(await A.needs_tracking(self.db, "text_another", later, max_share=0.9))  # потолок меняется настройкой


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "нужен TEST_POSTGRES_DSN")
class WithPostgres(WithDb):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PgStorage(os.environ["TEST_POSTGRES_DSN"])
        await self.db.init()
        for table in ("comment_replies", "post_metrics", "posts", "kv", "autopost_slots"):
            await self.db._execute(f"DELETE FROM {table}")


if __name__ == "__main__":
    unittest.main()
