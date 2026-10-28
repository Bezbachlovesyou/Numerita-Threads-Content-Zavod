"""Картинки к постам: фирменная карточка Нумериты 1080×1350 (формат 4:5 для ленты Threads).

Рисуем сами через Pillow — бесплатно и без нейросетей для картинок:
космический градиент, звёзды, золотое свечение и орбита, крупное число, планета,
цепляющая фраза и призыв — ответить, открыть комментарий или профиль.
"""

import io
import math
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
    "reply": "Напиши число — отвечу лично",
    "link": "Разбор — в первом комментарии",
    "profile": "Разбор — по ссылке в профиле",
    "none": "Напиши — отвечу лично",
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
        return Card(**data) if data and not {"carousel", "grid", "video"} & data.keys() else None


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


FOOTER = "Telegram · @Numeritabot"  # куда идти за разбором — на каждой картинке (слово владельца 24.10.2026)


def _footer(draw: ImageDraw.ImageDraw, cx: float) -> None:
    """Подпись внизу картинки: значок Telegram и @Numeritabot — чтобы человек знал, где найти Нумериту."""
    font = _font("Montserrat.ttf", 32, "SemiBold")
    tw = draw.textlength(FOOTER, font=font)
    r = 19
    x0 = cx - (tw + 2 * r + 14) / 2
    y = H - 68
    draw.ellipse((x0, y - r, x0 + 2 * r, y + r), fill=(42, 171, 238, 255))  # кружок цвета Telegram
    ox, oy = x0 + r, y
    draw.polygon([(ox - 10, oy - 1), (ox + 10, oy - 8), (ox + 6, oy + 9), (ox + 1, oy + 3)], fill=(255, 255, 255, 255))
    draw.polygon([(ox - 10, oy - 1), (ox + 1, oy + 3), (ox - 2, oy + 9)], fill=(214, 236, 250, 255))
    draw.text((x0 + 2 * r + 14, y), FOOTER, font=font, fill=(255, 255, 255, 235), anchor="lm")


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

    _footer(draw, cx)

    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


def card_from_text(text: str, cta: str | None = None) -> Card:
    """Карточка для готового или ручного поста: первая фраза, планета, если названа, и подходящий призыв."""
    cta_text = None
    if cta is None:
        lowered = text.lower()
        # Крючок в комментарии важнее ссылки: каждый пост зовёт ответить (слово владельца 24.10.2026).
        if "?" in text or "напиш" in lowered or "ответ" in lowered:
            cta = "reply"
            cta_text = "Напиши — отвечу лично" if "напиши" not in lowered or "числ" not in lowered else None
        elif "t.me/" in lowered:
            cta, cta_text = "link", "Разбор — по ссылке в посте"
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


# ---------- Головоломка «Какие числа ты видишь первыми?» ----------

# «Ангельские» и сильные сочетания, которые прячем в сетке. 666 не берём — пугает.
SEQUENCES = ["111", "222", "333", "444", "555", "777", "888", "999", "1111", "1212", "1010", "2222", "1234", "2828", "1717"]
GRID_COLS, GRID_ROWS = 12, 14


def make_grid(rng: random.Random, count: int = 7, style: str = "classic") -> dict:
    """Сетка цифр со спрятанными сочетаниями: {"rows": [...], "marks": [[r, c], ...], "hidden": [...]}."""
    if style in SHAPES:
        return make_shape(rng, style, count)
    grid = [[None] * GRID_COLS for _ in range(GRID_ROWS)]
    marks, hidden = set(), []
    for seq in rng.sample(SEQUENCES, len(SEQUENCES)):
        if len(hidden) >= count:
            break
        for _ in range(60):  # ищем место без пересечений
            vertical = rng.random() < 0.35
            r = rng.randrange(GRID_ROWS - (len(seq) if vertical else 0))
            c = rng.randrange(GRID_COLS - (0 if vertical else len(seq)))
            cells = [(r + i, c) if vertical else (r, c + i) for i in range(len(seq))]
            if all(grid[y][x] is None for y, x in cells):
                for (y, x), ch in zip(cells, seq):
                    grid[y][x] = ch
                    marks.add((y, x))
                hidden.append(seq)
                break
    for y in range(GRID_ROWS):
        for x in range(GRID_COLS):
            if grid[y][x] is None:
                grid[y][x] = str(rng.randrange(10))
    return {"style": "classic", "rows": ["".join(row) for row in grid], "marks": sorted(marks), "hidden": hidden}


