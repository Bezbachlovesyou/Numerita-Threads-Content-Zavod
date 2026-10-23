import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

DEFAULT_MODEL = "anthropic/claude-opus-5.5"
DEFAULT_KB_URL = "https://numerita.up.railway.app/kb.json"


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    openrouter_api_key: str
    openrouter_model: str
    zernio_api_key: str
    zernio_account_id: str
    timezone: ZoneInfo
    tts_voice: str
    tts_rate: str
    tts_auto: bool
    db_path: str
    database_url: str
    kb_url: str
    telegram_channel: str
    autopost_times: str
    autopost_channel_times: str
    autoreply: bool
    autoreply_per_hour: int

    @property
    def threads_enabled(self) -> bool:
        return bool(self.zernio_api_key and self.zernio_account_id)


def channel_id(raw: str) -> str:
    """«t.me/name», «https://t.me/name», «name» → «@name»; числовой ID (-100…) оставляем как есть."""
    value = raw.strip().removeprefix("https://").removeprefix("http://").removeprefix("t.me/")
    if not value or value.startswith("@") or value.lstrip("-").isdigit():
        return value
    return "@" + value


def autopost_times(raw: str) -> str:
    from .autopost import DEFAULT_TIMES

    raw = raw.strip()
    if raw.lower() in ("off", "0", "no", "нет"):
        return ""
    return raw or DEFAULT_TIMES


def load_config() -> Config:
    load_dotenv()

    def required(name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise SystemExit(f"Не задана переменная окружения {name} (см. .env.example)")
        return value

    # Принимаем и привычные варианты названия переменной.
    raw_admins = next(
        (os.getenv(n, "").strip() for n in ("ADMIN_IDS", "ADMIN_ID", "ADMIN_TELEGRAM_ID", "TELEGRAM_ID") if os.getenv(n, "").strip()),
        "",
    )
    if not raw_admins:
        raise SystemExit("Не задана переменная окружения ADMIN_IDS — ваш Telegram ID из @userinfobot")
    try:
        admin_ids = frozenset(int(x) for x in raw_admins.replace(" ", "").split(",") if x)
    except ValueError:
        raise SystemExit(f"ADMIN_IDS должен содержать только цифры через запятую, сейчас: {raw_admins!r}")
    return Config(
        bot_token=required("TELEGRAM_BOT_TOKEN"),
        admin_ids=admin_ids,
        openrouter_api_key=required("OPENROUTER_API_KEY"),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL,
        zernio_api_key=os.getenv("ZERNIO_API_KEY", "").strip(),
        zernio_account_id=os.getenv("ZERNIO_ACCOUNT_ID", "").strip(),
        timezone=ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow")),
        tts_voice=os.getenv("TTS_VOICE", "ru-RU-SvetlanaNeural"),
        tts_rate=os.getenv("TTS_RATE", "+100%"),
        tts_auto=os.getenv("TTS_AUTO", "1") == "1",
        db_path=os.getenv("DB_PATH", "zavod.db"),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        # Пустое значение KB_URL отключает базу знаний.
        kb_url=os.getenv("KB_URL", DEFAULT_KB_URL).strip(),
        telegram_channel=channel_id(os.getenv("TELEGRAM_CHANNEL", "")),
        # Время автопостов по TIMEZONE через запятую. По умолчанию каждые 90 минут, «off» — выключить.
        autopost_times=autopost_times(os.getenv("AUTOPOST_TIMES", "")),
        # В какие из этих слотов дублировать пост в Telegram-канал. Пусто — во все.
        autopost_channel_times=os.getenv("AUTOPOST_CHANNEL_TIMES", "").strip(),
        # Автоответы на комментарии в Threads: включены по умолчанию, AUTOREPLY=0 — выключить.
        autoreply=os.getenv("AUTOREPLY", "1") != "0",
        autoreply_per_hour=int(os.getenv("AUTOREPLY_PER_HOUR", "30") or 30),
    )
