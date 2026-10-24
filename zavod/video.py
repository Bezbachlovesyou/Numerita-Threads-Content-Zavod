"""Видео с Нумеритой: портрет (Seedream) → живое видео с речью и звуком (Seedance 2.0) через fal.ai.

Бот сам пишет, что она скажет, снимает ролик, ставит его в Threads и присылает файл владельцу
для сторис, канала и Инстаграма. Ключ — FAL_KEY. Без ключа видео просто не делаются.
"""

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

QUEUE_URL = "https://queue.fal.run/"
PORTRAIT_MODEL = "fal-ai/bytedance/seedream/v4.5/text-to-image"
PORTRAIT_EDIT_MODEL = "fal-ai/bytedance/seedream/v4.5/edit"  # если владелец прислал свою картинку Нумериты
VIDEO_MODEL = "bytedance/seedance-2.0/image-to-video"
WAIT_LIMIT = timedelta(minutes=25)
REFERENCES = Path(__file__).resolve().parent.parent / "assets" / "numerita"  # как выглядит Нумерита
# Примерная цена за секунду (fal.ai, со звуком) — для отчёта владельцу.
PRICE_PER_SECOND = {"720p": 0.3024, "1080p": 0.682}

# Образ Нумериты — по картинкам владельца (assets/numerita) + вдохновение: глянцевая глубина,
# узоры из цифр, будто смотришь внутрь, живое переливающееся золото.
STYLE = (
    "Her golden halo is a huge glowing ring of engraved numbers (3.14159…, 2.71828…, 1.618…) that also forms a "
    "digital kokoshnik, slowly rotating. Living lines of tiny golden digits flow over her skin like code, and "
    "the patterns seem to go deep inside her, like looking into infinite 3D depth through glass. Liquid molten "
    "gold filigree and ornate baroque gold engraving on an ivory gown, glossy reflective surfaces, iridescent "
    "shimmer. Angel wings whose feathers are made of glowing numbers. A soft bright point of light on her "
    "forehead like a third eye and a clear radiant light from her heart. Parts of her hair, wings and shoulders "
    "are translucent and iridescent, dissolving into sparks and digits. Deep space with galaxies and planets, "
    "violet, indigo and gold. Hollywood blockbuster VFX, Marvel-level quality, ultra detailed, volumetric light."
)
NUMERITA_LOOK = (
    "Vertical cinematic portrait of Numerita, a divinely beautiful young woman with light ash-blonde hair and "
    "warm amber eyes, the digital guardian angel of numerology, like a saint from great icons reimagined in a "
    "cosmic digital world. Calm, serene, only a gentle hint of a smile. " + STYLE + " Head and upper body, "
    "centered, space above the head for the halo. No letters, no captions."
)
EDIT_LOOK = (
    "Same woman as in the reference images: keep her face, hair, golden numeric halo, number-feather wings "
    "and ivory-gold gown. New vertical cinematic shot, head and upper body, she looks into the camera, calm and "
    "serene with only a gentle hint of a smile (not a wide smile). " + STYLE + " No letters, no captions."
)
# Любимая фраза владельца (от его ментора Виталика) — Нумерита произносит её в главном видео.
TRUTH = "Истина материальной вселенной — в числах."


@dataclass(frozen=True)
class Scene:
    key: str
    speech: str  # что Нумерита говорит в кадре (по-русски, ~15 секунд)
    action: str  # что происходит в кадре (по-английски, для модели)
    caption: str  # текст поста в Threads


