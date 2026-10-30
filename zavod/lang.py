"""Язык экземпляра завода (слово владельца 29.10.2026: отдельный английский аккаунт Threads, всё на английском).

Тот же код запускается вторым сервисом Railway с FACTORY_LANG=en, своим ZERNIO_ACCOUNT_ID (английский Threads),
своей базой и своим Telegram-ботом для отчётов. Публичные тексты (посты, ответы) — на английском; отчёты владельцу
остаются по-русски. Разовые русские задания, канал, Instagram, новости и хайп из русских лент, записки и истории
в английском экземпляре не запускаются. Ссылки ведут в @Numeritabot с меткой ad_en_th_ — бот сразу на английском.
"""

import os
import re

LANG = (os.getenv("FACTORY_LANG", "ru").strip().lower() or "ru")
PUBLIC_KINDS = {"post", "reply", "coherence", "sharpen", "strengthen", "note"}
EN_SKIP_RUBRICS = {"news", "text_hype", "text_note", "text_story", "text_story_call", "text_court",
                   "text_protocol", "jackpot", "video", "carousel"}
EN_RULE = (
    "\n\nLANGUAGE: Write the final public text in natural, warm, witty American English for an international "
    "English-speaking audience on Threads. The rules and knowledge above are in Russian — use their meaning, never "
    "output Russian words. Adapt humour to English speakers: no Soviet or Russian-only references, no rubles, no "
    "Russian celebrities. Humour for native speakers: relatable 'POV / me when', deadpan understatement, "
    "self-irony, rule of three with a twist, specific details, one line — one punch (see the English humour section "
    "of the playbook). Style of the masters: Wilde's paradox, Twain's and Seinfeld's observation with the punch on the "
    "last word, Wodehouse's precise unexpected comparisons, deadpan logic shifts. Literary, contemporary, crisp English "
    "— no excess slang ('lowkey', 'slay', 'bestie'). Keep numerology honest: a symbolic language, not science or prediction. Use 'you' warmly; "
    "keep the same length limits. "
    "ZERO Russian: not a single Cyrillic letter, Russian word, transliteration or Russian quote marks «» anywhere. "
    "Native-level English, as if written by a sharp English-speaking columnist: correct articles, tenses and "
    "prepositions; no word-for-word translations of Russian idioms or calques ('make a conclusion', 'on the photo', "
    "'it is necessary to', 'dear friends'); no clumsy or inappropriate jokes. First line — a hook with intrigue; "
    "then real value (a recognisable insight, a useful idea); topical humour of today's best comedians and writers."
)
CYRILLIC = re.compile(r"[\u0400-\u04FF«»]")
EN_EDITOR = (
    "You are a native English copy editor for a witty Threads account (numerology as a symbolic, playful language). "
    "Check the post: grammar, articles, tenses, idiom, natural rhythm, any Russian words or letters, Russian-sounding "
    "calques, jokes that land badly in English, a weak first line. If it already reads like a sharp native writer — "
    "answer exactly OK. Otherwise return only the corrected post: same meaning, numbers, birth days and length, "
    "a hook in the first line, no Cyrillic, no hashtags, no new facts.")


def is_en() -> bool:
    return LANG == "en"


def public_rule(kind: str) -> str:
    return EN_RULE if is_en() and kind in PUBLIC_KINDS else ""


def has_cyrillic(text: str | None) -> bool:
    return bool(text) and bool(CYRILLIC.search(text))
