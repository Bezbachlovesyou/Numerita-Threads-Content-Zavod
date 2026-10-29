"""Истории подписчиц (слово владельца 29.10.2026: «хайп из реальных историй — присылайте трешовые истории с датами
рождения участников, рассказываем без имён и через нумерологию»).

Приём — в @Numeritabot (в Threads нет API личных сообщений): человек присылает историю, роли и даты участников и даёт
согласие на анонимный пересказ. Бот Нумериты отдаёт заводу через /stories.json уже очищенный текст и ЧИСЛА участников
(сами даты, имена, города и скриншоты наружу не выходят). Завод раз в день пересказывает одну историю: смешно, но без
унижения участников (насмешка возвращается), через числа души/судьбы как символический язык, с вопросом читателям.
Раз в 2 дня — короткий пост-приглашение присылать истории. Всё включается, только когда /stories.json отвечает 200.
"""

import logging
from datetime import datetime, timedelta

import httpx

from . import funnel

log = logging.getLogger(__name__)

URL = "https://numerita.up.railway.app/stories.json"
CALL_EVERY = timedelta(days=2)

STORY_RULES = (
    "Перескажи реальную историю подписчицы для Threads. Строго: никаких имён, ников, городов, профессий-примет, дат "
    "и цитат длиннее 6 слов из переписки; участников называй ролями и числами («она — 6, он — 8»). Измени мелкие "
    "детали, чтобы никого нельзя было узнать. Тон: живой, остроумный, на злобу дня (приёмы: узнавание, «бровь», сухая "
    "подача), но без унижения участников и без диагнозов — смеёмся над ситуацией, а не над человеком. Нумерология — "
    "символический язык: как числа участников объясняют столкновение (по базе Нумериты), без приговора паре и без "
    "советов расстаться. Первая строка — хук («История подписчицы. Она — 6, он — 8. Спор вышел из-за 40 тысяч»). "
    "Финал — вопрос читателям, на чьей они стороне или как бы поступили. Пометь: «реальная история, детали изменены». "
    "Без мата, без ссылок, до 480 знаков.\n\nИстория (уже очищена ботом):\n{text}\n\nЧисла участников: {numbers}"
)
CALL_RULES = (
    "Напиши короткий пост-приглашение для Threads: Нумерита собирает реальные истории — смешные, нелепые, трешовые — "
    "из отношений, семьи, работы, и разбирает их через числа участников. Как прислать: в Telegram @Numeritabot, слово "
    "«история», с датами рождения участников; пересказываем анонимно — без имён, дат и скриншотов. Хук в первой "
    "строке, одна шутка, без призывов лайкать и репостить, без ссылок. До 300 знаков."
)


async def fetch() -> list[dict] | None:
    """Новые истории с согласием или None, если приём ещё не работает."""
    if not funnel.KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get(URL, params={"k": funnel.KEY})
        if r.status_code != 200:
            return None
        data = r.json()
        return [s for s in data.get("stories", []) if s.get("consent", True)]
    except (httpx.HTTPError, ValueError) as e:
        log.info("Истории: приём недоступен: %s", e)
        return None


async def mark(story_id, status: str, url: str | None = None) -> None:
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            params = {"k": funnel.KEY, "id": story_id, "status": status}
            if url:
                params["url"] = url
            await http.post(URL, params=params)
    except httpx.HTTPError as e:
        log.warning("Истории: не отметила %s: %s", story_id, e)


def numbers_line(story: dict) -> str:
    parts = []
    for p in story.get("people", []):
        role = p.get("role") or "участник"
        nums = ", ".join(f"{k} {v}" for k, v in p.items() if k in ("soul", "destiny") and v)
        parts.append(f"{role}: {nums}" if nums else role)
    return "; ".join(parts) or "не указаны"


async def due_call(db, now: datetime) -> bool:
    last = await db.kv_get("stories:last_call")
    return not last or now - datetime.fromisoformat(last) >= CALL_EVERY
