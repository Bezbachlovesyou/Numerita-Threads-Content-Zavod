"""Рукописная записка от лица числа (слово владельца 29.10.2026: формат «Жалоба от отца ученика», который собирает
тысячи реакций). Наша версия: «Объяснительная от восьмёрки», «Жалоба от шестёрки», «Заявление от единицы» — от лица
ЧИСЛА, а не выдуманного реального человека (честно: это шутка, не «реальная история»). Нейросеть пишет текст с
панчлайном в конце, код рисует его от руки (Marck Script, OFL) на тетрадном листе в клетку. Один пост в день, $0
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


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / "MarckScript.ttf"), size)


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
            small.putpixel((x, y), rng.randint(112, 150))
    shade = small.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(26))
    folds = Image.new("L", (W, H), 128)
    d = ImageDraw.Draw(folds)
    for _ in range(2):  # складки: мягкая светлая грань и тень рядом
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


def render(genre: str, sender: str, body: str, seed: str = "note") -> bytes:
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
    k.text((W - 70, 70), sender, font=_font(44), fill=INK + (225,), anchor="ra")
    k.text((W / 2 + 20, 170), genre[:1].upper() + genre[1:].lower(), font=_font(92), fill=INK + (235,), anchor="ma")
    size = 62
    while size > 40:
        font = _font(size)
        lines = _wrap(k, body, font, W - 250)
        if 300 + len(lines) * size * 1.2 < H - 110:
            break
        size -= 2
    y = 300.0
    drift = rng.uniform(-0.03, 0.03)  # строки чуть уходят вверх или вниз, как у живой руки
    for line in lines:
        x = 128 + rng.uniform(-8, 10)
        for word in line.split():
            tile = _word(word, size, rng.randint(205, 245), rng)
            yy = y + drift * (x - 128) + rng.uniform(-4, 4) - size * 0.3
            ink.alpha_composite(tile, (int(x), int(yy)))
            x += _font(size).getlength(word + " ") * rng.uniform(0.98, 1.06)
        if rng.random() < 0.08 and lines:  # изредка зачёркнутое и переписанное слово
            k.line((x - 120, y + size * 0.55, x - 30, y + size * 0.5), fill=INK + (190,), width=3)
        y += size * 1.2 + rng.uniform(-4, 4)
    k.line((W - 330, y + 40, W - 120, y + 26), fill=INK + (200,), width=3)  # росчерк-подпись
    k.line((W - 300, y + 52, W - 180, y + 30), fill=INK + (170,), width=2)
    ink = ink.filter(ImageFilter.GaussianBlur(0.7))
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
