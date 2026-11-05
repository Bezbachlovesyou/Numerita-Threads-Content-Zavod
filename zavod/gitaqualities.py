"""Сериал «26 даров светлой природы» (слово владельца 05.11.2026: «много-много постов, прям сериал; про 26 качеств из Гиты и про светлую природу, её богатство»).
Бхагавад-гита, глава 16, стихи 1–3 перечисляют 26 качеств «божественного богатства» (даиви сампад, «светлой природы»): их и берём. Названия на санскрите и смысл — knowledge/formats/gita_qualities.json
(смысл — наши слова, не цитата стиха). Подача — ТРАДИЦИЕЙ, не научным фактом и не прогнозом; цитат не выдумываем. Раз в сутки днём одно качество по порядку (kv gita:idx), потом круг сначала."""

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "knowledge" / "formats" / "gita_qualities.json"
HOURS = range(11, 20)
EVERY = timedelta(hours=20)


@lru_cache(maxsize=1)
def qualities() -> list[dict]:
    return json.loads(PATH.read_text(encoding="utf-8"))


def block(item: dict, en: bool) -> str:
    """Данные для задания: одно качество, его санскритское название и смысл (модель смысл не меняет и не добавляет цитат)."""
    if en:
        return (f"Quality {item['n']} of 26 from the Bhagavad Gita, chapter 16, verses 1–3 (the 'wealth of the light nature', daivi sampad): {item['en']} (Sanskrit: {item['sa']}). "
                f"Plain meaning (our words, not a quote): {item['mean_en']} Present it as tradition, not as science or a forecast; no invented quotes.")
    return (f"Качество {item['n']} из 26 из Бхагавад-гиты, глава 16, стихи 1–3 («богатство светлой природы», даиви сампад): {item['ru']} (санскрит: {item['sa_ru']}, {item['sa']}). "
            f"Простой смысл (наши слова, не цитата): {item['mean_ru']} Подай ТРАДИЦИЕЙ, не наукой и не прогнозом; цитат не выдумывай.")


async def due(db, now: datetime) -> bool:
    if now.hour not in HOURS:
        return False
    last = await db.kv_get("gita:last")
    return not last or now - datetime.fromisoformat(last) >= EVERY


async def take(db, now: datetime) -> dict:
    idx = int(await db.kv_get("gita:idx") or 0)
    item = qualities()[idx % len(qualities())]
    await db.kv_set("gita:idx", str(idx + 1))
    await db.kv_set("gita:last", now.isoformat())
    return item
