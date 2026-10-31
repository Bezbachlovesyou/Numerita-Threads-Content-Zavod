"""Вся цепочка от поста до оплаты одним расчётом кодом (слово владельца 31.10.2026: «пост, переход, запуск бота, оплата —
в одну цепочку, всё время по Голдратту искать слабое место; оптимизировать надо оплаты, а не только лайки и охваты»).

Звенья: посты → просмотры → люди, ответившие под постами → наши ответы → ответы со ссылкой → пришли в бота → новые →
«вау» → вернулись → оплатили. Конверсии считаются кодом, нейросеть получает готовые цифры, а не пересказ.
Малая выборка не равна нулю: звено с малой выборкой помечается «мало данных» и узким не объявляется.
Срез каждого обхода сохраняется в базе (история для сравнения недель)."""

import json
import re
from datetime import datetime, timedelta, timezone

from . import funnel

# Минимум людей/событий в знаменателе, чтобы считать звено узким (иначе это шум).
MIN_BASE = {"views": 300, "people": 10, "came": 10, "new": 5, "wow": 5, "returned": 3}
TOTAL_KEYS = ("came", "new", "wow", "returned", "paid", "stars")
# Необязательные поля, которые основной бот может отдавать по меткам (docs/handoff-main-bot-threads-map.md): выручка и подписки.
EXTRA_KEYS = ("subs_new", "subs_active", "renewed", "refunds")
TAG_RE = re.compile(r"^th_(?P<rubric>[a-z_]+?)\d_\d{4}")  # метка поста: рубрика + число души + ДДММ (+ способ подачи ссылки)


def by_rubric(data: dict | None) -> dict[str, dict]:
    """Итоги по рубрикам из меток постов (th_<рубрика><цифра>_<ДДММ>…); ответы, шапка и прочее сюда не входят."""
    out: dict[str, dict] = {}
    for r in (data or {}).get("labels", []):
        m = TAG_RE.match(str(r.get("label", "")))
        if not m:
            continue
        row = out.setdefault(m["rubric"], {"came": 0, "new": 0, "paid": 0, "stars": 0})
        for k in row:
            row[k] += int(r.get(k) or 0)
    return out

# Ориентиры доли по звеньям — ДОПУЩЕНИЯ (не измерения), чтобы сравнивать звено с ожидаемым, а не звенья друг с другом:
# наверху воронки доли всегда малы, внизу большие. Уточняются по истории срезов (chain:<дата>:<час>), когда накопится выборка.
REF = {"views_people": 0.005, "views_came": 0.001, "came_new": 0.8, "new_wow": 0.5, "wow_returned": 0.3, "returned_paid": 0.1}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def collect(db, now: datetime, days: int = 7) -> dict:
    """Цифры цепочки за days суток. None — данных нет (это не ноль)."""
    since = _iso(now - timedelta(days=days))
    posts = await db._rows("SELECT COUNT(*) AS n FROM posts WHERE status='published' AND published_at >= ?", (since,))
    views = await db._rows(
        "SELECT SUM(m.impressions) AS v, COUNT(*) AS k FROM posts p JOIN post_metrics m ON m.post_id = p.id "
        "WHERE p.status='published' AND p.published_at >= ? AND m.impressions > 0", (since,))
    people = await db._rows("SELECT COUNT(DISTINCT author) AS n FROM dialogue_messages WHERE role='user' AND created_at >= ?", (since,))
    replies = await db._rows("SELECT COUNT(*) AS n FROM comment_replies WHERE status='replied' AND created_at >= ?", (since,))
    linked = await db._rows("SELECT COUNT(*) AS n FROM comment_replies WHERE status='replied' AND reply LIKE ? AND created_at >= ?",
                            ("%t.me/%", since))
    data = await funnel.fetch(days)
    bot = None
    if data:
        rows = [r for r in data.get("labels", []) if str(r.get("label", "")).startswith("th_")]
        bot = {k: sum(int(r.get(k) or 0) for r in rows) for k in TOTAL_KEYS}
        bot["usd"] = sum(float(r.get("usd") or 0) for r in rows)  # если основной бот отдаёт выручку в долларах (см. записку для бота)
        bot["rub"] = sum(float(r.get("rub") or 0) for r in rows)
        for k in EXTRA_KEYS:  # подписки и возвраты, если бот их отдаёт; нет поля — None (неизвестно, не ноль)
            bot[k] = sum(int(r.get(k) or 0) for r in rows) if any(k in r for r in rows) else None
    v = int(views[0]["v"] or 0) if views and views[0]["k"] else None
    return {"days": days, "posts": int(posts[0]["n"]), "views": v, "views_posts": int(views[0]["k"] or 0) if views else 0,
            "people": int(people[0]["n"]), "replies": int(replies[0]["n"]), "linked": int(linked[0]["n"]), "bot": bot,
            "rubrics": by_rubric(data)}


