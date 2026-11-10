"""Каркас атрибуции — незыблемый (слово владельца 31.10.2026): всегда должно быть видно, какая рубрика и какой тип контента на какой площадке
ведёт сколько людей в бота и с какими параметрами (пришли, «вау», вернулись, оплатили), чтобы развивать то, что ведёт, а узкое звено
объявлять по данным, а не по ощущению. Нельзя сказать «рубрика Х лучшая», если не видно, из скольких постов, комментариев и людей это.

Метка ссылки на бота — единственный мост «контент → человек в боте». Правила каркаса:
1. Каждая ссылка на бота несёт метку `ad_[en_]<площадка>_<что>`; площадка — из PLATFORMS (новая площадка = запись здесь + метка bio в STATIC).
2. Метки разбирает только parse(): площадка, язык, вид (пост / ответ / шапка / закреп / канал / прочее), рубрика, номер поста, вариант.
3. Метка ответа несёт номер поста (th_r<id>), поэтому ответ-ссылка привязывается к рубрике через базу; метка поста несёт рубрику прямо;
   шапка и закреп привязать к рубрике нельзя — они считаются отдельно и открыто («не привязано X% пришедших»).
4. Для охвата измерением каждая рубрика получает ссылки первым комментарием с меткой (needs_tracking), пока выборка мала.
5. Контрактный тест (tests/test_attribution.py) просматривает код: новая ссылка с неизвестной меткой ломает тест, пока её не зарегистрируют."""

import re
from datetime import datetime, timedelta, timezone

PLATFORMS = {"th": "Threads", "ig": "Instagram", "tg": "Telegram-канал", "fb": "Facebook", "yt": "YouTube", "tt": "TikTok"}
# Статические метки (не рубрика и не пост): имя → (площадка, что это). Новая статическая метка без записи здесь ломает контрактный тест.
STATIC = {
    "bio": ("th", "шапка профиля"), "pin": ("th", "закреп профиля"), "story": ("th", "серия историй"), "cities": ("th", "серия «Город силы»"),
    "gaz": ("th", "ролик «Газ»"), "code": ("th", "приветственный ролик «Твой код»"), "angel": ("th", "приветственный ролик «Ангел»"),
    "pair": ("th", "«Пара недели» (первый комментарий)"), "game_redflag": ("th", "игра «Красный или зелёный?» вдвоём"), "values": ("tg", "канал: ценности Нумериты"), "reel": ("tg", "канал: ролик с новостью"), "school": ("tg", "канал: школа астрологии"), "tgasc": ("tg", "канал: пост про асцендент"), "tgwelcome": ("tg", "канал: приветствие"), "tgnew": ("tg", "анонс в канале"), "tgjokes": ("tg", "шутки в канале"), "tgvid": ("tg", "видео в канале"), "tggaz": ("tg", "«Газ» в канале"),
}
STATIC_PREFIXES = ("gift",)  # персональные подарки: gift<nonce><подпись>
PER_PLATFORM_BIO = {p: f"ad_{p}_bio" for p in PLATFORMS}

LABEL = re.compile(r"^ad_(?:(?P<en>en)_)?(?P<plat>[a-z]{2})_(?P<rest>[A-Za-z0-9_]+)$")
REPLY = re.compile(r"^r(?P<post>\d+)_(?P<letter>[aowlm])(?P<arm>[a-z]*)$")
CHANNEL = re.compile(r"^tg(?P<post>\d+)$")
POST = re.compile(r"^(?P<rubric>[a-z][a-z_]*?)(?P<digit>\d)_(?P<ddmm>\d{4})(?:_l(?P<mode>[tc]))?$")
VARIANT_NAMES = {"o": "old", "w": "old", "l": "ladder", "m": "ladder", "a": "link"}


def parse(label: str) -> dict:
    """Разбор метки (с `ad_` или уже без, как в статистике завода: `th_…`). kind: post, reply, channel, bio, pin, static, unknown."""
    raw = str(label or "").strip().lower()
    if "start=" in raw:  # ссылка целиком: берём метку после start=
        raw = raw.split("start=", 1)[1].split()[0] if raw.split("start=", 1)[1].split() else ""
    if not raw.startswith("ad_"):
        raw = "ad_" + raw
    out = {"raw": label, "platform": None, "lang": "ru", "kind": "unknown", "rubric": None, "post_id": None, "variant": None, "name": None}
    m = LABEL.match(raw)
    if not m or m["plat"] not in PLATFORMS:
        return out
    out["lang"], out["platform"], rest = ("en" if m["en"] else "ru"), m["plat"], m["rest"]
    if rest == "bio":
        return {**out, "kind": "bio", "name": "bio"}
    if rest == "pin":
        return {**out, "kind": "pin", "name": "pin"}
    if (r := REPLY.match(rest)):
        return {**out, "kind": "reply", "post_id": int(r["post"]), "variant": VARIANT_NAMES[r["letter"]]}
    if (c := CHANNEL.match(rest)):
        return {**out, "platform": "tg", "kind": "channel", "post_id": int(c["post"])}
    if rest in STATIC:
        plat = STATIC[rest][0]
        return {**out, "platform": plat, "kind": "static", "name": rest}
    if any(rest.startswith(p) for p in STATIC_PREFIXES):
        return {**out, "kind": "static", "name": rest[:4]}
    if (p := POST.match(rest)):
        return {**out, "kind": "post", "rubric": p["rubric"], "variant": ("comment" if p["mode"] == "c" else "text" if p["mode"] == "t" else None)}
    return out


