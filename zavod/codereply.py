"""Ответ на комментарий с датой рождения — кодом, без нейросети (слово владельца 25.10.2026: «даты в комментариях
считать кодом без ИИ, у нас в базе знаний много всего есть»). Числа считает код, описания — из базы Нумериты (kb.json).
Вопросы («?») и всё, где нет ясной даты или дня рождения, по-прежнему пишет нейросеть."""
from __future__ import annotations

import random
import re

from .knowledge import reduce_number

MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8, "сентябр": 9,
          "октябр": 10, "ноябр": 11, "декабр": 12}
NUM_DATE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)")
WORD_DATE = re.compile(r"(?<!\d)(\d{1,2})\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*"
                       r"(?:\s+(\d{4}))?", re.I)

OPENINGS = ["Какое красивое число!", "Ты в хорошей компании.", "Вот что видно по твоей дате.", "Записала — смотри.",
            "Спасибо, что поделился(-ась)!"]
QUESTIONS = ["Узнаёшь себя?", "Похоже на тебя?", "Отзывается?", "Как думаешь, про тебя?"]


def find_birth(message: str) -> tuple[int, int | None, int | None] | None:
    """(день, месяц, год) из комментария; год и месяц могут быть неизвестны. None — даты нет или она неясна."""
    t = message or ""
    if "?" in t:
        return None
    m = NUM_DATE.search(t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + (1900 if y > 30 else 2000) if y < 100 else y
        if 1 <= d <= 31 and 1 <= mo <= 12 and 1900 <= y <= 2026:
            return d, mo, y
        return None
    m = WORD_DATE.search(t)
    if m:
        d = int(m.group(1))
        mo = next(v for k, v in MONTHS.items() if m.group(2).lower().startswith(k))
        y = int(m.group(3)) if m.group(3) else None
        return (d, mo, y) if 1 <= d <= 31 else None
    if re.search(r"\d\s*(?:лет|год|раз|мин|час|%|кг|см|руб|₽|\$|шт|дн|недел|месяц)", t, re.I):
        return None  # «мне 30 лет», «2 часа» — не день рождения
    nums = re.findall(r"(?<!\d)(\d{1,2})(?!\d)", t)  # один день рождения в короткой реплике: «я 24-го», «6»
    if len(nums) == 1 and len(t.strip()) <= 60 and 1 <= int(nums[0]) <= 31:
        return int(nums[0]), None, None
    return None


PAIR = re.compile(r"^\D{0,40}?(?<!\d)(\d{1,2})(?!\d)(\D{1,12}?)(?<!\d)(\d{1,2})(?!\d)\D{0,40}$")
PAIR_OPEN = ["Вот как ладят ваши числа.", "Интересная пара!", "Посмотрим на вашу пару.", "О, это сочетание с характером."]
PAIR_ASK = ["Похоже на вас?", "Узнаёте свою пару?", "Так и есть?", "Отзывается?"]


def find_pair(message: str) -> tuple[int, int] | None:
    """Два дня рождения в короткой реплике: «6 и 17», «я 24, он 8». Вопросы и длинные тексты — нейросети."""
    t = (message or "").strip()
    if "?" in t or len(t) > 80 or re.search(r"\d\s*(?:лет|год|раз|мин|час|%|кг|см|руб|₽|\$)", t, re.I):
        return None
    m = PAIR.match(t)
    if not m:
        return None
    if re.fullmatch(r"\s*[./-]\s*", m.group(2)):  # «15.03» — это день и месяц, а не пара
        return None
    a, b = int(m.group(1)), int(m.group(3))
    return (a, b) if 1 <= a <= 31 and 1 <= b <= 31 else None


def pair_reply(message: str, kb: dict | None, seed: int = 0) -> str | None:
    """Совместимость пары по дням рождения — из базы Нумериты (pairs), без нейросети."""
    pair = find_pair(message)
    pairs = (kb or {}).get("pairs") or {}
    if not pair or not pairs:
        return None
    x, y = sorted((reduce_number(pair[0]), reduce_number(pair[1])))
    p = pairs.get(f"{x}-{y}")
    if not p:
        return None
    rnd = random.Random(seed)
    parts = [rnd.choice(PAIR_OPEN), f"{pair[0]} → {reduce_number(pair[0])} и {pair[1]} → {reduce_number(pair[1])}.",
             _first_sentence(p.get("how", "")), f"Сила: {_first_sentence(p.get('plus', '')).rstrip('.').lower()}.",
             f"Ключ: {_first_sentence(p.get('key', '')).rstrip('.').lower()}.", rnd.choice(PAIR_ASK)]
    text = " ".join(x for x in parts if x and x not in ("Сила: .", "Ключ: ."))
    while len(text) > 380 and len(parts) > 4:
        parts.pop(2)
        text = " ".join(parts)
    return text


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s", (text or "").strip(), maxsplit=1)[0]


def reply(message: str, kb: dict | None, seed: int = 0) -> str | None:
    """Готовый ответ до ~300 знаков или None, если кодом не ответить (нет даты или базы)."""
    birth = find_birth(message)
    numbers = (kb or {}).get("numbers") or {}
    if not birth or not numbers:
        return None
    day, month, year = birth
    soul = reduce_number(day)
    s = numbers.get(str(soul))
    if not s:
        return None
    rnd = random.Random(seed)
    parts = [rnd.choice(OPENINGS),
             f"Число души {soul} — {s.get('name', '')}: {s.get('qualities', '')}."]
    nature = _first_sentence(s.get("nature", ""))
    if nature and len(nature) < 140:
        parts.append(nature)
    if month and year:
        total = sum(int(c) for c in f"{day}{month}{year}")
        dest = reduce_number(total)
        d = numbers.get(str(dest))
        if d:
            parts.append(f"А миссия {dest} ({total} → {dest}) — {d.get('qualities', '')}.")
    parts.append(rnd.choice(QUESTIONS))
    text = " ".join(p for p in parts if p).replace("  ", " ")
    while len(text) > 320 and len(parts) > 3:  # длинное — без описания характера
        parts.pop(2)
        text = " ".join(parts)
    return text


def numbers_note(message: str) -> str:
    """Для ответа нейросети: числа уже посчитаны кодом — модель не считает сама и не ошибается."""
    birth = find_birth(message.replace("?", ""))
    if not birth:
        return ""
    day, month, year = birth
    note = f"Посчитано кодом: число души {reduce_number(day)} (день {day})"
    if month and year:
        total = sum(int(c) for c in f"{day}{month}{year}")
        note += f", миссия (судьба) {reduce_number(total)} ({total} → {reduce_number(total)})"
    return note + ". Используй эти числа, сам не пересчитывай.\n\n"