def transitions(c: dict) -> list[dict]:
    """Переходы между звеньями: имя, числитель, знаменатель, доля, хватает ли выборки."""
    out = []

    def add(name, num, den, key, ref):
        if den is None or num is None:
            out.append({"name": name, "num": num, "den": den, "rate": None, "ref": REF[ref], "ratio": None, "enough": False})
            return
        rate = num / den if den else None
        out.append({"name": name, "num": num, "den": den, "rate": rate, "ref": REF[ref],
                    "ratio": rate / REF[ref] if rate is not None else None, "enough": den >= MIN_BASE[key]})

    add("просмотры → люди, ответившие под постами", c["people"], c["views"], "views", "views_people")
    bot = c["bot"]
    add("просмотры → пришли в бота", bot["came"] if bot else None, c["views"], "views", "views_came")
    add("пришли → новые", bot["new"] if bot else None, bot["came"] if bot else None, "came", "came_new")
    add("новые → «вау»", bot["wow"] if bot else None, bot["new"] if bot else None, "new", "new_wow")
    add("«вау» → вернулись", bot["returned"] if bot else None, bot["wow"] if bot else None, "wow", "wow_returned")
    add("вернулись → оплатили", bot["paid"] if bot else None, bot["returned"] if bot else None, "returned", "returned_paid")
    return out


def weakest(c: dict) -> dict:
    """Узкое звено по цифрам (без нейросети): самая низкая доля относительно ориентира среди звеньев с достаточной выборкой.
    Нет достаточной выборки нигде — узкое звено само измерение (данных мало или бот не отдаёт цифры)."""
    if c["bot"] is None:
        return {"link": "нет данных из бота Нумериты — не видим пути после перехода", "kind": "data", "rate": None}
    ts = transitions(c)
    rows = [(i, t) for i, t in enumerate(ts) if t["enough"] and t["ratio"] is not None]
    if not rows:
        return {"link": "данных для вывода мало: выборка в каждом звене ниже порога", "kind": "sample", "rate": None}
    # Для Голдратта важна пропускная способность к оплатам: при равных долях берём звено ближе к оплате.
    _, t = min(rows, key=lambda r: (r[1]["ratio"], -r[0]))
    return {"link": t["name"], "kind": "rate", "rate": t["rate"], "ref": t["ref"], "num": t["num"], "den": t["den"]}


def _pct(t: dict) -> str:
    if t["rate"] is None:
        return "нет данных"
    return (f"{t['rate'] * 100:.1f}% ({t['num']} из {t['den']}), ориентир {t['ref'] * 100:g}%"
            + ("" if t["enough"] else ", мало данных"))


def lines(c: dict) -> list[str]:
    bot = c["bot"]
    head = (f"цепочка за {c['days']} дн.: постов {c['posts']}, просмотров "
            + (f"{c['views']} (по {c['views_posts']} постам)" if c["views"] is not None else "нет данных")
            + f", людей в комментариях {c['people']}, наших ответов {c['replies']}, из них со ссылкой {c['linked']}")
    out = [head]
    if bot:
        out.append(f"в боте: пришли {bot['came']}, новые {bot['new']}, «вау» {bot['wow']}, вернулись {bot['returned']}, "
                   f"оплатили {bot['paid']}" + (f" ({bot['stars']} ⭐)" if bot["stars"] else ""))
    if bot and bot.get("subs_active") is not None:
        out.append(f"подписки: новых {bot.get('subs_new') or 0}, активных {bot['subs_active']}, продлений {bot.get('renewed') or 0}"
                   + (f", возвратов {bot['refunds']}" if bot.get("refunds") else ""))
    out += [f"  {t['name']}: {_pct(t)}" for t in transitions(c)]
    top = sorted((c.get("rubrics") or {}).items(), key=lambda kv: (-kv[1]["paid"], -kv[1]["came"]))[:4]
    if top:
        out.append("по рубрикам с ссылкой (метка поста): " + ", ".join(
            f"{k} — пришли {v['came']}, оплатили {v['paid']}" for k, v in top))
    w = weakest(c)
    out.append("узкое звено по цифрам: " + w["link"] + (f" — {w['rate'] * 100:.1f}% при ориентире {w['ref'] * 100:g}%" if w.get("rate") is not None else ""))
    if c["replies"]:
        out.append(f"ценность на касание: ответов со ссылкой {c['linked'] / c['replies'] * 100:.0f}% "
                   f"(остальные — польза без приглашения)")
    return out


async def snapshot(db, now: datetime, c: dict) -> None:
    """Срез обхода в историю: chain:<дата>:<час>."""
    await db.kv_set(f"chain:{now.date().isoformat()}:{now.hour}", json.dumps(c, ensure_ascii=False))