def known(label: str) -> bool:
    return parse(label)["kind"] != "unknown"


FIRST_COMMENTS = {
    "ru": ["Полный разбор твоей даты — {link}", "Посчитать своё число души: {link}", "Узнать своё число души и судьбы: {link}",
           "Разбор по имени и дате ✨ {link}"],
    "en": ["Your full reading, by date: {link}", "Find your soul number: {link}", "Soul and destiny numbers, calculated: {link}",
           "A reading by name and date ✨ {link}"],
}


async def tracked_count(db, rubric: str, now: datetime, days: int = 14) -> int:
    """Сколько постов рубрики за days дней вышло с меткой-ссылкой в первом комментарии (их приход виден по рубрике)."""
    since = (now - timedelta(days=days)).astimezone(timezone.utc).isoformat()
    rows = await db._rows("SELECT COUNT(*) AS n FROM posts WHERE status='published' AND rubric = ? AND published_at >= ? "
                          "AND first_comment LIKE ?", (rubric, since, "%t.me/%"))
    return int(rows[0]["n"])


LINK_POST_GAP = timedelta(hours=48)  # слово владельца 02.11.2026: ссылка в посте (в тексте или первым комментарием) — не чаще раза в двое суток


async def last_link_post_at(db):
    """Когда вышел последний пост со ссылкой на бота (в тексте или первым комментарием) — или None."""
    rows = await db._rows("SELECT published_at FROM posts WHERE status='published' AND (first_comment LIKE '%t.me/%' OR text LIKE '%t.me/%')"
                          " ORDER BY id DESC LIMIT 1")
    if not rows or not rows[0]["published_at"]:
        return None
    value = rows[0]["published_at"]
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def link_post_allowed(db, now: datetime) -> bool:
    last = await last_link_post_at(db)
    return last is None or now - last >= LINK_POST_GAP


async def needs_tracking(db, rubric: str, now: datetime, minimum: int = 2, max_share: float = 0.3) -> bool:
    """Нужна ли этому посту ссылка с меткой первым комментарием: у рубрики мало меченых постов за 14 дней, а общая доля меченых
    среди последних 10 постов не выше max_share. Это измерительная выборка, а не реклама: польза поста та же."""
    if await tracked_count(db, rubric, now) >= minimum:
        return False
    if not await link_post_allowed(db, now):
        return False  # ссылок в постах не чаще раза в двое суток
    rows = await db._rows("SELECT first_comment FROM posts WHERE status='published' ORDER BY id DESC LIMIT 10")
    if not rows:
        return True
    share = sum(1 for r in rows if "t.me/" in (r["first_comment"] or "")) / len(rows)
    if rows and "t.me/" in (rows[0]["first_comment"] or ""):
        return False  # два меченых подряд не ставим
    return share < max_share


def _empty() -> dict:
    return {"came": 0, "new": 0, "wow": 0, "returned": 0, "paid": 0, "stars": 0}


async def outcomes(db, raw: dict | None) -> dict:
    """Приход по меткам, привязанный к рубрике и площадке.

    Возвращает {"by_rubric": {(площадка, рубрика): {...}}, "unattributed": {имя: {...}}, "total": {...}}.
    Метки поста привязаны прямо, метки ответов и канала — через номер поста в базе; шапка, закреп и статика — отдельно."""
    result = {"by_rubric": {}, "unattributed": {}, "total": _empty()}
    if not raw:
        return result
    cache: dict[int, str | None] = {}

    async def rubric_of(post_id: int) -> str | None:
        if post_id not in cache:
            rows = await db._rows("SELECT rubric FROM posts WHERE id = ?", (post_id,))
            cache[post_id] = rows[0]["rubric"] if rows else None
        return cache[post_id]

    for r in raw.get("labels", []):
        p = parse(r.get("label", ""))
        if p["kind"] == "unknown":
            continue
        row = {k: int(r.get(k) or 0) for k in _empty()}
        for k, v in row.items():
            result["total"][k] += v
        rubric = p["rubric"]
        if p["kind"] in ("reply", "channel") and p["post_id"]:
            rubric = await rubric_of(p["post_id"])
        if rubric:
            plat = "tg" if p["kind"] == "channel" else p["platform"]
            dst = result["by_rubric"].setdefault((plat, rubric), _empty() | {"via_reply": 0})
            for k, v in row.items():
                dst[k] += v
            if p["kind"] == "reply":
                dst["via_reply"] += row["came"]
        else:
            name = f"{PLATFORMS.get(p['platform'], p['platform'])}: {STATIC.get(p['name'], (None, p['name']))[1] if p['name'] else p['kind']}"
            dst = result["unattributed"].setdefault(name, _empty())
            for k, v in row.items():
                dst[k] += v
    return result


