"""Автоответы на комментарии под нашими постами в Threads.

Половина постов зовёт ответить числом дня рождения — бот отвечает каждому лично
по базе знаний Нумериты, иногда со ссылкой на полный разбор в @Numeritabot.
"""

import logging
from datetime import datetime, timedelta, timezone

from .autopost import BOT_LINK
from .generator import GenerationError, Generator
from .storage import Storage
from .threads_api import ThreadsClient, ThreadsError

log = logging.getLogger(__name__)

LOOKBACK = timedelta(days=3)  # под какими постами смотрим комментарии
MAX_REPLY_LENGTH = 500


def finish_reply(text: str, tag: str | None) -> str:
    """Обрезает слишком длинный ответ и подставляет ссылку (или убирает маркер, если ссылка не нужна)."""
    link = BOT_LINK + tag if tag else ""
    body = text.replace("{LINK}", "").strip()
    limit = MAX_REPLY_LENGTH - (len(link) + 1 if link else 0)
    if len(body) > limit:
        body = body[: limit - 1].rsplit(" ", 1)[0] + "…"
    return f"{body}\n{link}" if link else body


async def answer_comments(
    db: Storage,
    threads: ThreadsClient,
    generator: Generator,
    per_hour: int,
    per_run: int,
) -> int:
    """Отвечает на новые комментарии. Возвращает, сколько ответов отправлено за этот прогон."""
    now = datetime.now(timezone.utc)
    budget = min(per_run, per_hour - await db.replies_since(now - timedelta(hours=1)))
    if budget <= 0:
        return 0

    sent = 0
    for post in await db.recent_published(now - LOOKBACK):
        try:
            comments = await threads.comments(post.threads_id)
        except ThreadsError as e:
            log.warning("Не удалось получить комментарии к посту #%s: %s", post.id, e)
            continue

        fresh = [
            c for c in comments
            if c.get("id") and c.get("message") and not (c.get("from") or {}).get("isOwner")
            and c.get("canReply", True)
        ]
        handled = await db.handled_comments([c["id"] for c in fresh])
        for comment in fresh:
            if comment["id"] in handled:
                continue
            author = (comment.get("from") or {}).get("username") or (comment.get("from") or {}).get("name") or "?"
            # Если мы уже ответили в этой ветке (например, до перезапуска), второй раз не отвечаем.
            if any((r.get("from") or {}).get("isOwner") for r in comment.get("replies") or []):
                await db.record_comment(comment["id"], post.id, author, comment["message"], "", "skipped")
                continue

            replied_total = await db.replies_since(now - timedelta(days=3650))
            with_link = replied_total % 2 == 1  # ссылка примерно в каждом втором ответе
            try:
                text = (await generator.write_reply(post.text, comment["message"], author, with_link)).strip()
            except GenerationError as e:
                log.warning("Не удалось написать ответ на комментарий %s: %s", comment["id"], e)
                return sent

            if text.upper().strip(" .!\"'«»") == "SKIP":
                await db.record_comment(comment["id"], post.id, author, comment["message"], "", "skipped")
                continue
            text = finish_reply(text, f"r{post.id}" if with_link else None)

            try:
                await threads.reply(post.threads_id, comment["id"], text)
            except ThreadsError as e:
                log.warning("Не удалось ответить на комментарий %s: %s", comment["id"], e)
                continue
            await db.record_comment(comment["id"], post.id, author, comment["message"], text, "replied")
            log.info("Ответ @%s под постом #%s", author, post.id)
            sent += 1
            if sent >= budget:
                return sent
    return sent
