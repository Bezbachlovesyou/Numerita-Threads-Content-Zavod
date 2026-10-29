"""Звезда пары (слово владельца 29.10.2026: «две окружности пересекаются — и между ними рождается новая звезда,
новая энергия; сияюще, красиво, под музыку, чтобы люди думали о парах и хотели угадать»).

Два кольца из светящихся цифр — золотое и лазурное — плывут навстречу, вращаясь в разные стороны. В их пересечении
(vesica piscis) из искр рождается звезда с числом союза: числа души двоих складываются и сводятся к одной цифре —
так считает энергию союза база Нумериты (kb.json → unions). Это символический язык, не прогноз отношений.
Всё кодом (Pillow + ffmpeg), музыка — наша cosmos.m4a, $0.
"""

import math
import random

from PIL import Image, ImageDraw, ImageFilter

from .cards import H, W, _font, _gradient, digit_tile
from .gridvideo import FPS, MUSIC, ffmpeg

GOLD = (255, 214, 130)
AZURE = (140, 205, 255)
ROSE = (255, 170, 205)
STAR = (255, 246, 222)
R = 230  # радиус колец
CY = H / 2 + 40


def reduce(n: int) -> int:
    while n > 9:
        n = sum(int(c) for c in str(n))
    return n


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _star_shape(cx: float, cy: float, r_out: float, r_in: float, rays: int = 8, turn: float = 0.0):
    pts = []
    for k in range(rays * 2):
        r = r_out if k % 2 == 0 else r_in
        a = turn + math.pi * k / rays - math.pi / 2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def frames(a: int, b: int, seconds: float = 14.0, seed: str = "pairstar"):
    rng = random.Random(seed)
    union = reduce(a + b)
    bg = _gradient((8, 6, 26), (40, 16, 58)).convert("RGBA")
    neb = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    nd = ImageDraw.Draw(neb)
    for _ in range(9):  # мягкая туманность
        x, y, r = rng.randrange(W), rng.randrange(H), rng.randrange(160, 360)
        nd.ellipse((x - r, y - r, x + r, y + r), fill=rng.choice([(120, 60, 170, 38), (60, 90, 190, 34), (190, 90, 150, 26)]))
    bg = Image.alpha_composite(bg, neb.filter(ImageFilter.GaussianBlur(120)))
    stars = [(rng.randrange(W), rng.randrange(H), rng.choice((1, 1, 1, 2)), rng.randrange(70, 220),
              rng.uniform(0.3, 1.0), rng.uniform(0, 6.3)) for _ in range(230)]
    ring_digits = 56
    left = [str(a) if i % 7 == 0 else str(rng.randrange(10)) for i in range(ring_digits)]
    right = [str(b) if i % 7 == 0 else str(rng.randrange(10)) for i in range(ring_digits)]
    sparks = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.4, 1.0), rng.uniform(0, 1), rng.choice([GOLD, AZURE, ROSE]))
              for _ in range(140)]
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    od.text((W / 2, 74), "Звезда вашей пары", font=_font("PlayfairDisplay.ttf", 66, "SemiBold"), fill=(255, 250, 240),
            anchor="ma")
    od.text((W / 2, 160), "две окружности · одна новая энергия", font=_font("Montserrat.ttf", 30, "Medium"),
            fill=(230, 215, 245), anchor="ma")
    od.text((W / 2, H - 88), "@numerita.ai", font=_font("Montserrat.ttf", 28, "Medium"), fill=(215, 200, 235),
            anchor="ma")
    big = _font("PlayfairDisplay.ttf", 120, "SemiBold")
    mid = _font("Montserrat.ttf", 44, "Medium")
    cache: dict = {}
    total = int(seconds * FPS)
    for k in range(total):
        t = k / FPS
        img = bg.copy()
        sky = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sky)
        for x, y, r, al, sp, ph in stars:
            tw = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(2 * math.pi * sp * t + ph))
            sd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, int(al * tw)))
            if r == 2 and tw > 0.92:
                sd.line((x - 8, y, x + 8, y), fill=(255, 255, 255, int(110 * tw)))
                sd.line((x, y - 8, x, y + 8), fill=(255, 255, 255, int(110 * tw)))
        img = Image.alpha_composite(img, sky)
        meet = _ease((t - 0.8) / 4.2)  # кольца сходятся за 0,8–5 с
        gap = 268 - 118 * meet
        centers = ((W / 2 - gap, CY), (W / 2 + gap, CY))
        appear = _ease(t / 1.4)
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for side, ((cx, cy), digits, color) in enumerate(zip(centers, (left, right), (GOLD, AZURE))):
            gd.ellipse((cx - R, cy - R, cx + R, cy + R), outline=color + (int(190 * appear),), width=9)
            spin = (1 if side == 0 else -1) * 9 * t
            for i, ch in enumerate(digits):
                ang = 2 * math.pi * i / ring_digits + math.radians(spin)
                x, y = cx + (R + 34) * math.cos(ang), cy + (R + 34) * math.sin(ang)
                light = 0.55 + 0.45 * math.sin(2 * math.pi * (0.6 * t - i / 14))
                hero = ch == str(a if side == 0 else b) and i % 7 == 0
                alpha = int(255 * appear * (1.0 if hero else max(0.35, light)))
                size = 40 if hero else 30
                level = round(alpha / 32)
                tile = digit_tile(ch, size, color + (level * 32 if level < 8 else 255,),
                                  round(math.degrees(ang) + 90) % 360, cache)
                layer.alpha_composite(tile, (int(x - tile.width / 2), int(y - tile.height / 2)))
            # число души внутри своего кольца, сдвинуто наружу от пересечения
            nx = cx + (-1 if side == 0 else 1) * R * 0.48
            ld = ImageDraw.Draw(layer)
            ld.text((nx, cy), str(a if side == 0 else b), font=big, fill=color + (int(235 * appear),), anchor="mm")
        if meet > 0.3:  # пересечение (vesica) наливается светом — общее пространство двоих
            ma = Image.new("L", (W, H), 0)
            mb = Image.new("L", (W, H), 0)
            (lx, ly), (rx, ry) = centers
            ImageDraw.Draw(ma).ellipse((lx - R, ly - R, lx + R, ly + R), fill=255)
            ImageDraw.Draw(mb).ellipse((rx - R, ry - R, rx + R, ry + R), fill=255)
            lens = Image.new("RGBA", (W, H), (255, 196, 170, int(110 * _ease((meet - 0.3) / 0.7))))
            from PIL import ImageChops
            lens.putalpha(ImageChops.multiply(ma, mb).point(lambda v, m=lens.getpixel((0, 0))[3]: v * m // 255))
            img = Image.alpha_composite(img, lens.filter(ImageFilter.GaussianBlur(28)))
        img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(26)))
        img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(9)))
        img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(2)))
        img = Image.alpha_composite(img, layer)
        birth = (t - 5.0) / 1.2  # 5–6,2 с: искры летят в пересечение, вспышка, рождается звезда
        fx = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fx)
        sx, sy = W / 2, CY
        if 0 < birth < 1.6:
            for ang, sp, ph, col in sparks:
                p = min(1.0, max(0.0, birth * sp + ph * 0.3))
                side = -1 if col == GOLD else 1
                ox, oy = sx + side * 200 + 200 * math.cos(ang), sy + 260 * math.sin(ang)
                x, y = ox + (sx - ox) * _ease(p), oy + (sy - oy) * _ease(p)
                r = 2 + 3 * (1 - p)
                fd.ellipse((x - r, y - r, x + r, y + r), fill=col + (int(230 * (1 - p * 0.6)),))
        if birth > 0.8:  # вспышка и звезда
            s = _ease((birth - 0.8) / 0.9)
            flash = max(0.0, 1 - (birth - 0.8) / 1.2)
            if flash > 0:
                rr = 60 + 420 * (1 - flash)
                fd.ellipse((sx - rr, sy - rr, sx + rr, sy + rr), fill=(255, 245, 225, int(150 * flash)))
            pulse = 1 + 0.06 * math.sin(2 * math.pi * 1.1 * t)
            turn = math.radians(6 * t)
            halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(halo).ellipse((sx - 240, sy - 240, sx + 240, sy + 240), fill=(255, 215, 160, int(130 * s)))
            img = Image.alpha_composite(img, halo.filter(ImageFilter.GaussianBlur(70)))
            fd.polygon(_star_shape(sx, sy, 160 * s * pulse, 52 * s * pulse, 8, turn), fill=STAR + (int(235 * s),))
            fd.polygon(_star_shape(sx, sy, 112 * s * pulse, 46 * s * pulse, 8, turn + math.pi / 8),
                       fill=(255, 200, 105, int(255 * s)))
            fd.ellipse((sx - 62 * s, sy - 62 * s, sx + 62 * s, sy + 62 * s), fill=(255, 238, 200, int(255 * s)))
            for j in range(16):  # лучи
                aj = turn * 2 + math.pi * j / 8
                L = (210 + 40 * math.sin(2 * math.pi * (0.7 * t + j / 5))) * s
                fd.line((sx, sy, sx + L * math.cos(aj), sy + L * math.sin(aj)), fill=STAR + (int(70 * s),), width=3)
        img = Image.alpha_composite(img, fx.filter(ImageFilter.GaussianBlur(14)))
        img = Image.alpha_composite(img, fx)
        if birth > 1.2:
            s = _ease((birth - 1.2) / 0.8)
            tx = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            td = ImageDraw.Draw(tx)
            td.text((sx, sy + 4), str(union), font=_font("PlayfairDisplay.ttf", 104, "SemiBold"),
                    fill=(70, 30, 70, int(255 * s)), anchor="mm")
            td.text((W / 2, CY + R + 150), f"{a} + {b} = {a + b}" + (f" → {union}" if a + b > 9 else ""),
                    font=mid, fill=(255, 240, 215, int(255 * s)), anchor="mm")
            td.text((W / 2, CY + R + 210), "какая звезда родится у вас?", font=_font("Montserrat.ttf", 32, "Medium"),
                    fill=(225, 210, 245, int(230 * s)), anchor="mm")
            img = Image.alpha_composite(img, tx)
        if birth > 0.8:  # блёстки вокруг новой звезды
            gl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            gdl = ImageDraw.Draw(gl)
            for ang, sp, ph, col in sparks[:70]:
                rr = 170 + 120 * ((t * sp * 0.5 + ph) % 1)
                x, y = sx + rr * math.cos(ang + t * 0.3), sy + rr * math.sin(ang + t * 0.3)
                tw = 0.5 + 0.5 * math.sin(2 * math.pi * (sp * 1.5 * t + ph))
                r = 1.5 + 2.5 * tw
                gdl.ellipse((x - r, y - r, x + r, y + r), fill=col + (int(220 * tw),))
                if tw > 0.9:
                    gdl.line((x - 9, y, x + 9, y), fill=STAR + (160,), width=1)
                    gdl.line((x, y - 9, x, y + 9), fill=STAR + (160,), width=1)
            img = Image.alpha_composite(img, gl)
        img = Image.alpha_composite(img, over)
        yield img.convert("RGB")


def render_video(a: int = 6, b: int = 8, seconds: float = 14.0) -> bytes:
    import subprocess
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "pairstar.mp4"
        args = [ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                "-r", str(FPS), "-i", "-"]
        if MUSIC.exists():
            args += ["-stream_loop", "-1", "-i", str(MUSIC), "-af",
                     f"afade=in:st=0:d=1,afade=out:st={seconds - 1.8}:d=1.8", "-c:a", "aac", "-b:a", "128k"]
        args += ["-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(args, stdin=subprocess.PIPE)
        try:
            for frame in frames(a, b, seconds):
                proc.stdin.write(frame.tobytes())
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg не собрал звезду пары")
        return out.read_bytes()