async def rubric_table(db, now: datetime, days: int = 7, raw: dict | None = None) -> list[dict]:
    """Строка на (площадка, рубрика): сколько постов, просмотров, комментариев (и доля от всех), приход, «вау», оплаты — с оговоркой о выборке."""
    since = now - timedelta(days=days)
    posts = await db.engagement(since)
    out = await outcomes(db, raw)
    total_comments = sum(int(p["comments"] or 0) for p in posts) or 0
    rows: dict[tuple, dict] = {}
    for p in posts:
        row = rows.setdefault(("th", p["rubric"]), {"posts": 0, "views": 0, "views_known": 0, "likes": 0, "comments": 0})
        row["posts"] += 1
        row["likes"] += int(p["likes"] or 0)
        row["comments"] += int(p["comments"] or 0)
        if int(p["views"] or 0) > 0:
            row["views"] += int(p["views"])
            row["views_known"] += 1
    for key, o in out["by_rubric"].items():
        rows.setdefault(key, {"posts": 0, "views": 0, "views_known": 0, "likes": 0, "comments": 0}).update({"bot": o})
    table = []
    for (plat, rubric), r in rows.items():
        o = r.get("bot") or _empty() | {"via_reply": 0}
        n = max(r["posts"], 1)
        table.append({
            "platform": plat, "rubric": rubric, "posts": r["posts"], "views": r["views"] if r["views_known"] else None,
            "comments": r["comments"], "comments_share": (r["comments"] / total_comments) if total_comments else None,
            "comments_per_post": r["comments"] / n, "likes_per_post": r["likes"] / n,
            "came": o["came"], "new": o["new"], "wow": o["wow"], "returned": o["returned"], "paid": o["paid"], "stars": o["stars"],
            "via_reply": o.get("via_reply", 0), "came_per_post": o["came"] / n,
            "enough": r["posts"] >= 3 and r["comments"] >= 10,
        })
    table.sort(key=lambda t: (-t["paid"], -t["came"], -t["comments"]))
    return table


def share_attributed(out: dict) -> float | None:
    total = out["total"]["came"]
    if not total:
        return None
    attributed = sum(v["came"] for v in out["by_rubric"].values())
    return attributed / total


def lines(table: list[dict], out: dict | None = None, names: dict | None = None, top: int = 8) -> list[str]:
    """Отчёт по рубрикам: «рубрика — N постов, X комментариев из Y (доля), пришли…, оплатили…»; малая выборка помечена."""
    names = names or {}
    from .optimizer import short_name  # понятные названия рубрик без «text_…» (04.11.2026)
    total_comments = sum(t["comments"] for t in table)
    total_posts = sum(t["posts"] for t in table)
    res = [f"рубрики за период: постов {total_posts}, комментариев {total_comments}"]
    for t in table[:top]:
        share = f"{t['comments_share'] * 100:.0f}% всех комментариев" if t["comments_share"] is not None else "доля неизвестна"
        views = f", просмотров {t['views']}" if t["views"] is not None else ""
        res.append(f"  {names.get(t['rubric']) or short_name(t['rubric'])} ({PLATFORMS.get(t['platform'], t['platform'])}) — {t['posts']} постов{views}, "
                   f"комментариев {t['comments']} из {total_comments} ({share}, {t['comments_per_post']:.1f} на пост); в боте: пришли {t['came']} "
                   f"(по ответам {t['via_reply']}), «вау» {t['wow']}, оплатили {t['paid']}" + ("" if t["enough"] else " — мало данных"))
    if out:
        att = share_attributed(out)
        if att is not None:
            res.append(f"привязано к рубрике {att * 100:.0f}% пришедших; не привязано: " + (", ".join(
                f"{k} — {v['came']}" for k, v in sorted(out['unattributed'].items(), key=lambda kv: -kv[1]['came'])[:4]) or "ничего"))
            if att < 0.5:
                res.append("УЗКОЕ ЗВЕНО ИЗМЕРЕНИЯ: больше половины пришедших не привязаны к рубрике (идут через шапку или закреп); выводы по рубрикам "
                           "опираются на меньшинство — копим меченые посты (needs_tracking) и ответы со ссылкой")
    return res
