"""Звезда пары 3D — арт-объект (слово владельца 29.10.2026: «сделай 3D; энергия 1, 4 и 5 — видно, как 1 и 4
сходятся в 5; интрига, хук, юмор; арт-объект, а не дешёвка»).

Сюжет 14 с: хук «6 и 8 встретились. Угадай, что родится» → два объёмных кольца из светящихся цифр (золотое — 6,
лазурное — 8) влетают и сцепляются, как звенья (связь двух окружностей в пространстве), вращаются в 3D →
в точке сцепки вспыхивает 14 → 14 распадается на 1 и 4, они кружат друг вокруг друга по объёмной орбите и сливаются
→ рождается звезда 5 (Меркурий) → панчлайн. Числа союза — по базе Нумериты (kb.json → unions): души двоих
складываются и сводятся к цифре. Всё кодом (Pillow + ffmpeg), музыка cosmos.m4a, $0.
"""

import math
import random

from PIL import Image, ImageDraw, ImageFilter

from .cards import H, W, _font, _gradient
from .gridvideo import FPS, MUSIC, ffmpeg

GOLD = (255, 205, 120)
AZURE = (120, 200, 255)
WHITE = (255, 248, 235)
CX, CY = W / 2, H / 2 + 10
R = 300        # радиус колец в «мировых» единицах
FOCAL = 1250   # фокусное расстояние камеры
N = 84         # цифр на кольце


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _rot_y(p, a):
    x, y, z = p
    return x * math.cos(a) + z * math.sin(a), y, -x * math.sin(a) + z * math.cos(a)


def _rot_x(p, a):
    x, y, z = p
    return x, y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)


def _project(p):
    x, y, z = p
    k = FOCAL / (FOCAL + z)
    return CX + x * k, CY + y * k, k


_TILES: dict = {}


def _digit(ch: str, size: int, color: tuple, alpha: int) -> Image.Image:
    size = max(10, size - size % 2)
    alpha = alpha - alpha % 16
    key = (ch, size, color, alpha)
    if key not in _TILES:
        t = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        ImageDraw.Draw(t).text((size, size), ch, font=_font("Montserrat.ttf", size, "Bold"), fill=color + (alpha,),
                               anchor="mm")
        _TILES[key] = t
    return _TILES[key]


_FONTS: dict = {}


def _bold(size: int):
    size = max(10, size - size % 2)
    if size not in _FONTS:
        _FONTS[size] = _font("Montserrat.ttf", size, "Bold")
    return _FONTS[size]


def _scale(color: tuple, k: float) -> tuple:
    k = max(0.0, min(1.0, k))
    return tuple(int(c * k) for c in color)


