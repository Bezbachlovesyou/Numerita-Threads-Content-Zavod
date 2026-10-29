"""Сюрприз-подарок вместо объявленного розыгрыша (слово владельца 29.10.2026; проверка правил Meta).

Threads не рекомендует людям вне подписки посты, которые «продвигают конкурс или розыгрыш», а повторы могут снять
рекомендации со всего аккаунта (creators.instagram.com/threads). Поэтому розыгрыш постом НЕ объявляем: раз в 2 дня
в 20:00 код честно и случайно выбирает одного человека, написавшего дату рождения под любым нашим постом за сутки,
и отвечает ему в ветке сюрпризом — полный разбор + совместимость пары в @Numeritabot по личной ссылке ad_th_gift…
(подпись HMAC от NUMERITA_THREADS_KEY, бот Нумериты принимает её один раз). Ничего не обещаем заранее — значит,
и не нарушаем обещаний; это саттвический дар: вовремя и тому, кто проявил интерес.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
from datetime import datetime, timedelta

from . import funnel
from .autopost import BOT_LINK, OWN_HANDLES

log = logging.getLogger(__name__)

# Включается, когда бот Нумериты принимает ссылки ad_th_gift… (иначе подарок нерабочий).
ENABLED = True  # бот Нумериты принимает ad_th_gift (квитанция 644422d, 29.10.2026)
EVERY = timedelta(days=2)
HOUR = 20
DATE_RE = re.compile(r"\b\d{1,2}[./\-\s]\d{1,2}(?:[./\-\s]\d{2,4})?\b|\b\d{1,2}\s+[а-яё]{3,}|\b\d{1,2}\b")


def gift_code(key: str, nonce: str) -> str:
    sig = hmac.new(key.encode(), nonce.encode(), hashlib.sha256).hexdigest()[:12]
    return f"gift{nonce}{sig}"


def has_date(text: str) -> bool:
    return bool(DATE_RE.search(text or ""))


async def state(db) -> dict:
    return json.loads(await db.kv_get("giveaway:state") or "{}")


async def surprise(db, threads, now: datetime) -> str | None:
    """Раз в 2 дня в 20 ч: случайный человек с датой в комментариях за сутки получает подарок ответом в ветке."""
    if not ENABLED or now.hour != HOUR:
        return None
    st = await state(db)
    last = st.get("last")
    if last and now - datetime.fromisoformat(last) < EVERY - timedelta(hours=1):
        return None
    if not funnel.KEY:
        return None
    winners = set(st.get("winners", []))
    since = now - timedelta(days=1)
    seen, candidates = set(), []
    for row in await db.recent_comments(400):
        author = (row.get("author") or "").lower()
        created = datetime.fromisoformat(row["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=now.tzinfo)
        if (created < since or row.get("status") != "replied" or author in OWN_HANDLES or author in winners
                or author in seen or not has_date(row.get("comment") or "") or not row.get("post_id")):
            continue
        seen.add(author)
        candidates.append(row)
    st["last"] = now.isoformat()
    if not candidates:
        await db.kv_set("giveaway:state", json.dumps(st))
        return None
    winner = candidates[secrets.randbelow(len(candidates))]
    post = await db.get(winner["post_id"])
    if not post or not post.threads_id or post.threads_id == "published":
        await db.kv_set("giveaway:state", json.dumps(st))
        return None
    used = set(st.get("nonces", []))
    from .lang import is_en

    def fresh() -> str:  # английский завод — первая цифра 8–f, русский — 0–7: подарки двух заводов не пересекаются
        n = secrets.token_hex(3)
        return format(int(n[0], 16) | 8 if is_en() else int(n[0], 16) & 7, "x") + n[1:]
    nonce = fresh()
    while nonce in used:  # nonce уникален на каждый подарок
        nonce = fresh()
    st["nonces"] = sorted(used | {nonce})[-2000:]
    code = gift_code(funnel.KEY, nonce)
    from .lang import is_en
    text = (("A little surprise 🎁 Your birthday caught my eye today — the full reading and couple compatibility are "
             f"on me. The link is personal and works once:\n{BOT_LINK}{code}") if is_en() else
            ("А теперь сюрприз 🎁 Сегодня именно твоя дата попалась мне на глаза — дарю полный разбор и совместимость "
             f"пары. Ссылка личная и работает один раз:\n{BOT_LINK}{code}"))
    await threads.reply(post.threads_id, winner["comment_id"], text)
    st["winners"] = sorted(winners | {(winner.get("author") or "").lower()})[-500:]
    await db.kv_set("giveaway:state", json.dumps(st))
    log.info("Сюрприз-подарок: @%s из %d кандидатов", winner.get("author"), len(candidates))
    return f"🎁 Сюрприз-подарок: из {len(candidates)} человек с датой выбран один, ссылка на разбор отправлена в ветке."
