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


_cache: dict[int, tuple[float, dict | None]] = {}


async def fetch(days: int = 7) -> dict | None:
    if not KEY:
        return None
    hit = _cache.get(days)
    if hit and time.monotonic() - hit[0] < 3600:
        return hit[1]
    data = await _fetch(days)
    _cache[days] = (time.monotonic(), data)
    return data


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
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get(URL, params={"k": KEY, "days": days})
        return r.json() if r.is_success else None
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Статистика бота Нумериты недоступна: %s", e)
        return None


def lines(data: dict | None) -> list[str]:
    """Коротко: всего, посты против ответов, лучшие метки."""
    if not data:
        return ["переходы в бота и оплаты: нет данных (ключ NUMERITA_THREADS_KEY не задан или бот недоступен)"]
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
    return out
