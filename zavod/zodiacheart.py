"""Сердце зодиака — арт-ролик (слово владельца 11.11.2026: «обыграть сердце, цифры и знаки зодиака; красиво, мощно;
чтобы писали под постом и шли в ветку, дальше — канал и бот»).

Сюжет 15 с: хук «Какой знак любит сильнее?» → золотые цифры слетаются из цифрового дождя в объёмное сердце → оно
бьётся, вокруг плывёт кольцо из 12 знаков → по очереди загораются четыре стихии: три знака стихии соединяет
светящийся треугольник (тригон — так стихии и устроены в круге зодиака), сердце берёт её цвет, подпись «Огонь любит
поступком» → четыре треугольника складываются в двенадцатилучевую звезду → «А как любит твоё? Знак + число дня
рождения». Стихии и «язык любви» — традиция и символ, не прогноз отношений. Всё кодом (Pillow + ffmpeg), $0.
"""

import math
import random
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .cards import H, W, _gradient
from .gridvideo import FPS, ffmpeg
from .pairstar3d import (FONTS_DIR, LOGO, MUSIC, WHITE, _bloom, _bold, _ease, _galaxy, _lux, _project, _rot_x,
                         _rot_y, _scale, _text)

SECONDS = 15.0
CX, CY = W / 2, 590.0
S = 262            # размер сердца
N = 620            # цифр в сердце
RING_R = 455       # радиус кольца знаков
TILT = math.radians(22)
BEAT = 0.875       # период удара сердца, с
T0 = 3.2           # сердце собрано, начинаются стихии
PHASE = 2 * BEAT   # одна стихия — два удара
T_STAR = T0 + 4 * PHASE   # 10,2 с — звезда из четырёх тригонов
T_END = T_STAR + 0.9
GOLD = (255, 208, 128)
ROSE = (255, 96, 130)
SIGNS = "♈♉♊♋♌♍♎♏♐♑♒♓"
ELEMENTS = [  # (название, как любит, знаки, цвет)
    ("Огонь", "любит поступком", "Овен · Лев · Стрелец", (255, 122, 70)),
    ("Земля", "любит заботой", "Телец · Дева · Козерог", (150, 226, 130)),
    ("Воздух", "любит словом", "Близнецы · Весы · Водолей", (140, 214, 255)),
    ("Вода", "любит чувством", "Рак · Скорпион · Рыбы", (170, 140, 255)),
]
ELEMENTS_EN = [
    ("Fire", "loves with action", "Aries · Leo · Sagittarius", (255, 122, 70)),
    ("Earth", "loves with care", "Taurus · Virgo · Capricorn", (150, 226, 130)),
    ("Air", "loves with words", "Gemini · Libra · Aquarius", (140, 214, 255)),
    ("Water", "loves with feeling", "Cancer · Scorpio · Pisces", (170, 140, 255)),
]
TEXT = {
    "ru": {"hook": "Какой знак любит сильнее?", "sub": "у каждой стихии — своё сердце", "end": "А как любит твоё?",
           "end_sub": "знак + число дня рождения",
           "lines": ["Напиши свой знак", "и число дня рождения —", "расскажу, как любит твоё сердце"],
           "elements": ELEMENTS},
    "en": {"hook": "Which sign loves hardest?", "sub": "every element has its own heart", "end": "How does yours love?",
           "end_sub": "your sign + your birthday number",
           "lines": ["Tell me your sign", "and the day you were born —", "I'll tell you how your heart loves"],
           "elements": ELEMENTS_EN},
}
_G: dict = {}


def _glyph_font(size: int):
    size = max(12, size - size % 2)
    if size not in _G:
        _G[size] = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans-Bold.ttf"), size)
    return _G[size]


def _curve(a: float) -> tuple[float, float]:
    """Классическая кривая сердца, в долях: x ∈ ±0,94, y вниз по экрану."""
    x = 16 * math.sin(a) ** 3
    y = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
    return x / 17, -(y + 2.5) / 17


def heart_points(n: int, rng) -> list[tuple[float, float, float, float]]:
    """Объёмное сердце: чёткий контур (c = 1) и выпуклые «подушки» спереди и сзади. (x, y, z, c)."""
    pts = []
    rim = n // 6
    for i in range(rim):
        x, y = _curve(2 * math.pi * i / rim)
        pts.append((x, y, 0.0, 1.0))
    while len(pts) < n:
        c = math.sqrt(rng.random())
        x, y = _curve(rng.uniform(0, 2 * math.pi))
        z = 0.40 * math.sqrt(1 - c * c) * (1 if rng.random() < 0.62 else -1)
        pts.append((x * c, y * c, z, c))
    return pts


