"""Тихий режим для владельца (слово владельца 20.11.2026: «к утру уже 7 сообщений — крыша съедет; работа должна быть автономной»).

Служебные сообщения завода (квитанции, отчёты, обходы, «пост не вышел») владельцу сразу не идут: копятся и приходят
одной короткой сводкой раз в день (DIGEST_AT по времени бота), по строке на тему, повторы схлопнуты.
Сразу приходит только то, где нужно его решение: метка ‼️ (необратимое, деньги, минус сверх потолка) или 🆘.
Полный текст каждого сообщения по-прежнему уходит в журнал для сессий (bot._mirror_log) — сессии видят всё.
Пульт: notify_live — снова всё сразу; notify_digest — тихий режим (по умолчанию).
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, time

URGENT_MARKS = ("‼️", "🆘")
DIGEST_AT = time(19, 30)  # до 21:00, когда владельца пора отправлять спать
MAX_LINES = 6  # слово владельца 05.11: 3–6 коротких строк
LINE_LIMIT = 170
KV_BUF = "digest:buf"
KV_MODE = "notify:mode"

_buf: list[str] | None = None
_lock = asyncio.Lock()
PRIORITY = ("⚠️", "⛔", "💸", "❌")  # проблемы — первыми строками сводки


def is_urgent(text: str) -> bool:
    return any(mark in (text or "") for mark in URGENT_MARKS)


def headline(text: str) -> str:
    """Первая содержательная строка без разметки, обрезанная по границе предложения или слова."""
    from .constraint import short
    plain = re.sub(r"<[^>]+>", "", text or "")
    plain = re.sub(r"^\[[A-Z]{2}\]\s*", "", plain.strip())
    first = next((line.strip() for line in plain.splitlines() if line.strip()), "")
    return short(first, LINE_LIMIT)


async def live(db) -> bool:
    return (await db.kv_get(KV_MODE)) == "live"


async def _load(db) -> list[str]:
    global _buf
    if _buf is None:
        try:
            _buf = json.loads(await db.kv_get(KV_BUF) or "[]")
        except (TypeError, ValueError):
            _buf = []
    return _buf


async def add(db, text: str) -> None:
    async with _lock:
        buf = await _load(db)
        line = headline(text)
        if line:
            buf.append(line)
            del buf[:-300]  # потолок памяти: старьё не копим
            await db.kv_set(KV_BUF, json.dumps(buf, ensure_ascii=False))


def build(lines: list[str]) -> str:
    counts: dict[str, int] = {}
    for line in lines:
        counts[line] = counts.get(line, 0) + 1
    ordered = sorted(counts, key=lambda l: (not l.startswith("📈"), not l.startswith(PRIORITY), lines.index(l)))  # главная метрика — первой
    shown = [f"{l} (×{counts[l]})" if counts[l] > 1 else l for l in ordered[:MAX_LINES]]
    rest = len(ordered) - len(shown)
    word = "мелочь" if rest % 10 == 1 and rest % 100 != 11 else "мелочи" if rest % 10 in (2, 3, 4) and rest % 100 not in (12, 13, 14) else "мелочей"
    tail = [f"…и ещё {rest} {word} — они в журнале, сессия их видит."] if rest > 0 else []
    return "🌙 Завод за день — всё идёт само:\n" + "\n".join(shown + tail)


async def due(db, now: datetime) -> str | None:
    """Текст сводки, если пора (раз в день после DIGEST_AT) и есть что сказать; буфер очищается."""
    if now.time() < DIGEST_AT:
        return None
    async with _lock:
        buf = await _load(db)
        if not buf or not await db.claim_slot(f"digest {now.date().isoformat()}"):
            return None
        text = build(buf)
        buf.clear()
        await db.kv_set(KV_BUF, "[]")
        return text
