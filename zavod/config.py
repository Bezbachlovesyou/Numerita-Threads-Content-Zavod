import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    anthropic_api_key: str
    threads_user_id: str
    threads_access_token: str
    timezone: ZoneInfo
    tts_voice: str
    tts_rate: str
    tts_auto: bool
    db_path: str

    @property
    def threads_enabled(self) -> bool:
        return bool(self.threads_user_id and self.threads_access_token)


def load_config() -> Config:
    load_dotenv()

    def required(name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise SystemExit(f"Не задана переменная окружения {name} (см. .env.example)")
        return value

    admin_ids = frozenset(
        int(x) for x in required("ADMIN_IDS").replace(" ", "").split(",") if x
    )
    return Config(
        bot_token=required("TELEGRAM_BOT_TOKEN"),
        admin_ids=admin_ids,
        anthropic_api_key=required("ANTHROPIC_API_KEY"),
        threads_user_id=os.getenv("THREADS_USER_ID", "").strip(),
        threads_access_token=os.getenv("THREADS_ACCESS_TOKEN", "").strip(),
        timezone=ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow")),
        tts_voice=os.getenv("TTS_VOICE", "ru-RU-SvetlanaNeural"),
        tts_rate=os.getenv("TTS_RATE", "+100%"),
        tts_auto=os.getenv("TTS_AUTO", "1") == "1",
        db_path=os.getenv("DB_PATH", "zavod.db"),
    )
