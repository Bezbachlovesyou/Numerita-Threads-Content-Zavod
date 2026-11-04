"""Что было дальше в боте Нумериты: переходы и оплаты по меткам ad_th_… (без имён) — /threads.json.

Ключ NUMERITA_THREADS_KEY открывает только эту статистику (его показывает /threads в @Numeritabot).
Нужен обходу по Голдратту и отчёту /costs: какие посты и ответы реально приводят людей и оплаты.
"""

import logging
import time

import httpx

log = logging.getLogger(__name__)

URL = "https://numerita.up.railway.app/threads.json"
KEY = ""  # задаётся при запуске из переменной NUMERITA_THREADS_KEY
STATUS = ""  # почему нет данных — для отчёта владельцу простыми словами


_cache: dict[int, tuple[float, dict | None]] = {}


async def fetch(days: int = 7) -> dict | None:
    if not KEY:
        return None
    hit = _cache.get(days)
    if hit and time.monotonic() - hit[0] < 3600:
        return hit[1]
    data = normalize(await _fetch(days))
    _cache[days] = (time.monotonic(), data)
    return data


_raw_cache: dict[int, tuple[float, dict | None]] = {}


async def fetch_raw(days: int = 7) -> dict | None:
    """Все метки как отдал бот (без фильтра по языку и площадке): основа каркаса атрибуции (attribution.py)."""
    if not KEY:
        return None
    hit = _raw_cache.get(days)
    if hit and time.monotonic() - hit[0] < 3600:
        return hit[1]
    data = await _fetch(days)
    _raw_cache[days] = (time.monotonic(), data)
    return data


def own_language(raw: dict | None) -> dict | None:
    """Только метки своего языка (русский экземпляр — ad_…, английский — ad_en_…), все площадки."""
    if not raw:
        return raw
    from .lang import is_en
    en = is_en()
    keep = [r for r in raw.get("labels", []) if str(r.get("label", "")).lower().startswith("ad_en_") == en]
    return {**raw, "labels": keep}


def normalize(data: dict | None) -> dict | None:
    """Бот Нумериты отдаёт метки целиком («ad_th_soul8_2410», «ad_en_th_r12_o»), а завод считает по своему виду
    («th_…»). 30.10.2026: из-за этого расхождения обход неделю видел «никто не пришёл». Английскому экземпляру —
    его метки ad_en_th_ → th_, русские (ad_th_) ему не засчитываются; русскому — наоборот."""
    if not data:
        return data
    from .lang import is_en
    own, other = ("ad_en_th_", "ad_th_") if is_en() else ("ad_th_", "ad_en_th_")
    rows = []
    for r in data.get("labels", []):
        label = str(r.get("label", "")).lower()
        if label.startswith(own):
            rows.append({**r, "label": "th_" + label[len(own):]})
        elif not label.startswith(other) and not label.startswith("ad_"):
            rows.append(r)  # уже в виде th_… (старый ответ бота)
    return {**data, "labels": rows}


def arrivals_by_link_mode(data: dict | None) -> dict[str, int] | None:
    """Сколько людей пришло в бота по каждому способу подачи ссылки в постах (_lt, _lc, шапка профиля)."""
    if not data:
        return None
    out = {"text": 0, "comment": 0, "profile": 0}
    for r in data.get("labels", []):
        label, came = str(r.get("label", "")), int(r.get("came") or 0)
        if label.endswith("_lt"):
            out["text"] += came
        elif label.endswith("_lc"):
            out["comment"] += came
        elif label == "th_bio":
            out["profile"] += came
    return out


async def _fetch(days: int) -> dict | None:
    global STATUS
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get(URL, params={"k": KEY, "days": days})
        if r.status_code == 404:
            STATUS = "бот Нумериты не принял ключ: проверь значение NUMERITA_THREADS_KEY (строка «🔑» в /threads)"
            return None
        r.raise_for_status()
        STATUS = ""
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Статистика бота Нумериты недоступна: %s", e)
        STATUS = "бот Нумериты сейчас не отвечает, попробую позже"
        return None


def games_lines(data: dict | None) -> list[str]:
    """Игры бота (ключ games.redflag в /threads.json, слово владельца 04.11.2026: «игра растёт, когда друзья зовут друзей»): одна строка, K — коэффициент приглашений
    (сколько друзей доиграло на одного доигравшего; K>1 — игра растёт сама). Нет данных — молчим."""
    game = ((data or {}).get("games") or {}).get("redflag")
    if not isinstance(game, dict) or not game.get("started"):
        return []
    k = game.get("k")
    k_text = f", K={float(k):.2f}" if isinstance(k, (int, float)) else ""
    return [f"игра «Красный или зелёный?»: начали {game.get('started', 0)}, доиграли {game.get('finished_first', 0)}, "
            f"позвали близкого {game.get('pressed_invite', 0)}, друзей пришло {game.get('friends_came', 0)} (доиграли {game.get('friends_finished', 0)}){k_text}"]


def lines(data: dict | None) -> list[str]:
    """Коротко: всего, посты против ответов, лучшие метки."""
    if not data:
        why = STATUS if KEY else "на Railway не задана переменная NUMERITA_THREADS_KEY"
        return [f"переходы в бота и оплаты: нет данных — {why or 'неизвестная причина'}"]
    labels = [r for r in data.get("labels", []) if str(r.get("label", "")).startswith("th_")]
    if not labels:
        return [f"переходы в бота за {data.get('days')} дн.: по меткам Threads пока никто не пришёл"]

    def total(rows):
        return {k: sum(int(r.get(k) or 0) for r in rows) for k in ("came", "new", "wow", "returned", "paid", "stars")}

    t = total(labels)
    replies = total([r for r in labels if r["label"].startswith("th_r")])
    out = [f"бот Нумериты за {data.get('days')} дн. по меткам Threads: пришли {t['came']} (новых {t['new']}), "
           f"«вау» {t['wow']}, вернулись {t['returned']}, оплатили {t['paid']}"
           + (f" ({t['stars']} ⭐)" if t["stars"] else ""),
           f"из них по ссылкам в ответах (th_r…): пришли {replies['came']}, оплатили {replies['paid']}; "
           f"по постам и шапке профиля: пришли {t['came'] - replies['came']}, оплатили {t['paid'] - replies['paid']}"]
    best = sorted(labels, key=lambda r: (-int(r.get("paid") or 0), -int(r.get("came") or 0)))[:6]
    out.append("лучшие метки: " + ", ".join(f"{r['label'][3:]} — {r['came']} пришли, {r.get('paid', 0)} оплат" for r in best))
    return out + games_lines(data)
