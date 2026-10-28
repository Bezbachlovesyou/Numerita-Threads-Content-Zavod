"""Instagram Нумериты (слово владельца 28.10.2026: «попробуем Инстаграм вести от имени Нумериты»).

Первый шаг — без новых трат: лучшие посты Threads (по лайкам и комментариям, как для Telegram-канала) через
3–72 часа уходят в Instagram картинкой-карточкой «ночь и золото» (cards.py, $0) с подписью и призывом
«ссылка в шапке» — в подписях Instagram ссылки не кликабельны. Аккаунт Instagram бот находит в Zernio сам
(или берёт ZERNIO_INSTAGRAM_ACCOUNT_ID). Не больше 2 постов в день, с паузой 5 часов, днём.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from . import tgchannel
from .autopost import strip_credits
from .threads_api import ThreadsError

log = logging.getLogger(__name__)

PER_DAY = 2
GAP = timedelta(hours=5)
HOURS = range(10, 22)
MIN_AGE, MAX_AGE = timedelta(hours=3), timedelta(hours=72)
MIN_SCORE = 3
BIO_LINK = "t.me/Numeritabot?start=ad_ig_bio"  # её владелец ставит в шапку профиля Instagram
TAGS = "#нумерология #числосудьбы #астрология #нумерита #саморазвитие"
CTA = "🔮 Твой разбор по дате рождения за 10 секунд — ссылка в шапке профиля @numerita.ai"


async def account_id(db, client) -> str | None:
    """ID аккаунта Instagram в Zernio: переменная, сохранённый или найденный в списке подключённых аккаунтов."""
    env = os.getenv("ZERNIO_INSTAGRAM_ACCOUNT_ID", "").strip()
    if env:
        return env
    saved = await db.kv_get("ig:account:verified")
    if saved:
        return saved
    last = await db.kv_get("ig:lookup")  # не спрашиваем Zernio чаще раза в час
    now = datetime.now(timezone.utc)
    if last and now - datetime.fromisoformat(last) < timedelta(hours=1):
        return None
    await db.kv_set("ig:lookup", now.isoformat())
    try:
        _, payload = await client._request("GET", "/accounts")
    except ThreadsError as e:
        log.warning("Zernio: список аккаунтов недоступен: %s", e)
        return None
    accounts = payload if isinstance(payload, list) else payload.get("accounts") or payload.get("data") or []
    matches = []
    for acc in accounts:
        handle = str(acc.get("username") or acc.get("handle") or "").lstrip("@").lower()
        if (acc.get("platform") or "").lower() == "instagram" and handle == "numerita.ai":
            ident = acc.get("_id") or acc.get("id") or acc.get("accountId")
            if ident:
                matches.append(ident)
    if len(matches) != 1:
        log.warning("Instagram destination is not uniquely verified; set the confirmed account ID")
        return None
    await db.kv_set("ig:account:verified", matches[0])
    return matches[0]


def caption(post) -> str:
    from .bot import LINK_LINE
    text = tgchannel.no_grid_word(strip_credits(post.text))
    text = "\n".join(line.rstrip() for line in LINK_LINE.sub("", text).splitlines()).strip()
    return f"{text}\n\n{CTA}\n\n{TAGS}"[:2200]


def image(post) -> bytes:
    """Матрица — своей картинкой; остальное — карточкой из текста поста."""
    grid = tgchannel.grid_image(post)
    if grid:
        return grid
    from .cards import card_from_text, render_card
    return render_card(card_from_text(post.text), f"ig-{post.id}")


async def pick(db, now: datetime):
    best, best_score = None, MIN_SCORE - 1
    for post in await db.recent_published(now - MAX_AGE):
        if now - post.published_at < MIN_AGE or await db.kv_get(f"ig:posted:{post.id}"):
            continue
        raw = await db.kv_get(f"performance:{post.id}:latest")
        if not raw:
            continue  # нет замера — не ноль; ждём
        s = tgchannel.score(json.loads(raw))
        if s > best_score:
            best, best_score = post, s
    return best


async def publish(client, account: str, text: str, image_url: str) -> str:
    body = {"content": text, "mediaItems": [{"type": "image", "url": image_url}],
            "platforms": [{"platform": "instagram", "accountId": account}], "publishNow": True}
    _, payload = await client._request("POST", "/posts", json=body)
    post = payload.get("post") or {}
    if post.get("status") == "failed":
        reasons = [p.get("errorMessage") for p in post.get("platforms") or [] if p.get("errorMessage")]
        raise ThreadsError("Instagram отклонил пост: " + ("; ".join(reasons) or "без причины"))
    return post.get("_id", "")


async def tick(db, client, tz, notify) -> None:
    """Раз в проход планировщика. notify(text) — сообщение владельцу (первый пост и ошибки, не чаще раза в день)."""
    if client is None:
        return
    now = datetime.now(tz)
    if now.hour not in HOURS:
        return
    day_key = f"ig:{now.date().isoformat()}"
    done = json.loads(await db.kv_get(day_key) or "[]")
    last = await db.kv_get("ig:last")
    if len(done) >= PER_DAY or (last and now.astimezone(timezone.utc) - datetime.fromisoformat(last) < GAP):
        return
    account = await account_id(db, client)
    if not account:
        return
    post = await pick(db, now.astimezone(timezone.utc))
    if post is None:
        return
    await db.kv_set("ig:last", now.astimezone(timezone.utc).isoformat())  # сбой не повторяем каждую минуту
    try:
        data = await asyncio.to_thread(image, post)
        url = await client.upload_image(data, f"numerita_ig_{post.id}.jpg")
        ig_id = await publish(client, account, caption(post), url)
    except ThreadsError as e:
        if await db.claim_slot(f"ig error {now.date().isoformat()}"):
            await notify(f"⚠️ Instagram: пост не вышел — {e}")
        return
    await db.kv_set(f"ig:posted:{post.id}", ig_id or "published")
    await db.kv_set(day_key, json.dumps(done + [post.id]))
    if await db.claim_slot("ig first post"):
        await notify("📸 Первый пост в Instagram вышел. Дальше — до 2 в день, лучшие из Threads.\n"
                     f"Поставь в шапку профиля Instagram ссылку: {BIO_LINK}")
