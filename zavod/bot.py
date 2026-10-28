import asyncio
from pathlib import Path
import json
import logging
import random
import re
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .autopost import BOT_LINK, strip_credits, MIN_GAP, ContentPlan, ScriptedPost, Slot, topic_tag_for
from .cards import (
    GRID_TITLES, PLANETS, Card, birth_days, card_from_text, carousel_from_json, carousel_json, grid_json, make_grid, render_card,
    render_grid, soul_carousel, GRID_STYLES, SHAPES,
)
from .autoreply import answer_comments, finish_reply, redo_code_replies
from . import autoreply
from . import text_mode
from .optimizer import optimize
from . import costs, constraint, funnel, performance, approved_post, zero_research, api_budget, tgchannel, brandvideo, instagram, sketch, zero_cleanup
from .config import Config
from .generator import GenerationError, Generator
from .storage import PgStorage, Post, Storage
from .threads_api import MAX_LENGTH, ThreadsClient, ThreadsError
from .tts import synthesize
from . import video as vid
from .knowledge import reduce_number
from .news import GoodNews, HypeNews

log = logging.getLogger(__name__)

STATUS_LABELS = {
    "draft": "📝 Черновик",
    "scheduled": "🕒 Запланирован",
    "published": "✅ Опубликован",
    "failed": "⚠️ Ошибка публикации",
    "deleted": "🗑 Удалён",
}

COMMANDS = [
    ("new", "новый пост: /new <тема>"),
    ("queue", "черновики и запланированные посты"),
    ("stats", "статистика в Threads"),
    ("performance", "лайки и комментарии каждого поста"),
    ("safety", "квоты API и ограничения автоответов"),
    ("reviews", "квитанции трёх ежедневных обходов"),
    ("cleanup", "квитанции удаления нулевых постов"),
    ("costs", "расходы на нейросеть за сегодня"),
    ("compare", "сравнить ответы двух нейросетей"),
    ("status", "модель, база знаний, подключения"),
    ("plan", "контент-план: ближайшие автопосты"),
    ("replies", "последние автоответы на комментарии"),
    ("help", "справка"),
]

HELP = (
    "Я контент-завод Numerita для Threads.\n\n"
    "Просто напишите тему, и я пришлю готовый пост с кнопками:\n"
    "✅ опубликовать сейчас в Threads и Telegram-канал, 🕒 запланировать, 🔄 переписать, 🔊 озвучить, 🗑 удалить.\n\n"
    "Команды:\n"
    "/performance — лайки и комментарии каждого поста\n"
    "/safety — наблюдаемые квоты API и ограничения автоответов\n"
    "/new <тема> — новый пост\n"
    "/queue — черновики и запланированные посты\n"
    "/stats — статистика аккаунта в Threads\n"
    "/status — какая модель, база знаний и подключения\n"
    "/plan — расписание и темы ближайших автопостов\n"
    "/replies — последние автоответы на комментарии в Threads\n"
    "/help — эта справка"
)


class PostAction(CallbackData, prefix="post"):
    action: str  # publish | in1h | tomorrow | redo | voice | delete | stats
    post_id: int


def post_card(post: Post, cfg: Config) -> str:
    header = f"{STATUS_LABELS[post.status]} #{post.id}"
    if post.status == "scheduled" and post.scheduled_at:
        local = post.scheduled_at.astimezone(cfg.timezone)
        header += f" на {local:%d.%m %H:%M}"
    lines = [header, f"Тема: {post.topic}", "", post.text, "", f"{len(post.text)}/{MAX_LENGTH} символов"]
    targets = [name for name, done in (("Threads", post.threads_id), ("Telegram-канал", post.tg_message_id)) if done]
    if targets:
        lines.append("Опубликовано: " + ", ".join(targets))
    if post.status == "failed" and post.error:
        lines.append(f"Причина: {post.error}")
    return "\n".join(lines)


METRICS = [
    ("views", "👁"),
    ("impressions", "👁"),
    ("reach", "охват"),
    ("likes", "❤️"),
    ("comments", "💬"),
    ("shares", "🔁"),
    ("saves", "🔖"),
    ("clicks", "клики"),
]


def format_metrics(analytics: dict | None) -> str:
    """Строка вида «👁 120 · ❤️ 5 · 💬 2 · ER 3.1%» из того, что вернул Zernio."""
    if not isinstance(analytics, dict):
        return "нет данных"
    parts = [
        f"{label} {analytics[key]}"
        for key, label in METRICS
        if isinstance(analytics.get(key), (int, float))
    ]
    rate = analytics.get("engagementRate")
    if isinstance(rate, (int, float)):
        parts.append(f"ER {rate:.1f}%")
    return " · ".join(parts) or "нет данных"


def format_account_stats(payload: dict) -> str:
    lines = ["📊 Статистика Threads"]
    overview = payload.get("overview")
    if isinstance(overview, dict):
        lines += ["", f"Всего: {format_metrics(overview)}"]
    posts = payload.get("posts") or []
    if not posts:
        lines += ["", "Опубликованных постов пока нет."]
    for item in posts:
        content = (item.get("content") or "").replace("\n", " ")
        if len(content) > 60:
            content = content[:60] + "…"
        date = (item.get("publishedAt") or "")[:10]
        lines += ["", f"{date} {content}".strip(), format_metrics(item.get("analytics"))]
    return "\n".join(lines)


def post_keyboard(post: Post):
    kb = InlineKeyboardBuilder()

    def button(text: str, action: str) -> None:
        kb.button(text=text, callback_data=PostAction(action=action, post_id=post.id))

    if post.status in ("draft", "failed"):
        button("✅ Опубликовать", "publish")
        button("🕒 Через час", "in1h")
        button("🕒 Завтра 10:00", "tomorrow")
        button("🔄 Переписать", "redo")
    if post.status == "published" and post.threads_id:
        button("📊 Статистика", "stats")
    button("🔊 Озвучить", "voice")
    if post.status in ("draft", "failed", "scheduled"):
        button("🗑 Удалить", "delete")
    kb.adjust(1, 2, 2, 1)
    return kb.as_markup()


async def ensure_images(post: Post, db: Storage, threads: ThreadsClient) -> list[str]:
    """Рисует карточку (или карусель) к посту и загружает в Zernio. При ошибке пост выйдет без картинок."""
    if post.image_url:
        return post.image_url.split("\n")
    try:
        puzzle = json.loads(post.card) if post.card else None
        if puzzle and "grid" in puzzle:  # головоломка «какие числа ты видишь первыми»
            data = await asyncio.to_thread(
                render_grid, puzzle["grid"], puzzle["title"], puzzle["palette"], f"{post.id}-grid"
            )
            urls = [await threads.upload_image(data, f"numerita_{post.id}_grid.jpg")]
            await db.set_image(post.id, urls[0])
            return urls
        cards = carousel_from_json(post.card) or [Card.from_json(post.card) or card_from_text(post.text)]
        urls = []
        for i, card in enumerate(cards):
            data = await asyncio.to_thread(render_card, card, f"{post.id}-{i}-{post.text[:20]}")
            urls.append(await threads.upload_image(data, f"numerita_{post.id}_{i}.jpg"))
    except Exception:
        log.exception("Картинки к посту #%s не сделаны, публикую без них", post.id)
        return []
    await db.set_image(post.id, "\n".join(urls))
    return urls


async def heart_now(db: Storage, threads: ThreadsClient, bot: Bot, cfg: Config) -> None:
    """Однократно: живая матрица-сердце с хуком и интригой, вне очереди."""
    grid = make_grid(random.Random(3), style="heart")
    text = (f"В этом сердце {len(grid['digits'])} цифр. И одно сочетание ждёт именно тебя.\n"
            "Не ищи — смотри. Первые три секунды честнее любых раздумий.\n"
            "Увидел? Теперь главное: в нумерологии первое замеченное число читают как послание дня. "
            "И у каждого оно своё.\n"
            "Напиши в ответах, что показало тебе сердце, — расскажу, о чём оно 🤍")
    card = json.dumps({**json.loads(grid_json(grid, SHAPES["heart"][0], 2)), "anim": True}, ensure_ascii=False)
    post_id = await db.add_draft("heart-grid-now-2026-10-28", text, "grid", None, card)
    post = await publish(await db.get(post_id), db, threads, bot, "", True)
    await db.kv_set("heart:post", str(post_id))
    if not post.threads_id:
        await notify_admins(bot, cfg, f"⚠️ Сердце не вышло: {post.error}")


async def confirm_heart(db: Storage, threads: ThreadsClient, bot: Bot, cfg: Config) -> None:
    """Владельцу — только квитанция Threads: ссылка на вышедший пост или причина отказа. Если Threads не принял
    видео — тот же пост один раз выходит картинкой (живое сердце остаётся в канале владельца отдельно)."""
    raw = await db.kv_get("heart:post")
    if not raw:  # пост выложила прежняя версия бота — находим его по теме
        rows = await db._rows("SELECT id FROM posts WHERE topic = 'heart-grid-now-2026-10-28' ORDER BY id LIMIT 1")
        raw = str(rows[0]["id"]) if rows else "done:none"
        await db.kv_set("heart:post", raw)
    if raw.startswith("done"):
        return
    post = await db.get(int(raw))
    if not post:
        return
    remote = post.threads_id if post.threads_id not in (None, "published") else None
    if not remote:  # номера нет — ищем в самом Zernio; не нашли — пост не вышел
        found = await threads.find_posts("В этом сердце", datetime.now(timezone.utc) - timedelta(days=2))
        remote = found[0].get("_id") if found else None
    status, url, error = await threads.post_status(remote) if remote else ("failed", None, post.error)
    if status == "published":
        await db.kv_set("heart:post", "done:" + raw)
        await notify_admins(bot, cfg, f"💗 Живое сердце в Threads: {url or 'вышло, ссылку Zernio не дал'}")
    elif status in ("failed", "partial", "cancelled"):
        # Слово владельца: сначала ДНК, «а за ним сердце» — ждём, пока выйдет матрица-ДНК.
        dna = await db._rows("SELECT id FROM posts WHERE rubric = 'grid' AND status = 'published' "
                             "AND card LIKE ?", ('%"style": "dna"%',))
        if not dna:
            return
        await db.kv_set("heart:post", "done:" + raw)
        card = json.loads(post.card)
        if not card.get("anim"):
            await notify_admins(bot, cfg, f"⚠️ Сердце картинкой Threads тоже не принял: {error or status}.")
            return
        card["anim"] = False
        retry = await db.add_draft("heart-grid-image-2026-10-28", post.text, "grid", None,
                                   json.dumps(card, ensure_ascii=False))
        again = await publish(await db.get(retry), db, threads, bot, "", True)
        await db.kv_set("heart:post", str(retry) if again.threads_id else "done:" + raw)
        await notify_admins(bot, cfg, f"⚠️ Threads не принял видео-сердце ({error or status}). "
                                      "Выкладываю то же сердце картинкой — пришлю ссылку, когда Threads подтвердит.")


