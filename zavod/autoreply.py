"""Автоответы на комментарии под нашими постами в Threads.

Половина постов зовёт ответить числом дня рождения — бот отвечает каждому лично
по базе знаний Нумериты, иногда со ссылкой на полный разбор в @Numeritabot.
"""

import asyncio
import logging
import random
import re
from datetime import datetime, timedelta, timezone

from .autopost import BOT_LINK
from .cards import grid_hint
from .generator import GenerationError, Generator
from .storage import Storage
from .threads_api import ThreadsClient, ThreadsError

log = logging.getLogger(__name__)

LOOKBACK = timedelta(days=3)  # под какими постами смотрим комментарии
# Правила присутствия (prompts/threads_rules.md): отвечаем как живой человек, а не как спам-бот.
PER_AUTHOR_PER_DAY = 3  # не больше 3 ответов одному человеку за сутки — без бесконечных переписок
PAUSE = (20, 60)  # секунд между ответами внутри одного прохода
# Ссылка в ответе — только если человек сам попросил (не навязываемся): не больше 3 в час на всех
# и не чаще раза в неделю одному человеку. Остальных зовём «в шапку профиля» или не зовём вовсе.
LINKS_PER_HOUR = 3
ASKS_LINK = re.compile(
    r"ссылк|линк|\blink|где\b[^?]{0,40}(посчита|узна|найти|получ|бот|сайт)|как\b[^?]{0,40}(посчита|узна|найти)"
    r"|(ваш|ваше|вашего|вашем)\s+(бот|сайт|канал)|есть\s+(бот|сайт|канал)|куда\s+(писать|перейти)", re.I,
)


# Эксперимент: иногда ссылку даём и без просьбы — только тем, кто сам написал своё число (тёплый интерес).
# Осторожно: не больше 1 такого ответа в час, ~15% подходящих ответов, одному человеку — раз в неделю.
# Метки: _a — по просьбе, _p — сами предложили. Если Threads откажет в ответе со ссылкой — ссылки в ответах
# выключаются на 7 дней (стоп-кран), владельцу приходит сообщение.
OFFER_SHARE = 0.15
OFFERS_PER_HOUR = 1
LINK_PAUSE = timedelta(days=7)


def asks_link(message: str) -> bool:
    """Человек сам спрашивает, где посчитать или узнать больше."""
    return bool(ASKS_LINK.search(message))
MAX_REPLY_LENGTH = 500


def gave_number(message: str) -> bool:
    """В комментарии есть число дня рождения (1–31) или дата."""
    return any(1 <= int(n) <= 31 for n in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", message))


LINK_RE = re.compile(r"(https?://\S+|t\.me/\S+|@Numeritabot\b)", re.I)


def finish_reply(text: str) -> str:
    """Обрезает слишком длинный ответ и вычищает любые ссылки — в ответах их быть не должно."""
    body = re.sub(r"[ \t]{2,}", " ", LINK_RE.sub("", text.replace("{LINK}", ""))).strip()
    if len(body) > MAX_REPLY_LENGTH:
        body = body[: MAX_REPLY_LENGTH - 1].rsplit(" ", 1)[0] + "…"
    return body


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

            if await db.replies_to_author(author, now - timedelta(days=1)) >= PER_AUTHOR_PER_DAY:
                await db.record_comment(comment["id"], post_id, author, comment["message"], "", "skipped")
                continue
            # Ссылка — только по просьбе и в пределах лимитов; кто написал своё число — зовём в профиль.
            mode = "profile" if gave_number(comment["message"]) else "plain"
            paused = await db.kv_get("reply_links_paused_until")
            links_ok = (
                not (paused and now < datetime.fromisoformat(paused))
                and await db.link_replies(now - timedelta(hours=1)) < LINKS_PER_HOUR
                and not await db.link_replies(now - timedelta(days=7), author)
            )
            if links_ok and asks_link(comment["message"]):
                mode = "link"
            elif (links_ok and mode == "profile" and random.random() < OFFER_SHARE
                    and await db.link_replies(now - timedelta(hours=1), pattern="%_p") < OFFERS_PER_HOUR):
                mode = "offer"
            try:
                text = (await generator.write_reply(post_text, comment["message"], author, mode)).strip()
            except GenerationError as e:
                log.warning("Не удалось написать ответ на комментарий %s: %s", comment["id"], e)
                await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} нейросеть: {e}")
                return sent

            if text.upper().strip(" .!\"'«»") == "SKIP":
                await db.record_comment(comment["id"], post_id, author, comment["message"], "", "skipped")
                continue
            text = finish_reply(text)
            # Одинаковые ответы Threads считает спамом: похожий на недавний — переписываем или пропускаем.
            recent = {(r.get("reply") or "")[:60] for r in await db.recent_comments(50)}
            if text[:60] in recent:
                try:
                    text = finish_reply(await generator.write_reply(post_text, comment["message"], author, mode))
                except GenerationError:
                    continue
                if text[:60] in recent:
                    continue
            if mode in ("link", "offer"):
                text = f"{text[: MAX_REPLY_LENGTH - 45]}\n{BOT_LINK}r{post_id or 0}_{'a' if mode == 'link' else 'p'}"
            if sent:
                await asyncio.sleep(random.uniform(*PAUSE))

            try:
                await threads.reply(target_id, comment["id"], text)
            except ThreadsError as e:
                log.warning("Не удалось ответить на комментарий %s: %s", comment["id"], e)
                if mode in ("link", "offer"):  # стоп-кран: Threads не принял ответ со ссылкой
                    await db.kv_set("reply_links_paused_until", (now + LINK_PAUSE).isoformat())
                    e = ThreadsError(f"{e} — ссылки в ответах выключил на 7 дней")
                await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} ответ: {e}")
                continue
            await db.record_comment(comment["id"], post_id, author, comment["message"], text, "replied")
            await db.kv_set("autoreply_error", "")
            log.info("Ответ @%s под постом %s", author, target_id)
            sent += 1
            if sent >= budget:
                return sent
    return sent
