"""Говорящие рилсы Нумериты из ленты основного бота (слово владельца 30.10.2026, через сессию основного бота).

Основной бот снимает ролики сам и отдаёт ленту https://www.numerita.ru/reels/feed.json → [{id, day, lang, topic, hook,
caption, lines, url}]. Каждый экземпляр завода берёт ролики своего языка и публикует через Zernio туда, где аккаунт уже
подключён: Instagram своего языка (RU numerita.ai, EN numerita.love), YouTube Shorts, а английский — ещё и TikTok.
Новые аккаунты в Zernio платные — сами не подключаем. Публикация включается командой пульта reels_on (kv reels:on),
пока владелец не убедился в качестве роликов. Каждый ролик — один раз (claim reel:<id>:<площадка>).
"""

import logging
import time

import httpx

from . import instagram
from .lang import is_en

log = logging.getLogger(__name__)
FEED = "https://www.numerita.ru/reels/feed.json"
EVERY = 900
_last: float | None = None


async def feed() -> list[dict]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
        r = await http.get(FEED)
    if r.status_code != 200:
        return []
    data = r.json()
    return [x for x in data if isinstance(x, dict) and x.get("id") and x.get("url")] if isinstance(data, list) else []


async def platform_account(client, platform: str) -> str | None:
    _, payload = await client._request("GET", "/accounts")
    accounts = payload.get("accounts") or payload.get("data") or (payload if isinstance(payload, list) else [])
    for acc in accounts:
        if (acc.get("platform") or "").lower() == platform:
            return acc.get("_id") or acc.get("id")
    return None


def caption(item: dict, platform: str) -> str:
    text = (item.get("caption") or item.get("hook") or "").strip()
    tag = f"ad_{'en_' if is_en() else ''}{'yt' if platform == 'youtube' else 'tt' if platform == 'tiktok' else 'ig'}_reel"
    if platform == "instagram":
        tail = "Link in bio ✨" if is_en() else "Ссылка — в шапке профиля ✨"
        tags = ("#numerology #astrology #birthday #numerita" if is_en()
                else "#нумерология #астрология #датарождения #нумерита")
        return f"{text}\n\n{tail}\n\n{tags}"[:2200]
    return f"{text}\n\nt.me/Numeritabot?start={tag}"[:2200]


async def tick(db, client, notify) -> None:
    global _last
    if _last is not None and time.monotonic() - _last < EVERY:
        return
    _last = time.monotonic()
    if await db.kv_get("reels:on") != "1":
        return
    lang = "en" if is_en() else "ru"
    try:
        items = [x for x in await feed() if (x.get("lang") or "ru") == lang]
    except Exception as e:
        log.warning("Лента рилсов не прочитана: %s", e)
        return
    targets = ["instagram", "youtube"] + (["tiktok"] if is_en() else [])
    for item in items[:3]:
        for platform in targets:
            if await db.kv_get(f"reel:{item['id']}:{platform}"):
                continue
            account = (await instagram.account_id(db, client) if platform == "instagram"
                       else await platform_account(client, platform))
            if not account:
                continue
            await db.kv_set(f"reel:{item['id']}:{platform}", "claimed")  # вслепую не повторяем
            try:
                async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
                    data = (await http.get(item["url"])).content
                url = await client.upload_image(data, f"reel_{item['id']}.mp4", "video/mp4")
                target = {"platform": platform, "accountId": account}
                if platform == "youtube":
                    target["platformSpecificData"] = {"title": (item.get("hook") or "Numerita")[:95]}
                _, payload = await client._request("POST", "/posts", json={
                    "content": caption(item, platform), "mediaItems": [{"type": "video", "url": url}],
                    "platforms": [target], "publishNow": True})
                status = (payload.get("post") or payload).get("status") or "?"
                await db.kv_set(f"reel:{item['id']}:{platform}", status)
                await notify(f"{'[EN] ' if is_en() else ''}🎬 Рилс «{(item.get('hook') or item['id'])[:40]}» → {platform}: {status}")
            except Exception as e:
                log.exception("Рилс %s в %s не ушёл", item["id"], platform)
                await notify(f"⚠️ Рилс в {platform} не ушёл: {e}")