async def grid_tonight(db: Storage, threads: ThreadsClient, bot: Bot, cfg: Config) -> None:
    """Однократно: выпуск 1 серии «Угадай число» — живая спираль. Владельцу — только квитанция Threads
    (confirm_grid_videos; не принял видео — спираль перевыходит картинкой)."""
    await db.claim_slot("grid new shapes first 2026-10-28")  # прежний принудительный выпуск спирали больше не нужен
    grid = make_grid(random.Random(28), style="spiral")
    text = ("Угадай число · выпуск 1\n"
            "В этой спирали спрятаны семь сочетаний. Глаз выхватит одно — первым, и это не обязательно самое яркое.\n"
            "Не ищи. Просто смотри три секунды.\n"
            "Какое число вынырнуло у тебя? Напиши в ответах — расскажу, о чём оно ✨")
    card = json.dumps({**json.loads(grid_json(grid, SHAPES["spiral"][0], 1)), "anim": True}, ensure_ascii=False)
    post_id = await db.add_draft("grid-tonight-2026-10-28", text, "grid", None, card)
    await db.kv_set("grid:issue", "1")
    await db.kv_set("grid:last_style", "spiral")
    post = await publish(await db.get(post_id), db, threads, bot, "", True)
    await notify_admins(bot, cfg, "🌀 «Угадай число · выпуск 1» отправлен в Threads. Ссылку пришлю, когда Threads "
                                  "подтвердит публикацию." if post.threads_id else f"⚠️ Спираль не вышла: {post.error}")


