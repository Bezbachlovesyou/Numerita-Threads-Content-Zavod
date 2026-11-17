"""Презентация полного PDF-разбора (слово создателя 17.11.2026 через основную сессию: «нам уже говорят, что у нас крутые
PDF-разборы и это должно стоить денег — пусть об этом иногда говорит и контент-завод»). Рубрика text_pdf: не чаще раза
в неделю, днём, только когда ссылка в посте разрешена (attribution.LINK_POST_GAP); к посту — настоящая страница демо-PDF
с нашего сайта. Цену не называем: она видна в боте до оплаты."""
from datetime import datetime, timedelta

HOURS = range(12, 22)
EVERY = timedelta(days=7)
KEY = "pdfpost:last"
HERO = "https://www.numerita.ru/primer-razbora/hero.jpg"  # обложка веером + страницы (на картинке русский текст — только RU)


async def due(db, now: datetime) -> bool:
    if now.hour not in HOURS:
        return False
    last = await db.kv_get(KEY)
    return not last or now - datetime.fromisoformat(last) >= EVERY


async def mark(db, now: datetime) -> None:
    await db.kv_set(KEY, now.isoformat())


async def hero_bytes() -> bytes:
    import httpx
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
        r = await http.get(HERO)
        r.raise_for_status()
        return r.content