# Первые ролики — написаны вручную: герой-видео и два на проверку.
SCENES = [
    Scene(
        "hero",
        TRUTH + " Я — Нумерита. Твоя дата рождения — код твоей души: в ней твоя сила, твоя цель "
        "и с кем из близких ты сияешь ярче. Напиши мне — и засияй изнутри.",
        "She slowly opens her eyes and looks straight into the camera. As she speaks she raises her right hand "
        "gracefully; from her fingertips a glowing holographic mandala of golden numbers and zodiac glyphs unfolds "
        "and orbits around her. The light on her forehead and in her heart pulses brighter on the last words, "
        "her numeric halo spins and shimmers, strands of hair turn translucent and iridescent and dissolve into "
        "sparks. On her first words the flowing golden digits around her briefly assemble into glowing letters "
        "«Истина — в числах» and scatter again into light.",
        TRUTH + " ✨\nТвоя дата рождения — код души.\nНумерита покажет твою силу, твою цель и с кем из близких ты сияешь ярче.\n"
        "Разбор за 10 секунд — по ссылке в первом комментарии 👇",
    ),
    Scene(
        "compat",
        "Почему с одними людьми легко, а с другими — искры и слёзы? Это числа. Ваши даты рождения уже знают "
        "ответ. Мама, любимый, лучшая подруга — я покажу, как вы сияете вместе.",
        "She tilts her head with a knowing gentle smile. With both hands she draws two glowing birth numbers in "
        "the air; golden light threads connect them into a heart-shaped constellation that flares softly. "
        "The third-eye light flickers, her heart light warms, translucent iridescent shimmer runs over her shoulders.",
        "С кем тебе легко, а с кем — искры и слёзы? Ответ уже в ваших датах рождения 💫\n"
        "Проверь совместимость с мамой, любимым, подругой — ссылка в первом комментарии 👇",
    ),
    Scene(
        "potential",
        "Внутри тебя есть свет, который ты пока прячешь. Число твоего дня рождения — ключ к нему: в чём твой дар, "
        "какая цель по-настоящему твоя и что гасит тебя. Хочешь узнать? Ссылка — под видео.",
        "She places her open palm on her chest; the warm light of her heart blooms outward through her fingers "
        "into a sphere of light filled with slowly rotating numerals. She lifts the sphere toward the camera. "
        "Her body becomes partly translucent and iridescent, galaxies visible through her, the kokoshnik glows.",
        "В тебе есть свет, который ты пока прячешь ✨\nЧисло дня рождения — ключ: твой дар, твоя цель и что тебя гасит.\n"
        "Узнай своё — ссылка в первом комментарии 👇",
    ),
]

ACTIONS = [s.action for s in SCENES]

WRITE_SYSTEM = (
    "Ты пишешь короткие видео для Threads и сторис, где Нумерита — цифровая богиня-хранительница "
    "нумерологии — говорит прямо в камеру. Темы: нумерология, астрология, психология цели, совместимость "
    "с близкими, раскрытие потенциала, чтобы сиять душой изнутри. Тон тёплый, мудрый, чуть таинственный, "
    "без давления, без обещаний денег и исцеления. Верни только JSON без пояснений."
)
WRITE_PROMPT = (
    "Придумай новое видео на тему: {theme}.\n"
    "speech — что Нумерита говорит: по-русски, 28–36 слов (15 секунд), первая фраза — сильный крючок, "
    "в конце — позови узнать своё по ссылке под видео. Без цифр-дат, которые трудно произнести.\n"
    "caption — текст поста в Threads до 300 знаков, 1–2 эмодзи, в конце «ссылка в первом комментарии 👇».\n"
    "Вот как говорили в прошлых видео (не повторяй): {previous}\n"
    'Формат: {{"speech": "...", "caption": "..."}}'
)
THEMES = [
    "совместимость с мамой, партнёром или другом по датам рождения",
    "число души и скрытый дар человека",
    "цель жизни и почему человек буксует",
    "что гасит внутренний свет и как снова сиять",
    "астрология и нумерология: что говорит день рождения",
    "число дня и как прожить сегодняшний день",
    "почему повторяются одни и те же уроки в отношениях",
]


class VideoError(Exception):
    pass