async def confirm_grid_videos(db: Storage, threads: ThreadsClient, bot: Bot, cfg: Config) -> None:
    """Живые матрицы за сутки: Threads не принял видео — тот же пост один раз выходит картинкой, владельцу причина.
    Два отказа подряд — видео-матрицы выключаются (gridvideo:broken), дальше только картинки."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    for post in await db.recent_published(since):
        if post.rubric != "grid" or not post.card or post.topic.startswith("heart-grid"):
            continue
        card = json.loads(post.card)
        key = f"gridcheck:{post.id}"
        image_retry = post.topic.endswith(":image")
        if not (card.get("anim") or image_retry) or await db.kv_get(key) or post.threads_id in (None, "published"):
            continue
        status, url, error = await threads.post_status(post.threads_id)
        if status == "published":
            await db.kv_set(key, "ok")
            await notify_admins(bot, cfg, f"✅ Матрица в Threads: {url or 'вышла, ссылку Zernio не дал'}")
        elif status in ("failed", "partial", "cancelled") and image_retry:
            await db.kv_set(key, "failed")
            await notify_admins(bot, cfg, f"⚠️ Threads не принял и картинку матрицы: {error or status}.")
        elif status in ("failed", "partial", "cancelled"):
            await db.kv_set(key, "failed")
            fails = int(await db.kv_get("gridvideo:fails") or 0) + 1
            await db.kv_set("gridvideo:fails", str(fails))
            if fails >= 2:
                await db.kv_set("gridvideo:broken", error or status)
            card["anim"] = False
            retry = await db.add_draft(post.topic + ":image", post.text, "grid", None, json.dumps(card, ensure_ascii=False))
            await publish(await db.get(retry), db, threads, bot, "", True)
            await notify_admins(bot, cfg, f"⚠️ Threads не принял живую матрицу ({error or status}) — "
                                          "выкладываю её картинкой, ссылку пришлю после подтверждения.")


async def ensure_grid_video(post: Post, db: Storage, threads: ThreadsClient) -> str | None:
    """Живая матрица: видео формы с переливами и музыкой, если пост отмечен anim. Сбой — выйдет картинкой."""
    try:
        puzzle = json.loads(post.card) if post.card else {}
    except ValueError:
        return None
    if not puzzle.get("anim") or puzzle.get("grid", {}).get("style") not in SHAPES:
        return None
    if await db.kv_get("gridvideo:broken"):  # Threads не принял живую матрицу — пока выходим картинкой
        return None
    saved = await db.kv_get(f"gridvideo:{post.id}")
    if saved:
        return saved
    try:
        from .gridvideo import render_video
        data = await asyncio.to_thread(render_video, puzzle["grid"], puzzle["title"], puzzle["palette"],
                                       f"{post.id}-grid")
        url = await threads.upload_image(data, f"numerita_{post.id}_grid.mp4", "video/mp4")
    except Exception:
        log.exception("Живая матрица к посту #%s не собралась — выйдет картинкой", post.id)
        return None
    await db.kv_set(f"gridvideo:{post.id}", url)
    return url


LINK_LINE = re.compile(r"\S*t\.me/\S+")


def links_to_comment(text: str, first_comment: str | None) -> tuple[str, str | None]:
    """Ссылок в тексте поста не оставляем (prompts/threads_rules.md): переносим в первый комментарий."""
    links = LINK_LINE.findall(text)
    if not links:
        return text, first_comment
    clean = "\n".join(line.rstrip() for line in LINK_LINE.sub("", text).splitlines() if line.strip()).strip()
    return clean, first_comment or FIRST_COMMENTS[0].format(link=links[0])


NETWORK_ERROR = re.compile(r"Не удалось связаться|вернул ошибку 5\d\d|timed? ?out|502|503|504", re.I)
PUBLISH_RETRIES = 3
PUBLISH_RETRY_AFTER = timedelta(minutes=15)


async def publish(
    post: Post, db: Storage, threads: ThreadsClient | None, bot: Bot, channel: str, cards: bool = True
) -> Post:
    """Публикует в Threads (с картинкой-карточкой) и в Telegram-канал. Куда уже вышло, повторно не отправляет."""
    if threads is None and not channel:
        await db.mark_failed(
            post.id,
            "Некуда публиковать: подключите Zernio (ZERNIO_API_KEY, ZERNIO_ACCOUNT_ID) или канал (TELEGRAM_CHANNEL).",
        )
        return await db.get(post.id)

    errors = []
    if threads is not None and not post.threads_id and await db.kv_get(f"publish_retry:{post.id}"):
        try:  # прошлый раз связь оборвалась — пост мог выйти; дубль недопустим
            found = await threads.find_post(strip_credits(links_to_comment(post.text, None)[0]),
                                            datetime.now(timezone.utc) - timedelta(days=2))
        except ThreadsError:
            found = "unknown"
        if found:
            await db.set_threads_id(post.id, found if found != "unknown" else "published")
            post = await db.get(post.id)
    if threads is not None and not post.threads_id:
        try:
            grid_exception = text_mode.grid_post(post)
            video_url = (json.loads(post.card) or {}).get("video") if post.card and not text_mode.enabled() else None
            grid_video = await ensure_grid_video(post, db, threads) if grid_exception else None
            media_kind = 'number_grid_video' if grid_video else 'number_grid'
            video_url = grid_video or video_url
            image_urls = await ensure_images(post, db, threads) if not video_url and (
                (cards and not text_mode.enabled()) or grid_exception) else []
            if grid_exception and not grid_video and len(image_urls)!=1:
                raise ThreadsError('Матрица не загружена; головоломка без изображения не публикуется.')
            text, first_comment = (
                (post.text, post.first_comment) if post.link_mode == "text"  # эксперимент: ссылка в тексте
                else links_to_comment(post.text, post.first_comment)
            )
            text = strip_credits(text)  # без «по мотивам @…» и чужих @упоминаний
            threads_id = await threads.publish_text(
                text, topic_tag_for(post.rubric), first_comment, image_urls, video_url,
                **({'media_kind':media_kind} if grid_exception else {})
            )
            await db.set_threads_id(post.id, threads_id or "published")
        except ThreadsError as e:
            errors.append(f"Threads: {e}")
    if channel and threads is None and not post.tg_message_id:  # с Threads канал получает лучшее (tgchannel)
        try:
            sent = await bot.send_message(channel, post.text)
        except TelegramAPIError as e:
            errors.append(f"Telegram-канал {channel}: {e.message}. Бот должен быть админом канала с правом публикации.")
        else:
            await db.set_tg_message_id(post.id, str(sent.message_id))

    if errors and threads is not None and NETWORK_ERROR.search(errors[0]) and not post.threads_id:
        # Сбой связи: сначала проверяем, не вышел ли пост на самом деле, потом сами повторяем — без кнопок владельцу.
        attempts = int(await db.kv_get(f"publish_retry:{post.id}") or 0)
        try:
            found = await threads.find_post(strip_credits(links_to_comment(post.text, None)[0]),
                                            datetime.now(timezone.utc) - timedelta(days=1))
        except ThreadsError:
            found = None
            attempts = PUBLISH_RETRIES  # не можем проверить — повторять вслепую нельзя (дубль поста)
        if found:
            await db.set_threads_id(post.id, found)
            errors = errors[1:]
        elif attempts < PUBLISH_RETRIES:
            await db.kv_set(f"publish_retry:{post.id}", str(attempts + 1))
            await db.schedule(post.id, datetime.now(timezone.utc) + PUBLISH_RETRY_AFTER)
            log.warning("Пост #%s: сбой связи с Zernio, повторю через 15 минут (%s)", post.id, errors[0])
            return await db.get(post.id)
    if errors:
        await db.mark_failed(post.id, " ".join(errors))
    else:
        await db.mark_published(post.id)
    return await db.get(post.id)


async def send_voice(bot: Bot, chat_id: int, post: Post, cfg: Config) -> None:
    try:
        audio = await synthesize(post.text, cfg.tts_voice, cfg.tts_rate)
    except Exception:
        log.exception("TTS failed for post %s", post.id)
        await bot.send_message(chat_id, f"Не удалось озвучить пост #{post.id}.")
        return
    await bot.send_voice(
        chat_id,
        BufferedInputFile(audio, filename=f"post_{post.id}.mp3"),
        caption=f"🔊 Пост #{post.id}",
    )


def create_router(cfg: Config, plan: ContentPlan) -> Router:
    router = Router()
    router.message.filter(F.from_user.id.in_(cfg.admin_ids))

    @router.message(Command('safety'))
    async def safety_handler(message: Message, db: Storage):
        await message.answer(await api_budget.report(db,datetime.now(timezone.utc)),parse_mode=None)

    @router.message(Command("cleanup"))
    async def cleanup_handler(message: Message, db: Storage):
        await message.answer(await zero_cleanup.report(db, datetime.now(cfg.timezone)), parse_mode=None)

    @router.message(Command("reviews"))
    async def reviews_handler(message: Message, db: Storage):
        await message.answer(await constraint.report(db, datetime.now(cfg.timezone)), parse_mode=None)

    @router.message(Command("performance"))
    async def performance_handler(message: Message, db: Storage):
        await message.answer(await performance.report(db, datetime.now(timezone.utc)), parse_mode=None)

    router.callback_query.filter(F.from_user.id.in_(cfg.admin_ids))

    async def new_post(message: Message, topic: str, db: Storage, generator: Generator) -> None:
        status = await message.answer("✍️ Пишу пост…")
        try:
            text = await generator.write_post(topic)
        except GenerationError as e:
            await status.edit_text(f"❌ {e}")
            return
        post = await db.get(await db.add_draft(topic, text))
        await status.edit_text(post_card(post, cfg), reply_markup=post_keyboard(post))
        if cfg.tts_auto:
            await send_voice(message.bot, message.chat.id, post, cfg)

    @router.message(CommandStart())
    @router.message(Command("help", ignore_case=True))
    async def on_help(message: Message) -> None:
        await message.answer(HELP)

    @router.message(Command("new", ignore_case=True))
    async def on_new(message: Message, command: CommandObject, db: Storage, generator: Generator) -> None:
        if not command.args:
            await message.answer("Напишите тему после команды, например: /new утренние ритуалы")
            return
        await new_post(message, command.args.strip(), db, generator)

    @router.message(Command("status", ignore_case=True))
    async def on_status(message: Message, db: Storage, generator: Generator, threads: ThreadsClient | None) -> None:
        kb = generator.knowledge
        if not kb.url:
            kb_line = "выключена (KB_URL пустой)"
        elif kb.data:
            kb_line = f"загружена, версия {kb.data.get('version', '?')}"
        else:
            kb_line = "ещё не загружалась (загрузится с первым постом)"
        await message.answer(
            "⚙️ Состояние бота\n\n"
            f"Модель: {generator.model}\n"
            f"База знаний Numerita: {kb_line}\n"
            f"Хранилище: {'Postgres' if isinstance(db, PgStorage) else 'временный файл (задайте DATABASE_URL)'}\n"
            f"Публикация в Threads (Zernio): {'подключена' if threads else 'не подключена'}\n"
            f"Telegram-канал: {cfg.telegram_channel or 'не подключён (TELEGRAM_CHANNEL)'}\n"
            f"Автоозвучка: {'включена' if cfg.tts_auto else 'выключена'}\n"
            f"Автоответы на комментарии: {f'включены, до {cfg.autoreply_per_hour} в час' if cfg.autoreply and threads else 'выключены'}\n"
            f"Автопостинг: {'включён, время выбирает бот' if plan.enabled else 'выключен (AUTOPOST=off)'}\n"
            f"Самоулучшение: {'каждый день в 04:10' if plan.enabled else 'выключено'}"
        )

    @router.message(Command("plan", ignore_case=True))
    async def on_plan(message: Message, db: Storage) -> None:
        if not plan.enabled:
            await message.answer("Автопостинг выключен (AUTOPOST=off).")
            return
        now = datetime.now(cfg.timezone)
        stored = await db.kv_get("next_post_at")
        when = datetime.fromisoformat(stored).astimezone(cfg.timezone) if stored else now
        queued = [p for p in await db.queue() if p.status == "queued"]
        day = await db.engagement(now - timedelta(days=1))
        lines = [
            "🗓 Автопостинг: бот сам выбирает время и рубрику.",
            f"Следующий пост: {'сейчас' if when <= now else f'около {when:%H:%M}'}.",
            f"За сутки вышло автопостов: {len(day)}. Готовых текстов в очереди: {len(queued)}.",
            "",
            "Рубрики (вес: больше 1 — чаще, меньше 1 — реже):",
        ]
        label = {"link": "🔗", "reply": "💬", "profile": "👤", "none": "✨"}
        for rubric in plan.all_rubrics():
            mark = " 🧪 новая" if rubric.key.startswith("x") else ""
            mark += " ✍️ переписана" if rubric.key in plan.overrides else ""
            lines.append(f"{label[rubric.cta]} {rubric.key}: {plan.weights.get(rubric.key, 1.0):.1f}{mark}")
        await message.answer("\n".join(lines))

    @router.message(Command("replies", ignore_case=True))
    async def on_replies(message: Message, db: Storage) -> None:
        if not cfg.autoreply:
            await message.answer("Автоответы выключены (AUTOREPLY=0).")
            return
        hour = await db.replies_since(datetime.now(timezone.utc) - timedelta(hours=1))
        day = await db.replies_since(datetime.now(timezone.utc) - timedelta(days=1))
        lines = [f"💬 Автоответы: за час {hour} (лимит {cfg.autoreply_per_hour}), за сутки {day}."]
        error = await db.kv_get("autoreply_error")
        if error:
            lines.append(f"⚠️ Последняя ошибка: {error}")
        lines.append("")
        for row in await db.recent_comments(8):
            mark = "↩️" if row["status"] == "replied" else "⏭"
            lines.append(f"{mark} @{row['author']}: {row['comment'][:80]}")
            if row["reply"]:
                lines.append(f"   → {row['reply'][:160]}")
        if len(lines) == 2:
            lines.append("Комментариев пока не было.")
        await message.answer("\n".join(lines))

    @router.message(Command("queue", ignore_case=True))
    async def on_queue(message: Message, db: Storage) -> None:
        posts = await db.queue()
        if not posts:
            await message.answer("Очередь пуста. Напишите тему, чтобы создать пост.")
            return
        for post in posts:
            await message.answer(post_card(post, cfg), reply_markup=post_keyboard(post))

    @router.message(Command("delete", ignore_case=True))
    async def on_delete(message: Message, command: CommandObject, db: Storage, threads: ThreadsClient | None) -> None:
        """/delete <кусок текста поста> — снять неудачный пост из Threads."""
        fragment = (command.args or "").strip()
        if len(fragment) < 8 or threads is None:
            await message.answer("Напиши: /delete и кусок текста поста (от 8 букв), например /delete Колесо крутится")
            return
        removed = await unpublish_matching(db, threads, [fragment])
        await message.answer(f"🗑 Снято из Threads: {removed}." if removed else "Такой пост за 7 дней не нашла.")

    @router.message(Command("compare", ignore_case=True))
    async def on_compare(message: Message, command: CommandObject, generator: Generator) -> None:
        """/compare <комментарий> — ответы обеих моделей на один комментарий, ровно как их получат люди."""
        comment = (command.args or "").strip()
        if not comment:
            await message.answer("Напиши после команды комментарий, как его написал бы человек в Threads.\n"
                                 "Например: /compare 6 и 17 — что скажешь про нашу пару?")
            return
        post = "Напишите в ответах два числа: день вашего рождения и день рождения партнёра. Скажу, как ладят ваши планеты."
        mode = "profile" if re.search(r"\d", comment) else ("question" if "?" in comment else "plain")
        await message.answer("✍️ Пишу двумя нейросетями, это 10–30 секунд…")
        for model in dict.fromkeys([cfg.reply_model, cfg.reply_ab_model]):
            try:
                text = finish_reply(await generator.write_reply(post, comment, "test", mode, model))
            except GenerationError as e:
                text = f"❌ {e}"
            await message.answer(f"🤖 {model.split('/')[-1]}\n\n{text}")

    @router.message(Command("costs", ignore_case=True))
    async def on_costs(message: Message, db: Storage, generator: Generator) -> None:
        await message.answer(await costs.report(db, generator, cfg.timezone))

    @router.message(Command("stats", ignore_case=True))
    async def on_stats(message: Message, threads: ThreadsClient | None) -> None:
        if threads is None:
            await message.answer("Zernio не подключён: задайте ZERNIO_API_KEY и ZERNIO_ACCOUNT_ID.")
            return
        try:
            payload = await threads.account_stats()
        except ThreadsError as e:
            await message.answer(f"❌ {e}")
            return
        await message.answer(format_account_stats(payload))

    @router.message(F.photo)
    async def on_photo(message: Message, bot: Bot, db: Storage, threads: ThreadsClient | None) -> None:
        """Картинка Нумериты — образец лица для видео."""
        if threads is None:
            await message.answer("Сначала нужен Zernio — туда я сохраняю картинку.")
            return
        buffer = await bot.download(message.photo[-1])
        try:
            url = await threads.upload_image(buffer.read(), f"numerita_reference_{message.message_id}.jpg")
        except ThreadsError as e:
            await message.answer(f"❌ Не удалось сохранить картинку: {e}")
            return
        await db.kv_set("numerita_reference", url)
        await db.kv_set("numerita_portrait", "")  # следующий портрет — по этой картинке
        await message.answer("✨ Запомнила. Следующие видео — с этой Нумеритой.")

    @router.message(F.video)
    async def on_video(message: Message, bot: Bot) -> None:
        """Видео от владельца (своё, из Grok или пересланный ролик бота) — сразу в канал с подписью и ссылкой."""
        if not cfg.telegram_channel:
            await message.answer("Канал не подключён (TELEGRAM_CHANNEL).")
            return
        caption = tgchannel.video_caption(message.caption or "")
        try:
            sent = await bot.send_video(cfg.telegram_channel, message.video.file_id, caption=caption,
                                        supports_streaming=True)
            await tgchannel.react(bot, cfg.telegram_channel, sent.message_id)
        except TelegramAPIError as e:
            await message.answer(f"❌ Канал не принял видео: {e.message}")
            return
        await message.answer("✅ Опубликовала в канале.")

    @router.message(F.text.startswith("/"))
    async def on_unknown_command(message: Message) -> None:
        await message.answer("Не знаю такую команду.\n\n" + HELP)

    @router.message(F.text & ~F.text.startswith("/"))
    async def on_topic(message: Message, db: Storage, generator: Generator) -> None:
        await new_post(message, message.text.strip(), db, generator)

    @router.callback_query(PostAction.filter())
    async def on_action(
        callback: CallbackQuery,
        callback_data: PostAction,
        db: Storage,
        generator: Generator,
        threads: ThreadsClient | None,
    ) -> None:
        post = await db.get(callback_data.post_id)
        if post is None or post.status == "deleted":
            await callback.answer("Пост не найден или удалён.", show_alert=True)
            return

        action = callback_data.action
        if action == "stats":
            if threads is None or not post.threads_id:
                await callback.answer("Статистика недоступна.", show_alert=True)
                return
            try:
                stats = await threads.post_stats(post.threads_id)
            except ThreadsError as e:
                await callback.answer(str(e)[:200], show_alert=True)
                return
            if stats is None:
                await callback.answer("Zernio ещё собирает статистику, загляните позже.", show_alert=True)
                return
            link = stats.get("platformPostUrl")
            text = f"📊 Пост #{post.id}\n{format_metrics(stats.get('analytics'))}"
            await callback.message.answer(text + (f"\n{link}" if link else ""))
            await callback.answer()
            return

        if action == "voice":
            await callback.answer("Озвучиваю…")
            await send_voice(callback.bot, callback.message.chat.id, post, cfg)
            return

        if action == "publish":
            await callback.answer("Публикую…")
            post = await publish(post, db, threads, callback.bot, cfg.telegram_channel, cfg.cards)
        elif action in ("in1h", "tomorrow"):
            now = datetime.now(cfg.timezone)
            if action == "in1h":
                when = now + timedelta(hours=1)
            else:
                when = datetime.combine(now.date() + timedelta(days=1), time(10, 0), cfg.timezone)
            await db.schedule(post.id, when)
            post = await db.get(post.id)
            await callback.answer(f"Запланировано на {when:%d.%m %H:%M}")
        elif action == "redo":
            await callback.answer("Переписываю…")
            try:
                text = await generator.write_post(post.topic, previous=post.text)
            except GenerationError as e:
                await callback.message.answer(f"❌ {e}")
                return
            await db.update_text(post.id, text)
            post = await db.get(post.id)
            if cfg.tts_auto:
                await send_voice(callback.bot, callback.message.chat.id, post, cfg)
        elif action == "delete":
            await db.delete(post.id)
            post = await db.get(post.id)
            await callback.answer("Удалено")

        await callback.message.edit_text(post_card(post, cfg), reply_markup=post_keyboard(post))

    return router


async def send_long(bot: Bot, cfg: Config, text: str, limit: int = 3900) -> None:
    """Длинный текст — несколькими сообщениями, режем по строкам."""
    part = ""
    for line in text.splitlines():
        if len(part) + len(line) + 1 > limit:
            await notify_admins(bot, cfg, part)
            part = ""
        part += line + "\n"
    if part.strip():
        await notify_admins(bot, cfg, part)


async def day_review(db, now: datetime) -> str:
    """Обход дня одним сообщением: цифры Threads, переходы и оплаты в боте, шаблонные ответы и их переответы."""
    rows = await db.replied_since(redo_since := autoreply.REDO_SINCE)
    coded = [r for r in rows if autoreply.is_code_reply(r["reply"])]
    redone = sum([await db.kv_get(f"redo:{r['comment_id']}") == "done" for r in coded])
    parts = ["📊 Обход дня в Threads", await constraint.metrics(db, now, now.tzinfo),
             "Бот за сутки:\n" + ("\n".join(funnel.lines(await funnel.fetch(1))) or "нет данных"),
             f"Шаблонных ответов кодом с {redo_since:%d.%m}: {len(coded)}. Ответы кодом выключены; "
             f"живой ответ с извинением уже получили {redone}, остальные — по 3 за проход в лимитах."]
    return "\n\n".join(parts)[:4000]


def report_chunks(text: str, limit: int = 3500) -> list[str]:
    """Preserve all text and stay below Telegram's limit, including emoji."""
    chunks = []
    start = 0
    while start < len(text):
        end, units, newline = start, 0, None
        while end < len(text):
            width = 2 if ord(text[end]) > 0xFFFF else 1
            if units + width > limit:
                break
            units += width
            end += 1
            if text[end-1] == '\n':
                newline = end
        if end < len(text) and newline is not None and newline > start+(end-start)//2:
            end = newline
        chunks.append(text[start:end])
        start = end
    return chunks


