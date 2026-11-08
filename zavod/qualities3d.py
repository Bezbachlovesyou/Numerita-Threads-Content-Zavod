"""Серия «Качества чисел» (слово владельца 08.11.2026): русские прилагательные-качества характера —
«тёплый», «заботливый», «пробивной», «прирождённый лидер», «первопроходец», «эмпатичный» — вращаются в 3D
вокруг объёмной фигуры (сердце, сфера, ДНК, лента Мёбиуса, галактика, тор), сияют и переливаются.
Вопрос зрителю: какому числу принадлежат эти слова (один правильный ответ среди 4 чисел). Так люди учат,
какие качества связывают с каким числом, и изучают нумерологию играя.

База слов — knowledge/formats/number_qualities.json (≈110 слов на цифры 1–9; образ числа, не диагноз).
Каждое слово стоит на фигуре дважды, на противоположных сторонах, — вращаясь, фигура никогда не показывает
обе копии сразу. Всё кодом (Pillow + ffmpeg), музыка cosmos.m4a, $0 — по правилам завода (платных генераций нет).
"""

import json
import math
import random
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .cards import H, W, _arc_sample, _gradient, birth_days
from .gridvideo import FPS, MUSIC, _heart_xy, ffmpeg

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "knowledge" / "formats" / "number_qualities.json"
FONT = ROOT / "assets" / "fonts" / "CormorantGaramond.ttf"
SECONDS = 10
CX, CY = W / 2, H / 2 - 40
FOCAL = 1500
SHAPES = ("heart", "sphere", "dna", "moebius", "galaxy", "torus")
WORDS_ON_SHAPE = 24          # 12 слов по два раза
ROTATION_DEG_PER_SEC = 32    # медленно и приятно для глаза

# Палитры сияния: ближняя к зрителю сторона светлее. (холодный конец, тёплый конец)
PALETTES = {
    "heart": ((255, 150, 185), (255, 220, 160)),
    "sphere": ((150, 200, 255), (255, 235, 190)),
    "dna": ((140, 230, 255), (255, 190, 235)),
    "moebius": ((190, 160, 255), (255, 225, 170)),
    "galaxy": ((170, 170, 255), (255, 215, 150)),
    "torus": ((255, 170, 150), (255, 230, 180)),
}


def load_qualities() -> dict[int, list[str]]:
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items() if k.isdigit()}


# ---------- 3D-фигуры: точки (x, y, z) вокруг начала координат ----------

def _heart_points(n: int, t: float) -> list[tuple]:
    rings = ((1.0, 1, 10), (0.8, 1, 6), (0.8, -1, 6), (0.45, 1, 1), (0.45, -1, 1))
    depth = 200.0
    beat = 1 + 0.03 * max(0.0, math.sin(2 * math.pi * 1.1 * t)) ** 6  # сердце бьётся
    pts = []
    for s, side, count in rings:
        z = side * depth * math.sqrt(max(0.0, 1 - s * s))
        ring = _arc_sample(lambda u, s=s: tuple(v * s * 0.92 for v in _heart_xy(2 * math.pi * (0.04 + 0.92 * u))), count)
        pts += [(x * beat, (y + 20) * beat, z * beat) for x, y, _ in ring]
    return pts[:n]


def _sphere_points(n: int, t: float) -> list[tuple]:
    r = 330.0
    pts = []
    for i in range(n):
        y = 1 - 2 * (i + 0.5) / n
        rr = math.sqrt(1 - y * y)
        th = math.pi * (3 - math.sqrt(5)) * i
        pts.append((r * rr * math.cos(th), r * y, r * rr * math.sin(th)))
    return pts


def _dna_points(n: int, t: float) -> list[tuple]:
    half, height, radius, turns = n // 2, 820.0, 240.0, 1.75
    pts = []
    for strand in (0, 1):
        for i in range(half):
            v = (i + 0.5) / half
            a = 2 * math.pi * turns * v + math.pi * strand + 0.9 * t  # спираль сама закручивается
            pts.append((radius * math.cos(a), height * (v - 0.5), radius * math.sin(a)))
    return pts


