"""Картинки к постам: фирменная карточка Нумериты 1080×1350 (формат 4:5 для ленты Threads).

Рисуем сами через Pillow — бесплатно и без нейросетей для картинок:
космический градиент, звёзды, золотое свечение и орбита, крупное число, планета,
цепляющая фраза и призыв — ответить, открыть комментарий или профиль.
"""

import io
import json
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
W, H = 1080, 1350

PLANETS = {1: "Солнце", 2: "Луна", 3: "Юпитер", 4: "Раху", 5: "Меркурий", 6: "Венера", 7: "Кету", 8: "Сатурн", 9: "Марс"}

# (верх, низ, акцент) — глубокие ночные цвета и золото
PALETTES = [
    ((14, 12, 38), (58, 22, 82), (232, 196, 120)),
    ((8, 20, 40), (18, 66, 86), (236, 204, 140)),
    ((24, 10, 34), (92, 30, 76), (244, 190, 150)),
    ((10, 10, 30), (40, 34, 96), (220, 200, 255)),
    ((20, 14, 20), (70, 40, 30), (246, 206, 128)),
]

CTA_TEXT = {
    "reply": "Напиши своё число в ответах",
    "link": "Разбор — в первом комментарии",
    "profile": "Разбор — по ссылке в профиле",
    "none": "Сохрани, чтобы не потерять",
}


@dataclass
class Card:
    hook: str  # цепляющая фраза, до ~8 слов
    number: str | None = None  # крупно в центре: «8», «3 · 6»
    label: str | None = None  # под числом: «САТУРН», «АРКАН»
    cta: str = "none"
    cta_text: str | None = None  # свой текст призыва на кнопке, например для совместимости
    palette: int | None = None  # номер палитры (для самоулучшения картинок); None — по seed
    style: str | None = None  # стиль фразы: intrigue | question
    dates: str | None = None  # дни рождения с этим числом: «7 · 16 · 25» — чтобы человек сразу узнал себя

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(raw: str | None) -> "Card | None":
        data = json.loads(raw) if raw else None
        return Card(**data) if data and "carousel" not in data else None


def carousel_from_json(raw: str | None) -> list[Card] | None:
    data = json.loads(raw) if raw else None
    return [Card(**c) for c in data["carousel"]] if data and "carousel" in data else None


def carousel_json(cards: list[Card]) -> str:
    return json.dumps({"carousel": [asdict(c) for c in cards]}, ensure_ascii=False)


def soul_carousel(numbers: dict, palette: int) -> list[Card]:
    """Карусель «9 чисел души — найди своё»: обложка и по карточке на число (качества — из базы Нумериты)."""
    slides = [Card(
        "Найди своё число души: листай до своей даты", number=None, label="9 чисел души", cta="reply",
        cta_text="Листай →", palette=palette,
    )]
    for digit in range(1, 10):
        qualities = (numbers.get(str(digit)) or {}).get("qualities") or ""
        hook = ", ".join(q.strip() for q in qualities.split(",")[:3]) if qualities else f"Число души {digit}"
        slides.append(Card(
            hook[:1].upper() + hook[1:], number=str(digit), label=PLANETS[digit], cta="reply",
            cta_text="Совпало? Напиши в ответах", palette=palette, dates=birth_days(digit),
        ))
    return slides


def _font(name: str, size: int, weight: str) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / name), size)
    font.set_variation_by_name(weight)
    return font


def _strip_emoji(text: str) -> str:
    return re.sub(r"[\U0001F000-\U0001FFFF☀-➿️‍]", "", text).strip()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) <= width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _gradient(top: tuple, bottom: tuple) -> Image.Image:
    base = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / (H - 1)
        base.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return base.resize((W, H))