async def notify_admins(bot: Bot, cfg: Config, text: str, post: Post | None = None) -> None:
    chunks = report_chunks(text)
    for admin_id in cfg.admin_ids:
        try:
            for index, chunk in enumerate(chunks):
                await bot.send_message(admin_id, chunk,
                                       reply_markup=post_keyboard(post) if post and index == len(chunks)-1 else None)
        except TelegramAPIError:
            log.exception("Не удалось написать админу %s", admin_id)


# Каждый пост заканчивается крючком к действию в комментариях (слово владельца 24.10.2026): конкретный
# лёгкий ответ за 3 секунды — своё число, «да/нет», одно слово, свой пример. Не «сохрани», а «напиши».
COMMENT_HOOK = (
    "Последняя строка — крючок-обмен, а не просто призыв: «напиши X — и я лично сделаю для тебя Y». "
    "X — лёгкий ответ за 3 секунды (своё число, две даты, одно слово, эмодзи). Y — игривый личный подарок, "
    "которого в посте нет и ради которого хочется написать: твоя суперсила по числу, роль в фильме о твоей жизни, "
    "запрет на ноябрь, фраза, которую тебе нужно услышать сегодня, пароль недели, честный вердикт пары, "
    "какой ты персонаж или блюдо. Каждый раз новый подарок, с юмором и теплом. Ответ на всех чисел в посте "
    "не выдавай — пусть за ним приходят в комментарии. Пример: «Напиши своё число — скажу, какую одну "
    "вещь тебе запрещено делать до конца недели 😏»."
)
BUTTON_RULE = (
    "\nПосле строки КАРТИНКА с новой строки напиши «КНОПКА: » — надпись на золотой кнопке картинки до 32 знаков: "
    "тот же обмен коротко, с обещанием. Примеры: «Напиши число — выдам суперсилу», «Две даты — и вердикт пары»."
)
CTA_RULES = {
    "link": "Перед концом — короткая фраза, что полный разбор — по ссылке в первом комментарии. "
            "Саму ссылку и @Numeritabot не пиши: бот добавит ссылку первым комментарием. " + COMMENT_HOOK,
    "reply": "Без ссылок и без упоминания бота. " + COMMENT_HOOK,
    "profile": "Перед концом — короткая фраза, что полный разбор своей даты — по ссылке в профиле. "
               "Без ссылок и без упоминания бота. " + COMMENT_HOOK,
    "none": "Без ссылок и без упоминания бота. " + COMMENT_HOOK,
}
REPLY_INTERVAL = timedelta(minutes=5)
DAILY_POST_CAP = 20  # постов за сутки максимум (лимит Threads — 250, но живые авторы столько не пишут)
FAST_REPLY_INTERVAL = timedelta(minutes=2)
OPTIMIZE_AT = time(4, 10)  # ежедневный разбор рубрик, когда трафик минимальный
RETRY_AFTER_ERROR = timedelta(minutes=15)

# Первый комментарий со ссылкой: ссылка в самом посте снижает его показы в Threads.
FIRST_COMMENTS = [
    "Полный разбор твоей даты — {link}",
    "Посчитать своё число души: {link}",
    "Узнать своё число души и судьбы: {link}",
    "Разбор по имени и дате ✨ {link}",
]


def first_comment_for(slot: Slot, tag: str | None = None) -> str:
    tag = tag or slot.tag
    template = FIRST_COMMENTS[sum(map(ord, tag)) % len(FIRST_COMMENTS)]
    return template.format(link=BOT_LINK + tag)


# Эксперимент «где ставить ссылку» (prompts/threads_rules.md): в тексте поста, первым комментарием
# или только «ссылка в профиле». Буква режима — в метке ссылки (_lt / _lc), чтобы Нумерита видела переходы.
LINK_MODES = ("text", "comment", "profile")
LINK_MODE_MIN_POSTS = 4  # столько постов каждого способа — прежде чем выбирать лучший
LINK_RULES = {
    "text": "Закончи короткой фразой, что полный разбор — по ссылке ниже. Саму ссылку и @Numeritabot не пиши: "
            "бот добавит ссылку последней строкой.",
    "comment": None,  # обычное правило CTA_RULES["link"]
    "profile": "Закончи фразой, что полный разбор своей даты — по ссылке в профиле. Без ссылок и без упоминания бота.",
}
LINK_CARD_TEXT = {"text": "Разбор — по ссылке в посте", "profile": "Разбор — по ссылке в профиле"}


POST_LINKS = False  # 25.10.2026: по ссылкам в постах и первом комментарии за неделю не пришёл никто — ведём в шапку


async def choose_link_mode(db: Storage, now: datetime, rng: random.Random) -> str:
    """Сначала даём каждому способу набрать постов, потом чаще берём лучший (но остальные тоже пробуем).

    Если самоулучшение выяснило, что ссылка в посте убивает ответы, — 9 из 10 постов без ссылки.
    """
    if not POST_LINKS:
        return "profile"
    if await db.kv_get("links_in_posts") == "off" and rng.random() < 0.9:
        return "profile"
    rows = [r for r in await db.engagement(now - timedelta(days=14)) if r.get("link_mode")]
    counts = {m: sum(1 for r in rows if r["link_mode"] == m) for m in LINK_MODES}
    if min(counts.values()) < LINK_MODE_MIN_POSTS:
        return min(LINK_MODES, key=lambda m: (counts[m], rng.random()))
    weights = json.loads(await db.kv_get("link_mode_weights") or "{}")
    # Решают не комментарии, а люди в боте: способ, по которому за неделю не пришёл никто, пока шапка
    # профиля приводит людей, — на минимум (данные бота Нумериты по меткам).
    came = funnel.arrivals_by_link_mode(await funnel.fetch(7))
    if came and came["profile"]:
        weights = {m: (0.15 if came[m] == 0 and counts[m] >= LINK_MODE_MIN_POSTS and m != "profile"
                       else weights.get(m, 1.0)) for m in LINK_MODES}
    return rng.choices(LINK_MODES, [max(0.15, weights.get(m, 1.0)) for m in LINK_MODES])[0]


# Два стиля фразы на картинке — самоулучшение (optimizer.py) смотрит, какой лучше цепляет.
# Фраза на картинке — крючок, понятный БЕЗ текста поста: кому это (число, дни рождения) и какая польза.
# Никаких отвлечённых метафор без контекста вроде «Колесо крутится, пока ты раздумываешь».
CARD_CLEAR = (" Фраза должна быть понятна сама по себе, без текста поста: кому это (число или дни рождения) "
              "и что человек узнает или получит. Без отвлечённых метафор.")
