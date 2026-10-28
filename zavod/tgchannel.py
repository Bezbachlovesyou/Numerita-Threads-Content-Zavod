"""Telegram-канал Нумериты как инструмент роста (слово владельца 28.10.2026): юмор, знания, интрига, вовлечение
и переход к платному — вперемешку с новостями Нумериты (их публикует основной бот).

Канал получает не всё подряд (в Threads до 20 постов в сутки), а лучшее, что люди уже проверили лайками и
комментариями: через 3–48 часов после выхода в Threads берём самый сильный пост и переносим в канал с призывом
получить разбор в @Numeritabot. Метка ссылки ad_th_tg<id> — Нумерита считает, какой пост привёл человека.
Нейросеть не нужна — $0.
"""

import asyncio
import json
import logging
import random
import re
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


GRID_WORDS = {"сетка": "матрица", "сетку": "матрицу", "сетки": "матрицы", "сетке": "матрице", "сеткой": "матрицей"}
GRID_RE = re.compile(r"(?i)\b(" + "|".join(GRID_WORDS) + r")\b")


def no_grid_word(text: str) -> str:
    """Слово «сетка» владельцу не нравится (28.10.2026): картинка с числами — «матрица»."""
    def swap(m):
        word = GRID_WORDS[m.group(1).lower()]
        return word.capitalize() if m.group(1)[0].isupper() else word
    return GRID_RE.sub(swap, text)


def grid_image(post) -> bytes | None:
    """Пост-матрица без своей картинки непонятен: в канал идёт та же картинка, нарисованная заново ($0)."""
    try:
        data = json.loads(post.card) if post.card else None
    except ValueError:
        return None
    if not data or "grid" not in data:
        return None
    from .cards import render_grid
    return render_grid(data["grid"], data["title"], data["palette"], f"{post.id}-grid")


async def send(bot, channel: str, post, text: str):
    from aiogram.types import BufferedInputFile, LinkPreviewOptions
    image = await asyncio.to_thread(grid_image, post)
    if image:
        return await bot.send_photo(channel, BufferedInputFile(image, f"numerita_{post.id}.jpg"), caption=text[:1024])
    return await bot.send_message(channel, text, link_preview_options=LinkPreviewOptions(is_disabled=True))


async def fix_grid_post(db, bot, channel: str, post_id: int) -> None:
    """Однократно: матрица ушла в канал без картинки и со словом «сетка» — удаляем и публикуем заново."""
    key = f"tgch:fixed:{post_id}"
    if not channel or await db.kv_get(key):
        return
    post = await db.get(post_id)
    if not post or not post.tg_message_id:
        await db.kv_set(key, "skip")
        return
    from aiogram.exceptions import TelegramAPIError
    if not grid_image(post):  # картинки нет — хотя бы заменяем слово в тексте
        from aiogram.types import LinkPreviewOptions
        try:
            await bot.edit_message_text(adapt(post, random.Random(post_id)), chat_id=channel,
                                        message_id=int(post.tg_message_id),
                                        link_preview_options=LinkPreviewOptions(is_disabled=True))
        except (TelegramAPIError, ValueError):
            log.warning("Пост #%s в канале не исправлен", post_id)
        await db.kv_set(key, "edited")
        return
    try:
        await bot.delete_message(channel, int(post.tg_message_id))
    except (TelegramAPIError, ValueError):
        log.warning("Старый пост #%s в канале не удалён — публикую исправленный", post_id)
    msg = await send(bot, channel, post, adapt(post, random.Random(post_id)))  # сбой — повторим в следующий проход
    await db.set_tg_message_id(post.id, str(msg.message_id))
    await db.kv_set(key, "done")


def adapt(post, rng: random.Random) -> str:
    """Текст Threads → пост канала: без чужих упоминаний и Threads-ссылок, с одним призывом в бота."""
    from .bot import LINK_LINE
    text = no_grid_word(strip_credits(post.text))
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
    try:
        msg = await send(bot, channel, post, adapt(post, rng or random.Random()))
    except TelegramAPIError as e:
        await db.kv_set("tgch:last", now.astimezone(timezone.utc).isoformat())  # не долбим канал каждую минуту
        return f"Telegram-канал {channel}: {e.message}. Бот должен быть админом канала с правом публикации."
    await db.set_tg_message_id(post.id, str(msg.message_id))
    await db.kv_set(day_key, json.dumps(sent + [post.id]))
    await db.kv_set("tgch:last", now.astimezone(timezone.utc).isoformat())
    log.info("В канал перенесён пост #%s", post.id)
    return None


ANNOUNCE = """✨ Друзья, у нас новость!

Отныне и впредь посты здесь — с юмором, хуками и интригой. Такие, на которые хочется ответить, поспорить \
и отметить друга. Числа будут шутить, звёзды — интриговать, а главное иногда будет недосказано: разгадка — \
в комментариях 😉

Мы стараемся и трудимся для вас. Ставьте реакции, пишите, спорьте — так мы узнаём, что вам по душе. \
Надеемся, вам понравится 🤍

🔮 А пока — твой разбор по дате за 10 секунд: {link}"""


async def announce_once(db, bot, channel: str) -> None:
    """Однократно (слово владельца 28.10.2026): видео с Нумеритой и объявление о новом формате канала."""
    key = "tgch:announce:new_format"
    if not channel or await db.kv_get(key):
        return
    from pathlib import Path
    from aiogram.types import FSInputFile
    video = Path(__file__).parent.parent / "assets/channel/new_format.mp4"
    msg = await bot.send_video(channel, FSInputFile(video), caption=ANNOUNCE.format(link="t.me/Numeritabot?start=ad_th_tgnew"),
                               width=1080, height=1080, supports_streaming=True, request_timeout=180)
    await db.kv_set(key, str(msg.message_id))  # сбой — повторим в следующий проход, дубля не будет
