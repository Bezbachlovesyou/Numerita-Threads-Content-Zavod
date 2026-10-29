"""«Разбор в подарок» (слово владельца 29.10.2026, по образцу популярных постов «разбор вашей даты — пишите дату»).

Раз в 2 дня, днём, выходит пост: каждый, кто напишет дату рождения в комментариях, получает мини-разбор прямо там
(обычный автоответ), а на следующий день в 20:00 код честно и случайно выбирает одного участника — ему в ветке
уходит подарок: полный разбор + совместимость пары в @Numeritabot по личной ссылке ad_th_gift…, которую бот
Нумериты проверяет подписью (HMAC от NUMERITA_THREADS_KEY) и принимает один раз.
Условие участия — только комментарий с датой. Лайк и репост условием не делаем: Meta понижает «призывы ради
реакций», а проверить репост через API нельзя — обещать то, что не проверяем, нечестно.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
from datetime import datetime, time, timedelta

from . import funnel
from .autopost import BOT_LINK, OWN_HANDLES

log = logging.getLogger(__name__)

# Включается, когда бот Нумериты принимает ссылки ad_th_gift… (иначе победитель получит нерабочий подарок).
ENABLED = False
EVERY = timedelta(days=2)
POST_HOURS = (12, 17)
DRAW_AT = time(20, 0)
DATE_RE = re.compile(r"\b\d{1,2}[./\-\s]\d{1,2}(?:[./\-\s]\d{2,4})?\b|\b\d{1,2}\s+[а-яё]{3,}|\b\d{1,2}\b")

RULES = (
    "Напиши пост-розыгрыш для Threads: «нумерологический разбор в подарок». Механика (её нельзя менять): каждый, кто "
    "напишет дату рождения в комментариях, получит короткий разбор прямо здесь; завтра в 20:00 по Москве мы случайно "
    "выберем одного — ему полный разбор и совместимость пары в подарок. Условие одно — дата в комментариях; не проси "
    "лайки, репосты и подписки. Можно мягко: «перешли тому, с кем хочешь проверить совместимость». Первая строка — "
    "хук с интригой (о том, что дата знает о человеке больше, чем он думает), дальше одна искромётная шутка про числа "
    "(«бровь»: правдивая черта, доведённая до абсурда), затем механика двумя короткими фразами. Без ссылок и @, без "
    "обещаний судьбы и денег. 200–400 знаков, без эмодзи-гирлянд (не больше двух)."
)


def gift_code(key: str, nonce: str) -> str:
    sig = hmac.new(key.encode(), nonce.encode(), hashlib.sha256).hexdigest()[:12]
    return f"gift{nonce}{sig}"


def has_date(text: str) -> bool:
    return bool(DATE_RE.search(text or ""))


async def state(db) -> dict:
    return json.loads(await db.kv_get("giveaway:state") or "{}")


async def due_to_post(db, now: datetime) -> bool:
    if not ENABLED:
        return False
    st = await state(db)
    if st.get("active"):
        return False
    last = st.get("last_post")
    if last and now - datetime.fromisoformat(last) < EVERY:
        return False
    return POST_HOURS[0] <= now.hour < POST_HOURS[1]


async def start(db, generator, publish_text, now: datetime) -> int | None:
    """Пишет и публикует пост-розыгрыш. publish_text(text) -> post_id или None."""
    text = (await generator.improve("Ты — Нумерита, остроумный нумеролог в Threads.", RULES,
                                    max_tokens=500, kind="giveaway")).strip()
    post_id = await publish_text(text)
    if not post_id:
        return None
    draw = datetime.combine((now + timedelta(days=1)).date(), DRAW_AT, tzinfo=now.tzinfo)
    await db.kv_set("giveaway:state", json.dumps({"active": post_id, "draw_at": draw.isoformat(),
                                                  "last_post": now.isoformat()}))
    return post_id


async def draw(db, threads, now: datetime) -> str | None:
    """Если пора — выбирает победителя и пишет ему в ветке. Возвращает строку отчёта владельцу."""
    st = await state(db)
    if not st.get("active") or now < datetime.fromisoformat(st["draw_at"]):
        return None
    post = await db.get(st["active"])
    rows = await db.comments_for_post(st["active"])
    seen, candidates = set(), []
    for row in rows:
        author = (row.get("author") or "").lower()
        if author in OWN_HANDLES or author in seen or not has_date(row.get("comment") or ""):
            continue
        seen.add(author)
        candidates.append(row)
    st = {"last_post": st.get("last_post")}
    if not candidates or not post or not post.threads_id or not funnel.KEY:
        await db.kv_set("giveaway:state", json.dumps(st))
        why = ("нет участников с датой" if not candidates else "нет ключа NUMERITA_THREADS_KEY" if not funnel.KEY
               else "пост не найден в Threads")
        return f"🎁 Розыгрыш разбора закрыт без победителя: {why}."
    winner = candidates[secrets.randbelow(len(candidates))]
    code = gift_code(funnel.KEY, secrets.token_hex(3))
    text = (f"Обещанное случайное число выпало на тебя 🎁 Полный разбор и совместимость пары — в подарок. "
            f"Забирай здесь, ссылка личная и работает один раз:\n{BOT_LINK}{code}")
    await threads.reply(post.threads_id, winner["comment_id"], text)
    await db.kv_set("giveaway:state", json.dumps(st))
    log.info("Розыгрыш: победитель @%s из %d участников", winner.get("author"), len(candidates))
    return f"🎁 Розыгрыш разбора: участников с датой — {len(candidates)}, победителю отправлен подарок в ветке."