CARD_RULES = {
    "intrigue": (
        "После поста с новой строки напиши «КАРТИНКА: » и фразу для картинки к посту: до 9 слов, без эмодзи, "
        "интрига или узнавание с конкретикой, чтобы захотелось дочитать и ответить. Не повторяй первую строку "
        "поста дословно. Пример: «Родился 1, 10, 19 или 28? Ты сильнее, чем кажешься»." + CARD_CLEAR
    ),
    "question": (
        "После поста с новой строки напиши «КАРТИНКА: » и фразу для картинки к посту: прямой короткий вопрос "
        "к читателю до 9 слов, без эмодзи, на который хочется ответить в комментариях. Не повторяй первую строку "
        "поста. Пример: «Какое «да» ты откладываешь? Ответь числом»." + CARD_CLEAR
    ),
}


def split_card_hook(raw: str) -> tuple[str, str | None]:
    """Отделяет строку «КАРТИНКА: …» от текста поста."""
    lines, hook = [], None
    for line in raw.splitlines():
        stripped = line.strip().strip("*")
        if stripped.upper().startswith("КАРТИНКА:"):
            hook = stripped.split(":", 1)[1].strip().strip("«»\"") or None
        else:
            lines.append(line)
    return "\n".join(lines).replace("{LINK}", "").strip(), hook  # маркер ссылки не к месту — убираем


def split_button(text: str) -> tuple[str, str | None]:
    """Отделяет строку «КНОПКА: …» — надпись с обещанием на кнопке картинки."""
    lines, button = [], None
    for line in text.splitlines():
        stripped = line.strip().strip("*")
        if stripped.upper().startswith("КНОПКА:"):
            button = stripped.split(":", 1)[1].strip().strip("«»\"") or None
        else:
            lines.append(line)
    if button and len(button) > 34:
        button = None
    return "\n".join(lines).strip(), button


async def write_autopost(
    generator: Generator, slot: Slot, style: str = "intrigue", link_mode: str = "comment",
) -> tuple[str, str | None, str]:
    """Текст поста, первый комментарий (для постов со ссылкой) и фраза для картинки."""
    is_link = slot.rubric.cta == "link"
    rule = (LINK_RULES.get(link_mode) if is_link else None) or CTA_RULES[slot.rubric.cta]
    topic = (f"{text_mode.GRID_MARKER}\n{slot.topic}\n\n{rule}\n{text_mode.GRID_STYLE}"
             if slot.rubric.key == 'grid' and text_mode.enabled() and text_mode.grid_enabled() else
             f"{slot.topic}\n\n{rule}\n\n{text_mode.STYLE}" if text_mode.enabled() else
             f"{slot.topic}\n\n{rule}\n\n{CARD_RULES[style]}" + ("" if is_link else BUTTON_RULE))
    limit = MAX_LENGTH - (60 if is_link and link_mode == "text" else 0)  # место под ссылку в тексте
    text, hook = split_card_hook(await generator.write_post(topic))
    if len(text) > limit:
        text, hook = split_card_hook(
            await generator.write_post(f"{topic} Пиши заметно короче: весь пост до 380 символов.")
        )
    text, button = split_button(text)
    hook = hook or card_from_text(text).hook
    if not is_link:
        return text, None, hook, button
    tag = f"{slot.tag}_l{link_mode[0]}"
    if link_mode == "text":
        return f"{text[:limit].rstrip()}\n{BOT_LINK}{tag}", None, hook, None
    if link_mode == "profile":
        return text, None, hook, None
    return text, first_comment_for(slot, tag), hook, None


async def post_from_bank(
    cfg: Config, db: Storage, threads: ThreadsClient | None, bot: Bot, plan: ContentPlan, slot: Slot,
    rng: random.Random, generator: Generator | None = None,
) -> bool:
    """Следующий готовый пост «не подарок — джекпот». False — банк закончился, пишет нейросеть."""
    used = set(json.loads(await db.kv_get("jackpot_used") or "[]"))
    fresh = [i for i, item in enumerate(plan.bank) if i not in used]
    if not fresh:
        return False
    i = fresh[0]
    item = plan.bank[i]
    await db.kv_set("jackpot_used", json.dumps(sorted(used | {i})))
    lines = item.text.splitlines()
    hook = lines[1] if len(lines) > 1 else lines[0]
    digit = int(item.number) if item.number.isdigit() else None
    label = item.label or (PLANETS.get(digit) if digit and digit <= 9 else None)
    palette, style = plan.choose_card(rng)
    card = Card(hook, item.number, label, "reply", None, palette, style,
                birth_days(digit) if digit and digit <= 9 and not item.label else None)
    text = await hook_gate(generator, item.text) if generator else item.text
    post = await db.get(await db.add_draft(f"Банк: {lines[0]}", text, "jackpot", None, card.to_json()))
    post = await publish(post, db, threads, bot, "", cfg.cards)
    if post.status == "failed":
        await notify_admins(bot, cfg, "⚠️ Пост не опубликован\n\n" + post_card(post, cfg), post)
    return True


# «Второй шанс»: пост без реакций не удаляем (удаления и копии вредят аккаунту), а через несколько часов
# выпускаем ту же идею заново — короче, с сильнее первой строкой и в другое время. Не чаще раза в 8 часов.
DEAD_AFTER = timedelta(hours=6)
RETRY_EVERY = timedelta(hours=8)
NO_RETRY = {"script", "video", "grid", "jackpot", "carousel", "one_portrait"}
RETRY_TOPIC = (
    "Этот наш пост не собрал ни одного ответа. Напиши на ту же идею НОВЫЙ пост, совсем другими словами:\n"
    "- первая строка — сильный крючок про конкретных людей («Родился 9, 18 или 27?», «Есть тут…»), до 60 знаков;\n"
    "- всего 2–4 короткие строки, без лекции и длинной истории;\n"
    "- в конце вопрос, на который легко ответить одним словом или числом.\n"
    "Старый пост (не повторяй его фразы):\n{old}"
)


async def find_dead_post(db: Storage, now: datetime, skip: set[str] = frozenset()) -> dict | None:
    """Пост, на который за 6+ часов никто не ответил, — кандидат на «второй шанс»."""
    last = await db.kv_get("last_retry")
    if last and now - datetime.fromisoformat(last) < RETRY_EVERY:
        return None
    if await db.kv_get("autoreply_error"):  # комментарии не читаются — не знаем, кто живой, кто нет
        return None
    rows = await performance.comparable(db, now - timedelta(hours=48))
    if not any(r["comments"] for r in rows):  # ни одного комментария нигде — данных нет, не трогаем
        return None
    retried = set(json.loads(await db.kv_get("retried_posts") or "[]"))
    dead = [
        r for r in rows
        if r["rubric"] not in NO_RETRY | skip and r["id"] not in retried and not r["comments"] and r["likes"] <= 1
        and not (r.get("topic") or "").startswith(RETRY_TOPIC[:20])  # второй шанс — один
        and now - datetime.fromisoformat(r["published_at"]) >= DEAD_AFTER
    ]
    return min(dead, key=lambda r: r["published_at"]) if dead else None


NEWS = GoodNews()
HYPE = HypeNews()
NEWS_PAUSE = timedelta(hours=3)  # если доброго повода не нашлось — не пробуем новости пару часов
NEWS_RULES = (
    "\n\nДобрые новости последних часов (только заголовки):\n{items}\n\n"
    "Выбери ОДНУ — самую светлую и радостную: доброта, любовь, дети, природа, вера, добрые дела, "
    "научные прорывы и изобретения (удиви и восхитись умом людей, объясни просто). "
    "Перескажи её своими словами одной-двумя фразами, назови источник («пишет РИА Новости»), ничего не добавляй "
    "к фактам из заголовка. Дальше — свой лёгкий, умный и тёплый взгляд: улыбнись, поддержи, свяжи с числом дня "
    "{day} или числом души — как опора для людей. Никакой политики, войны и трагедий. "
    "Последней строкой напиши «ИСТОЧНИК: <номер новости>». Если ни одна новость не радостная — верни только SKIP."
)


HYPE_RULES = (
    "\n\nЧто сейчас обсуждают про медийных людей (только заголовки):\n{items}\n\n"
    "Выбери ОДНУ — самую громкую и хайповую историю про поп-звезду, юмориста, блогера, тиктокера или шоумена, "
    "которую и так все обсуждают. Это НЕ новостная заметка: не пересказывай новость и не ссылайся на издание. "
    "Напиши шутку на злобу дня — острую, остроумную, с перчинкой: читатель узнаёт повод по одному намёку или имени "
    "и смеётся. Можно сценкой, «протоколом», плакатом или репликой. Обязательно нумерология: обыграй, как на месте звезды повели бы "
    "себя Единицы, Пятёрки, Восьмёрки. Не приписывай звезде того, чего нет в заголовке; дату и числа звезды не называй. "
    "Смеёмся над ситуацией и хайпом, не над человеком: без внешности, веса, болезней, детей, развода, судов, денег "
    "в долг; никаких силовиков, военных, войны и политики; без мата и пошлости. 2–5 коротких строк, до 400 знаков, "
    "последняя — вопрос или подначка, на которую хочется ответить. Последней строкой напиши «ИСТОЧНИК: <номер "
    "новости>». Если ни одна история не смешная и не громкая — верни только SKIP."
)


def split_news_source(text: str) -> tuple[str, int | None]:
    match = re.search(r"^\s*ИСТОЧНИК:\s*(\d+)\s*$", text, re.M | re.I)
    if not match:
        return text, None
    return (text[: match.start()] + text[match.end():]).strip(), int(match.group(1))


