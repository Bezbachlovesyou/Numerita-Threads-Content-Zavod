"""Цифровой дождь в стиле «Матрицы» (слово владельца 29.10.2026: «стиль должен быть как у матрицы — Нео видел всё
иероглифами»). Столбцы падающих символов: зеркальная катакана и цифры (шрифт MatrixKana — подмножество Noto Sans JP,
OFL), голова столбца светится бело-зелёным, хвост гаснет; символы в хвосте изредка меняются. Всё кодом, $0.
"""

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
GLYPHS = [chr(c) for c in range(0xFF66, 0xFF9E)] + list("0123456789")
_CACHE: dict = {}


def _glyph(ch: str, size: int, color: tuple) -> Image.Image:
    key = (ch, size, color)
    if key not in _CACHE:
        font = ImageFont.truetype(str(FONTS / ("ShareTechMono.ttf" if ch.isdigit() else "MatrixKana.ttf")), size)
        tile = Image.new("RGBA", (size, int(size * 1.2)), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((size / 2, size * 0.6), ch, font=font, fill=color, anchor="mm")
        _CACHE[key] = tile if ch.isdigit() else ImageOps.mirror(tile)
    return _CACHE[key]


class Rain:
    def __init__(self, width: int, height: int, seed: str = "matrix", size: int = 26, density: float = 0.8):
        self.w, self.h, self.size = width, height, size
        rng = random.Random(seed)
        self.rng = rng
        step = int(size * 1.05)
        self.cols = []
        for x in range(step // 2, width, step):
            if rng.random() > density:
                continue
            self.cols.append({"x": x, "speed": rng.uniform(140, 420), "len": rng.randint(8, 26),
                              "off": rng.uniform(0, height * 2), "glyphs": [rng.choice(GLYPHS) for _ in range(80)],
                              "flip": rng.uniform(0.05, 0.2)})

    def layer(self, t: float, strength: float = 1.0) -> Image.Image:
        img = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        cell = int(self.size * 1.2)
        rows = self.h // cell + 2
        for c in self.cols:
            head = int(((c["off"] + c["speed"] * t) % (self.h + c["len"] * cell)) / cell)
            for k in range(c["len"]):
                row = head - k
                if row < 0 or row > rows:
                    continue
                idx = (row + int(t / c["flip"]) * (1 if k % 3 == 0 else 0)) % len(c["glyphs"])
                ch = c["glyphs"][idx]
                fade = (1 - k / c["len"]) ** 1.6
                level = max(1, int(8 * fade * strength))
                color = (225, 255, 230, min(255, level * 32)) if k == 0 else (40, 255, 110, level * 24)
                tile = _glyph(ch, self.size, color)
                img.alpha_composite(tile, (int(c["x"] - self.size / 2), row * cell))
        return img