def _moebius_points(n: int, t: float) -> list[tuple]:
    rows, per = 3, n // 3
    big, half_w = 300.0, 150.0
    pts = []
    for r in range(rows):
        v = (r - 1) * 0.72
        for i in range(per):
            u = 2 * math.pi * (i + 0.5 * (r % 2)) / per
            rad = big + v * half_w * math.cos(u / 2)
            pts.append((rad * math.cos(u), v * half_w * math.sin(u / 2) * 1.35, rad * math.sin(u)))
    return pts


def _galaxy_points(n: int, t: float) -> list[tuple]:
    pts = []
    for arm in (0, math.pi):
        for i in range(n // 2):
            u = (i + 0.7) / (n // 2)
            a = arm + u * 2.7 * math.pi
            rad = 70 + u * 330
            pts.append((rad * math.cos(a), 26 * math.sin(7 * u + arm), rad * math.sin(a)))
    return pts


def _torus_points(n: int, t: float) -> list[tuple]:
    big, small, rows = 285.0, 125.0, 3
    per = n // rows
    pts = []
    for r in range(rows):
        v = 2 * math.pi * (r / rows) + 0.5
        for i in range(per):
            u = 2 * math.pi * (i + 0.5 * (r % 2)) / per
            pts.append(((big + small * math.cos(v)) * math.cos(u), small * math.sin(v) * 1.25,
                        (big + small * math.cos(v)) * math.sin(u)))
    return pts


POINTS = {"heart": _heart_points, "sphere": _sphere_points, "dna": _dna_points, "moebius": _moebius_points,
          "galaxy": _galaxy_points, "torus": _torus_points}
TILT_X = {"heart": 0.0, "sphere": 0.0, "dna": 0.0, "moebius": 0.95, "galaxy": 0.85, "torus": 0.62}


# ---------- Каркас фигуры: тонкие светящиеся линии, чтобы форма читалась сразу ----------

def _heart_curves(t: float) -> list[list[tuple]]:
    depth, out = 200.0, []
    for s, side in ((1.0, 1), (0.8, 1), (0.8, -1)):
        z = side * depth * math.sqrt(max(0.0, 1 - s * s))
        out.append([(x * s * 0.92, (y + 20), z) for x, y in (_heart_xy(2 * math.pi * i / 90) for i in range(91))])
    return out


def _sphere_curves(t: float) -> list[list[tuple]]:
    r, out = 330.0, []
    for lat in (-0.6, -0.2, 0.2, 0.6):
        rr = math.sqrt(1 - lat * lat)
        out.append([(r * rr * math.cos(a / 40 * 2 * math.pi), r * lat, r * rr * math.sin(a / 40 * 2 * math.pi)) for a in range(41)])
    for lon in range(4):
        b = math.pi * lon / 4
        out.append([(r * math.sin(a / 40 * 2 * math.pi) * math.cos(b), r * math.cos(a / 40 * 2 * math.pi),
                     r * math.sin(a / 40 * 2 * math.pi) * math.sin(b)) for a in range(41)])
    return out


def _dna_curves(t: float) -> list[list[tuple]]:
    height, radius, turns, out = 820.0, 240.0, 1.75, []
    for strand in (0, 1):
        out.append([(radius * math.cos(2 * math.pi * turns * v + math.pi * strand + 0.9 * t), height * (v - 0.5),
                     radius * math.sin(2 * math.pi * turns * v + math.pi * strand + 0.9 * t))
                    for v in (i / 120 for i in range(121))])
    for i in range(1, 22):  # перекладины между цепями
        v = i / 22
        a = 2 * math.pi * turns * v + 0.9 * t
        out.append([(radius * math.cos(a), height * (v - 0.5), radius * math.sin(a)),
                    (-radius * math.cos(a), height * (v - 0.5), -radius * math.sin(a))])
    return out


def _moebius_curves(t: float) -> list[list[tuple]]:
    big, half_w, out = 300.0, 150.0, []

    def pt(u, v):
        rad = big + v * half_w * math.cos(u / 2)
        return rad * math.cos(u), v * half_w * math.sin(u / 2) * 1.35, rad * math.sin(u)

    out.append([pt(4 * math.pi * i / 160, 1.0) for i in range(161)])  # край ленты — одна непрерывная линия
    out.append([pt(2 * math.pi * i / 80, 0.0) for i in range(81)])
    return out


def _galaxy_curves(t: float) -> list[list[tuple]]:
    out = []
    for arm in (0, math.pi):
        curve = []
        for i in range(81):
            u = i / 80
            a = arm + u * 2.7 * math.pi
            rad = 70 + u * 330
            curve.append((rad * math.cos(a), 26 * math.sin(7 * u + arm), rad * math.sin(a)))
        out.append(curve)
    return out


def _torus_curves(t: float) -> list[list[tuple]]:
    big, small, out = 285.0, 125.0, []
    for k in range(3):
        v = 2 * math.pi * k / 3 + 0.5
        out.append([((big + small * math.cos(v)) * math.cos(a / 60 * 2 * math.pi), small * math.sin(v) * 1.25,
                     (big + small * math.cos(v)) * math.sin(a / 60 * 2 * math.pi)) for a in range(61)])
    for k in range(12):
        u = 2 * math.pi * k / 12
        out.append([((big + small * math.cos(a / 30 * 2 * math.pi)) * math.cos(u), small * math.sin(a / 30 * 2 * math.pi) * 1.25,
                     (big + small * math.cos(a / 30 * 2 * math.pi)) * math.sin(u)) for a in range(31)])
    return out


CURVES = {"heart": _heart_curves, "sphere": _sphere_curves, "dna": _dna_curves, "moebius": _moebius_curves,
          "galaxy": _galaxy_curves, "torus": _torus_curves}


def _pair_up(points: list[tuple], words: list[str]) -> list[str]:
    """Слово ставим дважды: на точку и на ближайшую к её зеркальной (поворот на 180° вокруг вертикали)."""
    n = len(points)
    free, out = set(range(n)), [""] * n
    seq = iter(words * 2)
    for i in range(n):
        if i not in free:
            continue
        free.discard(i)
        word = next(seq)
        out[i] = word
        if free:
            x, y, z = points[i]
            j = min(free, key=lambda k: (points[k][0] + x) ** 2 + (points[k][1] - y) ** 2 + (points[k][2] + z) ** 2)
            free.discard(j)
            out[j] = word
    return out


# ---------- Рисование ----------

_FONTS: dict = {}
_SPRITES: dict = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _FONTS:
        f = ImageFont.truetype(str(FONT), size)
        f.set_variation_by_name("SemiBold")
        _FONTS[size] = f
    return _FONTS[size]


def _sprite(word: str, size: int, color: tuple, level: int) -> Image.Image:
    """Слово с мягким сиянием; размер — шагом 3 px, яркость — 8 ступеней (кэш не разрастается)."""
    key = (word, size, color, level)
    if key in _SPRITES:
        return _SPRITES[key]
    font = _font(size)
    pad = int(size * 0.7)
    box = font.getbbox(word)
    w, h = box[2] - box[0] + pad * 2, box[3] - box[1] + pad * 2
    alpha = int(255 * level / 8)
    text = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(text).text((pad - box[0], pad - box[1]), word, font=font, fill=color + (alpha,))
    glow = text.filter(ImageFilter.GaussianBlur(size * 0.28))
    glow.putalpha(glow.getchannel("A").point(lambda v: min(255, int(v * 1.5))))
    core = ImageDraw.Draw(text)
    core.text((pad - box[0], pad - box[1]), word, font=font, fill=(255, 250, 238, alpha))  # светлая сердцевина
    out = Image.alpha_composite(glow, text)
    if len(_SPRITES) > 3000:
        _SPRITES.clear()
    _SPRITES[key] = out
    return out


def _mix(a: tuple, b: tuple, k: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def _rotate(p: tuple, tilt: float, phase: float) -> tuple:
    x, y, z = p
    x, z = x * math.cos(phase) + z * math.sin(phase), -x * math.sin(phase) + z * math.cos(phase)  # вокруг вертикали
    y, z = y * math.cos(tilt) - z * math.sin(tilt), y * math.sin(tilt) + z * math.cos(tilt)       # наклон
    return x, y, z


def _caption(draw: ImageDraw.ImageDraw, text: str, y: float, size: int, alpha: int, fill=(255, 244, 226)) -> None:
    draw.text((W / 2, y), text, font=_font(size), fill=fill + (alpha,), anchor="mm")


def frames(shape: str, digit: int, options: list[int], seed: str, seconds: float = SECONDS):
    """Кадры RGB (bytes). digit — чьи слова крутятся; options — четыре числа для выбора."""
    qualities = load_qualities()
    rng = random.Random(f"{seed}:{shape}:{digit}")
    words = rng.sample(qualities[digit], len(qualities[digit]))[: WORDS_ON_SHAPE // 2]
    base_pts = POINTS[shape](WORDS_ON_SHAPE, 0.0)
    labels = _pair_up(base_pts, words)
    cold, warm = PALETTES[shape]
    tilt = TILT_X[shape]
    n = len(labels)
    bg = _gradient((12, 7, 32), (36, 12, 54)).convert("RGBA")
    stars = [(rng.uniform(0, W), rng.uniform(0, H), rng.choice((1, 1, 2)), rng.uniform(0.3, 0.9), rng.uniform(0.4, 1.2),
              rng.uniform(0, 6.28)) for _ in range(110)]
    sparkles = [(rng.uniform(1.4, seconds - 0.6), rng.randrange(n)) for _ in range(int(seconds * 5))]
    breath_neb = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(breath_neb).ellipse((W * 0.1, H * 0.22, W * 0.9, H * 0.78), fill=(140, 100, 240, 70))
    breath_neb = breath_neb.filter(ImageFilter.GaussianBlur(130))
    for k in range(int(seconds * FPS)):
        t = k / FPS
        phase = math.radians(ROTATION_DEG_PER_SEC * t)
        pts = POINTS[shape](WORDS_ON_SHAPE, t)
        proj = []
        for i, p in enumerate(pts):
            x, y, z = _rotate(p, tilt, phase)
            persp = FOCAL / (FOCAL - z)
            proj.append((CX + x * persp, CY + y * persp, z, persp, i))
        zmax = max(abs(p[2]) for p in proj) or 1.0
        sky = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sky)
        for sx, sy, r, a, speed, ph in stars:
            tw = 0.2 + 0.8 * (0.5 + 0.5 * math.sin(2 * math.pi * speed * t + ph))
            sd.ellipse((sx - r, sy - r, sx + r, sy + r), fill=(255, 255, 255, int(255 * a * tw)))
        neb = breath_neb.copy()
        breath = 0.6 + 0.4 * math.sin(2 * math.pi * 0.3 * t)
        neb.putalpha(neb.getchannel("A").point(lambda v, b=breath: int(v * b)))
        img = Image.alpha_composite(Image.alpha_composite(bg, neb), sky)
        # мягкое сияние всей фигуры — чтобы форма читалась с первого взгляда
        aura = Image.new("RGBA", (W // 4, H // 4), (0, 0, 0, 0))
        ad = ImageDraw.Draw(aura)
        for x, y, z, persp, i in proj:
            c = _mix(cold, warm, i / n)
            ad.ellipse(((x - 80) / 4, (y - 80) / 4, (x + 80) / 4, (y + 80) / 4), fill=c + (26,))
        aura = aura.filter(ImageFilter.GaussianBlur(9)).resize((W, H), Image.BILINEAR)
        img = Image.alpha_composite(img, aura)
        wire = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        wd = ImageDraw.Draw(wire)
        draw_in = min(1.0, t / 1.2)  # каркас проявляется в начале
        for curve in CURVES[shape](t):
            q = []
            for p in curve:
                x, y, z = _rotate(p, tilt, phase)
                persp = FOCAL / (FOCAL - z)
                q.append((CX + x * persp, CY + y * persp, z))
            for (x0, y0, z0), (x1, y1, z1) in zip(q, q[1:]):
                nr = ((z0 + z1) / 2 / zmax + 1) / 2
                wd.line((x0, y0, x1, y1), fill=_mix(cold, warm, nr) + (int((40 + 110 * nr) * draw_in),), width=2)
        glow_w = wire.filter(ImageFilter.GaussianBlur(6))
        img = Image.alpha_composite(Image.alpha_composite(img, glow_w), wire)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for x, y, z, persp, i in sorted(proj, key=lambda q: q[2]):  # дальние — первыми
            near = (z / zmax + 1) / 2                                    # 0 — за фигурой, 1 — перед ней
            appear = min(1.0, max(0.0, (t - 1.4 * i / n) / 0.5))         # слова проявляются по очереди
            wave = 0.82 + 0.18 * math.sin(2 * math.pi * (0.9 * t - i / 7))  # по словам бежит волна света
            size = max(20, int((34 + 22 * near) * persp))
            size -= size % 3
            level = max(1, round((0.25 + 0.75 * near) * wave * appear * 8))
            if appear <= 0:
                continue
            tile = _sprite(labels[i], size, _mix(cold, warm, (i / n + 0.35 * near) % 1.0), level)
            layer.alpha_composite(tile, (int(x - tile.width / 2), int(y - tile.height / 2)))
        ld = ImageDraw.Draw(layer)
        for t0, idx in sparkles:  # блёстки: четырёхлучевая вспышка на слове, 0,45 с
            life = (t - t0) / 0.45
            if 0 <= life <= 1 and proj[idx][2] > -0.2 * zmax:
                sx, sy = proj[idx][0], proj[idx][1]
                kk = math.sin(math.pi * life)
                r = 38 * kk
                col = (255, 242, 210, int(255 * kk))
                ld.line((sx - r, sy, sx + r, sy), fill=col, width=2)
                ld.line((sx, sy - r, sx, sy + r), fill=col, width=2)
                ld.ellipse((sx - 4 * kk, sy - 4 * kk, sx + 4 * kk, sy + 4 * kk), fill=(255, 255, 255, int(255 * kk)))
        img = Image.alpha_composite(img, layer)
        text = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td = ImageDraw.Draw(text)
        _caption(td, "Чьи это слова?", 150, 84, int(255 * min(1.0, t / 0.9)))
        if t > 1.6:
            shown = min(1.0, (t - 1.6) / 0.8)
            _caption(td, "Какому числу они принадлежат?", 1090, 50, int(230 * shown), (232, 222, 255))
            step = 215
            x0 = W / 2 - step * (len(options) - 1) / 2
            for j, num in enumerate(options):
                cx = x0 + step * j
                td.ellipse((cx - 74, 1180, cx + 74, 1328), outline=(255, 226, 170, int(210 * shown)), width=3)
                td.text((cx, 1254), str(num), font=_font(96), fill=(255, 244, 226, int(255 * shown)), anchor="mm")
        img = Image.alpha_composite(img, text)
        yield img.convert("RGB").tobytes()


def render_video(shape: str, digit: int, options: list[int], seed: str = "", seconds: float = SECONDS) -> bytes:
    """MP4 1080×1350 с музыкой cosmos.m4a."""
    if shape not in POINTS:
        raise ValueError(f"нет фигуры {shape}")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "qualities.mp4"
        args = [ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                "-r", str(FPS), "-i", "-"]
        if MUSIC.exists():
            args += ["-stream_loop", "-1", "-i", str(MUSIC), "-af",
                     f"afade=in:st=0:d=1,afade=out:st={seconds - 1.8}:d=1.8", "-c:a", "aac", "-b:a", "128k"]
        args += ["-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(args, stdin=subprocess.PIPE)
        try:
            for frame in frames(shape, digit, options, seed, seconds):
                proc.stdin.write(frame)
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg не собрал видео качеств")
        return out.read_bytes()


def make_options(digit: int, rng: random.Random, count: int = 4) -> list[int]:
    """Правильное число и три других, по возрастанию — чтобы порядок не подсказывал ответ."""
    others = [d for d in range(1, 10) if d != digit]
    return sorted([digit, *rng.sample(others, count - 1)])


def post_text(digit: int, words: list[str], options: list[int]) -> str:
    """Текст поста: хук, три слова-подсказки, вопрос с выбором. Ответ в пост не входит (его даёт код в ответах)."""
    shown = ", ".join(w.capitalize() if i == 0 else w for i, w in enumerate(words[:3]))
    choice = ", ".join(str(o) for o in options[:-1]) + f" или {options[-1]}"
    return (f"Эти слова кружатся вокруг одного числа 💫\n{shown}…\n\n"
            f"Какое оно: {choice}?\n\n"
            "Образ числа по нумерологии, не диагноз. Угадаешь — запомнишь навсегда ✨")


def answer_text(digit: int) -> str:
    """Ответ тем, кто угадывал: число, дни рождения с ним и все слова образа."""
    words = load_qualities()[digit]
    return (f"Это {digit} — {', '.join(words[:6])}. Дни рождения с этим числом: {birth_days(digit)}. "
            "Образ числа, не приговор: в каждом из нас звучат все цифры.")


# ---------- Под постом: код проверяет ответ ----------

GUESS = re.compile(r"(?<![\d.,:/-])([1-9])(?![\d.,:/-])")
KEEP_IDS = 400


def spin_data(card: str | None) -> dict | None:
    try:
        spin = (json.loads(card or "{}") or {}).get("spin")
    except ValueError:
        return None
    return spin if isinstance(spin, dict) and spin.get("digit") else None


async def spin_of(db, post_id: int | None) -> dict | None:
    """Данные выпуска «Качества чисел» (число, форма, варианты) или None, если пост — не он."""
    if not post_id:
        return None
    post = await db.get(post_id)
    if not post or post.rubric != "text_spin":
        return None
    return spin_data(post.card)


def guess_of(comment: str, options: list[int]) -> int | None:
    """Число, которое человек назвал: первая одиночная цифра 1–9 из вариантов (даты «5 мая» и «15.05» не берём)."""
    if re.search(r"\d{2,}", comment or ""):  # в комментарии есть день, год или дата — это про рождение, а не ответ игры
        return None
    for g in GUESS.findall(comment or ""):
        if int(g) in options:
            return int(g)
    return None


def reply_note(spin: dict, comment: str) -> str:
    """Добавка к заданию ответа: код проверил выбор, нейросеть только говорит тепло и по расчёту (модель сама не угадывает)."""
    digit, options = int(spin["digit"]), [int(o) for o in spin["options"]]
    words = load_qualities()
    guess = guess_of(comment, options)
    head = "\n\nИГРА «КАЧЕСТВА ЧИСЕЛ» — порядок ответа. "
    if guess is None:
        return (head + "Код не нашёл в комментарии выбора из вариантов (" + ", ".join(map(str, options)) + "). Если человек "
                "назвал дату рождения или написал о другом — ответь по обычным правилам, игру не упоминай. Если просто "
                "поддержал пост — тепло поблагодари и мягко предложи выбрать число из вариантов; ответ не раскрывай.")
    if guess == digit:
        lead = (f"КОД ПРОВЕРИЛ: человек назвал {guess} — это верно. Образ числа {digit}: {', '.join(words[digit][:6])}. "
                f"Дни рождения с этим числом: {birth_days(digit)}.")
        todo = ("1) Порадуйся и похвали. 2) Назови 3–4 слова образа и скажи, чем число так узнаётся (образ из языка чисел, "
                "не диагноз). 3) Одной фразой мост к личному: напиши день рождения числом — скажу, чьи это слова в нём.")
    else:
        lead = (f"КОД ПРОВЕРИЛ: человек назвал {guess} — не угадал, верный ответ {digit}. Образ числа {digit}: "
                f"{', '.join(words[digit][:6])}. Образ числа {guess}: {', '.join(words[guess][:4])}. "
                f"Дни рождения с числом {digit}: {birth_days(digit)}.")
        todo = ("1) Тепло и с юмором: близко к смыслу, но это другое число — игра для того, чтобы учиться. 2) Открой верное число "
                f"и 2–3 его слова, потом 1–2 слова числа {guess}, чтобы человек увидел разницу. 3) Одной фразой мост: "
                "напиши день рождения числом — скажу, какие слова звучат в нём.")
    return head + lead + " " + todo + " Это игра-образ, не тест и не приговор; слов сверх базы не выдумывай."


async def record(db, post_id: int, comment_id: str, spin: dict, comment: str) -> None:
    """Копим ответы выпуска: сколько людей и кто что выбрал (для постов-итогов и оптимизатора)."""
    guess = guess_of(comment, [int(o) for o in spin["options"]])
    key = f"spin:{post_id}"
    data = json.loads(await db.kv_get(key) or "{}") or {"n": 0, "right": 0, "picks": {}, "seen": []}
    if comment_id in data["seen"]:
        return
    data["seen"] = (data["seen"] + [comment_id])[-KEEP_IDS:]
    if guess is not None:
        data["n"] += 1
        data["right"] += int(guess == int(spin["digit"]))
        data["picks"][str(guess)] = data["picks"].get(str(guess), 0) + 1
    await db.kv_set(key, json.dumps(data, ensure_ascii=False))
