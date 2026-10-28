import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from datetime import datetime, timezone

from .autopost import ContentPlan, load_bank, load_rubrics, load_script
from .bot import COMMANDS, create_router, import_script, run_scheduler
from .costs import make_sink
from . import funnel
from .config import load_config
from .generator import Generator
from .knowledge import KnowledgeBase
from .optimizer import apply_state
from .storage import PgStorage, Storage
from .threads_api import ThreadsClient

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
VOICE_PROMPT = PROMPTS / "brand_voice.md"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    storage = PgStorage(cfg.database_url) if cfg.database_url else Storage(cfg.db_path)
    await storage.init()
    from . import text_mode
    if text_mode.enabled() and not await storage.kv_get('experiment:text-only:started_at'):
        await storage.kv_set('experiment:text-only:started_at',datetime.now(timezone.utc).isoformat())
    await text_mode.seed(storage)
    await text_mode.seed_apology(storage)
    generator = Generator(cfg.openrouter_api_key, cfg.openrouter_model, VOICE_PROMPT, KnowledgeBase(cfg.kb_url))
    generator.cost_sink = make_sink(storage, cfg.timezone)
    funnel.KEY = os.getenv("NUMERITA_THREADS_KEY", "").strip()
    generator.reply_model = cfg.reply_model
    if not await storage.kv_get("reply_ab_since"):
        await storage.kv_set("reply_ab_since", datetime.now(timezone.utc).isoformat())
    generator.reply_ab_model, generator.reply_ab_share = cfg.reply_ab_model, cfg.reply_ab_share
    await generator.check_key()
    threads = ThreadsClient(cfg.zernio_api_key, cfg.zernio_account_id, storage) if cfg.threads_enabled else None
    if threads is None:
        logging.warning("Zernio не настроен (ZERNIO_API_KEY, ZERNIO_ACCOUNT_ID): посты будут только сохраняться.")

    bot = Bot(cfg.bot_token)
    dp = Dispatcher()
    dp["db"] = storage
    dp["generator"] = generator
    dp["threads"] = threads
    plan = ContentPlan(load_rubrics(PROMPTS / "content_plan.md"), enabled=cfg.autopost)
    plan.bank = load_bank(PROMPTS / "jackpot.md")
    await apply_state(storage, plan, datetime.now(cfg.timezone))
    added = await import_script(storage, load_script(PROMPTS / "threads_script.md"))
    if added:
        logging.info("Готовых текстов поставлено в очередь: %s", added)
    dp.include_router(create_router(cfg, plan))

    scheduler = asyncio.create_task(run_scheduler(bot, cfg, storage, threads, generator, plan))
    try:
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS])
        await dp.start_polling(bot)
    finally:
        scheduler.cancel()


if __name__ == "__main__":
    asyncio.run(main())
