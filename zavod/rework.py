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


# ---- Усилитель удачных постов (слово владельца 03.11.2026: «смотрю, какие темы залетают, и масштабирую: другой угол, другой формат, комментарии как источник тем») ----
HIT_EVERY = timedelta(hours=3)
HIT_DAILY = 2
HIT_MIN_VIEWS, HIT_FACTOR, HIT_COMMENTS, HIT_LIKES = 400, 4.0, 15, 25
HIT_TOPIC = (
    "Этот наш пост сработал лучше обычного: его читали и на него отвечали. Развей тему: напиши НОВЫЙ пост на ту же идею, но с другим углом и в другом формате "
    "(другой жанр, голос и хук из профиля ниже; не повторяй форму, слова и финал старого). Сохрани то, что зацепило: образ, узнавание, вопрос, на который легко ответить.\n"
    "Старый пост (не повторяй его фразы):\n{old}"
)


async def scan_hits(db, now: datetime) -> int:
    """Найти удачные посты за 72 ч и поставить в очередь развития (каждый один раз). Удача: просмотры в 4+ раза выше медианы (и не меньше 400), либо 15+ комментариев, либо 25+ лайков."""
    last = await db.kv_get("hit:scan")
    if last and now - datetime.fromisoformat(last) < timedelta(minutes=30):
        return 0
    await db.kv_set("hit:scan", now.isoformat())
    posts = await db.recent_published(now - timedelta(hours=72))
    samples = []
    for p in posts:
        s = json.loads(await db.kv_get(f"performance:{p.id}:latest") or "{}")
        samples.append((p, s))
    views = sorted(s["views"] for _, s in samples if isinstance(s.get("views"), (int, float)))
    median = views[len(views) // 2] if views else 0
    data = json.loads(await db.kv_get("hit:data") or "{}")
    queue = await _load(db, "hit:queue")
    added = 0
    for p, s in samples:
        if str(p.id) in data or p.rubric in NO_REWORK or not p.text:
            continue
        v, c, l = s.get("views") or 0, s.get("comments") or 0, s.get("likes") or 0
        if (v >= max(HIT_MIN_VIEWS, HIT_FACTOR * median)) or c >= HIT_COMMENTS or l >= HIT_LIKES:
            profile = json.loads(await db.kv_get(f"pm:post:{p.id}") or "{}")
            data[str(p.id)] = {"rubric": p.rubric, "text": p.text[:700], "profile": profile, "views": v, "comments": c, "likes": l, "ts": now.isoformat()}
            queue.append(p.id)
            added += 1
    if added:
        keep = queue[-60:]
        await db.kv_set("hit:data", json.dumps({str(i): data[str(i)] for i in keep if str(i) in data}, ensure_ascii=False))
        await db.kv_set("hit:queue", json.dumps(keep))
    return added


async def next_hit(db, now: datetime, skip=frozenset()) -> dict | None:
    last = await db.kv_get("hit:last")
    if last and now - datetime.fromisoformat(last) < HIT_EVERY:
        return None
    if int(await db.kv_get(f"hit:day:{now.date().isoformat()}") or 0) >= HIT_DAILY:
        return None
    data = json.loads(await db.kv_get("hit:data") or "{}")
    for ident in await _load(db, "hit:queue"):
        row = data.get(str(ident))
        if row and row["rubric"] not in skip:
            return {"id": ident, "rubric": row["rubric"], "text": row["text"], "profile": row.get("profile") or {}, "hit": True}
    return None


async def mark_hit_done(db, ident: int, now: datetime) -> None:
    await db.kv_set("hit:queue", json.dumps([i for i in await _load(db, "hit:queue") if i != ident]))
    await db.kv_set("hit:last", now.isoformat())
    day = f"hit:day:{now.date().isoformat()}"
    await db.kv_set(day, str(int(await db.kv_get(day) or 0) + 1))
