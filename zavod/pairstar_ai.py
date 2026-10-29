"""«Звезда пары» с кульминацией, нарисованной нейросетью (слово владельца 29.10.2026: «нарисуй в чём-нибудь
недешёвом — посмотрим, как это влияет; лимит 50 центов»).

Однократно: google/gemini-3-pro-image (≈$0,15 за кадр, не больше двух попыток и $0,50 всего) рисует финальный кадр —
литую золотую 5 в рождающейся звезде между двумя сферами из цифр; код собирает видео (pairstar3d: начало — наши сферы,
с 10-й секунды — картина с наездом и живыми искрами, наша партитура) и присылает владельцу на одобрение вместе с ценой.
Публикация — только после «да» владельца.
"""

import asyncio
import io
import logging

import httpx
from PIL import Image

from .sketch import API_URL

log = logging.getLogger(__name__)

KEY = "pairstar:ai:v1"
MODEL = "google/gemini-3-pro-image"
BUDGET = 0.50
PROMPT = (
    "Ultra-luxurious cinematic cosmic artwork, vertical 4:5. Center: a newborn radiant star holding a single ornate "
    "numeral 5 cast in polished solid gold, elegant high-contrast Didone (Bodoni-style) serif, soft metallic "
    "reflections, delicate anamorphic lens flare and fine golden dust. Behind it two large translucent spheres made of "
    "thousands of tiny glowing numerals overlap: the left sphere warm gold, the right sphere sapphire blue; the light "
    "of their intersection flows into the star. Deep space with distant spiral galaxies and twinkling stars, rich navy "
    "and violet palette, jewellery-advertisement quality. Keep the top 15% and bottom 28% of the image as calm dark "
    "space for captions. No other text, letters or logos — only the single numeral 5."
)


async def draw(api_key: str) -> tuple[bytes, float]:
    import base64
    body = {"model": MODEL, "modalities": ["image", "text"], "image_config": {"aspect_ratio": "4:5"},
            "usage": {"include": True}, "messages": [{"role": "user", "content": PROMPT}]}
    async with httpx.AsyncClient(timeout=180) as http:
        r = await http.post(API_URL, json=body, headers={"Authorization": f"Bearer {api_key}",
                                                         "X-Title": "Numerita Threads"})
        r.raise_for_status()
        data = r.json()
    url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
    return base64.b64decode(url.split(",", 1)[1]), float((data.get("usage") or {}).get("cost") or 0)


async def run_once(db, api_key: str, send_video) -> None:
    """send_video(bytes, caption) — владельцу. Однократно (kv), бюджет $0,50."""
    if not api_key or await db.kv_get(KEY):
        return
    await db.kv_set(KEY, "started")
    spent, art = 0.0, None
    for _ in range(2):
        if spent + 0.2 > BUDGET:
            break
        try:
            raw, cost = await draw(api_key)
            spent += cost or 0.15
            art = Image.open(io.BytesIO(raw)).convert("RGB")
            break
        except Exception as e:  # сеть, модель, пустой ответ — одна повторная попытка
            spent += 0.0
            log.warning("Звезда пары (нейросеть): не нарисовалось: %s", e)
    if art is None:
        await db.kv_set(KEY, f"failed ${spent:.2f}")
        return
    from .pairstar3d import render_video
    data = await asyncio.to_thread(render_video, 6, 8, 15.0, art)
    await send_video(data, f"✨ Звезда пары — вариант с нейросетью ({MODEL}), потрачено ${spent:.2f}. "
                           "Начало — наши сферы из цифр, финал — нарисованный кадр. Публиковать? Ответь Claude «да».")
    await db.kv_set(KEY, f"sent ${spent:.2f}")