def _bloom(img: Image.Image, light: Image.Image) -> Image.Image:
    """Свет складывается со сценой экраном (screen) — как настоящее сияние, а не наклейка."""
    from PIL import ImageChops, ImageEnhance
    small = light.resize((W // 2, H // 2), Image.BILINEAR)
    b1 = small.filter(ImageFilter.GaussianBlur(5)).resize((W, H), Image.BILINEAR)
    b2 = small.filter(ImageFilter.GaussianBlur(22)).resize((W, H), Image.BILINEAR)
    glow = ImageChops.add(ImageChops.add(light, ImageEnhance.Brightness(b1).enhance(1.8)),
                          ImageEnhance.Brightness(b2).enhance(2.2))
    return ImageChops.screen(img.convert("RGB"), glow).convert("RGBA")


def _star(cx, cy, r_out, r_in, rays, turn):
    pts = []
    for k in range(rays * 2):
        r = r_out if k % 2 == 0 else r_in
        a = turn + math.pi * k / rays - math.pi / 2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _text(draw, xy, text, font, fill, alpha):
    if alpha > 0:
        draw.text(xy, text, font=font, fill=fill + (int(alpha),), anchor="mm")


def frames(a: int = 6, b: int = 8, seconds: float = 15.0, seed: str = "pairstar3d"):
    rng = random.Random(seed)
    s = a + b
    d1, d2 = (s // 10, s % 10) if s > 9 else (s, 0)
    union = d1 + d2 if s > 9 else s
    while union > 9:
        union = sum(int(c) for c in str(union))
    bg = _gradient((5, 4, 18), (30, 10, 44)).convert("RGBA")
    neb = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    nd = ImageDraw.Draw(neb)
    for _ in range(12):
        x, y, r = rng.randrange(W), rng.randrange(H), rng.randrange(180, 420)
        nd.ellipse((x - r, y - r, x + r, y + r),
                   fill=rng.choice([(110, 50, 170, 34), (40, 80, 180, 30), (180, 80, 140, 22), (200, 140, 60, 16)]))
    bg = Image.alpha_composite(bg, neb.filter(ImageFilter.GaussianBlur(140)))
    stars = [(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0.2, 1.0), rng.uniform(0.3, 1.0), rng.uniform(0, 6.3))
             for _ in range(260)]  # (x, y, глубина, скорость мерцания, фаза)
    digits = {0: [str(a) if i % 12 == 0 else str(rng.randrange(10)) for i in range(N)],
              1: [str(b) if i % 12 == 0 else str(rng.randrange(10)) for i in range(N)]}
    sparks = [(rng.uniform(0, 2 * math.pi), rng.uniform(-1, 1), rng.uniform(0.5, 1.0), rng.random(),
               rng.choice([GOLD, AZURE, WHITE])) for _ in range(160)]
    f_hook = _font("PlayfairDisplay.ttf", 62, "SemiBold")
    f_sub = _font("Montserrat.ttf", 32, "Medium")
    f_big = _font("PlayfairDisplay.ttf", 190, "Bold")
    f_mid = _font("PlayfairDisplay.ttf", 150, "Bold")
    f_cap = _font("Montserrat.ttf", 38, "SemiBold")
    f_line = _font("PlayfairDisplay.ttf", 44, "SemiBold")
    f_tag = _font("Montserrat.ttf", 28, "Medium")
    total = int(seconds * FPS)
    for k in range(total):
        t = k / FPS
        img = bg.copy()
        # звёзды с параллаксом: дальние плывут медленнее
        sky = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sky)
        for x, y, depth, sp, ph in stars:
            px = (x * 0.62 + 0.012 * t * depth) % 1.24 - 0.62
            sx, sy = CX + px * W * 0.9, CY + y * H * 0.55
            tw = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(2 * math.pi * sp * t + ph))
            r = 0.6 + 1.6 * depth
            sd.ellipse((sx - r, sy - r, sx + r, sy + r), fill=(255, 255, 255, int(200 * tw * depth)))
            if depth > 0.85 and tw > 0.9:
                sd.line((sx - 9, sy, sx + 9, sy), fill=(255, 255, 255, int(120 * tw)))
                sd.line((sx, sy - 9, sx, sy + 9), fill=(255, 255, 255, int(120 * tw)))
        img = Image.alpha_composite(img, sky)

        # --- кольца в 3D: золотое в плоскости XY, лазурное в плоскости XZ, сцеплены как звенья
        fly = _ease((t - 0.2) / 2.8)
        link_fade = 1 - _ease((t - 7.4) / 1.0)  # кольца отступают в тень, когда рождается число
        spin = 0.55 * t + 0.4
        tilt = math.radians(-18 + 8 * math.sin(0.4 * t))
        pts = []
        for ring in (0, 1):
            off = (-1 if ring == 0 else 1) * (R / 2 + (1 - fly) * 620)
            for i in range(N):
                th = 2 * math.pi * i / N + (0.25 * t if ring == 0 else -0.25 * t)
                if ring == 0:
                    p = (off + R * math.cos(th), R * math.sin(th), 0.0)
                else:
                    p = (off + R * math.cos(th), 0.0, R * math.sin(th))
                p = _rot_x(_rot_y(p, spin), tilt)
                pts.append((p[2], ring, i, *_project(p)))
        appear = _ease((t - 0.1) / 0.9) * (0.3 + 0.7 * link_fade)
        light = Image.new("RGB", (W, H), (0, 0, 0))
        ld = ImageDraw.Draw(light)
        by_ring = {0: sorted((q for q in pts if q[1] == 0), key=lambda q: q[2]),
                   1: sorted((q for q in pts if q[1] == 1), key=lambda q: q[2])}
        for ring, ring_pts in by_ring.items():  # нить кольца — свет, ближе к зрителю ярче и толще
            color = GOLD if ring == 0 else AZURE
            for q0, q1 in zip(ring_pts, ring_pts[1:] + ring_pts[:1]):
                near = max(0.0, min(1.0, 0.5 - q0[0] / (2 * R)))
                br = appear * (0.18 + 0.5 * near)
                ld.line((q0[3], q0[4], q1[3], q1[4]), fill=_scale(color, br), width=max(2, int(5 * q0[5])))
        for z, ring, i, x, y, kk in sorted(pts, key=lambda q: -q[0]):
            near = max(0.0, min(1.0, 0.5 - z / (2 * R)))
            color = GOLD if ring == 0 else AZURE
            hero = i % 12 == 0
            wave = 0.55 + 0.45 * math.sin(2 * math.pi * (0.7 * t - i / 16))
            br = appear * (0.2 + 0.8 * near) * (1.0 if hero else wave)
            if br < 0.04:
                continue
            size = max(10, int((62 if hero else 34) * kk))
            core = tuple(min(255, c + 60) for c in color) if hero else color
            ld.text((x, y), digits[ring][i], font=_bold(size), fill=_scale(core, br), anchor="mm")
        img = _bloom(img, light)

        fx = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fx)
        txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td = ImageDraw.Draw(txt)

        # --- 4,0–7,4 с: в точке сцепки вспыхивает 14
        p14 = _ease((t - 4.0) / 0.8)
        split = _ease((t - 7.4) / 0.6)
        if p14 > 0 and split < 1:
            flash = max(0.0, 1 - (t - 4.0) / 0.9)
            if flash > 0:
                rr = 40 + 380 * (1 - flash)
                fd.ellipse((CX - rr, CY - rr, CX + rr, CY + rr), fill=WHITE + (int(140 * flash),))
            halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(halo).ellipse((CX - 210, CY - 210, CX + 210, CY + 210),
                                         fill=(255, 200, 130, int(120 * p14 * (1 - split))))
            img = Image.alpha_composite(img, halo.filter(ImageFilter.GaussianBlur(80)))
            _text(td, (CX, CY), str(s), f_big, WHITE, 255 * p14 * (1 - split))
            _text(td, (CX, CY + 190), f"{a} + {b} = {s}", f_cap, (255, 228, 190), 255 * p14 * (1 - split))

        # --- 7,4–10,2 с: 14 распадается на 1 и 4, они кружат по объёмной орбите и сливаются
        merge = _ease((t - 7.6) / 2.6)
        if split > 0 and t < 10.6 and s > 9:
            orbit_r = 230 * (1 - merge)
            ang = 2 * math.pi * 1.15 * max(0.0, t - 7.4)
            for idx, (ch, col) in enumerate(((str(d1), GOLD), (str(d2), AZURE))):
                a3 = ang + idx * math.pi
                p = (orbit_r * math.cos(a3), -40 * math.sin(a3) * (1 - merge), orbit_r * math.sin(a3) * 0.9)
                x, y, kk = _project(p)
                size = int(130 * kk)
                al = int(255 * split * (1 - _ease((t - 10.0) / 0.4)))
                # светящийся шлейф
                for tr in range(1, 9):
                    a4 = a3 - tr * 0.11
                    q = (orbit_r * math.cos(a4), -40 * math.sin(a4) * (1 - merge), orbit_r * math.sin(a4) * 0.9)
                    qx, qy, qk = _project(q)
                    rr = 22 * qk * (1 - tr / 10)
                    fd.ellipse((qx - rr, qy - rr, qx + rr, qy + rr), fill=col + (int(al * 0.45 * (1 - tr / 9)),))
                tile = _digit(ch, size, col, al)
                txt.alpha_composite(tile, (int(x - tile.width / 2), int(y - tile.height / 2)))
            _text(td, (CX, CY + 250), f"{d1} + {d2}", f_cap, (255, 228, 190), 255 * split * (1 - merge))

        # --- с 10,0 с: вспышка слияния и звезда числа союза
        born = _ease((t - 10.0) / 0.7)
        if born > 0:
            flash = max(0.0, 1 - (t - 10.0) / 1.0)
            if flash > 0:
                rr = 60 + 560 * (1 - flash)
                fd.ellipse((CX - rr, CY - rr, CX + rr, CY + rr), fill=WHITE + (int(190 * flash),))
            halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(halo).ellipse((CX - 250, CY - 250, CX + 250, CY + 250), fill=(255, 205, 140, int(140 * born)))
            img = Image.alpha_composite(img, halo.filter(ImageFilter.GaussianBlur(90)))
            pulse = 1 + 0.05 * math.sin(2 * math.pi * 1.2 * t)
            turn = 0.25 * t
            for j in range(24):  # лучи
                aj = turn + math.pi * j / 12
                L = (300 + 70 * math.sin(2 * math.pi * (0.6 * t + j / 7))) * born
                fd.line((CX, CY, CX + L * math.cos(aj), CY + L * math.sin(aj)), fill=WHITE + (int(60 * born),), width=3)
            fd.polygon(_star(CX, CY, 175 * born * pulse, 62 * born, 8, turn), fill=WHITE + (int(235 * born),))
            fd.polygon(_star(CX, CY, 128 * born * pulse, 56 * born, 8, turn + math.pi / 8), fill=GOLD + (int(255 * born),))
            fd.ellipse((CX - 82 * born, CY - 82 * born, CX + 82 * born, CY + 82 * born), fill=(255, 240, 210, int(255 * born)))
            _text(td, (CX, CY + 6), str(union), f_mid, (60, 22, 70), 255 * born)
            for ang0, h, sp, ph, col in sparks:  # блёстки вокруг звезды
                rr = (200 + 260 * ((t * sp * 0.35 + ph) % 1)) * born
                x, y = CX + rr * math.cos(ang0 + 0.2 * t), CY + rr * math.sin(ang0 + 0.2 * t) * 0.85 + h * 30
                tw = 0.5 + 0.5 * math.sin(2 * math.pi * (sp * 1.6 * t + ph))
                r = 1.4 + 2.6 * tw
                fd.ellipse((x - r, y - r, x + r, y + r), fill=col + (int(230 * tw * born),))
                if tw > 0.92:
                    fd.line((x - 10, y, x + 10, y), fill=WHITE + (170,), width=1)
                    fd.line((x, y - 10, x, y + 10), fill=WHITE + (170,), width=1)
        img = Image.alpha_composite(img, fx.filter(ImageFilter.GaussianBlur(16)))
        img = Image.alpha_composite(img, fx)
        glow_txt = Image.new("RGB", (W, H), (0, 0, 0))
        glow_txt.paste(txt.convert("RGB"), mask=txt)
        img = _bloom(img, glow_txt)
        img = Image.alpha_composite(img, txt)

        # --- надписи: хук → интрига → панчлайн
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        hook = _ease(t / 0.6) * (1 - _ease((t - 9.6) / 0.6))
        _text(od, (CX, 92), f"{a} и {b} встретились", f_hook, WHITE, 255 * hook)
        _text(od, (CX, 168), "угадай, что у них родится", f_sub, (230, 214, 245), 230 * hook)
        end = _ease((t - 10.4) / 0.6)
        _text(od, (CX, 92), "Звезда вашей пары", f_hook, WHITE, 255 * end)
        _text(od, (CX, 168), f"{a} + {b} = {s} → {d1} + {d2} = {union}" if s > 9 else f"{a} + {b} = {union}",
              f_sub, (255, 226, 180), 240 * end)
        lines = [(f"{a} сажает сад.", 11.0), (f"{b} строит забор.", 11.9), ("Вместе — «поехали на море».", 12.8)]
        for n, (line, start) in enumerate(lines):
            _text(od, (CX, H - 250 + n * 56), line, f_line, WHITE if n < 2 else (255, 214, 140),
                  255 * _ease((t - start) / 0.5))
        _text(od, (CX, H - 64), "Telegram @Numeritabot", f_tag, (210, 196, 232), 200)
        img = Image.alpha_composite(img, ov)
        yield img.convert("RGB")


def render_video(a: int = 6, b: int = 8, seconds: float = 15.0) -> bytes:
    import subprocess
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "pairstar3d.mp4"
        args = [ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                "-r", str(FPS), "-i", "-"]
        if MUSIC.exists():
            args += ["-stream_loop", "-1", "-i", str(MUSIC), "-af",
                     f"afade=in:st=0:d=1,afade=out:st={seconds - 1.8}:d=1.8", "-c:a", "aac", "-b:a", "128k"]
        args += ["-t", str(seconds), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(args, stdin=subprocess.PIPE)
        try:
            for frame in frames(a, b, seconds):
                proc.stdin.write(frame.tobytes())
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg не собрал 3D-звезду пары")
        return out.read_bytes()
