"""Telegram-канал Нумериты как инструмент роста (слово владельца 28.10.2026): юмор, знания, интрига, вовлечение
и переход к платному — вперемешку с новостями Нумериты (их публикует основной бот).

Канал получает не всё подряд (в Threads до 20 постов в сутки), а лучшее, что люди уже проверили лайками и
комментариями: через 3–48 часов после выхода в Threads берём самый сильный пост и переносим в канал с призывом
получить разбор в @Numeritabot. Метка ссылки ad_th_tg<id> — Нумерита считает, какой пост привёл человека.
Нейросеть не нужна — $0.
"""

import json
import logging
import random
from datetime import datetime, timedelta, timezone

from .autopost import strip_credits

log = logging.getLogger(__name__)

PER_DAY = 3  # канал — не лента: лучше три сильных поста, чем двадцать
GAP = timedelta(hours=3)
HOURS = range(9, 22)  # по часовому поясу бота; ночью канал молчит
MIN_AGE, MAX_AGE = timedelta(hours=3), timedelta(hours=48)
MIN_SCORE = 3  # лайк — 1, комментарий — 3: пост, на который никто не отозвался, в канал не идёт

CTA = (
    "🔮 Твой разбор по дате — за 10 секунд: {link}",
    "✨ Узнай, что говорит твоя дата: {link}",
    "💫 Напиши дату рождения Нумерите — покажу твою сильную сторону: {link}",
    "🤍 Хочешь так же про себя? Разбор по дате: {link}",
)


def link(post_id: int) -> str:
    return f"t.me/Numeritabot?start=ad_th_tg{post_id}"


def score(sample: dict) -> int:
    return (sample.get("likes") or 0) + 3 * (sample.get("comments") or 0)


def adapt(post, rng: random.Random) -> str:
    """Текст Threads → пост канала: без чужих упоминаний и Threads-ссылок, с одним призывом в бота."""
    from .bot import LINK_LINE
    text = strip_credits(post.text)
    text = "\n".join(line.rstrip() for line in LINK_LINE.sub("", text).splitlines()).strip()
    text = text.replace("в комментариях", "в комментариях к посту")
    return f"{text}\n\n{rng.choice(CTA).format(link=link(post.id))}"


async def pick(db, now: datetime):
    best, best_score = None, MIN_SCORE - 1
    for post in await db.recent_published(now - MAX_AGE):
        if post.tg_message_id or now - post.published_at < MIN_AGE:
            continue
        raw = await db.kv_get(f"performance:{post.id}:latest")
        if not raw:
            continue  # нет данных — не значит, что пост слабый; просто ждём замера
        s = score(json.loads(raw))
        if s > best_score:
            best, best_score = post, s
    return best


async def tick(db, bot, channel: str, tz, rng: random.Random | None = None) -> str | None:
    """Раз в проход планировщика: если пора — переносит в канал лучший пост. Возвращает ошибку для владельца."""
    if not channel:
        return None
    now = datetime.now(tz)
    if now.hour not in HOURS:
        return None
    day_key = f"tgch:{now.date().isoformat()}"
    sent = json.loads(await db.kv_get(day_key) or "[]")
    if len(sent) >= PER_DAY:
        return None
    last = await db.kv_get("tgch:last")
    if last and now.astimezone(timezone.utc) - datetime.fromisoformat(last) < GAP:
        return None
    post = await pick(db, now.astimezone(timezone.utc))
    if post is None:
        return None
    from aiogram.exceptions import TelegramAPIError
    from aiogram.types import LinkPreviewOptions
    try:
        msg = await bot.send_message(channel, adapt(post, rng or random.Random()),
                                     link_preview_options=LinkPreviewOptions(is_disabled=True))
    except TelegramAPIError as e:
        await db.kv_set("tgch:last", now.astimezone(timezone.utc).isoformat())  # не долбим канал каждую минуту
        return f"Telegram-канал {channel}: {e.message}. Бот должен быть админом канала с правом публикации."
    await db.set_tg_message_id(post.id, str(msg.message_id))
    await db.kv_set(day_key, json.dumps(sent + [post.id]))
    await db.kv_set("tgch:last", now.astimezone(timezone.utc).isoformat())
    log.info("В канал перенесён пост #%s", post.id)
    return None
