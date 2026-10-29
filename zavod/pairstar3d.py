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
from pathlib import Path as _P

from .gridvideo import FPS, ffmpeg

MUSIC = _P(__file__).resolve().parent.parent / "assets" / "channel" / "pairstar_score.m4a"

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


SR_ = 225        # радиус сфер
SPHERE_N = 300   # цифр на сфере


def _fib_sphere(n: int):
    pts = []
    for i in range(n):
        y = 1 - 2 * (i + 0.5) / n
        r = math.sqrt(1 - y * y)
        th = math.pi * (3 - math.sqrt(5)) * i
        pts.append((r * math.cos(th), y, r * math.sin(th)))
    return pts


def _galaxy(rng, size: int, tint: tuple) -> Image.Image:
    """Спиральная галактика: два рукава из звёздной пыли, яркое ядро, лёгкий наклон."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = size / 2
    for arm in (0, math.pi):
        for _ in range(int(size * 7)):
            u = rng.random() ** 0.8
            ang = arm + u * 3.6 * math.pi / 1.4
            rad = u * c * 0.92
            x = c + rad * math.cos(ang) + rng.gauss(0, size * 0.025)
            y = c + 0.55 * (rad * math.sin(ang) + rng.gauss(0, size * 0.025))
            a = int(200 * (1 - u) + 55)
            d.point((x, y), fill=tint + (a,))
    d.ellipse((c - size * 0.035, c - size * 0.024, c + size * 0.035, c + size * 0.024), fill=(255, 245, 225, 210))
    soft = img.filter(ImageFilter.GaussianBlur(size * 0.006))
    glow = img.filter(ImageFilter.GaussianBlur(size * 0.035))
    out = Image.alpha_composite(glow, soft)
    out.putalpha(out.getchannel("A").point(lambda v: int(min(255, v * 1.1))))
    return out


FONTS_DIR = _P(__file__).resolve().parent.parent / "assets" / "fonts"
_GOLD: dict = {}


def _lux(size: int, weight: str = "SemiBold", face: str = "CormorantGaramond.ttf"):
    from PIL import ImageFont
    key = (face, size, weight)
    if key not in _FONTS:
        f = ImageFont.truetype(str(FONTS_DIR / face), size)
        f.set_variation_by_name(weight)
        _FONTS[key] = f
    return _FONTS[key]


def _gold_numeral(ch: str, size: int) -> Image.Image:
    """Число из «литого золота»: Bodoni Moda, вертикальный градиент светлое золото → тёплое → бронза, тонкий
    тёмный кант и блик сверху. Рисуется кодом один раз и кэшируется."""
    key = (ch, size)
    if key in _GOLD:
        return _GOLD[key].copy()
    font = _lux(size, "Bold", "BodoniModa.ttf")
    w, h = int(size * 0.9 * max(1, len(ch))), int(size * 1.4)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((w / 2, h / 2), ch, font=font, fill=255, anchor="mm")
    grad = Image.new("RGB", (1, h))
    stops = [(0.0, (255, 250, 225)), (0.38, (247, 214, 140)), (0.55, (214, 158, 70)), (0.75, (255, 222, 150)),
             (1.0, (150, 96, 38))]
    for y in range(h):
        u = y / (h - 1)
        for (u0, c0), (u1, c1) in zip(stops, stops[1:]):
            if u0 <= u <= u1:
                k = (u - u0) / (u1 - u0)
                grad.putpixel((0, y), tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(3)))
                break
    grad = grad.resize((w, h))
    edge = mask.filter(ImageFilter.MaxFilter(5))
    out = Image.new("RGBA", (w, h), (70, 40, 12, 0))
    out.putalpha(edge)
    gold = grad.convert("RGBA")
    gold.putalpha(mask)
    out = Image.alpha_composite(out, gold)
    _GOLD[key] = out
    return out.copy()


_TILES: dict = {}


def _digit(ch: str, size: int, color: tuple, alpha: int) -> Image.Image:
    size = max(10, size - size % 2)
    alpha = alpha - alpha % 16
    key = (ch, size, color, alpha)
    if key not in _TILES:
        t = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        ImageDraw.Draw(t).text((size, size), ch, font=_lux(size, "Bold", "BodoniModa.ttf"), fill=color + (alpha,),
                               anchor="mm")
        _TILES[key] = t
    return _TILES[key]


_FONTS: dict = {}


def _bold(size: int):
    size = max(10, size - size % 2)
    if size not in _FONTS:
        _FONTS[size] = _lux(size, "SemiBold", "BodoniModa.ttf")
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


def frames(a: int = 6, b: int = 8, seconds: float = 15.0, seed: str = "pairstar3d", art: Image.Image | None = None):
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
    sphere = _fib_sphere(SPHERE_N)
    digits = {0: [str(a) if i % 9 == 0 else str(rng.randrange(10)) for i in range(SPHERE_N)],
              1: [str(b) if i % 9 == 0 else str(rng.randrange(10)) for i in range(SPHERE_N)]}
    galaxies = [(_galaxy(rng, size, tint), x, y, rng.uniform(-4, 4), rng.uniform(0.15, 0.4), rng.uniform(0, 6.3))
                for size, tint, x, y in [(360, (255, 220, 190), 170, 330), (260, (190, 210, 255), 920, 260),
                                         (230, (230, 190, 255), 900, 1120), (190, (255, 235, 200), 140, 1080)]]
    lens_pts = [(rng.random(), rng.random(), rng.uniform(0.4, 1.0), rng.uniform(0, 6.3)) for _ in range(420)]
    sparks = [(rng.uniform(0, 2 * math.pi), rng.uniform(-1, 1), rng.uniform(0.5, 1.0), rng.random(),
               rng.choice([GOLD, AZURE, WHITE])) for _ in range(160)]
    f_hook = _lux(72, "SemiBold")
    f_sub = _lux(38, "Medium")
    f_big = _lux(200, "Bold", "BodoniModa.ttf")
    f_mid = _font("PlayfairDisplay.ttf", 150, "Bold")
    f_cap = _lux(44, "SemiBold")
    f_line = _lux(50, "SemiBold")
    f_tag = _lux(32, "Medium")
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
        for sprite, gx, gy, spin_g, sp, ph in galaxies:  # далёкие галактики медленно вращаются и мерцают
            g = sprite.rotate(spin_g * t, resample=Image.BICUBIC)
            tw = 0.7 + 0.3 * math.sin(2 * math.pi * sp * t + ph)
            g.putalpha(g.getchannel("A").point(lambda v, k=tw: int(v * k)))
            img.alpha_composite(g, (int(gx - g.width / 2), int(gy - g.height / 2)))

        # --- две сферы из цифр: золотая (a) и лазурная (b) сходятся и пересекаются
        fly = _ease((t - 0.2) / 3.0)
        link_fade = 1 - _ease((t - 7.4) / 1.0)  # сферы отступают в тень, когда рождается число
        tilt = math.radians(-14 + 6 * math.sin(0.4 * t))
        pts = []
        centers2d = []
        for ring in (0, 1):
            side = -1 if ring == 0 else 1
            off = side * (SR_ * 0.62 + (1 - fly) * 560)
            spin = side * (0.45 * t + 0.3)
            for i, (ux, uy, uz) in enumerate(sphere):
                p = _rot_y((ux * SR_, uy * SR_, uz * SR_), spin)
                p = _rot_x((p[0] + off, p[1], p[2]), tilt)
                pts.append((p[2], ring, i, *_project(p)))
            centers2d.append(_project(_rot_x((off, 0.0, 0.0), tilt)))
        appear = _ease((t - 0.1) / 0.9) * (0.3 + 0.7 * link_fade)
        light = Image.new("RGB", (W, H), (0, 0, 0))
        ld = ImageDraw.Draw(light)
        for ring, (px, py, pk) in enumerate(centers2d):  # мягкая атмосфера каждой сферы
            color = GOLD if ring == 0 else AZURE
            rr = SR_ * pk
            ld.ellipse((px - rr, py - rr, px + rr, py + rr), fill=_scale(color, 0.10 * appear))
        meet = _ease((t - 2.6) / 1.4) * (1 - _ease((t - 7.6) / 0.8))
        if meet > 0:  # энергия в пересечении сфер — вихрь искр в «линзе»
            (lx, ly, lk), (rx, ry, rk) = centers2d
            rl, rr_ = SR_ * lk, SR_ * rk
            for u, v, br, ph in lens_pts:
                x = lx + (rx - lx) * (0.5 + (u - 0.5) * 0.9) + 40 * math.sin(2 * math.pi * (0.5 * t + ph))
                y = ly + (v - 0.5) * 2 * rl * 0.9
                if (x - lx) ** 2 + (y - ly) ** 2 > rl ** 2 or (x - rx) ** 2 + (y - ry) ** 2 > rr_ ** 2:
                    continue
                tw = 0.5 + 0.5 * math.sin(2 * math.pi * (1.3 * t * br + ph))
                r = 1.2 + 2.2 * tw
                ld.ellipse((x - r, y - r, x + r, y + r), fill=_scale(WHITE, meet * br * tw))
        for z, ring, i, x, y, kk in sorted(pts, key=lambda q: -q[0]):
            near = max(0.0, min(1.0, 0.5 - z / (2 * SR_)))
            color = GOLD if ring == 0 else AZURE
            hero = i % 9 == 0
            wave = 0.55 + 0.45 * math.sin(2 * math.pi * (0.7 * t - i / 16))
            br = appear * (0.12 + 0.88 * near ** 1.5) * (1.0 if hero else wave)
            if br < 0.04:
                continue
            size = max(10, int((40 if hero else 24) * kk))
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
            n14 = _gold_numeral(str(s), 200)
            n14.putalpha(n14.getchannel("A").point(lambda v, k=p14 * (1 - split): int(v * k)))
            txt.alpha_composite(n14, (int(CX - n14.width / 2), int(CY - n14.height / 2)))
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
            pulse = 1 + 0.04 * math.sin(2 * math.pi * 1.2 * t)
            # анаморфная вспышка: длинный горизонтальный луч, короткий вертикальный, тонкие диагональные блики
            flare = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            fl = ImageDraw.Draw(flare)
            for (dx, dy, length, width, al) in ((1, 0, 540, 7, 210), (0, 1, 250, 5, 150),
                                                 (0.707, 0.707, 150, 3, 90), (0.707, -0.707, 150, 3, 90)):
                L = length * born * pulse
                fl.line((CX - dx * L, CY - dy * L, CX + dx * L, CY + dy * L), fill=(255, 236, 200, int(al * born)),
                        width=width)
            img = Image.alpha_composite(img, flare.filter(ImageFilter.GaussianBlur(5)))
            img = Image.alpha_composite(img, flare.filter(ImageFilter.GaussianBlur(14)))
            fd.ellipse((CX - 120 * born, CY - 120 * born, CX + 120 * born, CY + 120 * born),
                       fill=(255, 226, 170, int(120 * born)))
            num = _gold_numeral(str(union), 230)
            num.putalpha(num.getchannel("A").point(lambda v, k=born: int(v * k)))
            txt.alpha_composite(num, (int(CX - num.width / 2), int(CY - num.height / 2)))
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

        if art is not None and t >= 10.0:  # кульминация — кадр, нарисованный нейросетью, медленно приближается
            z = 1.0 + 0.06 * (t - 10.0) / max(0.1, seconds - 10.0)
            aw, ah = int(W * z), int(H * z)
            frame_art = art.resize((aw, ah), Image.LANCZOS).crop(((aw - W) // 2, (ah - H) // 2, (aw - W) // 2 + W,
                                                                    (ah - H) // 2 + H)).convert("RGBA")
            frame_art.putalpha(int(255 * _ease((t - 10.0) / 0.8)))
            img = Image.alpha_composite(img, frame_art)
            spark = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            spd = ImageDraw.Draw(spark)
            for ang0, h, sp, ph, col in sparks[:90]:  # живые искры поверх картины
                rr = 220 + 300 * ((t * sp * 0.3 + ph) % 1)
                x, y = CX + rr * math.cos(ang0 + 0.15 * t), CY + rr * math.sin(ang0 + 0.15 * t) * 0.85
                tw = 0.5 + 0.5 * math.sin(2 * math.pi * (sp * 1.6 * t + ph))
                spd.ellipse((x - 1.5 - 2 * tw, y - 1.5 - 2 * tw, x + 1.5 + 2 * tw, y + 1.5 + 2 * tw),
                            fill=col + (int(200 * tw),))
            img = Image.alpha_composite(img, spark)

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
        lines = [(f"{a} хотела уют.", 11.0), (f"{b} — надёжность.", 11.8), (f"Родилась {union}:", 12.6),
                 ("«а давайте всё бросим и на море»", 12.9)]
        for n, (line, start) in enumerate(lines):
            _text(od, (CX, H - 290 + n * 54), line, f_line, WHITE if n < 2 else (255, 214, 140),
                  255 * _ease((t - start) / 0.5))
        _text(od, (CX, H - 64), "Telegram @Numeritabot", f_tag, (210, 196, 232), 200)
        img = Image.alpha_composite(img, ov)
        yield img.convert("RGB")


def render_video(a: int = 6, b: int = 8, seconds: float = 15.0, art: Image.Image | None = None) -> bytes:
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
            for frame in frames(a, b, seconds, art=art):
                proc.stdin.write(frame.tobytes())
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg не собрал 3D-звезду пары")
        return out.read_bytes()