async def post_next(
    bot: Bot, cfg: Config, db: Storage, threads: ThreadsClient | None, generator: Generator,
    plan: ContentPlan, now: datetime, rng: random.Random,
) -> bool:
    """Выпускает следующий пост: готовый текст из очереди (через пост) или новый по рубрике.

    Возвращает False, только если пост не удалось написать (тогда повторим скоро).
    """
    recent = await db.recent_rubrics(6)
    queued = await text_mode.next_seed(db) if text_mode.enabled() else await db.next_queued()
    if queued and (not recent or recent[0] not in ('script','text_seed')):
        if queued.rubric != 'text_seed' and (queued.rubric == "script" or text_mode.enabled()):
            queued = await sharpen_script(db, generator, queued)
        post = await publish(queued, db, threads, bot, "", cfg.cards)
    else:
        rubric = plan.choose(recent, rng)
        news_pause = await db.kv_get("news_pause_until")
        for _ in range(5):  # новости — только когда есть свежий добрый повод
            hype_done = rubric.key == "text_hype" and await db.kv_get(f"hype:{now.date().isoformat()}")
            if not hype_done and (rubric.key not in ("news", "text_hype")
                                  or not (news_pause and now < datetime.fromisoformat(news_pause))):
                break
            rubric = plan.choose(recent, rng)
        grid_rubric = next((r for r in plan.all_rubrics() if r.key == "grid"), None)
        if grid_rubric and (not text_mode.enabled() or text_mode.allowed(grid_rubric)):
            # Слово владельца 28.10.2026: сегодня спираль (grid_tonight), ДНК — «завтра с утра», за ней сердце.
            if now >= datetime(2026, 10, 29, 8, 0, tzinfo=now.tzinfo) \
                    and await db.claim_slot("grid dna first 2026-10-28"):  # ДНК из цифр — живым видео
                await db.kv_set("grid:last_style", GRID_STYLES[GRID_STYLES.index("dna") - 1])
                await db.kv_set("grid:last_anim", "0")
                rubric = plan.effective(grid_rubric)
        # Рубрики со ссылкой не повторяем: у ссылок свои лимиты (prompts/threads_rules.md).
        dead = await find_dead_post(db, now, {r.key for r in plan.all_rubrics() if r.cta == "link"})
        if dead:
            original = {r.key: r for r in plan.all_rubrics()}.get(dead["rubric"])
            if original is None or original.cta == "link" or (text_mode.enabled() and not text_mode.allowed(original)):
                dead = None
            else:
                rubric = plan.effective(original)
        slot = plan.render(rubric, now, rng)
        post_focus = await constraint.focus(db, "post_focus")  # обход по Голдратту: фокус на узкое звено
        if post_focus:
            slot = replace(slot, topic=slot.topic + "\n\nФокус на сегодня (узкое звено): " + post_focus)
        if not await db.claim_slot(slot.key):
            return True
        if dead:
            retried = json.loads(await db.kv_get("retried_posts") or "[]")
            await db.kv_set("retried_posts", json.dumps((retried + [dead["id"]])[-200:]))
            await db.kv_set("last_retry", now.isoformat())
            slot = replace(slot, topic=RETRY_TOPIC.format(old=dead["text"]) + "\n\nИсходное задание рубрики: " + slot.topic)
            log.info("Второй шанс для поста #%s", dead["id"])
        if slot.rubric.key == "jackpot" and await post_from_bank(cfg, db, threads, bot, plan, slot, rng, generator):
            return True
        news = []
        hype = slot.rubric.key == "text_hype"
        if slot.rubric.key == "news" or hype:
            used = set(json.loads(await db.kv_get("news_used") or "[]"))
            news = await (HYPE if hype else NEWS).candidates(used, rng)
            if not news:
                await db.kv_set("news_pause_until", (now + NEWS_PAUSE).isoformat())
                return False
            items = "\n".join(f"{i}. {h.title} ({h.source})" for i, h in enumerate(news, 1))
            rules = HYPE_RULES if hype else NEWS_RULES
            slot = replace(slot, topic=slot.topic + rules.format(items=items, day=reduce_number(now.day)))
        portrait_deck = None
        if slot.rubric.key == "one_portrait":
            from . import solar_portraits
            portrait_deck = solar_portraits.choose(rng)
            slot = replace(slot, topic=slot.topic + solar_portraits.topic(portrait_deck))
        grid = None
        if slot.rubric.key == "grid":
            # Формы чередуются по кругу, чтобы матрица не приедалась (слово владельца 28.10.2026).
            last = await db.kv_get("grid:last_style") or "classic"
            shape = GRID_STYLES[(GRID_STYLES.index(last) + 1) % len(GRID_STYLES)] if last in GRID_STYLES else "spiral"
            await db.kv_set("grid:last_style", shape)
            grid = make_grid(rng, style=shape)
            grid_title = SHAPES[shape][0] if shape in SHAPES else rng.choice(GRID_TITLES)
            issue = int(await db.kv_get("grid:issue") or 1) + 1  # серия «Угадай число»; выпуск 1 — спираль 28.10
            await db.kv_set("grid:issue", str(issue))
            # Модели — какие числа спрятаны, чтобы пост мог намекнуть, но не выдать их все.
            slot = replace(slot, topic=slot.topic + "\nНа картинке спрятаны: " + ", ".join(grid["hidden"])
                           + ". Не перечисляй их в тексте."
                           + f"\nЭто серия «Угадай число» — первая строка поста: «Угадай число · выпуск {issue}»."
                           + (f"\nФорма картинки: {SHAPES[shape][1]}. Вопрос на картинке: «{grid_title}» — "
                              "в тексте задай свой, новый вопрос в духе формы, не повторяя картинку." if shape in SHAPES else ""))
        log.info("Автопост (%s): %s", slot.rubric.key, slot.topic)
        link_mode = await choose_link_mode(db, now, rng) if slot.rubric.cta == "link" else None
        try:
            palette, style = plan.choose_card(rng)
            text, first_comment, hook, button = await write_autopost(generator, slot, style, link_mode or "comment")
            if news:
                text, number = split_news_source(text)
                if text.strip().upper().startswith("SKIP"):
                    await db.kv_set("news_pause_until", (now + NEWS_PAUSE).isoformat())
                    return False
                if hype:  # проба: одна шутка о хайпе в день
                    await db.kv_set(f"hype:{now.date().isoformat()}", "1")
                if number and 1 <= number <= len(news):
                    used = json.loads(await db.kv_get("news_used") or "[]") + [news[number - 1].title]
                    await db.kv_set("news_used", json.dumps(used[-300:], ensure_ascii=False))
        except GenerationError as e:
            await notify_admins(bot, cfg, f"❌ Автопост не написан: {e}\nТема: {slot.topic}")
            return False
        if not (grid and text_mode.enabled()):
            text = await hook_gate(generator, text)
        if grid:
            card_json = grid_json(grid, grid_title, palette)
            if shape in SHAPES:  # через раз — живое видео с музыкой, через раз — картинка: сравниваем отклик
                anim = (await db.kv_get("grid:last_anim")) != "1"
                await db.kv_set("grid:last_anim", "1" if anim else "0")
                card_json = json.dumps({**json.loads(card_json), "anim": anim}, ensure_ascii=False)
        elif text_mode.enabled():
            card_json = None
        elif portrait_deck is not None:
            card_json = carousel_json(solar_portraits.cards(portrait_deck, palette))
        elif slot.rubric.key == "eight_growth":
            from .cards import eight_growth_carousel
            card_json = carousel_json(eight_growth_carousel(palette))
        elif slot.rubric.key == "carousel":
            numbers = (generator.knowledge.data or {}).get("numbers", {})
            card_json = carousel_json(soul_carousel(numbers, palette))
        else:
            card_json = Card(
                hook, slot.card_number, slot.card_label, slot.rubric.cta,
                slot.card_cta_text or button or LINK_CARD_TEXT.get(link_mode or ""), palette, style, slot.card_dates,
            ).to_json()
        post_id = await db.add_draft(slot.topic, text, slot.rubric.key, first_comment, card_json)
        if link_mode:
            await db.set_link_mode(post_id, link_mode)
        post = await db.get(post_id)
        post = await publish(post, db, threads, bot, "", cfg.cards)
    if post.status == "failed":  # пишем владельцу только о проблемах
        await notify_admins(bot, cfg, "⚠️ Пост не опубликован\n\n" + post_card(post, cfg), post)
    return True


SCRIPT_LINK_LINE = re.compile(r"^.*t\.me/\S+.*$", re.M)


async def sharpen_script(db: Storage, generator: Generator, post: Post) -> Post:
    """Готовые посты из плана перед выходом проходят огранку: крючок, юмор, повод ответить (слово владельца 24.10.2026).
    Ссылку с меткой сохраняем как была — бот сам решит, где ей стоять."""
    links = SCRIPT_LINK_LINE.findall(post.text)
    try:
        text = (await generator.sharpen(SCRIPT_LINK_LINE.sub("", post.text).strip())).strip()
    except GenerationError as e:
        log.warning("Огранка поста #%s не удалась, выходит как есть: %s", post.id, e)
        return post
    text = "\n".join([strip_credits(SCRIPT_LINK_LINE.sub("", text).strip())] + links)
    if not text.strip() or len(text) > MAX_LENGTH:
        return post
    await db.update_text(post.id, text)
    return await db.get(post.id) or post


HOOK_MIN = 8  # ниже — пост переписывается (слово владельца 24.10.2026: «в каждом посте интрига и хук»)


async def hook_gate(generator: Generator, text: str) -> str:
    """Каждый пост перед выходом проходит проверку крючка: не цепляет — переписываем один раз.
    Ссылки с меткой сохраняем как были."""
    links = SCRIPT_LINK_LINE.findall(text)
    body = SCRIPT_LINK_LINE.sub("", text).strip()
    try:
        score, why = await generator.hook_score(body)
        if score >= HOOK_MIN:
            return text
        log.info("Пост без крючка (%s/10: %s) — переписываю", score, why)
        better = strip_credits(SCRIPT_LINK_LINE.sub("", (await generator.strengthen(body, why)).strip()).strip())
    except GenerationError as e:
        log.warning("Проверка крючка не удалась, пост выходит как есть: %s", e)
        return text
    result = "\n".join([better] + links)
    return result if better and len(result) <= MAX_LENGTH else text


# Перерывы в постах по слову владельца: с, по (время Config.timezone).
POST_BREAKS = [("2026-10-25T04:00", "2026-10-25T06:00")]


def post_break_end(now: datetime) -> datetime | None:
    for start, end in POST_BREAKS:
        a, b = (datetime.fromisoformat(x).replace(tzinfo=now.tzinfo) for x in (start, end))
        if a <= now < b:
            return b
    return None


async def autopost_tick(
    bot: Bot, cfg: Config, db: Storage, threads: ThreadsClient | None, generator: Generator,
    plan: ContentPlan, rng: random.Random,
) -> None:
    """Пора ли выпускать пост. Время следующего поста бот выбирает сам и хранит в базе."""
    now = datetime.now(cfg.timezone)
    last = await db.last_published_at()
    stored = await db.kv_get("next_post_at")
    if stored:
        next_at = datetime.fromisoformat(stored)
    else:
        # Первый запуск: если давно ничего не выходило — постим сразу.
        next_at = now if last is None or now - last >= MIN_GAP else last + MIN_GAP
    if now < next_at:
        return
    pause_end = post_break_end(now)
    if pause_end:
        await db.kv_set("next_post_at", (pause_end + timedelta(minutes=rng.randint(3, 20))).isoformat())
        return
    if len(await db.recent_published(now - timedelta(days=1))) >= DAILY_POST_CAP:
        await db.kv_set("next_post_at", (now + timedelta(hours=1)).isoformat())
        return
    if last is not None and now - last < MIN_GAP:  # пост уже вышел другим путём — выдерживаем паузу
        await db.kv_set("next_post_at", (last + MIN_GAP).isoformat())
        return
    ok = await post_next(bot, cfg, db, threads, generator, plan, now, rng)
    delay = plan.next_gap(now, rng) if ok else RETRY_AFTER_ERROR
    await db.kv_set("next_post_at", (now + delay).isoformat())


