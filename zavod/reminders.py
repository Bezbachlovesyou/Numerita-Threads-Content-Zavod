"""Напоминания владельцу (слово владельца 31.10.2026): не забыть свои идеи и держать масштаб — «все проекты должны иметь масштаб
человеческой цивилизации, благо для цивилизации в целом». Только в дневное окно (10–12 по поясу бота), никогда вечером.

Идеи лежат в базе (kv ideas:list) и в docs/ideas.md; раз в 7 дней бот напоминает об открытых. О масштабе — раз в 3 дня, по кругу
шесть коротких формулировок. Всё без нейросети, с квитанциями (kv), без повторов при перезапуске."""

import json
from datetime import datetime

CIVILIZATION_EVERY_DAYS = 3
IDEAS_EVERY_DAYS = 7
WINDOW = range(10, 12)  # часы по поясу бота

CIVILIZATION = [
    "🌍 Масштаб. Проект живёт для человеческой цивилизации, а не для одной воронки. Какое благо в нём сегодня для людей вообще — "
    "и что из этого можно отдать открыто всем?",
    "🌍 Масштаб. Планетарный эгрегор строится дарами: что в Нумерите уже полезно тысячам людей, а не только тем, кто заплатил? "
    "Один шаг на этой неделе, чтобы эта польза дошла дальше.",
    "🌍 Масштаб. Если бы проект вырос в тысячу раз, остался бы он добром для людей и честным с ними? Что стоит заложить в основу "
    "сейчас, пока он мал?",
    "🌍 Масштаб. Знание, которое не искажено и не продаётся страхом, — вклад в цивилизацию. Что мы на этой неделе сделали "
    "честнее, яснее, добрее?",
    "🌍 Масштаб. Прибыль нужна, чтобы благо росло. Какой доход этой недели можно прямо связать с пользой для людей — и как "
    "вернуть часть этой пользы миру?",
    "🌍 Масштаб. Каждый человек, которого Нумерита поддержала, делает мир чуть светлее. Сколько таких людей стало на этой неделе "
    "и что помогло бы, чтобы их стало больше?",
]


async def ideas(db) -> list[dict]:
    return json.loads(await db.kv_get("ideas:list") or "[]")


async def add_idea(db, idea_id: str, title: str, now: datetime) -> bool:
    """Записать идею (повторная запись с тем же id ничего не меняет). True — новая."""
    items = await ideas(db)
    if any(i["id"] == idea_id for i in items):
        return False
    await db.kv_set("ideas:list", json.dumps(items + [{"id": idea_id, "title": title, "added": now.date().isoformat()}],
                                             ensure_ascii=False))
    return True


async def close_idea(db, idea_id: str) -> bool:
    items = await ideas(db)
    kept = [i for i in items if i["id"] != idea_id]
    await db.kv_set("ideas:list", json.dumps(kept, ensure_ascii=False))
    return len(kept) != len(items)


async def _due(db, key: str, now: datetime, every_days: int) -> bool:
    last = await db.kv_get(key)
    return not last or (now.date() - datetime.fromisoformat(last).date()).days >= every_days


async def run_due(db, now: datetime, tz) -> list[str]:
    """Сообщения владельцу на сейчас (обычно пусто). Окно 10–12 по часовому поясу бота."""
    now = now.astimezone(tz)
    if now.hour not in WINDOW:
        return []
    out = []
    if await _due(db, "remind:civ:last", now, CIVILIZATION_EVERY_DAYS):
        n = int(await db.kv_get("remind:civ:n") or 0)
        await db.kv_set("remind:civ:last", now.isoformat())
        await db.kv_set("remind:civ:n", str(n + 1))
        out.append(CIVILIZATION[n % len(CIVILIZATION)])
    if await _due(db, "remind:lesson:last", now, 1):  # ежедневный короткий урок: Голдратт, теории роста, ТРИЗ (слово владельца 05.11.2026)
        from . import owner_lessons
        n = int(await db.kv_get("remind:lesson:n") or 0)
        await db.kv_set("remind:lesson:last", now.isoformat())
        await db.kv_set("remind:lesson:n", str(n + 1))
        out.append(owner_lessons.lesson_text(n))
    if await _due(db, "remind:chakra:last", now, 1):  # ежедневная заметка о чакрах (слово владельца 05.11.2026)
        from . import chakras
        n = int(await db.kv_get("remind:chakra:n") or 0)
        await db.kv_set("remind:chakra:last", now.isoformat())
        await db.kv_set("remind:chakra:n", str(n + 1))
        out.append(chakras.note_text(n))
    if await _due(db, "remind:dailypost:last", now, 1):  # пост дня для ручной публикации в Facebook/Instagram (слово владельца 08.11.2026)
        from . import dailypost
        await db.kv_set("remind:dailypost:last", now.isoformat())
        out.extend(await dailypost.messages(db, now))
    open_ideas = await ideas(db)
    if open_ideas and await _due(db, "remind:ideas:last", now, IDEAS_EVERY_DAYS):
        await db.kv_set("remind:ideas:last", now.isoformat())
        out.append("💡 Ваши идеи, которые ждут разработки:\n" + "\n".join(f"• {i['title']} (с {i['added']})" for i in open_ideas)
                   + "\nСкажите, с какой начать, или «снять с учёта».")
    return out