# Формы матрицы (слово владельца 28.10.2026: «чередуй матрицу в разных красивых стилях, крути, вращай числа,
# пускай необычными формами»). Цифры идут одной лентой по линии формы, спрятанные сочетания — подряд по линии.
SHAPES = {
    "spiral": ("Какое число вынырнет из спирали первым?", "Спираль чисел: читай по завитку от центра"),
    "rings": ("Какое число на кольцах поймало твой взгляд?", "Кольца чисел: читай по кругу"),
    "heart": ("Какое число в сердце ты увидишь первым?", "Сердце из чисел: читай по контурам"),
    "wave": ("Какое число вынесла к тебе волна?", "Волны чисел: читай слева направо"),
    "galaxy": ("Какое число светит тебе из галактики?", "Галактика чисел: читай по рукавам от центра"),
    # Оптические иллюзии только из цифр: спираль Фрейзера (1908) — ровные круги кажутся спиралью;
    # «вращающиеся змеи» Акиёси Китаоки (2003) — неподвижные кольца будто вращаются.
    "fraser": ("Это круги или спираль? И какое число ты увидел первым?",
               "Иллюзия Фрейзера из цифр: ровные кольца, наклонённые цифры делают их похожими на спираль"),
    "drift": ("Кольца будто плывут? Какое число видишь первым?",
              "Иллюзия Китаоки «вращающиеся змеи» из цифр: неподвижные кольца кажутся вращающимися"),
}
# Цветовая лестница «змей» Китаоки: тёмный → синий → белый → жёлтый.
DRIFT_COLORS = [(18, 18, 30), (50, 100, 230), (250, 250, 250), (250, 205, 40)]
GRID_STYLES = ["classic", *SHAPES]


def make_shape(rng: random.Random, style: str, count: int = 7) -> dict:
    n = len(_shape_points(style))
    digits: list[str | None] = [None] * n
    marks, hidden = set(), []
    for seq in rng.sample(SEQUENCES, len(SEQUENCES)):
        if len(hidden) >= count:
            break
        for _ in range(60):
            start = rng.randrange(n - len(seq))
            cells = range(start, start + len(seq))
            if all(digits[i] is None for i in cells) and start - 1 not in marks and start + len(seq) not in marks:
                for i, ch in zip(cells, seq):
                    digits[i] = ch
                    marks.add(i)
                hidden.append(seq)
                break
    text = "".join(d if d is not None else str(rng.randrange(10)) for d in digits)
    return {"style": style, "digits": text, "marks": sorted(marks), "hidden": hidden}


def _arc_sample(curve, count: int, steps: int = 4000) -> list[tuple[float, float, float]]:
    """Равномерно по длине кривой: (x, y, угол касательной в градусах для поворота надписи)."""
    pts = [curve(i / steps) for i in range(steps + 1)]
    lens = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        lens.append(lens[-1] + math.hypot(x1 - x0, y1 - y0))
    out, j = [], 0
    for k in range(count):
        target = lens[-1] * (k + 0.5) / count
        while lens[j + 1] < target:
            j += 1
        (x0, y0), (x1, y1) = pts[j], pts[j + 1]
        out.append((x0, y0, -math.degrees(math.atan2(y1 - y0, x1 - x0))))
    return out


