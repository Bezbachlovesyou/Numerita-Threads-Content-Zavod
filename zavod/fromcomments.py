"""Темы из комментариев читателей (слово владельца 03.11.2026: «максимально использую комментарии под постами для новых тем»).
Раз в сутки в дневное окно берём 3–8 настоящих недавних комментариев под нашими постами (без имён и ссылок, без чувствительных тем) и просим написать один пост-ответ на то, что людей
реально волнует. Это не пересказ комментариев: человек не узнаваем, формулировки меняем. Рубрика text_from_comments не выбирается по жребию."""

import re
from datetime import datetime, timedelta, timezone

EVERY = timedelta(hours=20)
HOURS = range(10, 22)
MIN_ITEMS, MAX_ITEMS = 3, 8
URL = re.compile(r"(https?://\S+|t\.me/\S+|@\w+)", re.I)
SENSITIVE = re.compile(r"суицид|умер(ла|ли)?\b|смерт|болезн|рак\b|диагноз|развод|измен|насили|пока(й|йся)|депресс|не хочу жить|kill|suicide|died|cancer", re.I)


def clean(text: str) -> str | None:
    t = URL.sub("", text or "").strip()
    t = re.sub(r"\s+", " ", t)
    if not 15 <= len(t) <= 220 or re.fullmatch(r"[\d\s./:,\-]+", t) or SENSITIVE.search(t):
        return None
    return t


async def sample(db, now: datetime) -> list[str]:
    since = (now - timedelta(days=3)).astimezone(timezone.utc).isoformat()
    out = []
    for row in await db.recent_comments(80):
        if (row.get("created_at") or "") < since:
            continue
        t = clean(row.get("comment") or "")
        if t and t not in out:
            out.append(t)
        if len(out) >= MAX_ITEMS:
            break
    return out if len(out) >= MIN_ITEMS else []


async def due(db, now: datetime) -> bool:
    if now.hour not in HOURS:
        return False
    last = await db.kv_get("fromcomments:last")
    if last and now - datetime.fromisoformat(last) < EVERY:
        return False
    return bool(await sample(db, now))


async def take(db, now: datetime) -> str:
    items = await sample(db, now)
    await db.kv_set("fromcomments:last", now.isoformat())
    return "\n".join(f"— «{t}»" for t in items)
