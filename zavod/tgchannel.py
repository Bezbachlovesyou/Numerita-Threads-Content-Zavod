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

# Ссылка — аккуратной строкой-ссылкой в конце, без длинного адреса и «магических» эмодзи (слово владельца 29.10.2026:
# «убого выглядит — ссылка внизу и розовая сфера»).
CTA = (
    "Узнать своё число у Нумериты →",
    "Посчитать мою дату →",
    "А какое число у тебя? Нумерита скажет за 10 секунд →",
    "Разбор по моей дате →",
)
GROUP = re.compile(r"^\s*((?:\d{1,2},\s*){1,4}\d{1,2})\s*[:—–-]", re.M)


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


REACTIONS = ["❤", "👍", "🔥", "🥰", "👏", "🙏", "💯", "🤩", "⚡", "😍"]  # только положительные


async def react(bot, channel: str, message_id: int, rng: random.Random | None = None) -> bool:
    """Каждый свой пост в канале — с положительной реакцией (слово владельца 28.10.2026), разной от поста к посту.
    Канал может не разрешать какую-то реакцию — пробуем следующую."""
    from aiogram.exceptions import TelegramAPIError
    from aiogram.types import ReactionTypeEmoji
    choices = (rng or random.Random()).sample(REACTIONS, len(REACTIONS))
    for emoji in choices[:4]:
        try:
            await bot.set_message_reaction(channel, message_id, [ReactionTypeEmoji(emoji=emoji)])
            return True
        except TelegramAPIError as e:
            if "REACTION_INVALID" not in str(e) and "reaction" not in str(e).lower():
                return False  # пост удалён или нет прав — дальше пробовать бессмысленно
        except Exception:  # реакция не должна ломать публикацию (иначе пост выйдет повторно)
            log.exception("Реакция на пост %s не поставлена", message_id)
            return False
    return False


async def send(bot, channel: str, post, text: str):
    """У каждого поста — картинка (матрица или карточка), текст подписью; группы чисел — опрос под постом."""
    from aiogram.types import BufferedInputFile, LinkPreviewOptions
    image = await asyncio.to_thread(grid_image, post) or await asyncio.to_thread(card_image, post)
    photo = BufferedInputFile(image, f"numerita_{post.id}.jpg")
    if len(re.sub(r"<[^>]+>", "", text)) <= 1024:
        msg = await bot.send_photo(channel, photo, caption=text, parse_mode="HTML")
    else:  # длинный текст в подпись не влезет — картинка, затем текст
        await bot.send_photo(channel, photo)
        msg = await bot.send_message(channel, text, parse_mode="HTML",
                                     link_preview_options=LinkPreviewOptions(is_disabled=True))
    await react(bot, channel, msg.message_id)
    options = poll_options(post.text)
    if options:
        try:
            await bot.send_poll(channel, "Какая группа — про тебя?", options, is_anonymous=True)
        except Exception as e:  # опрос — украшение, без него пост всё равно вышел
            log.warning("Опрос к посту #%s не отправлен: %s", post.id, e)
    return msg


async def restyle(db, bot, channel: str, post_id: int) -> None:
    """Однократно: пост, вышедший голым текстом с длинной ссылкой, — заново в новом виде."""
    key = f"tgch:restyled:{post_id}"
    if not channel or await db.kv_get(key):
        return
    await db.kv_set(key, "done")
    post = await db.get(post_id)
    if not post or not post.tg_message_id or not str(post.tg_message_id).isdigit():
        return
    from aiogram.exceptions import TelegramAPIError
    try:
        await bot.delete_message(channel, int(post.tg_message_id))
    except TelegramAPIError as e:
        log.warning("Старый пост #%s не удалён: %s", post_id, e)
    msg = await send(bot, channel, post, adapt(post, random.Random(post_id)))
    await db.set_tg_message_id(post_id, str(msg.message_id))


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
                                        message_id=int(post.tg_message_id), parse_mode="HTML",
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
    """Текст Threads → пост канала (HTML): без чужих упоминаний и Threads-ссылок, в конце — одна строка-ссылка."""
    from html import escape
    from .bot import LINK_LINE
    text = no_grid_word(strip_credits(post.text))
    text = "\n".join(line.rstrip() for line in LINK_LINE.sub("", text).splitlines()).strip()
    text = text.replace("в комментариях", "в комментариях к посту")
    return f'{escape(text)}\n\n<a href="https://{link(post.id)}">{rng.choice(CTA)}</a>'


def poll_options(text: str) -> list[str]:
    """Группы дней рождения из поста («2, 11, 20, 29») — варианты опроса «Какая группа про тебя?»."""
    groups = [re.sub(r"\s+", " ", g).strip() for g in GROUP.findall(text)]
    return list(dict.fromkeys(groups))[:10] if len(groups) >= 3 else []


def card_image(post) -> bytes:
    """Картинка к текстовому посту канала: карточка «ночь и золото» из первой строки ($0)."""
    from .cards import card_from_text, render_card
    from dataclasses import replace
    return render_card(replace(card_from_text(post.text), cta_text="Обсудим в комментариях ↓"), f"tg-{post.id}")


MIN_TEXT = 120  # короче — обычно подпись к картинке или карусели; в канале без картинки она непонятна


def standalone(post) -> bool:
    """Пост понятен без картинки: матрица идёт со своей картинкой, а подписи к карточкам и каруселям в канал не берём
    (слово владельца 28.10.2026 — «Узнаёте себя? Шестёрки, откликнитесь» без картинки было непонятно)."""
    if grid_image(post):
        return True
    from .text_mode import needs_visual
    return not post.image_url and not post.card and len(post.text.strip()) >= MIN_TEXT and not needs_visual(post.text)


