"""Ролик по команде пульта {"action": "reel", ...} (слово владельца 09.11.2026: «ты сама генерируешь через OpenRouter, мне ничего копировать не надо»).
Grok Imagine Video (OpenRouter) из канонического кадра Нумерты: речь и звук модели, 9:16, 480p. Результат — владельцу в Telegram на проверку (публикуем по его слову).
Деньги: смета seconds × PRICE_PER_SEC; жёсткий потолок CEILING_USD на команду; номер задания сохраняется сразу, повтор после перезапуска не платит заново."""
import asyncio
import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)
API = "https://openrouter.ai/api/v1"
MODEL = "x-ai/grok-imagine-video-1.5-lite"
PRICE_PER_SEC = 0.031  # по смете приветственных роликов: $0,46 за 15 с
CEILING_USD = 0.20
ASSETS = Path(__file__).resolve().parent.parent / "assets"


async def make(db, api_key: str, threads, cmd: dict, send_video, notify) -> None:
    key = f"reel:job:{cmd['id']}"
    seconds = max(3, min(int(cmd.get("seconds") or 5), 8))
    estimate = seconds * PRICE_PER_SEC
    if estimate > CEILING_USD:
        await notify(f"⚠️ Ролик не заказан: смета ${estimate:.2f} выше потолка ${CEILING_USD:.2f}.")
        return
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=120) as http:
        jid = await db.kv_get(key)
        if jid == "failed":
            await notify("ℹ️ Этот ролик уже не получился, повторно не заказываю.")
            return
        if not jid:
            frame = (ASSETS / (cmd.get("image") or "numerita_angel.jpg")).read_bytes()
            frame_url = await threads.upload_image(frame, "reel_frame.jpg")
            body = {"model": cmd.get("model") or MODEL, "prompt": cmd["prompt"], "duration": seconds,
                    "resolution": cmd.get("resolution") or "480p", "aspect_ratio": "9:16",
                    "frame_images": [{"type": "image_url", "image_url": {"url": frame_url}, "frame_type": "first_frame"}]}
            r = await http.post(f"{API}/videos", json=body, headers=headers)
            if r.status_code >= 400:
                await db.kv_set(key, "failed")
                await notify(f"⚠️ Ролик не заказан: {r.status_code} {r.text[:200]}")
                return
            jid = r.json()["id"]
            await db.kv_set(key, jid)  # сразу: повтор после перезапуска не платит заново
            await notify(f"🎬 Ролик заказан: {seconds} с, 480p, смета ≈${estimate:.2f}. Пришлю сюда, когда будет готов (минуты).")
        for _ in range(90):
            st = (await http.get(f"{API}/videos/{jid}", headers=headers)).json()
            if st.get("status") == "completed":
                cost = float((st.get("usage") or {}).get("cost") or estimate)
                v = await http.get(f"{API}/videos/{jid}/content", headers=headers, follow_redirects=True)
                v.raise_for_status()
                await send_video(v.content, f"🎬 Ролик готов. Стоимость по факту ${cost:.2f}. Лицо, нимб и губы — как вам? «Выкладывай» или «переделай».")
                return
            if st.get("status") in ("failed", "cancelled", "expired"):
                await db.kv_set(key, "failed")
                await notify(f"⚠️ Ролик не получился: {st.get('error') or st.get('status')}")
                return
            await asyncio.sleep(10)
    await notify("⚠️ Ролик не готов за 15 минут; номер задания сохранён, заберу при следующем запуске команды.")
