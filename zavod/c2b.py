"""Метрика «из комментариев в бота» (слово владельца 20.11.2026: «введём процент людей, перешедших в бота с комментариев,
и будем работать над её возрастанием»).

Доля = пришли в бота по ссылкам из наших ответов (метки ответов th_r<пост>_…, данные бота) / разные люди, оставившие комментарий
(comment_replies, без своих аккаунтов) за те же 7 дней. Промежуточное звено — сколько комментаторов вообще получили ссылку.
Разрез по вариантам ответа: стиль e «живой» / n «обычный», лестница (l, m) / прежний (o, w) — чтобы растить то, что ведёт.
Каждый день значение пишется в историю (kv c2b:<дата>) — видно, растёт ли. Владельцу — одна строка в вечерней сводке (digest.py)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

DAYS = 7
REPLY_LABEL = re.compile(r"^th_r(?P<post>\d+)_(?P<letter>[aowlm])(?P<arm>[a-z]*)$")
GROUPS = {"o": "прежний", "w": "прежний", "l": "лестница", "m": "лестница", "a": "по просьбе"}
STYLES = {"e": "живой", "n": "обычный"}


def _own() -> set[str]:
    from .autopost import OWN_HANDLES
    return {h.lower().lstrip("@") for h in OWN_HANDLES} | {"numerita.love"}


async def commenters(db, since: datetime) -> tuple[int, int]:
    """(разных комментаторов, из них получили ссылку на бота в нашем ответе)."""
    rows = await db._rows("SELECT author, reply, status FROM comment_replies WHERE created_at >= ?",
                          (since.astimezone(timezone.utc).isoformat(),))
    own = _own()
    people, linked = set(), set()
    for r in rows:
        author = str(r["author"] or "").lower().lstrip("@")
        if not author or author in own:
            continue
        people.add(author)
        if r["status"] == "replied" and "t.me/numeritabot" in str(r["reply"] or "").lower():
            linked.add(author)
    return len(people), len(linked)


def arrivals(data: dict | None) -> dict:
    """Пришли по меткам ответов: всего и по вариантам. data — funnel.fetch() (метки своего языка в виде th_…)."""
    out = {"came": 0, "paid": 0, "by_group": {}, "by_style": {}}
    for r in (data or {}).get("labels", []):
        m = REPLY_LABEL.match(str(r.get("label", "")).lower())
        if not m:
            continue
        came, paid = int(r.get("came") or 0), int(r.get("paid") or 0)
        out["came"] += came
        out["paid"] += paid
        g = GROUPS.get(m["letter"], m["letter"])
        out["by_group"][g] = out["by_group"].get(g, 0) + came
        s = STYLES.get(m["arm"][:1]) if m["arm"] else None
        if s:
            out["by_style"][s] = out["by_style"].get(s, 0) + came
    return out


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


async def measure(db, now: datetime, data: dict | None) -> dict:
    people, linked = await commenters(db, now - timedelta(days=DAYS))
    a = arrivals(data)
    return {"date": now.date().isoformat(), "people": people, "linked": linked, "came": a["came"], "paid": a["paid"],
            "rate": pct(a["came"], people), "link_rate": pct(linked, people), "by_group": a["by_group"], "by_style": a["by_style"],
            "has_bot_data": data is not None}


async def record(db, now: datetime, m: dict) -> None:
    await db.kv_set(f"c2b:{m['date']}", json.dumps(m, ensure_ascii=False))


async def past(db, now: datetime, days_ago: int = 7) -> dict | None:
    raw = await db.kv_get(f"c2b:{(now - timedelta(days=days_ago)).date().isoformat()}")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:.1f}".replace(".", ",") + "%"


def line(m: dict, prev: dict | None = None) -> str:
    """Одна строка для владельца (термин поясняем сразу)."""
    if not m["has_bot_data"]:
        return f"📈 Из комментариев в бота: нет данных бота; комментаторов за 7 дней — {m['people']}, ссылку получили {m['linked']}."
    trend = ""
    if prev and prev.get("rate") is not None and m["rate"] is not None:
        diff = m["rate"] - prev["rate"]
        trend = f", неделю назад {_fmt(prev['rate'])} ({'▲' if diff > 0 else '▼' if diff < 0 else '='})"
    return (f"📈 Из комментариев в бота: {_fmt(m['rate'])} — {m['came']} из {m['people']} комментаторов за 7 дней{trend}; "
            f"ссылку получили {_fmt(m['link_rate'])}.")


def best_arm(m: dict) -> str | None:
    """Какой вариант ответа ведёт больше (для сессий и обходов): «живой»/«обычный», «лестница»/«прежний»."""
    parts = []
    for key in ("by_style", "by_group"):
        d = m.get(key) or {}
        if len(d) >= 2 and sum(d.values()) >= 5:
            parts.append(max(d, key=d.get))
    return ", ".join(parts) or None
