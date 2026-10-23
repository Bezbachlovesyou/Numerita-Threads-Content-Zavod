import asyncio
import logging
import random
from datetime import datetime, time, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .autopost import BOT_LINK, MIN_GAP, ContentPlan, ScriptedPost, Slot, topic_tag_for
from .cards import Card, card_from_text, carousel_from_json, carousel_json, render_card, soul_carousel
from .autoreply import answer_comments
from .optimizer import optimize
from .config import Config
from .generator import GenerationError, Generator
from .storage import PgStorage, Post, Storage
from .threads_api import MAX_LENGTH, ThreadsClient, ThreadsError
from .tts import synthesize

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
    if threads is not None and not post.threads_id:
        try:
            image_urls = await ensure_images(post, db, threads) if cards else []
            threads_id = await threads.publish_text(
                post.text, topic_tag_for(post.rubric), post.first_comment, image_urls
            )
            await db.set_threads_id(post.id, threads_id or "published")
        except ThreadsError as e:
            errors.append(f"Threads: {e}")
    if channel and not post.tg_message_id:
        try:
            sent = await bot.send_message(channel, post.text)
        except TelegramAPIError as e:
            errors.append(f"Telegram-канал {channel}: {e.message}. Бот должен быть админом канала с правом публикации.")
        else:
            await db.set_tg_message_id(post.id, str(sent.message_id))

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


async def notify_admins(bot: Bot, cfg: Config, text: str, post: Post | None = None) -> None:
    for admin_id in cfg.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=post_keyboard(post) if post else None)
        except TelegramAPIError:
            log.exception("Не удалось написать админу %s", admin_id)


CTA_RULES = {
    "link": "Закончи короткой фразой, что полный разбор — по ссылке в первом комментарии (можно 👇). "
            "Саму ссылку и @Numeritabot не пиши: бот добавит ссылку первым комментарием.",
    "reply": "Закончи приглашением ответить в комментариях. Без ссылок и без упоминания бота.",
    "profile": "Закончи фразой, что полный разбор своей даты — по ссылке в профиле. Без ссылок и без упоминания бота.",
    "none": "Без ссылок и без упоминания бота.",
}
REPLY_INTERVAL = timedelta(minutes=5)
FAST_REPLY_INTERVAL = timedelta(minutes=2)
OPTIMIZE_AT = time(4, 10)  # ежедневный разбор рубрик, когда трафик минимальный
RETRY_AFTER_ERROR = timedelta(minutes=15)

# Первый комментарий со ссылкой: ссылка в самом посте снижает его показы в Threads.
FIRST_COMMENTS = [
    "Полный разбор твоей даты — {link}",
    "Твоя личная карточка за 10 секунд 👉 {link}",
    "Узнать своё число души и судьбы: {link}",
    "Разбор по имени и дате, бесплатно для начала ✨ {link}",
]


def first_comment_for(slot: Slot) -> str:
    template = FIRST_COMMENTS[sum(map(ord, slot.tag)) % len(FIRST_COMMENTS)]
    return template.format(link=BOT_LINK + slot.tag)


