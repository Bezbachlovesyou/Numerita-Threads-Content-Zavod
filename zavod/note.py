"""Рукописная записка от лица числа (слово владельца 29.10.2026: формат «Жалоба от отца ученика», который собирает
тысячи реакций). Наша версия: «Объяснительная от восьмёрки», «Жалоба от шестёрки», «Заявление от единицы» — от лица
ЧИСЛА, а не выдуманного реального человека (честно: это шутка, не «реальная история»). Нейросеть пишет текст с
панчлайном в конце, код рисует его от руки (Marck Script, OFL) на тетрадном листе в клетку (почерк Bad Script, OFL). Один пост в день, $0
на картинку. В текстовом режиме Threads — исключение media_kind note_image (одна картинка).
"""

import io
import json
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
W, H = 1080, 1350
INK = (28, 42, 110)

RULES = (
    "Напиши шуточную рукописную записку от лица числа {digit} (рождённые {group}) — как знаменитая «Жалоба от отца "
    "ученика». Жанр выбери сам: жалоба, объяснительная, заявление, расписка, претензия, характеристика. Пишет само "
    "число, а не реальный человек. 5–8 коротких фраз: узнаваемая черта числа по базе Нумериты, нарастание абсурда и "
    "сильный панчлайн в последней строке (как «Пугать мной можно бесплатно. Выезд — платный»). Тепло, без унижения, "
    "без мата и политики. Ответ строго JSON: {{\"genre\": \"ЖАЛОБА\", \"from\": \"от восьмёрки, 26-го числа\", "
    "\"body\": \"текст записки\", \"post\": \"подпись к посту для Threads: 1–2 строки с хуком и вопросом, кто узнал "
    "себя или своё число, без ссылок\"}}"
)