async def import_script(db: Storage, script: list[ScriptedPost]) -> int:
    """Ставит готовые тексты в очередь (каждый — один раз). Когда их выпускать, бот решает сам."""
    await db.requeue_scheduled_scripts()
    await db.drop_credited_posts()
    added = 0
    for item in script:
        if len(item.text) > MAX_LENGTH:
            log.warning("Готовый пост %s длиннее %s символов, пропущен", item.key, MAX_LENGTH)
            continue
        if await db.claim_slot(item.key):
            post_id = await db.add_draft("Готовый пост из плана", item.text, "script")
            await db.queue_post(post_id)
            added += 1
    return added


VIDEO_RETRY = timedelta(hours=1)
_video_busy = False


async def numerita_references(db: Storage, threads: ThreadsClient) -> list[str]:
    """Картинки Нумериты для образца: присланная владельцем или из assets/numerita (загружаем в Zernio один раз)."""
    sent = await db.kv_get("numerita_reference")
    if sent:
        return [sent]
    stored = json.loads(await db.kv_get("numerita_assets") or "[]")
    if not stored:
        for path in sorted(vid.REFERENCES.glob("*.jpg")):
            stored.append(await threads.upload_image(path.read_bytes(), f"numerita_ref_{path.name}"))
        await db.kv_set("numerita_assets", json.dumps(stored))
    return stored


async def video_tick(
    bot: Bot, cfg: Config, db: Storage, threads: ThreadsClient, generator: Generator, rng: random.Random,
) -> None:
    """Видео с Нумеритой: сначала три главных ролика, потом новые — не больше VIDEO_PER_DAY в сутки."""
    global _video_busy
    now = datetime.now(cfg.timezone)
    if post_break_end(now):
        return
    retry = await db.kv_get("video_retry_at")
    if _video_busy or (retry and now < datetime.fromisoformat(retry)):
        return
    done = json.loads(await db.kv_get("video_done") or "[]")
    count_key = f"videos {now.date().isoformat()}"
    made_today = int(await db.kv_get(count_key) or 0)
    # Два ролика — сразу, главный (hero) — к утру.
    pending = sorted((s for s in vid.SCENES if s.key not in done), key=lambda s: s.key == "hero")
    if not pending and made_today >= cfg.video_per_day:
        return
    _video_busy = True
    asyncio.create_task(_make_video(bot, cfg, db, threads, generator, rng, pending, done, count_key, made_today))


async def _make_video(
    bot: Bot, cfg: Config, db: Storage, threads: ThreadsClient, generator: Generator, rng: random.Random,
    pending: list, done: list, count_key: str, made_today: int,
) -> None:
    global _video_busy
    fal = vid.FalClient(cfg.fal_key)
    try:
        if pending:
            scene, resolution = pending[0], "1080p"  # первые ролики — в лучшем качестве
        else:
            previous = json.loads(await db.kv_get("video_speeches") or "[]")
            scene, resolution = await vid.invent_scene(generator, previous, rng), cfg.video_resolution
        image_url = await db.kv_get("numerita_portrait")
        if not image_url:
            raw = await vid.download(await vid.portrait(fal, await numerita_references(db, threads)))
            jpeg = vid.to_jpeg(raw)
            image_url = await threads.upload_image(jpeg, "numerita_portrait.jpg")
            await db.kv_set("numerita_portrait", image_url)
            for admin_id in cfg.admin_ids:  # портрет пригодится и для аватарок, и для сторис
                try:
                    await bot.send_document(admin_id, BufferedInputFile(jpeg, "numerita_portrait.jpg"),
                                            caption="✨ Новый портрет Нумериты — с него сниму видео.")
                except TelegramAPIError:
                    log.exception("Не удалось отправить портрет админу %s", admin_id)
        data = await vid.download(await vid.shoot(fal, image_url, scene, resolution))
        video_url = await threads.upload_image(data, f"numerita_{scene.key}.mp4", "video/mp4")

        now = datetime.now(cfg.timezone)
        when = vid.morning_after(now) if scene.key == "hero" else now
        tag = f"v{scene.key}_{now:%d%m}"
        first_comment = FIRST_COMMENTS[0].format(link=BOT_LINK + tag)
        card = json.dumps({"video": video_url, "scene": scene.key, "speech": scene.speech}, ensure_ascii=False)
        # Meta требует помечать реалистичное видео и голос, сделанные ИИ; через API метку не поставить — пишем в тексте.
        caption = scene.caption + "\n\n🤖 Видео создано с помощью ИИ"
        post_id = await db.add_draft(f"Видео: {scene.key}", caption, "video", first_comment, card)
        await db.schedule(post_id, when)

        done.append(scene.key)
        await db.kv_set("video_done", json.dumps(done))
        await db.kv_set(count_key, str(made_today + 1))
        speeches = json.loads(await db.kv_get("video_speeches") or "[]") + [scene.speech]
        await db.kv_set("video_speeches", json.dumps(speeches[-10:], ensure_ascii=False))
        caption = (
            f"🎬 Новое видео с Нумеритой. В Threads выйдет {when:%d.%m в %H:%M}.\n"
            f"Для сторис, канала и Инстаграма — сохраняй отсюда.\n\nОна говорит: «{scene.speech}»\n\n"
            f"Стоило ≈ ${vid.cost(resolution):.1f} ({resolution}, 15 сек)."
        )
        for admin_id in cfg.admin_ids:
            try:
                await bot.send_video(admin_id, BufferedInputFile(data, f"numerita_{scene.key}.mp4"),
                                     caption=caption[:1024], supports_streaming=True)
            except TelegramAPIError:
                log.exception("Не удалось отправить видео админу %s", admin_id)
    except (vid.VideoError, ThreadsError, GenerationError) as e:
        log.warning("Видео не сделано: %s", e)
        await db.kv_set("video_retry_at", (datetime.now(cfg.timezone) + VIDEO_RETRY).isoformat())
        if await db.kv_get("video_last_error") != str(e)[:300]:  # об одной и той же ошибке пишем один раз
            await db.kv_set("video_last_error", str(e)[:300])
            await notify_admins(bot, cfg, f"⚠️ Видео не получилось, попробую через час.\n{e}")
    except Exception:
        log.exception("Видео: непредвиденная ошибка")
        await db.kv_set("video_retry_at", (datetime.now(cfg.timezone) + VIDEO_RETRY).isoformat())
    finally:
        _video_busy = False


ADDON_HELP = (
    "\n\nКак починить (2 минуты):\n1. Зайди на zernio.com → Billing (Оплата).\n"
    "2. Включи дополнение Inbox.\n3. Всё — бот сам ответит всем, кто уже написал."
)


# Неудачные посты, которые владелец попросил снять (24.10.2026: «позорит красоту системы выкладки»).
UNPUBLISH = ["Колесо крутится, пока ты раздумываешь",
             "Признаюсь: последние дни я отвечала вам как автоответчик ЖЭКа",  # 28.10: извинение не нужно
             "Протокол проверки бизнес-идеи"]  # 28.10: «тематика мимо» — без нумерологии


async def unpublish_matching(db: Storage, threads: ThreadsClient, fragments: list[str]) -> list[str]:
    """Снимает из Threads посты недели с этими кусками текста. Номер поста ищет и в базе, и в самом Zernio
    (в базе бывает заглушка «published»); после снятия сверяет статус. Возвращает строки для владельца."""
    report = []
    since = datetime.now(timezone.utc) - timedelta(days=7)
    for fragment in fragments:
        if await db.kv_get(f"unpub:{fragment[:40]}") == "done":
            continue
        local = await db.find_published(fragment, since)
        remote_ids = {p.threads_id for p in local if p.threads_id and p.threads_id != "published"}
        try:
            remote_ids |= {p.get("_id") for p in await threads.find_posts(fragment, since) if p.get("_id")}
        except ThreadsError as e:
            log.warning("Поиск поста «%s» в Zernio не удался: %s", fragment, e)
        removed = False
        for remote in remote_ids:
            try:
                status, _, _ = await threads.post_status(remote)
                if status in ("published", "publishing"):
                    await threads.unpublish(remote)
                    status, _, _ = await threads.post_status(remote)
                removed = removed or status not in ("published", "publishing")
            except ThreadsError as e:
                log.warning("Не удалось снять пост %s: %s", remote, e)
        if removed or (remote_ids and not local):
            for post in local:
                await db.delete(post.id)
        if removed:
            await db.kv_set(f"unpub:{fragment[:40]}", "done")
            report.append(f"🗑 Снят из Threads: «{fragment}»")
        elif local or remote_ids:
            report.append(f"⚠️ Не получилось снять «{fragment}» — попробую снова через 10 минут.")
    return report


async def report_autoreply_error(bot: Bot, cfg: Config, db: Storage) -> None:
    """Если автоответы сломались — сообщаем владельцу один раз на каждую новую причину."""
    paused = await db.kv_get("reply_links_paused_until") or ""
    if paused and paused != (await db.kv_get("reply_links_pause_sent") or ""):
        await db.kv_set("reply_links_pause_sent", paused)
        await notify_admins(bot, cfg, "⛔ Сервис публикации не принял ответ со ссылкой. На всякий случай выключил ссылки "
                                      f"в ответах до {datetime.fromisoformat(paused):%d.%m}. Ответы без ссылок идут как обычно.")
    error = await db.kv_get("autoreply_error") or ""
    stage, _, reason = error.partition(": ")
    stage = stage.split(" ")[-1] if reason else ""
    fingerprint = 'zernio-http-429' if 'Zernio HTTP 429' in reason else reason
    previous = await db.kv_get("autoreply_error_sent") or ""
    if fingerprint == previous:
        return
    success = await db.kv_get('autoreply:last_success') or ''
    if not reason:
        if not success or success == (await db.kv_get('autoreply:success_at_warning') or ''):
            return
    else:
        await db.kv_set('autoreply:success_at_warning', success)
    await db.kv_set("autoreply_error_sent", fingerprint)
    if reason:
        await notify_admins(bot, cfg, explain_autoreply_error(stage, reason))
    else:
        await notify_admins(bot, cfg, "✅ Подтверждена успешная отправка нового ответа в Threads.")


