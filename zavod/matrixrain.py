"""Цифровой дождь Нумериты (слово владельца 29.10.2026: «стиль как у Матрицы, только не зелёные иероглифы, а наши
цифры: на фоне вселенная, звёзды, темнота — и мерцают золотые, дорого-богатые цифры, всё переливается, искрит»).

Столбцы падающих цифр в три глубины (дальние мельче, тусклее и медленнее — объём, как коридор кода в «Матрице»),
голова столбца — светлое золото с искрой-бликом, хвост гаснет тёплым золотом, цифры в хвосте переливаются и изредка
меняются. Шрифт Share Tech Mono (OFL). Всё кодом, $0. Палитра «green» — классическая матрица для сравнения.
"""

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
DIGITS = "0123456789"
PALETTES = {
    "gold": ((255, 250, 228), (236, 186, 92), (150, 100, 40)),   # голова, хвост, глубина
    "green": ((225, 255, 230), (40, 255, 110), (10, 120, 50)),
}
_CACHE: dict = {}


def _glyph(ch: str, size: int, color: tuple) -> Image.Image:
    key = (ch, size, color)
    if key not in _CACHE:
        font = ImageFont.truetype(str(FONTS / "ShareTechMono.ttf"), size)
        tile = Image.new("RGBA", (size, int(size * 1.25)), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((size / 2, size * 0.62), ch, font=font, fill=color, anchor="mm")
        _CACHE[key] = tile
    return _CACHE[key]


def _mix(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


class Rain:
    def __init__(self, width: int, height: int, seed: str = "rain", size: int = 28, density: float = 0.85,
                 palette: str = "gold"):
        self.w, self.h, self.size = width, height, size
        self.head, self.tail, self.deep = PALETTES[palette]
        rng = random.Random(seed)
        self.cols = []
        for depth, share in ((0.45, 1.0), (0.7, 0.8), (1.0, 0.55)):  # дальний, средний, ближний план
            s = int(size * depth)
            step = int(s * 1.1)
            for x in range(step // 2, width, step):
                if rng.random() > density * share:
                    continue
                self.cols.append({"x": x + rng.uniform(-3, 3), "z": depth, "size": s,
                                  "speed": rng.uniform(90, 300) * depth, "len": rng.randint(8, 24),
                                  "off": rng.uniform(0, height * 2),
                                  "glyphs": [rng.choice(DIGITS) for _ in range(90)],
                                  "flip": rng.uniform(0.06, 0.25), "ph": rng.uniform(0, 6.3)})
        self.cols.sort(key=lambda c: c["z"])

    def layer(self, t: float, strength: float = 1.0) -> Image.Image:
        img = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        glints = ImageDraw.Draw(img)
        for c in self.cols:
            s, z = c["size"], c["z"]
            cell = int(s * 1.25)
            head = int(((c["off"] + c["speed"] * t) % (self.h + c["len"] * cell)) / cell)
            for k in range(c["len"]):
                row = head - k
                if row < 0 or row * cell > self.h:
                    continue
                idx = (row + int(t / c["flip"]) * (1 if k % 3 == 0 else 0)) % len(c["glyphs"])
                fade = (1 - k / c["len"]) ** 1.5
                shimmer = 0.75 + 0.25 * math.sin(2 * math.pi * (1.3 * t + row * 0.37 + c["ph"]))
                level = max(1, min(8, int(8 * fade * shimmer * strength * (0.45 + 0.55 * z))))
                color = (self.head if k == 0 else _mix(self.deep, self.tail, z)) + (level * 31,)
                y = row * cell
                img.alpha_composite(_glyph(c["glyphs"][idx], s, color), (int(c["x"] - s / 2), y))
                if k == 0 and z > 0.6:  # искра-блик на голове ближних столбцов
                    gx, gy = c["x"], y + s * 0.62
                    tw = 0.5 + 0.5 * math.sin(2 * math.pi * (2.1 * t + c["ph"]))
                    L = s * (0.5 + 0.6 * tw)
                    a = int(150 * tw * strength)
                    glints.line((gx - L, gy, gx + L, gy), fill=(255, 245, 210, a), width=1)
                    glints.line((gx, gy - L, gx, gy + L), fill=(255, 245, 210, a), width=1)
        return img