def parse(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not data or not all(data.get(k) for k in ("genre", "from", "body", "post")):
        return None
    return data


_FONTCACHE: dict = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Bad Script (OFL) — похож на обычный «школьный» почерк шариковой ручкой."""
    if size not in _FONTCACHE:
        _FONTCACHE[size] = ImageFont.truetype(str(FONTS / "BadScript.ttf"), size)
    return _FONTCACHE[size]


def _write(k: ImageDraw.ImageDraw, x: float, base: float, text: str, size: int, rng: random.Random,
           alpha: int = 235) -> float:
    """Пишет текст по буквам на строке: высота и нажим букв чуть гуляют, строка ровная. Возвращает новый x."""
    for ch in text:
        sz = max(20, int(size * rng.uniform(0.96, 1.04)))
        a = max(150, min(255, int(alpha * rng.uniform(0.88, 1.0))))
        k.text((x, base + rng.uniform(-1.2, 1.2)), ch, font=_font(sz), fill=INK + (a,), anchor="ls")
        x += _font(sz).getlength(ch) * rng.uniform(0.97, 1.03)
    return x


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            test = (cur + " " + word).strip()
            if draw.textlength(test, font=font) <= width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        lines.append(cur)
    return [line for line in lines if line is not None]


def _word(word: str, size: int, alpha: int, rng: random.Random) -> Image.Image:
    """Слово «от руки»: свой размер, наклон и нажим — почерк живой, не идеальный."""
    font = _font(max(30, int(size * rng.uniform(0.93, 1.07))))
    tile = Image.new("RGBA", (int(font.getlength(word)) + 30, int(size * 1.9)), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((12, size * 1.3), word, font=font, fill=INK + (alpha,), anchor="ls")
    if rng.random() < 0.25:  # нажим ослаб — штрих бледнее, местами «перо» подсыхает
        fade = Image.new("L", tile.size, 0)
        fd = ImageDraw.Draw(fade)
        for _ in range(3):
            x = rng.randrange(tile.width)
            fd.ellipse((x - 20, -10, x + 20, tile.height + 10), fill=rng.randint(25, 60))
        a = tile.getchannel("A")
        from PIL import ImageChops
        tile.putalpha(ImageChops.subtract(a, fade.filter(ImageFilter.GaussianBlur(12))))
    return tile.rotate(rng.uniform(-3.0, 3.0), resample=Image.BICUBIC, center=(tile.width / 2, size * 1.3))


def _crumple(rng: random.Random) -> Image.Image:
    """Карта мятости: мягкие пятна света и тени плюс две складки."""
    small = Image.new("L", (27, 34), 128)
    for x in range(27):
        for y in range(34):
            small.putpixel((x, y), rng.randint(122, 136))
    shade = small.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(26))
    folds = Image.new("L", (W, H), 128)
    d = ImageDraw.Draw(folds)
    for _ in range(1):  # одна мягкая складка: светлая грань и тень рядом
        x0, y0 = rng.randrange(-100, W), rng.choice((rng.randrange(0, 300), rng.randrange(H - 300, H)))
        x1, y1 = x0 + rng.randrange(500, 1300), y0 + rng.randrange(-250, 250)
        d.line((x0, y0, x1, y1), fill=168, width=10)
        d.line((x0, y0 + 12, x1, y1 + 12), fill=98, width=14)
    from PIL import ImageChops
    folds = folds.filter(ImageFilter.GaussianBlur(9))
    return ImageChops.add(shade, folds, scale=1.0, offset=-128)


def _bend(img: Image.Image, rng: random.Random) -> Image.Image:
    """Лист не лежит идеально ровно: волна и лёгкая перспектива через сетку искажений."""
    cols, rows = 8, 10
    amp = rng.uniform(6, 12)
    ph = rng.uniform(0, 6.3)
    mesh = []
    for i in range(cols):
        for j in range(rows):
            x0, y0 = i * W // cols, j * H // rows
            x1, y1 = (i + 1) * W // cols, (j + 1) * H // rows

            def src(x, y):
                return (x + amp * math.sin(y / 230 + ph) + (y / H) * 18,
                        y + amp * 0.7 * math.sin(x / 260 + ph * 1.7))
            quad = (*src(x0, y0), *src(x0, y1), *src(x1, y1), *src(x1, y0))
            mesh.append(((x0, y0, x1, y1), quad))
    return img.transform((W, H), Image.MESH, mesh, Image.BICUBIC, fillcolor=(40, 38, 46))


def render(genre: str, sender: str, body: str, seed: str = "note", digit: int | None = None) -> bytes:
    rng = random.Random(seed)
    paper = Image.new("RGB", (W, H), (246, 245, 240))
    d = ImageDraw.Draw(paper)
    for x in range(0, W, 44):  # клетка тетради
        d.line((x, 0, x, H), fill=(200, 212, 232), width=1)
    for y in range(0, H, 44):
        d.line((0, y, W, y), fill=(200, 212, 232), width=1)
    d.line((96, 0, 96, H), fill=(228, 118, 118), width=2)  # поля
    for _ in range(9000):  # фактура бумаги
        x, y = rng.randrange(W), rng.randrange(H)
        c = rng.randint(222, 240)
        d.point((x, y), fill=(c, c, c - 6))
    ink = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    k = ImageDraw.Draw(ink)
    _write(k, W - 70 - _font(42).getlength(sender), 88, sender, 42, rng, 220)
    title = genre[:1].upper() + genre[1:].lower()
    _write(k, W / 2 + 20 - _font(84).getlength(title) / 2, 220, title, 84, rng, 240)
    size, step = 50, 88  # пишем по линиям клетки: две клетки на строку
    while True:
        font = _font(size)
        lines = _wrap(k, body, font, W - 240)
        if 308 + len(lines) * step < H - 120 or size <= 36:
            break
        size, step = size - 4, (88 if size - 4 >= 44 else 66)
    base = 308.0
    spots = []  # где перо остановилось — там и клякса
    words_all = [(i, w) for i, line in enumerate(lines) for w in line.split()]
    fix = None  # без описок: пишет грамотный человек (слово владельца 29.10.2026)
    for i, line in enumerate(lines):
        x = 124 + rng.uniform(-3, 5)
        for word in line.split():
            if fix and (i, word) == fix:  # описка: начало слова зачёркнуто и написано заново
                start_x = x
                x = _write(k, x, base, word[:3], size, rng)
                k.line((start_x - 2, base - size * 0.28, x + 2, base - size * 0.34), fill=INK + (215,), width=3)
                k.line((start_x, base - size * 0.18, x, base - size * 0.24), fill=INK + (190,), width=2)
                x += _font(size).getlength(" ")
                fix = None
            x = _write(k, x, base, word, size, rng)
            spots.append((x, base))
            x += _font(size).getlength(" ") * rng.uniform(0.9, 1.15)
        base += step
    # подпись: сама цифра с росчерком
    sign = str(digit) if digit else ""
    if not sign:
        k.line((W - 300, base + 12, W - 150, base), fill=INK + (200,), width=2)
    else:
        sx = _write(k, W - 300, base + 10, sign, int(size * 1.3), rng)
        k.line((W - 310, base + 22, sx + 70, base + 8), fill=INK + (200,), width=2)
    # чернила неровные: шарик ручки то подсыхает, то даёт больше пасты
    grain = Image.new("L", (W // 6, H // 6), 255)
    for gx in range(grain.width):
        for gy in range(grain.height):
            grain.putpixel((gx, gy), rng.randint(150, 255))
    grain = grain.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(2))
    from PIL import ImageChops
    ink.putalpha(ImageChops.multiply(ink.getchannel("A"), grain))
    blots = ImageDraw.Draw(ink)
    for _ in range(1):  # одна клякса пасты
        bx, by = rng.choice(spots) if spots else (W / 2, H / 2)
        bx, by = bx + rng.uniform(4, 12), by - rng.uniform(1, 6)
        r = rng.uniform(5, 8)
        bx, by = bx + 14, by - size * 0.9  # над строкой, между словами
        blots.ellipse((bx - r, by - r * 0.7, bx + r, by + r * 0.8), fill=INK + (215,))
        blots.ellipse((bx - r * 0.5, by - r * 1.1, bx + r * 0.9, by + r * 0.2), fill=INK + (200,))
        for _ in range(3):
            sx, sy = bx + rng.uniform(-9, 9), by + rng.uniform(-6, 6)
            blots.ellipse((sx - 1.5, sy - 1.5, sx + 1.5, sy + 1.5), fill=INK + (200,))
    ink = ink.filter(ImageFilter.GaussianBlur(0.55))
    page = Image.alpha_composite(paper.convert("RGBA"), ink).convert("RGB")
    shade = _crumple(rng)  # мятость: умножаем свет/тень на лист
    light = Image.merge("RGB", [shade.point(lambda v: min(255, int(v * 1.95)))] * 3)
    from PIL import ImageChops
    page = ImageChops.multiply(page, light)
    page = ImageChops.screen(page, Image.merge("RGB", [shade.point(lambda v: max(0, int((v - 150) * 1.4)))] * 3))
    page = _bend(page, rng)
    vig = Image.new("L", (W, H), 0)  # виньетка, как на фото листа
    ImageDraw.Draw(vig).ellipse((-220, -220, W + 220, H + 220), fill=255)
    vignette = Image.new("RGBA", (W, H), (50, 48, 60, 0))
    vignette.putalpha(vig.filter(ImageFilter.GaussianBlur(170)).point(lambda v: int((255 - v) * 0.45)))
    out = Image.alpha_composite(page.convert("RGBA"), vignette).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=90)
    return buf.getvalue()
