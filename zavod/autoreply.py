"""Автоответы на комментарии под нашими постами в Threads.

Половина постов зовёт ответить числом дня рождения — бот отвечает каждому лично
по базе знаний Нумериты, иногда со ссылкой на полный разбор в @Numeritabot.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from .autopost import BOT_LINK
from .cards import grid_hint
from .generator import GenerationError, Generator
from .storage import Storage
from .threads_api import ThreadsClient, ThreadsError

log = logging.getLogger(__name__)

LOOKBACK = timedelta(days=3)  # под какими постами смотрим комментарии
MAX_REPLY_LENGTH = 500


def gave_number(message: str) -> bool:
    """В комментарии есть число дня рождения (1–31) или дата."""
    return any(1 <= int(n) <= 31 for n in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", message))


def finish_reply(text: str, tag: str | None) -> str:
    """Обрезает слишком длинный ответ и подставляет ссылку (или убирает маркер, если ссылка не нужна)."""
    link = BOT_LINK + tag if tag else ""
    body = text.replace("{LINK}", "").strip()
    limit = MAX_REPLY_LENGTH - (len(link) + 1 if link else 0)
    if len(body) > limit:
        body = body[: limit - 1].rsplit(" ", 1)[0] + "…"
    return f"{body}\n{link}" if link else body


async def reply_targets(db: Storage, threads: ThreadsClient, now: datetime) -> list[tuple[str, int | None, str]]:
    """Под какими постами смотреть комментарии: (id поста для Zernio, наш номер поста или None, текст поста).

    Берём и свои посты из базы, и все посты аккаунта с комментариями из Zernio — так бот отвечает
    и под постами, опубликованными до подключения базы или вручную.
    """
    targets: dict[str, tuple[str, int | None, str]] = {}
    ours = await db.recent_published(now - LOOKBACK)
    for post in ours:
        targets[post.threads_id] = (post.threads_id, post.id, post.text + grid_hint(post.card))
    try:
        for item in await threads.commented_posts(now - LOOKBACK):
            if not item.get("id") or item["id"] in targets:
                continue
            content = item.get("content") or ""
            match = next((p for p in ours if content and p.text[:60] == content[:60]), None)
            if match and match.threads_id in targets:
                continue  # тот же пост, который уже есть в базе под id Zernio
            targets[item["id"]] = (item["id"], match.id if match else None, content)
    except ThreadsError as e:
        await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} список постов с комментариями: {e}")
    return list(targets.values())


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
    for target_id, post_id, post_text in await reply_targets(db, threads, now):
        try:
            comments = await threads.comments(target_id)
        except ThreadsError as e:
            log.warning("Не удалось получить комментарии к посту %s: %s", target_id, e)
            await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} комментарии: {e}")
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
                await db.record_comment(comment["id"], post_id, author, comment["message"], "", "skipped")
                continue

            replied_total = await db.replies_since(now - timedelta(days=3650))
            # Написал свою дату — он уже заинтересован: ссылку на полный разбор даём всегда.
            # Остальным (спасибо, вопросы) — примерно в каждом втором ответе.
            with_link = gave_number(comment["message"]) or replied_total % 2 == 1
            try:
                text = (await generator.write_reply(post_text, comment["message"], author, with_link)).strip()
            except GenerationError as e:
                log.warning("Не удалось написать ответ на комментарий %s: %s", comment["id"], e)
                await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} нейросеть: {e}")
                return sent

            if text.upper().strip(" .!\"'«»") == "SKIP":
                await db.record_comment(comment["id"], post_id, author, comment["message"], "", "skipped")
                continue
            text = finish_reply(text, f"r{post_id or 0}" if with_link else None)

            try:
                await threads.reply(target_id, comment["id"], text)
            except ThreadsError as e:
                log.warning("Не удалось ответить на комментарий %s: %s", comment["id"], e)
                await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} ответ: {e}")
                continue
            await db.record_comment(comment["id"], post_id, author, comment["message"], text, "replied")
            await db.kv_set("autoreply_error", "")
            log.info("Ответ @%s под постом %s", author, target_id)
            sent += 1
            if sent >= budget:
                return sent
    return sent
