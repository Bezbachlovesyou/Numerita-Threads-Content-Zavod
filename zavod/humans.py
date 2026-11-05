"""Живые ли люди нас комментируют (слово владельца 05.11.2026: «комментируют боты, живые не подписываются, не факт, что среди ста подписчиков есть живые»).
Доказать «человек» или «бот» по тексту нельзя. Но признаки видны: одинаковые тексты у разных авторов, рекламные фразы, авторы-«конвейеры»
(много комментариев под многими постами без смысла), доля осмысленных реплик (вопросы, истории, числа дней рождения). Отчёт — по базе ответов за 14 дней, без имён людей: только числа и 3 примера ников для проверки глазами."""

import re
from collections import Counter
from datetime import datetime, timedelta, timezone

PROMO = re.compile(r"link in bio|dm me|dm for|check my|follow me|подпис(ывайся|ывайтесь) на|заработ|курс|пиши в (лс|директ)|канал\b.*t\.me|https?://", re.I)
GENERIC = re.compile(r"^(nice|great|good|love it|amazing|wow|thanks|thank you|супер|класс|круто|спасибо|👍|🔥|❤️?)\W*$", re.I)
MEANINGFUL = re.compile(r"[?？]|\b(родил|рожд|born|birthday|мне|я |my )\b|\d{1,2}[./]\d{1,2}|\b\d{1,2}\b", re.I)


async def report(db, now: datetime) -> str:
    since = (now - timedelta(days=14)).astimezone(timezone.utc).isoformat()
    rows = await db._rows("SELECT c.comment_id AS cid, c.post_id AS post_id, c.author AS author, c.comment AS comment, c.created_at AS at,"
                          " 0 AS pub FROM comment_replies c WHERE c.created_at >= ?", (since,))
    if not rows:
        return "Живые ли люди: в базе нет комментариев за 14 дней."
    texts = Counter((r["comment"] or "").strip().lower() for r in rows if len((r["comment"] or "").strip()) >= 12)
    dup_texts = {t for t, n in texts.items() if n >= 3}
    authors = Counter((r["author"] or "?").lower() for r in rows)
    per_author_posts: dict[str, set] = {}
    for r in rows:
        per_author_posts.setdefault((r["author"] or "?").lower(), set()).add(r["post_id"])
    promo = sum(1 for r in rows if PROMO.search(r["comment"] or ""))
    generic = sum(1 for r in rows if GENERIC.match((r["comment"] or "").strip()))
    meaningful = sum(1 for r in rows if MEANINGFUL.search(r["comment"] or "") and not GENERIC.match((r["comment"] or "").strip()))
    dup = sum(1 for r in rows if (r["comment"] or "").strip().lower() in dup_texts)
    conveyor = [a for a, posts in per_author_posts.items() if len(posts) >= 5 and a != "?"]
    n = len(rows)
    pct = lambda x: f"{round(100 * x / n)}%"
    lines = [f"🔎 Живые ли комментаторы (за 14 дней: {n} комментариев, {len(authors)} разных авторов)",
             f"Осмысленные (вопрос, число, дата, история): {pct(meaningful)}; пустые «супер/спасибо/смайл»: {pct(generic)}",
             f"Подозрительные признаки: одинаковый текст у разных авторов {pct(dup)}, реклама и ссылки {pct(promo)}",
             f"Авторы, пишущие под 5+ разными постами: {len(conveyor)}" + (f" (проверьте глазами: {', '.join(conveyor[:3])})" if conveyor else "")]
    bad = dup + promo
    verdict = ("Похоже на людей: подозрительного мало." if bad / n < 0.1 else "Заметная доля похожа на ботов — стоит разобрать.")
    lines.append(verdict + " Точно «человек или бот» по тексту доказать нельзя; это признаки.")
    return "\n".join(lines)