# Два стиля фразы на картинке — самоулучшение (optimizer.py) смотрит, какой лучше цепляет.
CARD_RULES = {
    "intrigue": (
        "После поста с новой строки напиши «КАРТИНКА: » и фразу для картинки к посту: до 8 слов, без эмодзи, "
        "интрига или узнавание, чтобы захотелось дочитать и ответить. Не повторяй первую строку поста дословно."
    ),
    "question": (
        "После поста с новой строки напиши «КАРТИНКА: » и фразу для картинки к посту: прямой короткий вопрос "
        "к читателю до 8 слов, без эмодзи, на который хочется ответить в комментариях. Не повторяй первую строку поста."
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


async def write_autopost(generator: Generator, slot: Slot, style: str = "intrigue") -> tuple[str, str | None, str]:
    """Текст поста, первый комментарий (для постов со ссылкой) и фраза для картинки."""
    topic = f"{slot.topic}\n\n{CTA_RULES[slot.rubric.cta]}\n\n{CARD_RULES[style]}"
    text, hook = split_card_hook(await generator.write_post(topic))
    if len(text) > MAX_LENGTH:
        text, hook = split_card_hook(
            await generator.write_post(f"{topic} Пиши заметно короче: весь пост до 400 символов.")
        )
    hook = hook or card_from_text(text).hook
    return text, first_comment_for(slot) if slot.rubric.cta == "link" else None, hook


async def post_next(
    bot: Bot, cfg: Config, db: Storage, threads: ThreadsClient | None, generator: Generator,
    plan: ContentPlan, now: datetime, rng: random.Random,
) -> bool:
    """Выпускает следующий пост: готовый текст из очереди (через пост) или новый по рубрике.

    Возвращает False, только если пост не удалось написать (тогда повторим скоро).
    """
    recent = await db.recent_rubrics(6)
    queued = await db.next_queued()
    if queued and (not recent or recent[0] != "script"):
        post = await publish(queued, db, threads, bot, "", cfg.cards)
    else:
        slot = plan.render(plan.choose(recent, rng), now, rng)
        if not await db.claim_slot(slot.key):
            return True
        log.info("Автопост (%s): %s", slot.rubric.key, slot.topic)
        try:
            palette, style = plan.choose_card(rng)
            text, first_comment, hook = await write_autopost(generator, slot, style)
        except GenerationError as e:
            await notify_admins(bot, cfg, f"❌ Автопост не написан: {e}\nТема: {slot.topic}")
            return False
        if slot.rubric.key == "carousel":
            numbers = (generator.knowledge.data or {}).get("numbers", {})
            card_json = carousel_json(soul_carousel(numbers, palette))
        else:
            card_json = Card(
                hook, slot.card_number, slot.card_label, slot.rubric.cta, slot.card_cta_text, palette, style,
                slot.card_dates,
            ).to_json()
        post = await db.get(await db.add_draft(slot.topic, text, slot.rubric.key, first_comment, card_json))
        post = await publish(post, db, threads, bot, "", cfg.cards)
    if post.status == "failed":  # пишем владельцу только о проблемах
        await notify_admins(bot, cfg, "⚠️ Пост не опубликован\n\n" + post_card(post, cfg), post)
    return True


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
    if last is not None and now - last < MIN_GAP:  # пост уже вышел другим путём — выдерживаем паузу
        await db.kv_set("next_post_at", (last + MIN_GAP).isoformat())
        return
    ok = await post_next(bot, cfg, db, threads, generator, plan, now, rng)
    delay = plan.next_gap(now, rng) if ok else RETRY_AFTER_ERROR
    await db.kv_set("next_post_at", (now + delay).isoformat())


async def import_script(db: Storage, script: list[ScriptedPost]) -> int:
    """Ставит готовые тексты в очередь (каждый — один раз). Когда их выпускать, бот решает сам."""
    await db.requeue_scheduled_scripts()
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


async def run_scheduler(
    bot: Bot,
    cfg: Config,
    db: Storage,
    threads: ThreadsClient | None,
    generator: Generator,
    plan: ContentPlan,
) -> None:
    """Раз в 30 секунд: посты по кнопкам «через час», автопостинг; раз в 5 минут — ответы на комментарии."""
    rng = random.Random()
    next_replies = datetime.now()
    while True:
        try:
            for post in await db.due():
                post = await publish(post, db, threads, bot, cfg.telegram_channel, cfg.cards)
                if post.status == "failed":
                    await notify_admins(bot, cfg, "⚠️ Пост не опубликован\n\n" + post_card(post, cfg), post)
            if plan.enabled and threads is not None:
                await autopost_tick(bot, cfg, db, threads, generator, plan, rng)
        except Exception:
            log.exception("Scheduler iteration failed")
        now = datetime.now(cfg.timezone)
        if plan.enabled and now.time() >= OPTIMIZE_AT and await db.claim_slot(f"optimize {now.date().isoformat()}"):
            try:
                report = await optimize(db, threads, generator, plan, now)
                await notify_admins(bot, cfg, "🧠 Самоулучшение за сутки\n\n" + "\n".join(report))
            except Exception:
                log.exception("Optimizer failed")
        if threads is not None and cfg.autoreply and datetime.now() >= next_replies:
            # Первые 15–30 минут решают, покажет ли Threads пост шире: в первый час после поста отвечаем быстрее.
            last = await db.last_published_at()
            fresh = last is not None and datetime.now(cfg.timezone) - last < timedelta(hours=1)
            next_replies = datetime.now() + (FAST_REPLY_INTERVAL if fresh else REPLY_INTERVAL)
            try:
                await answer_comments(db, threads, generator, cfg.autoreply_per_hour, per_run=5)
            except Exception:
                log.exception("Autoreply iteration failed")
        await asyncio.sleep(30)