async def pick(db, now: datetime):
    best, best_score = None, MIN_SCORE - 1
    for post in await db.recent_published(now - MAX_AGE):
        if post.tg_message_id or now - post.published_at < MIN_AGE or not standalone(post):
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
    await react(bot, channel, msg.message_id)
    await db.kv_set(key, str(msg.message_id))  # сбой — повторим в следующий проход, дубля не будет


JOKES_CAPTION = """Говорят, у ангелов нет чувства юмора. Я проверила — врут 😉

Во мне целая библиотека знаний: числа и звёзды, психология и наука, бизнес и технологии. Помогу с проектом, \
проведу по миру технологий — без паники и без жаргона. А истина материальной вселенной — в числах.

🔮 Ответ — твоя дата рождения: t.me/Numeritabot?start=ad_th_tgjokes"""
VIDEO_LINK = "t.me/Numeritabot?start=ad_th_tgvid"


def video_caption(caption: str) -> str:
    """Подпись к видео владельца в канале: ролик «Нумерита шутит» — готовая подпись; свой текст — с нашей ссылкой."""
    if "Нумерита шутит" in caption or caption.startswith("🎬"):
        return JOKES_CAPTION
    text = caption.strip()
    if "t.me/" not in text:
        text = (text + "\n\n" if text else "") + f"✨ Твой разбор по дате за 10 секунд: {VIDEO_LINK}"
    return text[:1024]


async def publish_sent_jokes(db, bot, channel: str, admin_ids) -> str | None:
    """Однократно (слово владельца 28.10.2026: «последнее видео хорошее, его используем»): находит в личке с владельцем
    последний присланный ботом ролик «Нумерита шутит» и публикует его в канал. Пересланные для проверки копии сразу
    удаляются. Возвращает итог для владельца или None."""
    key = "tgch:jokes_published"
    if not channel or await db.kv_get(key):
        return None
    from aiogram.exceptions import TelegramAPIError
    for admin in admin_ids:
        try:
            marker = await bot.send_message(admin, "⏳ Публикую ролик «Нумерита шутит» в канал…", disable_notification=True)
        except TelegramAPIError:
            continue
        found = None
        for back in range(1, 60):
            try:
                copy = await bot.forward_message(admin, admin, marker.message_id - back, disable_notification=True)
            except TelegramAPIError:
                continue
            try:
                await bot.delete_message(admin, copy.message_id)
            except TelegramAPIError:
                pass
            if copy.video and "Нумерита шутит" in (copy.caption or ""):
                found = copy.video.file_id
                break
        if not found:
            await bot.edit_message_text("Не нашла ролик в нашей переписке — Claude разберётся.",
                                        chat_id=admin, message_id=marker.message_id)
            continue
        msg = await bot.send_video(channel, found, caption=JOKES_CAPTION, supports_streaming=True)
        await react(bot, channel, msg.message_id)
        await db.kv_set(key, str(msg.message_id))
        await bot.edit_message_text("✅ Ролик «Нумерита шутит» опубликован в канале.", chat_id=admin,
                                    message_id=marker.message_id)
        return "done"
    await db.kv_set(key, "not_found")
    return None


async def react_backfill(db, bot, channel: str, upto: int) -> int:
    """Однократно: положительная реакция на все посты канала с 1 по upto (бот не видит, где реакции уже есть, —
    ставит свою; удалённые номера пропускает). Медленно, чтобы не упереться в лимиты Telegram."""
    if not channel or await db.kv_get("tgch:react_backfill"):
        return 0
    start = int(await db.kv_get("tgch:react_from") or 1)
    done = 0
    rng = random.Random(611)
    for mid in range(start, upto + 1):
        if await react(bot, channel, mid, rng):
            done += 1
        if mid % 20 == 0:
            await db.kv_set("tgch:react_from", str(mid))  # после перезапуска продолжим, а не начнём сначала
        await asyncio.sleep(1.2)
    await db.kv_set("tgch:react_backfill", str(done))
    return done


async def latest_id(db) -> int:
    """Самый свежий известный номер поста канала (наши публикации) — до него и проходим реакциями, с запасом."""
    ids = [int(r["tg_message_id"]) for r in await db._rows(
        "SELECT tg_message_id FROM posts WHERE tg_message_id IS NOT NULL") if str(r["tg_message_id"]).isdigit()]
    for key in ("tgch:announce:new_format", "tgch:jokes_published"):
        value = await db.kv_get(key) or ""
        if value.isdigit():
            ids.append(int(value))
    return max(ids) + 30 if ids else 0


async def run_backfill(db, bot, channel: str) -> None:
    await asyncio.sleep(600)  # после запуска сначала выйдут разовые посты, их номера войдут в проход
    upto = await latest_id(db)
    if upto:
        await react_backfill(db, bot, channel, upto)


async def remove_posts(db, bot, channel: str, post_ids) -> None:
    """Однократно убирает из канала неудачные переносы (слово владельца 28.10.2026)."""
    from aiogram.exceptions import TelegramAPIError
    for post_id in post_ids:
        key = f"tgch:removed:{post_id}"
        if not channel or await db.kv_get(key):
            continue
        post = await db.get(post_id)
        if post and post.tg_message_id and str(post.tg_message_id).isdigit():
            try:
                await bot.delete_message(channel, int(post.tg_message_id))
            except TelegramAPIError as e:
                log.warning("Пост #%s из канала не удалён: %s", post_id, e)
        await db.kv_set(key, "done")  # tg_message_id оставляем — повторно этот пост в канал не пойдёт
