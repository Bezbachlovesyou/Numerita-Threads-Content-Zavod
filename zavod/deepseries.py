"""Глубокие серии (слово владельца 20.11.2026: «спам не работает; глубокое исследование за каждым постом; каждый пост — серия,
каждая серия — исследование вглубь»). Методология — docs/research-methodology.md, досье — knowledge/series/deep_series.json.

Пока ENABLED, каждый автопост — следующий эпизод текущей серии (рубрика text_deep, бриф эпизода вместо [[DEEP]]).
Порядок: kv deep:pos = «индекс серии:индекс эпизода», сдвигается при взятии эпизода; после последней серии — круг сначала.
Подпись «🔭 Название · N/M» добавляет код (label), тема Threads — у серии своя (topic)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ENABLED = True
RUBRIC = "text_deep"
PATH = Path(__file__).resolve().parent.parent / "knowledge" / "series" / "deep_series.json"
KV_POS = "deep:pos"
CURRENT: dict = {}  # последний взятый эпизод: подпись и тема для публикации


@lru_cache(maxsize=1)
def series() -> list[dict]:
    return json.loads(PATH.read_text(encoding="utf-8"))


def _pos(raw: str | None) -> tuple[int, int]:
    try:
        s, e = (int(x) for x in str(raw).split(":"))
        return s, e
    except (TypeError, ValueError):
        return 0, 0


async def take(db) -> dict:
    """Следующий эпизод: {series, n, total, brief_ru, brief_en}; позиция сдвигается."""
    all_series = series()
    s, e = _pos(await db.kv_get(KV_POS))
    s %= len(all_series)
    if e >= len(all_series[s]["episodes"]):
        s, e = (s + 1) % len(all_series), 0
    item = all_series[s]
    nxt = (s, e + 1) if e + 1 < len(item["episodes"]) else ((s + 1) % len(all_series), 0)
    await db.kv_set(KV_POS, f"{nxt[0]}:{nxt[1]}")
    ep = {"series": item, "n": e + 1, "total": len(item["episodes"]), "episode": item["episodes"][e]}
    CURRENT.clear()
    CURRENT.update(ep)
    return ep


def block(ep: dict, en: bool) -> str:
    item, lang_key = ep["series"], "en" if en else "ru"
    if en:
        return (f"Deep series \"{item['title_en']}\", part {ep['n']} of {ep['total']}. Research question of the series: {item['question_en']}\n"
                f"Brief of this part (facts are verified; use only these numbers and names, invent nothing, no quotes): {ep['episode']['en']}\n"
                "One finding and one image, hook in the first line, clear even to a child, warm humor about the situation. "
                "Mark what is FACT and what is TRADITION in plain words. Up to 400 characters. Don't write the series label — the bot adds it.")
    return (f"Глубокая серия «{item['title_ru']}», часть {ep['n']} из {ep['total']}. Вопрос исследования: {item['question_ru']}\n"
            f"Бриф этой части (факты проверены; только эти цифры и имена, ничего не выдумывай, без цитат): {ep['episode'][lang_key]}\n"
            "Одна находка и один образ, хук в первой строке, понятно даже ребёнку, тёплый юмор над ситуацией. "
            "Простыми словами отдели, что ФАКТ, а что ТРАДИЦИЯ. До 400 знаков. Подпись серии не пиши — её добавит бот.")


def label(en: bool, ep: dict | None = None) -> str | None:
    ep = ep or CURRENT
    if not ep:
        return None
    title = ep["series"]["title_en" if en else "title_ru"]
    return f"🔭 {title} · {ep['n']}/{ep['total']}"


def with_label(text: str, en: bool, limit: int = 500) -> str:
    tail = label(en)
    if not tail or tail in text:
        return text
    return text if len(text) + len(tail) + 2 > limit else f"{text.rstrip()}\n\n{tail}"


def topic(en: bool) -> str | None:
    if not CURRENT:
        return None
    return CURRENT["series"]["topic_en" if en else "topic_ru"]
