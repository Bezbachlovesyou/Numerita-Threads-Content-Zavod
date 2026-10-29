"""Язык экземпляра завода (слово владельца 29.10.2026: отдельный английский аккаунт Threads, всё на английском).

Тот же код запускается вторым сервисом Railway с FACTORY_LANG=en, своим ZERNIO_ACCOUNT_ID (английский Threads),
своей базой и своим Telegram-ботом для отчётов. Публичные тексты (посты, ответы) — на английском; отчёты владельцу
остаются по-русски. Разовые русские задания, канал, Instagram, новости и хайп из русских лент, записки и истории
в английском экземпляре не запускаются. Ссылки ведут в @Numeritabot с меткой ad_en_th_ — бот сразу на английском.
"""

import os

LANG = (os.getenv("FACTORY_LANG", "ru").strip().lower() or "ru")
PUBLIC_KINDS = {"post", "reply", "coherence", "sharpen", "strengthen", "note"}
EN_SKIP_RUBRICS = {"news", "text_hype", "grid", "text_note", "text_story", "text_story_call", "text_court",
                   "text_protocol", "jackpot", "video", "carousel"}
EN_RULE = (
    "\n\nLANGUAGE: Write the final public text in natural, warm, witty American English for an international "
    "English-speaking audience on Threads. The rules and knowledge above are in Russian — use their meaning, never "
    "output Russian words. Adapt humour to English speakers: no Soviet or Russian-only references, no rubles, no "
    "Russian celebrities. Keep numerology honest: a symbolic language, not science or prediction. Use 'you' warmly; "
    "keep the same length limits."
)


def is_en() -> bool:
    return LANG == "en"


def public_rule(kind: str) -> str:
    return EN_RULE if is_en() and kind in PUBLIC_KINDS else ""