def explain_autoreply_error(stage: str, reason: str) -> str:
    """Ошибка автоответов — простыми словами: что случилось, что бот делает сам, нужно ли что-то от владельца."""
    low = reason.lower()
    if stage == "бюджет":
        return (f"💰 Автоответы: {reason}.\nТак работает закон «всегда в плюсе»: дневной потолок расходов на ответы — "
                "переменная REPLY_BUDGET_USD. Посты выходят как обычно.")
    if "inbox add-on" in low:
        what, todo = "в тарифе Zernio нет доступа к комментариям.", ADDON_HELP.strip()
    elif "401" in low or "unauthorized" in low or "api key" in low or "ключ" in low and stage != "нейросеть":
        what, todo = "Zernio не принимает ключ доступа.", "Нужно от тебя: проверь ZERNIO_API_KEY в Railway (Variables)."
    elif stage == "нейросеть":
        what = "нейросеть, которая пишет ответы (OpenRouter), не ответила."
        todo = ("Если повторится — проверь баланс OpenRouter. Бот сам попробует снова через 5 минут."
                if "402" in low or "баланс" in low or "credit" in low else "Бот сам попробует снова через 5 минут.")
    elif 'zernio http 403' in low and '80016' in low:
        what = 'Zernio вернул HTTP 403 с кодом платформы 80016. Точная причина отказа не установлена; это не подтверждение бана.'
        todo = 'Автоответы приостановлены минимум на 30 минут; при повторах пауза растёт до 6 часов. Повторные попытки не идут каждые 5 минут.'
    elif 'zernio http 429' in low:
        what = 'API Zernio вернул HTTP 429 — ограничение запросов. Источник внутри цепочки Zernio/Threads не установлен.'
        todo = 'Пауза автоответов сохранена; бот учтёт Retry-After и повторит позже.'
    else:
        part = {"комментарии": "получить комментарии", "ответ": "отправить ответ",
                "комментариями": "получить список постов"}.get(stage, "ответить")
        what = f"не получилось {part}. Техническая причина: {reason[:200]}"
        todo = "Бот сам повторит через 5 минут. Если сообщение будет повторяться — перешли его мне."
    return ("⚠️ Автоответы в Threads: заминка.\n\n"
            f"Что случилось: {what}\n{todo}\n\nСтатус публикации постов проверяется отдельно.")


async def run_scheduler(
    bot: Bot,
    cfg: Config,
    db: Storage,
    threads: ThreadsClient | None,
    generator: Generator,
    plan: ContentPlan,
) -> None:
    """Раз в 30 секунд: посты по кнопкам «через час», автопостинг; раз в 5 минут — ответы на комментарии."""
    try:
        await zero_research.send_admin_report(bot, cfg, db)
    except Exception:
        log.exception("Owner zero research report was not confirmed; no blind resend")
    rng = random.Random()
    next_replies = datetime.now()
    if await db.claim_slot("owner note margarita"):  # владелец попросил прислать в Telegram (25.10.2026)
        await notify_admins(bot, cfg, "👤 Маргарита — @Ruma7775\n\nТвоя личная клиентка продюсера (стримерша, мама двоих "
                                      "детей). В боте Нумериты за 7 дней на неё ушло $2,3 нейросети, оплат 0 ⭐ — "
                                      "40% всех расходов бота. Реши: ведём без ограничений или ставим потолок.")
    async def send_brand_video(path, caption):  # ролик «Нумерита шутит» фирменным голосом — владельцу (28.10.2026)
        from aiogram.types import FSInputFile
        for admin_id in cfg.admin_ids:
            sent = await bot.send_video(admin_id, FSInputFile(path), caption=caption, width=1080, height=1080,
                                        supports_streaming=True, request_timeout=180)
            await db.kv_set("brandvideo:file_id", sent.video.file_id)  # чтобы потом выложить без пересылки
    brand_task = asyncio.create_task(brandvideo.run_once(db, generator.api_key, send_brand_video))
    async def send_sketch(data, caption):  # проба рисованных картинок — владельцу (28.10.2026)
        for admin_id in cfg.admin_ids:
            await bot.send_photo(admin_id, BufferedInputFile(data, "numerita_sketch.jpg"), caption=caption[:1024])
    sketch_task = asyncio.create_task(sketch.run_trial(db, generator, send_sketch))
    react_task = asyncio.create_task(tgchannel.run_backfill(db, bot, cfg.telegram_channel))  # реакции на все посты канала
    if await db.claim_slot("owner names kindness 2026-10-28"):  # владелец попросил 1000 названий в Telegram
        await send_long(bot, cfg, (Path(__file__).parent.parent / "docs/drafts/kindness-names-2026-10-28.md").read_text())
    if await db.claim_slot("toc summary"):  # владелец попросил выжимку теории ограничений
        await notify_admins(bot, cfg, constraint.SUMMARY)
    if await db.claim_slot("cost report 2026-10-24"):  # владелец спросил, куда ушли деньги, — отчёт сразу
        try:
            await notify_admins(bot, cfg, await costs.report(db, generator, cfg.timezone))
        except Exception:
            log.exception("Отчёт о расходах не собран")
    if threads is not None:
        try:
            for line in await unpublish_matching(db, threads, UNPUBLISH):
                await notify_admins(bot, cfg, line)
        except Exception:
            log.exception("Снятие неудачных постов не удалось")
    while True:
        try:
            priority_pending = False if text_mode.enabled() else await approved_post.tick(
                db, threads, datetime.now(timezone.utc), lambda text: notify_admins(bot, cfg, text))
            if not priority_pending:
                for post in await db.due():
                    if text_mode.enabled():
                        post = await sharpen_script(db,generator,post)
                    post = await publish(post, db, threads, bot, cfg.telegram_channel, cfg.cards)
                    if post.status == "failed":
                        await notify_admins(bot, cfg, "⚠️ Пост не опубликован\n\n" + post_card(post, cfg), post)
            if plan.enabled and threads is not None and not priority_pending:
                await autopost_tick(bot, cfg, db, threads, generator, plan, rng)
            if cfg.video and not text_mode.enabled() and cfg.fal_key and threads is not None and not priority_pending:
                await video_tick(bot, cfg, db, threads, generator, rng)
        except Exception:
            log.exception("Scheduler iteration failed")
        now = datetime.now(cfg.timezone)
        if threads is not None:
            try:
                await performance.collect(db, threads, now)
                await zero_cleanup.tick(db, threads, now)
            except Exception:
                log.exception("Post performance collection failed")
            try:
                await tgchannel.announce_once(db, bot, cfg.telegram_channel)
                await tgchannel.remove_posts(db, bot, cfg.telegram_channel, [68])  # подпись без картинки, 28.10
                await tgchannel.publish_sent_jokes(db, bot, cfg.telegram_channel, cfg.admin_ids)
                await tgchannel.fix_grid_post(db, bot, cfg.telegram_channel, 64)  # матрица без картинки, 28.10
                problem = await tgchannel.tick(db, bot, cfg.telegram_channel, cfg.timezone)
                if problem and await db.claim_slot(f"tgch error {now.date().isoformat()}"):
                    await notify_admins(bot, cfg, "⚠️ " + problem)
            except Exception:
                log.exception("Telegram channel tick failed")
            if now.minute % 10 == 0 and await db.claim_slot(f"unpub retry {now:%Y-%m-%d %H:%M}"):
                try:
                    for line in await unpublish_matching(db, threads, UNPUBLISH):
                        if "Снят" in line:
                            await notify_admins(bot, cfg, line)
                except Exception:
                    log.exception("Повторное снятие постов не удалось")
            try:  # квитанции Threads — раз в 5 минут, чтобы не тратить запросы API
                if await db.claim_slot(f"grid receipts {now:%Y-%m-%d %H}:{now.minute // 5}"):
                    await confirm_grid_videos(db, threads, bot, cfg)
                    await confirm_heart(db, threads, bot, cfg)
            except Exception:
                log.exception("Проверка поста с сердцем не удалась")
            if await db.claim_slot("grid tonight 2026-10-28"):  # слово владельца: «сегодня перед сном — один пост»
                try:
                    await grid_tonight(db, threads, bot, cfg)
                except Exception:
                    log.exception("Ночная матрица не вышла")
            if await db.claim_slot("heart grid now 2026-10-28"):  # слово владельца: «сердечко — прямо сейчас постом»
                try:
                    await heart_now(db, threads, bot, cfg)
                except Exception:
                    log.exception("Пост с живым сердцем не вышел")
            if await db.claim_slot("day review 2026-10-28"):  # разовый обход дня по просьбе владельца
                try:
                    await notify_admins(bot, cfg, await day_review(db, now))
                except Exception:
                    log.exception("Day review failed")
            try:
                await instagram.tick(db, threads, cfg.timezone, lambda text: notify_admins(bot, cfg, text))
            except Exception:
                log.exception("Instagram tick failed")
        if plan.enabled and now.time() >= OPTIMIZE_AT and await db.claim_slot(f"optimize {now.date().isoformat()}"):
            try:
                report = await optimize(db, threads, generator, plan, now)
                await notify_admins(bot, cfg, "🧠 Отчёт за сутки: что я узнал и что поменял\n\n" + "\n".join(report))
                await notify_admins(bot, cfg, await performance.report(db, now))
                await notify_admins(bot, cfg, await costs.report(db, generator, cfg.timezone))
                tuned = await costs.tune_code_share(db, now)
                if tuned:
                    await notify_admins(bot, cfg, tuned)
            except Exception:
                log.exception("Optimizer failed")
        try:
            for notice in await constraint.run_due(db, generator, now, cfg.timezone):
                await notify_admins(bot, cfg, notice)
        except Exception:
            log.exception("Review scheduler failed")
        if threads is not None and cfg.autoreply and datetime.now() >= next_replies:
            # Первые 15–30 минут решают, покажет ли Threads пост шире: в первый час после поста отвечаем быстрее.
            last = await db.last_published_at()
            fresh = last is not None and datetime.now(cfg.timezone) - last < timedelta(hours=1)
            next_replies = datetime.now() + (FAST_REPLY_INTERVAL if fresh else REPLY_INTERVAL)
            try:
                await answer_comments(db, threads, generator, cfg.autoreply_per_hour, per_run=10,
                                      daily_usd=cfg.reply_budget_usd, ab_model=cfg.reply_ab_model,
                                      ab_share=cfg.reply_ab_share, tz=cfg.timezone)
                await report_autoreply_error(bot, cfg, db)
            except Exception:
                log.exception("Autoreply iteration failed")
            try:
                await redo_code_replies(db, threads, generator, cfg.autoreply_per_hour)
            except Exception:
                log.exception("Redo of code replies failed")
        await asyncio.sleep(30)


