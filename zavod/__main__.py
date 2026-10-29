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
    from .lang import is_en
    if not is_en():  # готовые русские тексты — только русскому аккаунту
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
    if threads is not None and is_en():  # защита: английский завод не должен писать в русский аккаунт
        own = {h.strip().lower().lstrip("@") for h in os.getenv("OWN_HANDLE", "").split(",") if h.strip()}
        try:
            _, payload = await threads._request("GET", "/accounts")
            acc = next((a for a in payload.get("accounts", []) if a.get("_id") == cfg.zernio_account_id), {})
            user = (acc.get("username") or "").lower().lstrip("@")
        except Exception as e:  # не смогли проверить — не публикуем вслепую
            user = ""
            logging.warning("Не удалось проверить аккаунт Zernio: %s", e)
        if not user or user == "numerita.ai" or not own or user not in own:
            logging.error("FACTORY_LANG=en, но ZERNIO_ACCOUNT_ID ведёт на «%s» (OWN_HANDLE=%s) — Threads отключён, "
                          "чтобы английские посты не ушли в русский аккаунт.", user or "?", ",".join(own) or "не задан")
            threads = None

    bot = Bot(cfg.bot_token)
    dp = Dispatcher()
    dp["db"] = storage
    dp["generator"] = generator
    dp["threads"] = threads
    plan = ContentPlan(load_rubrics(PROMPTS / "content_plan.md"), enabled=cfg.autopost)
    plan.bank = [] if is_en() else load_bank(PROMPTS / "jackpot.md")
    await apply_state(storage, plan, datetime.now(cfg.timezone))
    added = 0 if is_en() else await import_script(storage, load_script(PROMPTS / "threads_script.md"))
    if added:
        logging.info("Готовых текстов поставлено в очередь: %s", added)
    dp.include_router(create_router(cfg, plan))

    scheduler = asyncio.create_task(run_scheduler(bot, cfg, storage, threads, generator, plan))
    if os.getenv("ZAVOD_NO_POLLING") == "1":  # английский экземпляр внутри общего сервиса: бот общий, только отчёты
        await scheduler
        return
    try:
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS])
        await dp.start_polling(bot)
    finally:
        scheduler.cancel()


EN_HANDLE_DEFAULT = "numerita.love"


async def zernio_get(path: str, **params) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get("https://zernio.com/api/v1" + path, params=params,
                           headers={"Authorization": f"Bearer {os.getenv('ZERNIO_API_KEY', '').strip()}"})
        r.raise_for_status()
        return r.json()


async def find_en_account(handle: str) -> str:
    """ID английского Threads в Zernio по нику — владельцу не нужно ничего вписывать вручную."""
    data = await zernio_get("/accounts")
    for acc in data.get("accounts", []):
        user = (acc.get("username") or "").lower().lstrip("@")
        if acc.get("platform") == "threads" and user == handle:
            return acc.get("_id") or ""
    return ""


async def english_child() -> None:
    """Слово владельца 29.10.2026: один сервис — два аккаунта Threads. Русский завод запускает рядом английский
    экземпляр отдельным процессом: тот же код, FACTORY_LANG=en, свой аккаунт Zernio (ZERNIO_EN_ACCOUNT_ID или найденный
    по нику EN_OWN_HANDLE, по умолчанию numerita.love), своя схема «en» в той же базе, без опроса Telegram (бот общий —
    отчёты он только шлёт). Пока аккаунт не подключён в Zernio — проверяем раз в 10 минут. Упал — перезапуск с паузой."""
    import sys
    if os.getenv("FACTORY_LANG", "ru").strip().lower() == "en" or not os.getenv("ZERNIO_API_KEY", "").strip():
        return
    handle = (os.getenv("EN_OWN_HANDLE", "").strip().lower().lstrip("@") or EN_HANDLE_DEFAULT)
    account = os.getenv("ZERNIO_EN_ACCOUNT_ID", "").strip()
    while not account:
        try:
            account = await find_en_account(handle)
        except Exception as e:
            logging.warning("Английский Threads в Zernio не проверен: %s", e)
        if not account:
            await asyncio.sleep(600)
    logging.info("Английский завод: аккаунт @%s найден в Zernio, запускаю", handle)
    env = {k: v for k, v in os.environ.items() if k not in ("TELEGRAM_CHANNEL", "ZERNIO_INSTAGRAM_ACCOUNT_ID")}
    env.update(FACTORY_LANG="en", ZERNIO_ACCOUNT_ID=account, OWN_HANDLE=handle,
               DB_SCHEMA="en", DB_PATH="zavod_en.db", ZAVOD_NO_POLLING="1", INSTANCE_LABEL="EN")
    pause = 10
    while True:
        proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "zavod", env=env)
        code = await proc.wait()
        logging.error("Английский завод остановился (код %s), перезапуск через %s с", code, pause)
        await asyncio.sleep(pause)
        pause = min(600, pause * 2)


async def run_all() -> None:
    child = asyncio.create_task(english_child())
    try:
        await main()
    finally:
        child.cancel()


if __name__ == "__main__":
    asyncio.run(run_all())