def _outline(scale: float, yaw: float, grow: float = 1.0) -> list[tuple[float, float]]:
    out = []
    for i in range(90):
        x, y = _curve(2 * math.pi * i / 90)
        px, py, _k = _project(_rot_y((x * scale * grow, y * scale * grow, 0.0), yaw))
        out.append((px, py))
    return out


def _pulse(t: float) -> float:
    """Двойной удар «тук-тук»: 0…1."""
    tb = (t - T0) % BEAT
    p = math.exp(-tb * 10)
    if tb > 0.26:
        p += 0.6 * math.exp(-(tb - 0.26) * 10)
    return min(1.0, p)


def _mix(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def _ring_pos(i: int, t: float):
    spin = 0.42 * t + 0.6 * _ease((t - T_STAR) / 1.2) * (t - T_STAR)
    a = 2 * math.pi * i / 12 - spin
    return _project(_rot_x((RING_R * math.cos(a), 0.0, RING_R * math.sin(a)), TILT)), math.sin(a)


def frames(lang: str = "ru", seconds: float = SECONDS, seed: str = "zodiacheart", start: int = 0, stop: int | None = None):
    tx = TEXT[lang]
    rng = random.Random(seed)
    bg = _gradient((5, 4, 18), (34, 8, 40)).convert("RGBA")
    from .matrixrain import Rain
    rain = Rain(W, H, seed)
    neb = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    nd = ImageDraw.Draw(neb)
    for _ in range(12):
        x, y, r = rng.randrange(W), rng.randrange(H), rng.randrange(180, 420)
        nd.ellipse((x - r, y - r, x + r, y + r),
                   fill=rng.choice([(110, 50, 170, 34), (40, 80, 180, 28), (200, 70, 120, 26), (200, 140, 60, 16)]))
    bg = Image.alpha_composite(bg, neb.filter(ImageFilter.GaussianBlur(140)))
    stars = [(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0.2, 1.0), rng.uniform(0.3, 1.0), rng.uniform(0, 6.3))
             for _ in range(240)]
    galaxies = [(_galaxy(rng, size, tint), x, y, rng.uniform(-4, 4), rng.uniform(0.15, 0.4), rng.uniform(0, 6.3))
                for size, tint, x, y in [(300, (255, 220, 190), 150, 250), (230, (190, 210, 255), 940, 210),
                                         (200, (230, 190, 255), 930, 1010)]]
    heart = heart_points(N, rng)
    digits = [str(rng.randrange(1, 10)) for _ in range(N)]
    # откуда летит каждая цифра: из струй дождя сверху и с краёв
    origin = [(rng.uniform(-620, 620), rng.uniform(-900, -520) if rng.random() < 0.7 else rng.uniform(-500, 700),
               rng.uniform(-300, 500), rng.uniform(0.0, 1.5)) for _ in range(N)]
    sparks = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.5, 1.0), rng.random(), rng.randrange(4)) for _ in range(150)]
    examples = [(SIGNS[rng.randrange(12)], rng.randrange(1, 32)) for _ in range(12)]
    f_hook = _lux(60, "Bold", "JetBrainsMono.ttf")
    f_sub = _lux(30, "Regular", "JetBrainsMono.ttf")
    f_el = _lux(54, "Bold", "JetBrainsMono.ttf")
    f_names = _lux(30, "Medium", "JetBrainsMono.ttf")
    f_line = _lux(40, "Bold", "JetBrainsMono.ttf")
    f_tag = _lux(26, "Regular", "JetBrainsMono.ttf")
    total = int(seconds * FPS)
    for k in range(start, total if stop is None else min(stop, total)):
        t = k / FPS
        built = _ease((t - 2.2) / 1.0)                      # сердце собрано
        pulse = _pulse(t) * (0.25 + 0.75 * built)
        ph = int((t - T0) // PHASE) if T0 <= t < T_STAR else -1     # какая стихия сейчас
        ph_k = (_ease((t - T0 - ph * PHASE) / 0.35) * (1 - _ease((t - T0 - (ph + 1) * PHASE + 0.3) / 0.3))) if ph >= 0 else 0.0
        star = _ease((t - T_STAR) / 0.6)
        end = _ease((t - T_END) / 0.6)
        tint = _mix(ROSE, tx["elements"][ph][3], 0.75 * ph_k) if ph >= 0 else ROSE

        img = bg.copy()
        sky = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sky)
        for x, y, depth, sp, phs in stars:
            px = (x * 0.62 + 0.012 * t * depth) % 1.24 - 0.62
            sx, sy = W / 2 + px * W * 0.9, H / 2 + y * H * 0.55
            tw = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(2 * math.pi * sp * t + phs))
            r = 0.6 + 1.6 * depth
            sd.ellipse((sx - r, sy - r, sx + r, sy + r), fill=(255, 255, 255, int(200 * tw * depth)))
            if depth > 0.85 and tw > 0.9:
                sd.line((sx - 9, sy, sx + 9, sy), fill=(255, 255, 255, int(120 * tw)))
                sd.line((sx, sy - 9, sx, sy + 9), fill=(255, 255, 255, int(120 * tw)))
        img = Image.alpha_composite(img, sky)
        img = Image.alpha_composite(img, rain.layer(t, 0.85 - 0.4 * built + 0.25 * pulse - 0.3 * end))
        for sprite, gx, gy, spin_g, sp, phs in galaxies:
            g = sprite.rotate(spin_g * t, resample=Image.BICUBIC)
            tw = 0.7 + 0.3 * math.sin(2 * math.pi * sp * t + phs)
            g.putalpha(g.getchannel("A").point(lambda v, q=tw: int(v * q)))
            img.alpha_composite(g, (int(gx - g.width / 2), int(gy - g.height / 2)))

        light = Image.new("RGB", (W, H), (0, 0, 0))
        ld = ImageDraw.Draw(light)
        soft = Image.new("RGB", (W, H), (0, 0, 0))   # мягкий внутренний свет сердца
        sdr = ImageDraw.Draw(soft)
        scale = S * (1 + 0.085 * pulse)
        yaw = 0.62 * math.sin(0.55 * t + 0.4)
        glow_r = (210 + 70 * pulse) * built
        if glow_r > 4:
            sdr.polygon(_outline(scale, yaw, 0.93 * built), fill=_scale(_mix(tint, WHITE, 0.25 * star),
                                                                        0.30 + 0.24 * pulse + 0.12 * star))

        # --- кольцо знаков: дальняя половина до сердца, ближняя — после
        ring = []
        for i in range(12):
            (x, y, kk), s_a = _ring_pos(i, t)
            ring.append((i, x, y, kk))
        ring_in = _ease((t - 1.6) / 1.4)

        def draw_ring(front: bool):
            for i, x, y, kk in ring:
                if (kk >= 1.0) != front:
                    continue
                el = i % 4
                col_el = tx["elements"][el][3]
                lit = (ph_k if el == ph else 0.0) + star
                near = max(0.0, min(1.0, (kk - 0.74) / 0.72))
                br = ring_in * (0.22 + 0.5 * near) * (1 - 0.5 * ph_k * (el != ph)) + 0.75 * min(1.0, lit)
                size = int((58 + 26 * min(1.0, lit) * (0.6 + 0.4 * pulse)) * kk)
                col = _mix(GOLD, col_el, min(1.0, lit))
                if lit > 0.05:
                    rr = size * 0.95
                    sdr.ellipse((x - rr, y - rr, x + rr, y + rr), fill=_scale(col_el, 0.45 * min(1.0, lit)))
                ld.text((x, y), SIGNS[i], font=_glyph_font(size), fill=_scale(col, min(1.0, br)), anchor="mm")

        def draw_trine(el: int, kq: float):
            if kq <= 0.02:
                return
            col = tx["elements"][el][3]
            p3 = [ring[el + 4 * j] for j in range(3)]
            for j in range(3):
                _, x1, y1, _k1 = p3[j]
                _, x2, y2, _k2 = p3[(j + 1) % 3]
                grow = min(1.0, kq * 1.6)
                ld.line((x1, y1, x1 + (x2 - x1) * grow, y1 + (y2 - y1) * grow), fill=_scale(col, 0.85 * kq), width=3)
                sdr.line((x1, y1, x1 + (x2 - x1) * grow, y1 + (y2 - y1) * grow), fill=_scale(col, 0.5 * kq), width=12)

        draw_ring(False)
        for el in range(4):
            draw_trine(el, max(ph_k if el == ph else 0.0, star * (1 - 0.55 * end)))

        # --- сердце из цифр
        pts = []
        for i, (hx, hy, hz, hc) in enumerate(heart):
            p = _rot_y((hx * scale, hy * scale, hz * scale), yaw)
            ox, oy, oz, delay = origin[i]
            fly = _ease((t - 0.25 - delay) / 1.25)
            if fly < 1:
                swirl = (1 - fly) * 2.2
                o = _rot_y((ox, oy, oz), swirl)
                p = (o[0] + (p[0] - o[0]) * fly, o[1] + (p[1] - o[1]) * fly, o[2] + (p[2] - o[2]) * fly)
            pts.append((p[2], i, fly, *_project(p)))
        for z, i, fly, x, y, kk in sorted(pts, key=lambda q: -q[0]):
            near = max(0.0, min(1.0, 0.5 - z / (2.2 * S)))
            hx, hy, _hz, edge = heart[i]
            rim = edge == 1.0
            wave = 0.55 + 0.45 * math.sin(2 * math.pi * (0.8 * t - (hy + 1) * 0.9 - i / 97))
            col = _mix(_mix(tint, WHITE, 0.2 + 0.5 * star), GOLD, edge ** 2.2 * (0.95 - 0.5 * ph_k))
            if rim:
                col = _mix(GOLD, WHITE, 0.35 + 0.4 * pulse)
            br = (0.10 + 0.90 * near ** 1.6) * (0.5 + 0.4 * wave + 0.5 * pulse) * (0.6 + 0.4 * fly)
            if rim:
                br = (0.8 + 0.2 * wave) * (0.6 + 0.4 * fly)
            br *= 1 - 0.45 * end * (1 - edge)   # в финале середина сердца притихает — там формула
            if br < 0.05:
                continue
            ch = digits[i] if (k // 5 + i) % 23 else str((k // 5 + i * 7) % 9 + 1)
            size = max(10, int(((42 if rim else 27) + 6 * pulse) * kk * (0.75 + 0.25 * fly)))
            ld.text((x, y), ch, font=_bold(size), fill=_scale(col, min(1.0, br)), anchor="mm")
        draw_ring(True)

        # --- ударная волна и искры
        if built > 0.3:
            for shift in (0.0, 0.26):
                tb = (t - T0 - shift) % BEAT
                wv = tb / BEAT
                a = (1 - wv) ** 2 * (1.0 if shift == 0 else 0.55) * built
                poly = _outline(scale, yaw, 1.06 + 1.5 * wv)
                ld.line(poly + poly[:1], fill=_scale(_mix(tint, WHITE, 0.3), 0.55 * a), width=3)
        if star > 0:
            flash = max(0.0, 1 - (t - T_STAR) / 0.9)
            if flash > 0:
                rr = 80 + 640 * (1 - flash)
                sdr.ellipse((CX - rr, CY - rr, CX + rr, CY + rr), fill=_scale(WHITE, 0.55 * flash))
            for ang0, sp, phs, el in sparks:
                rr = (240 + 330 * ((t * sp * 0.33 + phs) % 1)) * star
                x, y = CX + rr * math.cos(ang0 + 0.2 * t), CY + rr * math.sin(ang0 + 0.2 * t) * 0.9
                tw = 0.5 + 0.5 * math.sin(2 * math.pi * (sp * 1.6 * t + phs))
                r = 1.4 + 2.6 * tw
                ld.ellipse((x - r, y - r, x + r, y + r), fill=_scale(tx["elements"][el][3], tw * star))
                if tw > 0.92:
                    ld.line((x - 10, y, x + 10, y), fill=_scale(WHITE, 0.7), width=1)
                    ld.line((x, y - 10, x, y + 10), fill=_scale(WHITE, 0.7), width=1)
        from PIL import ImageChops
        img = ImageChops.screen(img.convert("RGB"), soft.filter(ImageFilter.GaussianBlur(70))).convert("RGBA")
        img = _bloom(img, light)

        # --- надписи
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        hook = _ease(t / 0.5) * (1 - _ease((t - T_STAR + 0.1) / 0.5))
        _text(od, (W / 2, 92), tx["hook"], f_hook, WHITE, 255 * hook)
        _text(od, (W / 2, 166), tx["sub"], f_sub, (230, 214, 245), 230 * hook)
        _text(od, (W / 2, 92), tx["end"], f_hook, WHITE, 255 * end)
        _text(od, (W / 2, 166), tx["end_sub"], f_sub, (255, 226, 180), 240 * end)
        if ph >= 0:
            name, how, names, col = tx["elements"][ph]
            _text(od, (W / 2, 1030), f"{name} {how}", f_el, _mix(col, WHITE, 0.25), 255 * ph_k)
            _text(od, (W / 2, 1100), names, f_names, (236, 226, 246), 235 * ph_k)
        if end > 0:  # в сердце мелькают примеры «знак + число»: подсказка, что писать
            sign, num = examples[int((t - T_END) / 0.95) % len(examples)]
            local = ((t - T_END) % 0.95) / 0.95
            a = end * min(1.0, local * 6) * min(1.0, (1 - local) * 6)
            gf, nf = _glyph_font(96), _lux(92, "Bold", "JetBrainsMono.ttf")
            parts = [(sign, gf), (" + ", nf), (str(num), nf)]
            width = sum(od.textlength(s_, font=f_) for s_, f_ in parts)
            x = W / 2 - width / 2
            for s_, f_ in parts:
                od.text((x + 3, CY - 17), s_, font=f_, fill=(40, 6, 24, int(200 * a)), anchor="lm")
                od.text((x, CY - 20), s_, font=f_, fill=(255, 244, 224, int(255 * a)), anchor="lm")
                x += od.textlength(s_, font=f_)
        for n, line in enumerate(tx["lines"]):
            _text(od, (W / 2, H - 300 + n * 56), line, f_line, WHITE if n < 2 else (255, 214, 140),
                  255 * _ease((t - T_END - 0.5 - 0.6 * n) / 0.5))
        tw_ = od.textlength("@Numeritabot", font=f_tag)
        x0 = W / 2 - (tw_ + LOGO.width + 12) / 2
        ov.paste(LOGO, (int(x0), int(H - 64 - LOGO.height / 2)), LOGO)
        od.text((x0 + LOGO.width + 12, H - 64), "@Numeritabot", font=f_tag, fill=(210, 196, 232, 200), anchor="lm")
        shadow = ov.filter(ImageFilter.GaussianBlur(6))
        shadow = Image.merge("RGBA", (*Image.new("RGB", (W, H), (8, 4, 20)).split(), shadow.getchannel("A")))
        img = Image.alpha_composite(Image.alpha_composite(img, shadow), ov)
        yield img.convert("RGB")


def heartbeat_wav(path: Path, seconds: float = SECONDS, rate: int = 44100) -> None:
    """Низкий «тук-тук» в такт кадру: синтез кодом, $0."""
    n = int(seconds * rate)
    buf = [0.0] * n
    t = T0 - 3 * BEAT
    while t < seconds - 0.4:
        gain = (0.35 + 0.65 * _ease((t - 0.3) / 2.6)) * (1 - 0.6 * _ease((t - T_END - 2.2) / 1.6))
        for shift, f0, amp, dur in ((0.0, 62.0, 1.0, 0.22), (0.26, 78.0, 0.62, 0.16)):
            i0 = int((t + shift) * rate)
            for j in range(int(dur * rate)):
                if not 0 <= i0 + j < n:
                    continue
                u = j / rate
                f = f0 * (1 - 0.45 * u / dur)
                env = min(1.0, u / 0.006) * math.exp(-u * 16)
                buf[i0 + j] += gain * amp * env * math.sin(2 * math.pi * f * u)
        t += BEAT
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v * 0.9)) * 32000)) for v in buf))


