"""Цифровой дождь Нумериты (уточнение владельца 29.10.2026: «иероглифы стекают, а цифры ярко мерцают и видны
именно цифры; всё золотое, сияющее») (слово владельца 29.10.2026: «стиль как у Матрицы, только не зелёные иероглифы, а наши
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
KANA = [chr(c) for c in range(0xFF66, 0xFF9E)]  # зеркальная катакана, как в «Матрице» (MatrixKana — подмножество Noto Sans JP)
PALETTES = {
    "gold": ((255, 238, 170), (226, 166, 66), (120, 80, 28)),   # голова, хвост, глубина
    "green": ((225, 255, 230), (40, 255, 110), (10, 120, 50)),
}
_CACHE: dict = {}


def _glyph(ch: str, size: int, color: tuple) -> Image.Image:
    key = (ch, size, color)
    if key not in _CACHE:
        font = ImageFont.truetype(str(FONTS / ("ShareTechMono.ttf" if ch.isdigit() else "MatrixKana.ttf")), size)
        tile = Image.new("RGBA", (size, int(size * 1.25)), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((size / 2, size * 0.62), ch, font=font, fill=color, anchor="mm")
        from PIL import ImageOps
        _CACHE[key] = tile if ch.isdigit() else ImageOps.mirror(tile)
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
        # 30.10.2026, слово владельца «раз и навсегда»: как в «Матрице», но только цифры; 10 планов глубины — от мелких
        # дальних струй до крупных ближних (с 30.10 вечером — 20 планов); нижняя цифра струи (капля) — самая яркая и крупная, след бледнеет вверх.
        planes = [(0.3 + 0.065 * i, max(0.06, 0.45 - 0.02 * i)) for i in range(20)]
        for depth, share in planes:
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
        lit = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))  # яркие цифры — отдельно, с золотым свечением
        glints = ImageDraw.Draw(lit)
        for c in self.cols:
            s, z = c["size"], c["z"]
            cell = int(s * 1.25)
            head = int(((c["off"] + c["speed"] * t) % (self.h + c["len"] * cell)) / cell)
            for k in range(c["len"]):
                row = head - k
                if row < 0 or row * cell > self.h:
                    continue
                idx = (row + int(t / c["flip"]) * (1 if k % 3 == 0 else 0)) % len(c["glyphs"])
                fade = (1 - k / c["len"]) ** (0.6 if c["glyphs"][(row + int(t / c["flip"]) * (1 if k % 3 == 0 else 0))
                                                     % len(c["glyphs"])].isdigit() else 1.3)
                shimmer = 0.75 + 0.25 * math.sin(2 * math.pi * (1.3 * t + row * 0.37 + c["ph"]))
                ch = c["glyphs"][idx]
                digit = ch.isdigit()  # иероглифы стекают приглушённо, цифры ярко мерцают и читаются
                twinkle = 0.6 + 0.4 * math.sin(2 * math.pi * (2.4 * t + row * 0.61 + c["ph"])) if digit else 0.55
                level = max(1, min(8 if digit else 5, int(8 * fade * shimmer * twinkle * strength
                                                          * (0.5 + 0.5 * z) * (2.0 if digit else 1.2))))
                color = (self.head if k == 0 or (digit and twinkle > 0.9) else
                         (255, 212, 110) if digit else _mix(self.deep, self.tail, z)) + (level * 31,)
                y = row * cell
                gs = int(s * 1.35) if k == 0 else s  # капля внизу струи — крупнее остальных
                color = (255, 246, 220, 255) if k == 0 else color
                (lit if digit or k == 0 else img).alpha_composite(_glyph(ch, gs, color), (int(c["x"] - gs / 2), y))
                if k == 0 and z > 0.6:  # искра-блик на голове ближних столбцов
                    gx, gy = c["x"], y + s * 0.62
                    tw = 0.5 + 0.5 * math.sin(2 * math.pi * (2.1 * t + c["ph"]))
                    L = s * (0.5 + 0.6 * tw)
                    a = int(150 * tw * strength)
                    glints.line((gx - L, gy, gx + L, gy), fill=(255, 226, 150, a), width=1)
                    glints.line((gx, gy - L * 0.6, gx, gy + L * 0.6), fill=(255, 226, 150, a), width=1)
        from PIL import ImageFilter
        halo = lit.filter(ImageFilter.GaussianBlur(7))
        img = Image.alpha_composite(Image.alpha_composite(img, halo), halo)
        img = Image.alpha_composite(img, lit.filter(ImageFilter.GaussianBlur(2)))
        return Image.alpha_composite(img, lit)