def _shape_points(style: str) -> list[tuple[float, float, float, float]]:
    """Точки формы на картинке: (x, y, поворот, масштаб шрифта)."""
    cx, cy, R = W / 2, H / 2 + 20, 430
    pts: list[tuple[float, float, float, float]] = []
    if style == "spiral":
        turns = 5.2
        curve = lambda t: (cx + (40 + 380 * t) * math.cos(t * turns * 2 * math.pi),  # noqa: E731
                           cy + (40 + 380 * t) * math.sin(t * turns * 2 * math.pi))
        pts = [(x, y, a, 0.6 + 0.55 * math.hypot(x - cx, y - cy) / R) for x, y, a in _arc_sample(curve, 190)]
    elif style == "rings":
        for r, k in ((420, 54), (330, 42), (240, 30), (150, 19), (65, 8)):
            pts += [(x, y, a, 0.55 + 0.5 * r / R) for x, y, a in _arc_sample(
                lambda t, r=r: (cx + r * math.sin(2 * math.pi * t), cy - r * math.cos(2 * math.pi * t)), k)]
    elif style == "heart":
        def heart(t, k):
            u = 2 * math.pi * t
            return (cx + k * 26 * 16 * math.sin(u) ** 3,
                    cy - 10 - k * 26 * (13 * math.cos(u) - 5 * math.cos(2 * u) - 2 * math.cos(3 * u) - math.cos(4 * u) + 2.5))
        for k, n in ((1.0, 60), (0.7, 40), (0.4, 20)):  # у выемки сверху не пишем — там контуры сходятся
            pts += [(x, y, a, 0.6 + 0.5 * k) for x, y, a in _arc_sample(lambda t, k=k: heart(0.04 + 0.92 * t, k), n)]
    elif style == "wave":
        for row in range(10):
            y0 = 330 + row * 76
            pts += [(x, y, a, 1.0) for x, y, a in _arc_sample(
                lambda t, y0=y0: (120 + 840 * t, y0 + 34 * math.sin(2 * math.pi * 1.25 * t)), 17)]
    elif style == "fraser":
        for j, r in enumerate(range(440, 40, -36)):
            k = int(2 * math.pi * r / 30)
            pts += [(x, y, a + 28, 0.62) for x, y, a in _arc_sample(
                lambda t, r=r: (cx + r * math.sin(2 * math.pi * t), cy - r * math.cos(2 * math.pi * t)), k)]
    elif style == "drift":
        for j, r in enumerate(range(440, 50, -42)):
            k = (int(2 * math.pi * r / 34) // 4) * 4  # кратно четырём — лестница цвета замыкается без шва
            pts += [(x, y, a, 0.78) for x, y, a in _arc_sample(
                lambda t, r=r, j=j: (cx + r * math.sin(2 * math.pi * (t if j % 2 else 1 - t)),
                                     cy - r * math.cos(2 * math.pi * (t if j % 2 else 1 - t))), k)]
    elif style == "galaxy":
        for arm in range(3):
            base = arm * 2 * math.pi / 3
            curve = lambda t, base=base: (cx + (30 + 400 * t) * math.cos(base + 3.4 * math.pi * t),  # noqa: E731
                                          cy + (30 + 400 * t) * math.sin(base + 3.4 * math.pi * t))
            pts += [(x, y, a, 0.55 + 0.6 * math.hypot(x - cx, y - cy) / R) for x, y, a in _arc_sample(curve, 60)]
    return pts


def _shape_color(style: str, i: int, scale: float) -> tuple:
    if style == "drift":  # лестница цвета по ходу кольца — она и создаёт ощущение вращения
        return DRIFT_COLORS[i % 4] + (255,)
    if style == "fraser":  # чередование светлых и тёмных наклонённых цифр — «скрученный шнур»
        return (245, 240, 255, 255) if i % 2 else (120, 140, 210, 255)
    return (236, 232, 245, int(150 + 90 * min(scale, 1.0)))


def shape_parts(grid: dict, title: str, palette: int, seed: str) -> dict:
    """Слои картинки-формы отдельно — для картинки и для живого видео (gridvideo.py):
    фон без звёзд, звёзды, цифры (x, y, поворот, размер, цифра, цвет, спрятана ли), надписи поверх."""
    rng = random.Random(seed)
    top, bottom, accent = PALETTES[palette % len(PALETTES)]
    cta_top = top
    if grid["style"] == "drift":  # иллюзии нужен средний тон фона, на чёрном «змеи» не ползут
        top, bottom = (92, 96, 120), (60, 62, 84)
    bg = _gradient(top, bottom).convert("RGBA")
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((W / 2 - 300, H / 2 - 280, W / 2 + 300, H / 2 + 320), fill=accent + (60,))
    bg = Image.alpha_composite(bg, halo.filter(ImageFilter.GaussianBlur(120)))
    stars = [(rng.randrange(W), rng.randrange(H), rng.choice((1, 1, 2)), rng.randrange(40, 190)) for _ in range(180)]
    marks = set(grid["marks"])
    hint = tuple(min(255, int(a * 0.55 + 255 * 0.45)) for a in accent)
    digits = [(x, y, angle, int(40 * scale), ch, hint + (255,) if i in marks else _shape_color(grid["style"], i, scale),
               i in marks)
              for i, ((x, y, angle, scale), ch) in enumerate(zip(_shape_points(grid["style"]), grid["digits"]))]
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(over)
    font = _font("PlayfairDisplay.ttf", 56, "SemiBold")
    lines = _wrap(draw, _strip_emoji(title), font, W - 140)[:2]
    y = 60 if len(lines) == 2 else 95
    for line in lines:
        draw.text((W // 2, y), line, font=font, fill=(255, 255, 255, 255), anchor="ma")
        y += 68
    cta = "Напиши в ответах — расскажу, что они значат"
    font = _font("Montserrat.ttf", 32, "SemiBold")
    tw = draw.textlength(cta, font=font)
    bx0, by0, bx1, by1 = W / 2 - tw / 2 - 36, H - 175, W / 2 + tw / 2 + 36, H - 109
    draw.rounded_rectangle((bx0, by0, bx1, by1), radius=33, fill=accent + (255,))
    draw.text((W / 2, (by0 + by1) / 2), cta, font=font, fill=cta_top + (255,), anchor="mm")
    _footer(draw, W / 2)
    return {"bg": bg, "stars": stars, "digits": digits, "over": over}


def digit_tile(ch: str, size: int, color: tuple, angle: float, cache: dict) -> Image.Image:
    key = (ch, size, color)
    if key not in cache:
        tile = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((size, size), ch, font=_font("Montserrat.ttf", size, "SemiBold"), fill=color, anchor="mm")
        cache[key] = tile
    return cache[key].rotate(angle, resample=Image.BICUBIC)


def _render_shape(grid: dict, title: str, palette: int, seed: str) -> bytes:
    parts = shape_parts(grid, title, palette, seed)
    img = parts["bg"].copy()
    sd = ImageDraw.Draw(img)
    for x, y, r, a in parts["stars"]:
        sd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, a))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cache: dict = {}
    for x, y, angle, size, ch, color, _ in parts["digits"]:
        tile = digit_tile(ch, size, color, angle, cache)
        layer.alpha_composite(tile, (int(x - tile.width / 2), int(y - tile.height / 2)))
    img = Image.alpha_composite(Image.alpha_composite(img, layer), parts["over"])
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


def render_grid(grid: dict, title: str, palette: int, seed: str) -> bytes:
    """Картинка-головоломка: заголовок, светящаяся рамка с сеткой цифр, призыв написать в ответах."""
    if grid.get("style", "classic") in SHAPES:
        return _render_shape(grid, title, palette, seed)
    rng = random.Random(seed)
    top, bottom, accent = PALETTES[palette % len(PALETTES)]
    img = _gradient(top, bottom).convert("RGBA")

    stars = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stars)
    for _ in range(140):
        x, y, r = rng.randrange(W), rng.randrange(H), rng.choice((1, 1, 2))
        sd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rng.randrange(50, 200)))
    img = Image.alpha_composite(img, stars)

    # Рамка со свечением.
    box = (70, 230, W - 70, H - 230)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(box, radius=36, outline=accent + (200,), width=14)
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(18)))
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle(box, radius=36, fill=(4, 4, 16, 150), outline=accent + (230,), width=3)
    img = Image.alpha_composite(img, panel)
    draw = ImageDraw.Draw(img)

    # Заголовок.
    font = _font("PlayfairDisplay.ttf", 58, "SemiBold")
    lines = _wrap(draw, _strip_emoji(title), font, W - 140)[:2]
    y = 70 if len(lines) == 2 else 110
    for line in lines:
        draw.text((W // 2, y), line, font=font, fill=(255, 255, 255, 255), anchor="ma")
        y += 70

    # Сетка: спрятанные сочетания чуть теплее и ярче — глаз цепляется, но не сразу.
    marks = {tuple(m) for m in grid["marks"]}
    rows = grid["rows"]
    cell_w = (box[2] - box[0] - 60) / len(rows[0])
    cell_h = (box[3] - box[1] - 50) / len(rows)
    font = _font("Montserrat.ttf", 44, "Medium")
    hint = tuple(min(255, int(a * 0.55 + 255 * 0.45)) for a in accent)
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            cx = box[0] + 30 + cell_w * (c + 0.5)
            cy = box[1] + 25 + cell_h * (r + 0.5)
            color = hint + (255,) if (r, c) in marks else (236, 232, 245, 225)
            draw.text((cx, cy), ch, font=font, fill=color, anchor="mm")

    cta = "Напиши в ответах — расскажу, что они значат"
    font = _font("Montserrat.ttf", 32, "SemiBold")
    tw = draw.textlength(cta, font=font)
    bx0, by0, bx1, by1 = W / 2 - tw / 2 - 36, H - 190, W / 2 + tw / 2 + 36, H - 124
    draw.rounded_rectangle((bx0, by0, bx1, by1), radius=33, fill=accent + (255,))
    draw.text((W / 2, (by0 + by1) / 2), cta, font=font, fill=top + (255,), anchor="mm")
    _footer(draw, W / 2)

    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


GRID_TITLES = [
    "Какие 3 числа ты видишь первыми?",
    "Какое число бросилось в глаза первым?",
    "Первые 3 числа, что ты увидишь, — твоё послание",
]


def grid_json(grid: dict, title: str, palette: int) -> str:
    return json.dumps({"grid": grid, "title": title, "palette": palette}, ensure_ascii=False)


def grid_hint(raw: str | None) -> str:
    """Для автоответов: какие сочетания спрятаны в картинке-головоломке поста (или пусто)."""
    data = json.loads(raw) if raw else None
    if not data or "grid" not in data:
        return ""
    return "\n\n(К посту — картинка-матрица чисел, в ней спрятаны: " + ", ".join(data["grid"]["hidden"]) + ")"


def eight_growth_carousel(palette: int) -> list[Card]:
    """Шесть шагов саморефлексии; дата не предсказывает характер или доход."""
    slides = [["8, 17, 26: можно хотеть большего и оставаться добрым человеком","Листай →"],["Число 8 — символ ответственности в нумерологии. Не доказательство характера и не прогноз дохода.","2 / 6 · Проверяем по своей жизни"],["Бывает, что берёшь на себя больше, а попросить достойную оплату неловко. Узнаёшь эту ситуацию?","3 / 6 · Может касаться любой даты"],["Амбиции и порядочность совместимы. Важно, какую пользу ты создаёшь и как обращаешься с людьми.","4 / 6 · Без отказа от своих ценностей"],["Запиши: какую задачу решаешь, чем полезен результат и о каких условиях хочешь договориться.","5 / 6 · Один шаг вместо обещаний богатства"],["Что тебе труднее: назвать цену, попросить помощь или отказаться от лишней задачи?","6 / 6 · Расскажи — обсудим здесь"]]
    return [Card(hook, label="ВОСЬМЁРКИ · МАСШТАБ И ЗАБОТА", cta="reply",
                 cta_text=button, palette=palette, dates="8 · 17 · 26")
            for hook, button in slides]