def render_card(card: Card, seed: str) -> bytes:
    """JPEG-байты карточки. seed делает звёзды и палитру стабильными для одного поста."""
    rng = random.Random(seed)
    index = rng.randrange(len(PALETTES))
    top, bottom, accent = PALETTES[card.palette % len(PALETTES) if card.palette is not None else index]
    img = _gradient(top, bottom).convert("RGBA")

    # Свечение за числом.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = W // 2, 420
    gd.ellipse((cx - 330, cy - 330, cx + 330, cy + 330), fill=accent + (70,))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(120)))

    # Звёзды.
    stars = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stars)
    for _ in range(170):
        x, y, r = rng.randrange(W), rng.randrange(H), rng.choice((1, 1, 1, 2, 2, 3))
        sd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rng.randrange(60, 220)))
    img = Image.alpha_composite(img, stars)

    draw = ImageDraw.Draw(img)
    # Орбита с «планетой».
    ring = 270
    draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=accent + (150,), width=3)
    draw.ellipse((cx - ring - 40, cy - ring - 40, cx + ring + 40, cy + ring + 40), outline=accent + (45,), width=2)
    angle = rng.uniform(0, 6.283)
    import math

    px, py = cx + ring * math.cos(angle), cy + ring * math.sin(angle)
    draw.ellipse((px - 14, py - 14, px + 14, py + 14), fill=accent + (255,))

    # Число или звезда в центре.
    if card.number:
        size = 330 if len(card.number) <= 2 else 210
        font = _font("PlayfairDisplay.ttf", size, "Bold")
        box = draw.textbbox((0, 0), card.number, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        draw.text((cx - tw / 2 - box[0], cy - th / 2 - box[1]), card.number, font=font, fill=accent + (255,))
    else:
        points = []
        for i in range(16):
            r = 140 if i % 2 == 0 else 42
            a = math.pi / 8 * i - math.pi / 2
            points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        draw.polygon(points, fill=accent + (255,))

    y = cy + ring + 60
    if card.label:
        font = _font("Montserrat.ttf", 34, "SemiBold")
        label = " ".join(card.label.upper())  # разрядка
        draw.text((cx, y), label, font=font, fill=accent + (235,), anchor="ma")
        y += 60
    if card.dates:
        font = _font("Montserrat.ttf", 30, "Medium")
        draw.text((cx, y), f"родились {card.dates}", font=font, fill=(255, 255, 255, 200), anchor="ma")
        y += 58
    elif card.label:
        y += 6

    # Цепляющая фраза: крупно; уменьшаем, пока не влезет между подписью и кнопкой, и центрируем.
    hook = _strip_emoji(card.hook)
    space = (H - 230) - y
    for size in (76, 68, 60, 54, 48, 42, 38):
        font = _font("PlayfairDisplay.ttf", size, "SemiBold")
        lines = _wrap(draw, hook, font, W - 150)
        line_h = int(size * 1.2)
        if len(lines) <= 4 and len(lines) * line_h <= space:
            break
    lines = lines[:4]
    y += max(0, (space - len(lines) * line_h) // 2)
    for line in lines:
        draw.text((cx, y), line, font=font, fill=(255, 255, 255, 255), anchor="ma")
        y += line_h

    # Призыв — «таблетка» внизу.
    cta = card.cta_text or CTA_TEXT.get(card.cta, CTA_TEXT["none"])
    font = _font("Montserrat.ttf", 34, "SemiBold")
    tw = draw.textlength(cta, font=font)
    bx0, by0, bx1, by1 = cx - tw / 2 - 40, H - 190, cx + tw / 2 + 40, H - 120
    draw.rounded_rectangle((bx0, by0, bx1, by1), radius=35, fill=accent + (255,))
    draw.text((cx, (by0 + by1) / 2), cta, font=font, fill=top + (255,), anchor="mm")

    font = _font("Montserrat.ttf", 28, "Medium")
    draw.text((cx, H - 70), "@numerita.ai", font=font, fill=(255, 255, 255, 170), anchor="mm")

    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


def card_from_text(text: str, cta: str | None = None) -> Card:
    """Карточка для готового или ручного поста: первая фраза, планета, если названа, и подходящий призыв."""
    cta_text = None
    if cta is None:
        lowered = text.lower()
        if "t.me/" in lowered:
            cta, cta_text = "link", "Разбор — по ссылке в посте"
        elif "?" in text or "напиш" in lowered or "ответ" in lowered:
            cta = "reply"
            cta_text = "Ответь в комментариях" if "напиши" not in lowered or "числ" not in lowered else None
        else:
            cta = "none"
    first = re.split(r"(?<=[.!?…])\s|\n", _strip_emoji(text).strip(), maxsplit=1)[0]
    first = first.split(" — ")[0] if len(first) > 70 else first
    if len(first) > 90:
        first = first[:88].rsplit(" ", 1)[0] + "…"
    digit = next((d for d, name in PLANETS.items() if name.lower() in text.lower()), None)
    return Card(
        hook=first, number=str(digit) if digit else None, label=PLANETS.get(digit), cta=cta, cta_text=cta_text,
        dates=birth_days(digit) if digit else None,
    )


def birth_days(digit: int) -> str:
    """Дни рождения с этим числом души: 7 → «7 · 16 · 25»."""
    return " · ".join(str(d) for d in range(1, 32) if (d - 1) % 9 + 1 == digit)
