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


def render(genre: str, sender: str, body: str, seed: str = "note") -> bytes:
    rng = random.Random(seed)
    paper = Image.new("RGB", (W, H), (248, 248, 252))
    d = ImageDraw.Draw(paper)
    for x in range(0, W, 44):  # клетка тетради
        d.line((x, 0, x, H), fill=(205, 215, 235), width=1)
    for y in range(0, H, 44):
        d.line((0, y, W, y), fill=(205, 215, 235), width=1)
    d.line((96, 0, 96, H), fill=(232, 120, 120), width=2)  # поля
    ink = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    k = ImageDraw.Draw(ink)
    k.text((W - 70, 70), sender, font=_font(44), fill=INK + (235,), anchor="ra")
    k.text((W / 2 + 20, 170), genre[:1].upper() + genre[1:].lower(), font=_font(92), fill=INK + (240,), anchor="ma")
    size = 62
    while size > 40:
        font = _font(size)
        lines = _wrap(k, body, font, W - 230)
        if 300 + len(lines) * size * 1.18 < H - 90:
            break
        size -= 2
    y = 300
    for line in lines:
        x = 130 + rng.uniform(-6, 6)
        k.text((x, y), line, font=font, fill=INK + (rng.randint(215, 245),))
        y += size * 1.18 + rng.uniform(-3, 3)
    k.line((W - 330, y + 40, W - 120, y + 30), fill=INK + (200,), width=3)  # подпись-росчерк
    ink = ink.rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC, center=(W / 2, H / 2))
    paper = Image.alpha_composite(paper.convert("RGBA"), ink.filter(ImageFilter.GaussianBlur(0.6)))
    shade = Image.new("L", (W, H), 0)  # лёгкая виньетка, как у фото листа
    ImageDraw.Draw(shade).ellipse((-200, -200, W + 200, H + 200), fill=255)
    vignette = Image.new("RGBA", (W, H), (60, 60, 80, 0))
    vignette.putalpha(shade.filter(ImageFilter.GaussianBlur(160)).point(lambda v: int((255 - v) * 0.35)))
    out = Image.alpha_composite(paper, vignette).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=92)
    return buf.getvalue()