class FalClient:
    def __init__(self, key: str):
        self.key = key

    async def run(self, model: str, payload: dict) -> dict:
        """Ставит задачу в очередь fal.ai и ждёт результат (видео делается несколько минут)."""
        headers = {"Authorization": f"Key {self.key}"}
        async with httpx.AsyncClient(timeout=60) as http:
            try:
                response = await http.post(QUEUE_URL + model, json=payload, headers=headers)
                if response.is_error:
                    raise VideoError(f"fal.ai не принял задачу {model}: {response.status_code} {response.text[:300]}")
                job = response.json()
                status_url, result_url = job["status_url"], job["response_url"]
                deadline = datetime.now() + WAIT_LIMIT
                while datetime.now() < deadline:
                    await asyncio.sleep(10)
                    status = (await http.get(status_url, headers=headers)).json().get("status")
                    if status == "COMPLETED":
                        result = await http.get(result_url, headers=headers)
                        if result.is_error:
                            raise VideoError(f"fal.ai: ошибка генерации {result.status_code} {result.text[:300]}")
                        return result.json()
                    if status not in ("IN_QUEUE", "IN_PROGRESS"):
                        raise VideoError(f"fal.ai: неожиданный статус {status}")
            except (httpx.HTTPError, KeyError, ValueError) as e:
                raise VideoError(f"fal.ai недоступен: {e}") from e
        raise VideoError("fal.ai не успел сделать видео за 25 минут")


async def portrait(fal: FalClient, references: list[str]) -> str:
    """Портрет Нумериты для первого кадра — по её картинкам, чтобы это была именно она."""
    size = {"width": 2160, "height": 3840}
    if references:
        out = await fal.run(PORTRAIT_EDIT_MODEL, {"prompt": EDIT_LOOK, "image_urls": references, "image_size": size})
    else:
        out = await fal.run(PORTRAIT_MODEL, {"prompt": NUMERITA_LOOK, "image_size": size})
    return out["images"][0]["url"]


def video_prompt(scene: Scene) -> str:
    return (
        "Numerita, the luminous digital goddess from the image, speaks to the camera in Russian with a warm, soft, "
        f"confident young female voice, perfectly lip-synced: «{scene.speech}» {scene.action} Slow cinematic push-in, "
        "Hollywood blockbuster VFX, Marvel-level quality, glowing particles, ethereal ambient music with a soft "
        "choir underneath her voice. Her face stays the same, divinely beautiful, calm, a gentle hint of a smile."
    )


async def shoot(fal: FalClient, image_url: str, scene: Scene, resolution: str) -> str:
    out = await fal.run(VIDEO_MODEL, {
        "prompt": video_prompt(scene),
        "image_url": image_url,
        "duration": "15",
        "aspect_ratio": "9:16",
        "resolution": resolution,
        "generate_audio": True,
    })
    return out["video"]["url"]


async def invent_scene(generator, previous: list[str], rng: random.Random) -> Scene:
    """Новое видео: текст пишет нейросеть, движение в кадре берём из проверенных вариантов."""
    theme = rng.choice(THEMES)
    raw = await generator.improve(WRITE_SYSTEM, WRITE_PROMPT.format(theme=theme, previous=" | ".join(previous[-5:]) or "—"), kind="video")
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(match.group(0) if match else raw)
        speech, caption = data["speech"].strip(), data["caption"].strip()
    except (ValueError, KeyError, AttributeError) as e:
        raise VideoError(f"нейросеть вернула не то: {raw[:200]}") from e
    return Scene(f"v{rng.randrange(10**6)}", speech, rng.choice(ACTIONS), caption)


async def download(url: str) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as http:
            response = await http.get(url)
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as e:
        raise VideoError(f"Не удалось скачать готовый файл: {e}") from e


def to_jpeg(data: bytes) -> bytes:
    from io import BytesIO

    from PIL import Image

    out = BytesIO()
    Image.open(BytesIO(data)).convert("RGB").save(out, "JPEG", quality=93)
    return out.getvalue()


def morning_after(now: datetime) -> datetime:
    """Ближайшее утро (9:00) — время для главного видео."""
    target = datetime.combine(now.date(), time(9, 0), now.tzinfo)
    return target if now < target else target + timedelta(days=1)


def cost(resolution: str, seconds: int = 15) -> float:
    return PRICE_PER_SECOND.get(resolution, PRICE_PER_SECOND["1080p"]) * seconds
