import asyncio
import logging
from datetime import datetime, time, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import Config
from .generator import GenerationError, Generator
from .storage import Post, Storage
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

HELP = (
    "Я контент-завод Numerita для Threads.\n\n"
    "Просто напишите тему, и я пришлю готовый пост с кнопками:\n"
    "✅ опубликовать сейчас, 🕒 запланировать, 🔄 переписать, 🔊 озвучить, 🗑 удалить.\n\n"
    "Команды:\n"
    "/new <тема> — новый пост\n"
    "/queue — черновики и запланированные посты\n"
    "/help — эта справка"
)


class PostAction(CallbackData, prefix="post"):
    action: str  # publish | in1h | tomorrow | redo | voice | delete
    post_id: int


def post_card(post: Post, cfg: Config) -> str:
    header = f"{STATUS_LABELS[post.status]} #{post.id}"
    if post.status == "scheduled" and post.scheduled_at:
        local = post.scheduled_at.astimezone(cfg.timezone)
        header += f" на {local:%d.%m %H:%M}"
    lines = [header, f"Тема: {post.topic}", "", post.text, "", f"{len(post.text)}/{MAX_LENGTH} символов"]
    if post.status == "failed" and post.error:
        lines.append(f"Причина: {post.error}")
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
    button("🔊 Озвучить", "voice")
    if post.status in ("draft", "failed", "scheduled"):
        button("🗑 Удалить", "delete")
    kb.adjust(1, 2, 2, 1)
    return kb.as_markup()


async def publish(post: Post, db: Storage, threads: ThreadsClient | None) -> Post:
    if threads is None:
        await db.mark_failed(post.id, "Threads API не подключён (нет токена в .env).")
    else:
        try:
            threads_id = await threads.publish_text(post.text)
        except ThreadsError as e:
            await db.mark_failed(post.id, str(e))
        else:
            await db.mark_published(post.id, threads_id)
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


def create_router(cfg: Config) -> Router:
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
    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await message.answer(HELP)

    @router.message(Command("new"))
    async def on_new(message: Message, command: CommandObject, db: Storage, generator: Generator) -> None:
        if not command.args:
            await message.answer("Напишите тему после команды, например: /new утренние ритуалы")
            return
        await new_post(message, command.args.strip(), db, generator)

    @router.message(Command("queue"))
    async def on_queue(message: Message, db: Storage) -> None:
        posts = await db.queue()
        if not posts:
            await message.answer("Очередь пуста. Напишите тему, чтобы создать пост.")
            return
        for post in posts:
            await message.answer(post_card(post, cfg), reply_markup=post_keyboard(post))

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
        if action == "voice":
            await callback.answer("Озвучиваю…")
            await send_voice(callback.bot, callback.message.chat.id, post, cfg)
            return

        if action == "publish":
            await callback.answer("Публикую…")
            post = await publish(post, db, threads)
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


async def run_scheduler(bot: Bot, cfg: Config, db: Storage, threads: ThreadsClient | None) -> None:
    """Раз в 30 секунд публикует посты, у которых наступило время."""
    while True:
        try:
            for post in await db.due():
                post = await publish(post, db, threads)
                for admin_id in cfg.admin_ids:
                    await bot.send_message(admin_id, post_card(post, cfg), reply_markup=post_keyboard(post))
        except Exception:
            log.exception("Scheduler iteration failed")
        await asyncio.sleep(30)