def mux(silent: Path, out: Path, seconds: float = SECONDS) -> None:
    """Немой ролик + музыка + удары сердца."""
    with tempfile.TemporaryDirectory() as tmp:
        beat = Path(tmp) / "beat.wav"
        heartbeat_wav(beat, seconds)
        args = [ffmpeg(), "-v", "error", "-y", "-i", str(silent), "-i", str(beat)]
        if MUSIC.exists():
            args += ["-stream_loop", "-1", "-i", str(MUSIC), "-filter_complex",
                     f"[2:a]volume=0.8,afade=in:st=0:d=1[m];[1:a]volume=1.6[b];[m][b]amix=inputs=2:normalize=0,"
                     f"afade=out:st={seconds - 1.6}:d=1.6,alimiter=limit=0.95[a]", "-map", "0:v", "-map", "[a]"]
        else:
            args += ["-map", "0:v", "-map", "1:a"]
        args += ["-t", str(seconds), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]
        subprocess.run(args, check=True)


def render_silent(out: Path, lang: str = "ru", seconds: float = SECONDS, start: int = 0, stop: int | None = None) -> None:
    args = [ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
            "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", str(out)]
    proc = subprocess.Popen(args, stdin=subprocess.PIPE)
    try:
        for frame in frames(lang, seconds, start=start, stop=stop):
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg не собрал сердце зодиака")


def render_video(lang: str = "ru", seconds: float = SECONDS) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        silent, out = Path(tmp) / "silent.mp4", Path(tmp) / "zodiacheart.mp4"
        render_silent(silent, lang, seconds)
        mux(silent, out, seconds)
        return out.read_bytes()
