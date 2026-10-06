import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher

from .bot import create_router, run_scheduler
from .config import load_config
from .generator import Generator
from .storage import Storage
from .threads_api import ThreadsClient

VOICE_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "brand_voice.md"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    storage = Storage(cfg.db_path)
    await storage.init()
    generator = Generator(cfg.anthropic_api_key, VOICE_PROMPT)
    threads = ThreadsClient(cfg.threads_user_id, cfg.threads_access_token) if cfg.threads_enabled else None
    if threads is None:
        logging.warning("Threads API не настроен: посты будут только сохраняться.")

    bot = Bot(cfg.bot_token)
    dp = Dispatcher()
    dp["db"] = storage
    dp["generator"] = generator
    dp["threads"] = threads
    dp.include_router(create_router(cfg))

    scheduler = asyncio.create_task(run_scheduler(bot, cfg, storage, threads))
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.cancel()


if __name__ == "__main__":
    asyncio.run(main())
