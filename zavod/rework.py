"""Переписыватель слабых постов и учёт снятых (слово владельца 02.11.2026: «настоящий автоматический переписыватель слабых постов; перестать делать посты, на которые нет реакции;
убрать то, что не стреляет, менять стили»).

Проблема, которую это закрывает: чистка снимает пост без реакции через 6 ч, а замер «24 ч» к этому времени ещё не готов — снятые посты исчезали из статистики, и завод не видел,
какие рубрики и стили их порождают («выжившие» выглядели лучше, чем есть). Теперь каждое снятие записывается: рубрика, профиль стиля, текст.
1) Статистика рубрик и значений профилей считает снятые как посты с нулевой реакцией → слабое реже, явно слабое (80%+ пустых при 5+ постах) уходит почти из выдачи.
2) Очередь «второго шанса»: снятый пост один раз переписывается новым ходом (другой жанр, голос и хук — значения прежнего профиля исключаются), не чаще раза в 2 часа и не больше 6 в сутки."""

import json
from datetime import datetime, timedelta

KEEP = 500
REWORK_EVERY = timedelta(hours=2)
REWORK_DAILY = 6
ZERO_RATE = 0.8   # доля пустых постов у значения/рубрики, после которой оно почти уходит из выдачи
ZERO_MIN_POSTS = 5
NO_REWORK = {"script", "video", "grid", "jackpot", "carousel", "one_portrait"}


async def _load(db, key: str) -> list:
    return json.loads(await db.kv_get(key) or "[]")


async def record_removed(db, saved: dict, now: datetime) -> None:
    """Записать снятый пост (один раз): в журнал для статистики и в очередь на переписывание."""
    ident = saved.get("id")
    if ident is None:
        return
    removed = await _load(db, "zero:removed")
    if any(r.get("id") == ident for r in removed):
        return
    profile = json.loads(await db.kv_get(f"pm:post:{ident}") or "{}")
    entry = {"id": ident, "rubric": saved.get("rubric"), "ts": (saved.get("published_at") or now.isoformat()),
             "profile": profile, "text": (saved.get("local_text") or saved.get("text") or "")[:700]}
    await db.kv_set("zero:removed", json.dumps((removed + [entry])[-KEEP:], ensure_ascii=False))
    if entry["rubric"] not in NO_REWORK and entry["text"]:
        queue = await _load(db, "rework:queue")
        await db.kv_set("rework:queue", json.dumps((queue + [ident])[-100:]))


async def removed_rows(db, since: datetime) -> list[dict]:
    """Снятые посты как строки статистики с нулевой реакцией (для оптимизатора и обучения профилей)."""
    rows = []
    for r in await _load(db, "zero:removed"):
        try:
            when = datetime.fromisoformat(r["ts"])
        except (ValueError, TypeError, KeyError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=since.tzinfo)
        if when >= since and r.get("rubric"):
            rows.append({"id": r["id"], "rubric": r["rubric"], "likes": 0, "comments": 0, "published_at": r["ts"], "removed": True, "profile": r.get("profile") or {}})
    return rows


async def next_candidate(db, now: datetime, skip=frozenset()) -> dict | None:
    """Следующий снятый пост на переписывание или None (спейсинг 2 ч, не больше 6 в сутки, каждый один раз)."""
    last = await db.kv_get("rework:last")
    if last and now - datetime.fromisoformat(last) < REWORK_EVERY:
        return None
    day = f"rework:day:{now.date().isoformat()}"
    if int(await db.kv_get(day) or 0) >= REWORK_DAILY:
        return None
    queue = await _load(db, "rework:queue")
    removed = {r["id"]: r for r in await _load(db, "zero:removed")}
    for ident in queue:
        row = removed.get(ident)
        if row and row.get("rubric") not in skip:
            return {"id": ident, "rubric": row["rubric"], "text": row["text"], "profile": row.get("profile") or {}, "published_at": row["ts"], "queued": True}
    return None


async def mark_done(db, ident: int, now: datetime) -> None:
    queue = [i for i in await _load(db, "rework:queue") if i != ident]
    await db.kv_set("rework:queue", json.dumps(queue))
    await db.kv_set("rework:last", now.isoformat())
    day = f"rework:day:{now.date().isoformat()}"
    await db.kv_set(day, str(int(await db.kv_get(day) or 0) + 1))


def zero_share(rows: list[dict]) -> float:
    return sum(1 for r in rows if r["comments"] == 0 and r["likes"] <= 2) / len(rows) if rows else 0.0
