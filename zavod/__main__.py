import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from datetime import datetime

from .autopost import ContentPlan, load_rubrics, load_script, parse_times
from .bot import COMMANDS, create_router, import_script, run_scheduler
from .config import load_config
from .generator import Generator
from .knowledge import KnowledgeBase
from .storage import PgStorage, Storage
from .threads_api import ThreadsClient

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
VOICE_PROMPT = PROMPTS / "brand_voice.md"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    storage = PgStorage(cfg.database_url) if cfg.database_url else Storage(cfg.db_path)
    await storage.init()
    generator = Generator(cfg.openrouter_api_key, cfg.openrouter_model, VOICE_PROMPT, KnowledgeBase(cfg.kb_url))
    await generator.check_key()
    threads = ThreadsClient(cfg.zernio_api_key, cfg.zernio_account_id) if cfg.threads_enabled else None
    if threads is None:
        logging.warning("Zernio не настроен (ZERNIO_API_KEY, ZERNIO_ACCOUNT_ID): посты будут только сохраняться.")

    bot = Bot(cfg.bot_token)
    dp = Dispatcher()
    dp["db"] = storage
    dp["generator"] = generator
    dp["threads"] = threads
    times = parse_times(cfg.autopost_times)
    plan = ContentPlan(times, parse_times(cfg.autopost_channel_times) or times, load_rubrics(PROMPTS / "content_plan.md"))
    if plan.enabled:
        logging.info("Автопостинг: %s", ", ".join(f"{t:%H:%M}" for t in plan.times))
    script = load_script(PROMPTS / "threads_script.md", cfg.timezone)
    added = await import_script(storage, script, datetime.now(cfg.timezone))
    if added:
        logging.info("Готовых постов поставлено в расписание: %s", added)
    dp.include_router(create_router(cfg, plan))

    scheduler = asyncio.create_task(run_scheduler(bot, cfg, storage, threads, generator, plan))
    try:
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS])
        await dp.start_polling(bot)
    finally:
        scheduler.cancel()


if __name__ == "__main__":
    asyncio.run(main())
