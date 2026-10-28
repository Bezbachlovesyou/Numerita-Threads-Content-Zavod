"""Проба рисованных картинок к постам (слово владельца 28.10.2026: «да, давай делай пробу»).

Стиль — карандашный скетч с лёгкой акварелью на фактурной бумаге: живые выразительные герои, сцена со смыслом,
как у популярных каруселей «картинки с глубоким смыслом» (чужие рисунки не копируем — сцены свои, по нашему посту).
Целомудренно: Нумериту читают и дети. Сцену придумывает нейросеть постов, рисует google/gemini-3-pro-image
(≈$0,15 за картинку), русский заголовок накладывает код — нейросети пишут кириллицу с ошибками.
Проба — однократно 2 картинки к двум лучшим постам; владельцу в личку с ценой. Не больше двух попыток.
"""

import base64
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
IMAGE_MODEL = "google/gemini-3-pro-image"
KEY = "sketch:trial:v1"
FONT = Path(__file__).parent.parent / "assets/fonts/Montserrat.ttf"
W, H = 1080, 1350

STYLE = ("Hand-drawn editorial illustration: expressive pencil sketch with soft muted watercolor tints on textured "
         "dusty-blue paper, realistic characters with vivid emotions and body language, cross-hatching shadows, "
         "plain paper background, lots of empty space in the lower third for a title. Modest, elegant everyday "
         "clothing, family-friendly, no nudity, no cleavage. Absolutely no text, letters, numbers or logos in the image.")

SCENE_SYSTEM = (
    "Ты — арт-директор Нумериты. По тексту поста придумай ОДНУ визуальную сцену-метафору с 1–4 героями, которая "
    "без слов передаёт смысл и юмор поста, как карикатура с глубоким смыслом. Добрая ирония, без унижения людей, без "
    "мистики-страшилок, без политики. Герои одеты скромно и красиво. Ответ строго JSON: "
    '{"scene": "описание сцены по-английски, 40–70 слов, только что видно на картинке", '
    '"title": "заголовок для картинки по-русски, 2–5 слов, цепляющий, без кавычек"}')


def parse(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        return json.loads(match.group(0)) if match else {}
    except ValueError:
        return {}


async def draw(http: httpx.AsyncClient, api_key: str, scene: str) -> tuple[bytes, float]:
    body = {"model": IMAGE_MODEL, "modalities": ["image", "text"], "image_config": {"aspect_ratio": "4:5"},
            "usage": {"include": True},
            "messages": [{"role": "user", "content": f"{STYLE}\n\nScene: {scene}"}]}
    r = await http.post(API_URL, json=body, headers={"Authorization": f"Bearer {api_key}",
                                                     "X-Title": "Numerita Threads"})
    r.raise_for_status()
    data = r.json()
    url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
    return base64.b64decode(url.split(",", 1)[1]), float((data.get("usage") or {}).get("cost") or 0)


def with_title(raw: bytes, title: str) -> bytes:
    """Крупный заголовок плакатным шрифтом внизу картинки, как в каруселях-образцах."""
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img = img.resize((W, round(img.height * W / img.width)), Image.LANCZOS).crop((0, 0, W, H))
    d = ImageDraw.Draw(img)
    words, lines = title.upper().split(), []
    size = 132
    while size > 60:
        font = ImageFont.truetype(str(FONT), size)
        font.set_variation_by_axes([900])
        lines, line = [], ""
        for word in words:
            test = f"{line} {word}".strip()
            if d.textlength(test, font=font) <= W - 140:
                line = test
            else:
                lines.append(line)
                line = word
        lines.append(line)
        if len(lines) <= 3 and all(lines):
            break
        size -= 8
    step = int(size * 1.02)
    y = H - 60 - step * len(lines)
    for i, line in enumerate(lines):
        color = (246, 238, 222) if i % 2 == 0 else (32, 34, 40)
        x = (W - d.textlength(line, font=font)) / 2
        d.text((x + 3, y + 4), line, font=font, fill=(20, 20, 24) if i % 2 == 0 else (246, 238, 222))
        d.text((x, y), line, font=font, fill=color)
        y += step
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


async def best_posts(db, now: datetime, n: int = 2):
    from . import tgchannel
    scored = []
    for post in await db.recent_published(now - timedelta(days=7)):
        raw = await db.kv_get(f"performance:{post.id}:latest")
        if raw and len(post.text.strip()) >= tgchannel.MIN_TEXT and not tgchannel.grid_image(post):
            scored.append((tgchannel.score(json.loads(raw)), post))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:n]]


async def run_trial(db, generator, send_photo) -> None:
    """send_photo(bytes, caption) — владельцу. Однократно, максимум две попытки."""
    state = await db.kv_get(KEY) or ""
    if state == "done" or state.count("fail") >= 2:
        return
    try:
        posts = await best_posts(db, datetime.now(timezone.utc))
        if not posts:
            return  # ещё нет замеров — попробуем в следующий запуск
        async with httpx.AsyncClient(timeout=180) as http:
            for i, post in enumerate(posts, 1):
                plan = parse(await generator.improve(SCENE_SYSTEM, post.text, max_tokens=400, kind="other"))
                if not plan.get("scene"):
                    continue
                raw, cost = await draw(http, generator.api_key, plan["scene"])
                image = with_title(raw, plan.get("title") or "")
                await send_photo(image, f"🎨 Проба {i}/{len(posts)} · картинка ${cost:.2f}\n«{plan.get('title', '')}»\n\n"
                                        f"К посту:\n{post.text[:700]}")
        await db.kv_set(KEY, "done")
    except Exception:
        log.exception("Проба рисованных картинок не удалась")
        await db.kv_set(KEY, state + "fail;")
