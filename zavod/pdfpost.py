"""Презентация полного PDF-разбора (слово создателя 17.11.2026 через основную сессию: «нам уже говорят, что у нас крутые
PDF-разборы и это должно стоить денег — пусть об этом иногда говорит и контент-завод»). Рубрика text_pdf: не чаще раза
в неделю, днём, только когда ссылка в посте разрешена (attribution.LINK_POST_GAP); к посту — настоящая страница демо-PDF
с нашего сайта. Цену не называем: она видна в боте до оплаты."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Слово создателя 17.11.2026, 21:30 МСК (через основную сессию): «выберем дни, исторически успешные по просмотрам, реакциям и
# комментариям, и в эти дни будем давать». Дни и часы считаются из нашей же базы за 30 дней (best_slots), раз в неделю.
MSK = ZoneInfo("Europe/Moscow")
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MIN_POSTS = 12  # меньше опубликованных постов за 30 дней — данных мало, берём любой день в окнах постов
HOURS = range(12, 22)
EVERY = timedelta(days=7)
KEY = "pdfpost:last"
HERO = "https://www.numerita.ru/primer-razbora/hero.jpg"  # обложка веером + страницы (на картинке русский текст — только RU)


def _score(p: dict) -> float:
    """Очки поста как в autopost: комментарии весят больше всего, затем лайки и просмотры."""
    return int(p["comments"] or 0) + 0.2 * int(p["likes"] or 0) + int(p["views"] or 0) / 200


async def best_slots(db, now: datetime) -> dict:
    """Лучшие 2 дня недели и окно (день 10–13 или вечер 18–22) по среднему очку поста за 30 дней, по Москве."""
    posts = [p for p in await db.engagement(now - timedelta(days=30)) if p.get("published_at")]
    days: dict[int, list] = {}
    parts: dict[str, list] = {"day": [], "evening": []}
    for p in posts:
        t = datetime.fromisoformat(p["published_at"]).astimezone(MSK)
        days.setdefault(t.weekday(), []).append(_score(p))
        parts["day" if t.hour < 15 else "evening"].append(_score(p))
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    ranked = sorted((d for d in days if len(days[d]) >= 2), key=lambda d: -mean(days[d]))
    enough = len(posts) >= MIN_POSTS and len(ranked) >= 2
    part = "day" if mean(parts["day"]) >= mean(parts["evening"]) else "evening"
    return {"enough": enough, "weekdays": ranked[:2] if enough else list(range(7)),
            "hours": range(10, 14) if (enough and part == "day") else range(18, 22) if enough else HOURS,
            "means": {WEEKDAYS[d]: round(mean(days[d]), 1) for d in ranked}, "posts": len(posts),
            "part": part, "part_means": {k: round(mean(v), 1) for k, v in parts.items()}}


def describe(slots: dict) -> str:
    if not slots["enough"]:
        return f"PDF-пост: данных мало ({slots['posts']} постов за 30 дней) — любой день, 12–22"
    days = ", ".join(WEEKDAYS[d] for d in slots["weekdays"])
    return (f"PDF-пост: лучшие дни {days}, {'днём 10–13' if slots['part'] == 'day' else 'вечером 18–22'} "
            f"(среднее очко поста по дням: {slots['means']}; день/вечер: {slots['part_means']}; постов {slots['posts']})")


async def due(db, now: datetime) -> bool:
    last = await db.kv_get(KEY)
    if last and now - datetime.fromisoformat(last) < EVERY:
        return False
    slots = await best_slots(db, now)
    local = now.astimezone(MSK) if now.tzinfo else now
    return local.weekday() in slots["weekdays"] and local.hour in slots["hours"]


async def mark(db, now: datetime) -> None:
    await db.kv_set(KEY, now.isoformat())


async def hero_bytes() -> bytes:
    import httpx
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
        r = await http.get(HERO)
        r.raise_for_status()
        return r.content
