"""Живая матрица чисел (слово владельца 28.10.2026: «сделай цифры динамичными — пусть шевелятся и переливаются
светом, звёзды мерцают, и музыка — посмотрим отклик»).

Видео 12 секунд по той же форме, что и картинка (cards.shape_parts): цифры прорисовываются по линии формы,
по ним бежит волна света, спрятанные сочетания мягко пульсируют золотом, звёзды мерцают каждая в своём ритме.
Спираль, кольца и галактика медленно вращаются, сердце бьётся, волна колышется; оптические иллюзии стоят —
движение в них создаёт сам глаз. Музыка — наша, синтезированная кодом (assets/channel/cosmos.m4a). Всё кодом, $0.
"""

import math
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .cards import H, W, _arc_sample, _shape_color, _shape_points, digit_tile, draw_dna_backbones, shape_parts

FPS = 24
SECONDS = 12
MUSIC = Path(__file__).resolve().parent.parent / "assets" / "channel" / "cosmos.m4a"
ROTATING = {"spiral": 22.0, "galaxy": 26.0, "rings": 18.0}  # градусов в секунду; 30.10 владелец: «с большой скоростью»
LEVELS = 8  # ступени яркости (кэш плиток не разрастается)


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def _motion(style: str, x: float, y: float, angle: float, t: float) -> tuple[float, float, float]:
    cx, cy = W / 2, H / 2 + 20
    if style in ROTATING:
        a = math.radians(ROTATING[style] * t)
        dx, dy = x - cx, y - cy
        x, y = cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)
        angle -= ROTATING[style] * t
    elif style == "heart":  # сердце бьётся: два коротких толчка в секунду с паузой
        beat = 1 + 0.035 * max(0.0, math.sin(2 * math.pi * 1.1 * t)) ** 6
        x, y = cx + (x - cx) * beat, cy + (y - cy) * beat
    elif style == "wave":
        y += 14 * math.sin(2 * math.pi * (0.45 * t + x / 420))
    return x, y, angle


HEART_RINGS = ((1.0, 1, 36), (0.78, 1, 24), (0.78, -1, 24), (0.48, 1, 14), (0.48, -1, 14), (0.2, 1, 4), (0.2, -1, 4))


def _heart_xy(u: float) -> tuple[float, float]:
    return (26 * 16 * math.sin(u) ** 3,
            -10 - 26 * (13 * math.cos(u) - 5 * math.cos(2 * u) - 2 * math.cos(3 * u) - math.cos(4 * u) + 2.5))


def heart3d_points(n: int, phase: float) -> list[tuple[float, float, float, float]]:
    """Объёмное сердце из цифр (слово владельца 30.10.2026): «пухлая» поверхность — контур сердца, сжатый к центру,
    с выпуклостью вперёд и назад. Цифры лежат кольцами-контурами: внешний обод, затем кольца лицевой и обратной
    стороны. Сердце вращается вокруг вертикали; дальние цифры мельче и темнее. (x, y, поворот, масштаб)."""
    cx, cy, depth = W / 2, H / 2 + 20, 250
    raw = []
    for s, side, count in HEART_RINGS:
        z = side * depth * math.sqrt(max(0.0, 1 - s * s))
        ring = _arc_sample(lambda t, s=s: tuple(v * s for v in _heart_xy(2 * math.pi * (0.04 + 0.92 * t))), count)
        raw += [(x, y, z) for x, y, _ in (ring if side > 0 else ring[::-1])]
    raw = (raw + raw)[:n]
    proj = []
    for x, y, z in raw:
        xr, zr = x * math.cos(phase) + z * math.sin(phase), -x * math.sin(phase) + z * math.cos(phase)
        persp = 1500 / (1500 - zr)
        proj.append((cx + xr * persp, cy + y * persp, zr / depth, persp))
    pts = []
    for i, (x, y, zn, persp) in enumerate(proj):  # поворот цифры — по линии кольца на экране, без «вверх ногами»
        a, b = (proj[i + 1], proj[i]) if i + 1 < n else (proj[i], proj[i - 1])
        ang = math.degrees(math.atan2(-(a[1] - b[1]), a[0] - b[0]))
        ang = ang - 180 if ang > 90 else ang + 180 if ang < -90 else ang
        pts.append((x, y, ang, (0.66 + 0.28 * zn) * persp))
    return pts


def heart_glow(phase: float, beat: float) -> Image.Image:
    """Светящийся силуэт сердца за цифрами — чтобы форма читалась с первого взгляда."""
    small = Image.new("RGBA", (W // 4, H // 4), (0, 0, 0, 0))
    cx, cy = W / 8, (H / 2 + 20) / 4
    k = math.hypot(math.cos(phase), 0.6 * math.sin(phase))  # ширина силуэта при повороте (обод + выпуклость)
    poly = [(cx + x * k * beat / 4, cy + y * beat / 4) for x, y in
            (_heart_xy(2 * math.pi * i / 120) for i in range(120))]
    ImageDraw.Draw(small).polygon(poly, fill=(255, 90, 140, 70))
    return small.filter(ImageFilter.GaussianBlur(10)).resize((W, H), Image.BILINEAR)


def frames(grid: dict, title: str, palette: int, seed: str, seconds: float = SECONDS):
    """Кадры RGB (bytes) по одному."""
    parts = shape_parts(grid, title, palette, seed)
    rng = random.Random(seed + "stars")
    stars = [(x, y, r, a, rng.uniform(0.25, 0.9), rng.uniform(0, 2 * math.pi)) for x, y, r, a in parts["stars"]]
    style, digits, n = grid["style"], parts["digits"], max(1, len(parts["digits"]))
    if style in ("dna", "heart"):  # исходный порядок цифр по ленте (shape_parts сортирует по глубине)
        marks = set(grid["marks"])
        hint = next((d[5] for d in parts["digits"] if d[6]), (255, 220, 150, 255))
        order = [(ch, i in marks) for i, ch in enumerate(grid["digits"])]
    static = style not in ROTATING and style not in ("heart", "wave", "dna")
    # 30.10.2026, слово владельца: «вращаются с большой скоростью, мерцают, вселенная вокруг мерцает».
    # Блёстки вспыхивают на цифрах (≈6 в секунду), по небу проносятся падающие звёзды, туманность дышит.
    spark_rng = random.Random(seed + "spark")
    sparkles = [(spark_rng.uniform(1.2, seconds), spark_rng.randrange(n), spark_rng.uniform(26, 46))
                for _ in range(int(seconds * 9))]
    meteors = [(spark_rng.uniform(0.5, seconds - 1), spark_rng.uniform(0, W), spark_rng.uniform(0, H * 0.5))
               for _ in range(int(seconds / 2.5))]
    nebula = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(nebula).ellipse((W * 0.12, H * 0.2, W * 0.88, H * 0.8), fill=(150, 110, 255, 70))
    nebula = nebula.filter(ImageFilter.GaussianBlur(120))
    cache: dict = {}
    rotated: dict = {}
    glows: dict = {}
    for k in range(int(seconds * FPS)):
        t = k / FPS
        img = parts["bg"].copy()
        sky = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sky)
        for x, y, r, a, speed, phase in stars:
            tw = 0.15 + 0.85 * (0.5 + 0.5 * math.sin(2 * math.pi * 2.5 * speed * t + phase))
            sd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, int(a * tw)))
            if r == 2 and tw > 0.9:  # яркие звёзды вспыхивают лучиками
                sd.line((x - 7, y, x + 7, y), fill=(255, 255, 255, int(120 * tw)))
                sd.line((x, y - 7, x, y + 7), fill=(255, 255, 255, int(120 * tw)))
        for t0, mx, my in meteors:  # падающая звезда: 0,7 с по диагонали с хвостом
            life = (t - t0) / 0.7
            if 0 <= life <= 1:
                hx, hy = mx + 520 * life, my + 300 * life
                for j in range(14):
                    f = j / 14
                    sd.line((hx - 26 * f * 2, hy - 15 * f * 2, hx - 26 * (f + 0.07) * 2, hy - 15 * (f + 0.07) * 2),
                            fill=(255, 245, 220, int(230 * (1 - f) * (1 - abs(2 * life - 1) ** 3))), width=3)
        breath = 0.55 + 0.45 * math.sin(2 * math.pi * 0.35 * t)
        neb = nebula.copy()
        neb.putalpha(neb.getchannel("A").point(lambda v, b=breath: int(v * b)))
        img = Image.alpha_composite(Image.alpha_composite(img, neb), sky)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if style == "dna":  # спираль вращается: точки пересчитываются, дальние цифры — первыми
            pts = _shape_points("dna", 0.8 * t)
            img = draw_dna_backbones(img, pts)
            live = [(x, y, a, int(40 * sc), ch, hint if marked else _shape_color(style, i, sc), marked)
                    for i, ((x, y, a, sc), (ch, marked)) in enumerate(zip(pts, order))]
            digits = sorted(live, key=lambda d: d[3])
        elif style == "heart":  # объёмное сердце вращается (≈30°/с) и бьётся (_motion)
            phase = math.radians(30 * t)
            img = Image.alpha_composite(img, heart_glow(phase, 1 + 0.035 * max(0.0, math.sin(2 * math.pi * 1.1 * t)) ** 6))
            pts = heart3d_points(len(order), phase)
            live = [(x, y, a, int(40 * sc), ch, hint if marked else (255, 150 + int(60 * sc), 170, int(max(70, min(255, 330 * (sc - 0.3))))), marked)
                    for (x, y, a, sc), (ch, marked) in zip(pts, order)]
            digits = sorted(live, key=lambda d: d[3])
        for i, (x, y, angle, size, ch, color, marked) in enumerate(digits):
            appear = min(1.0, max(0.0, (t - 1.6 * i / n) / 0.35))  # цифры прорисовываются по линии формы
            if appear <= 0:
                continue
            light = (0.75 if style == "dna" else 0.55) + (0.25 if style == "dna" else 0.45) * math.sin(
                2 * math.pi * (1.1 * t - i / 28))
            if marked:
                light = 0.75 + 0.25 * math.sin(2 * math.pi * 0.9 * t)
            level = max(1, round(light * appear * LEVELS))
            shade = color[:3] + (int(color[3] * level / LEVELS),)
            x, y, ang = _motion(style, x, y, angle, t)
            if static:
                key = (i, level)
                if key not in rotated:
                    rotated[key] = digit_tile(ch, size, shade, ang, cache)
                tile = rotated[key]
            else:
                tile = digit_tile(ch, size, shade, round(ang), cache)
            if marked and appear >= 1:
                if (ch, size) not in glows:
                    glow = digit_tile(ch, size, color[:3] + (255,), 0, cache).filter(ImageFilter.GaussianBlur(9))
                    glows[(ch, size)] = glow
                g = glows[(ch, size)].rotate(round(ang), resample=Image.BICUBIC)
                g.putalpha(g.getchannel("A").point(lambda v, s=light: int(v * 0.9 * s)))
                layer.alpha_composite(g, (int(x - g.width / 2), int(y - g.height / 2)))
            layer.alpha_composite(tile, (int(x - tile.width / 2), int(y - tile.height / 2)))
        ld = ImageDraw.Draw(layer)
        for t0, idx, size in sparkles:  # блёстки: четырёхлучевая вспышка на цифре, 0,45 с
            life = (t - t0) / 0.45
            if 0 <= life <= 1 and idx < len(digits):
                dx, dy, _ = _motion(style, digits[idx][0], digits[idx][1], 0, t)
                k = math.sin(math.pi * life)
                r = size * k
                col = (255, 240, 200, int(255 * k))
                ld.line((dx - r, dy, dx + r, dy), fill=col, width=2)
                ld.line((dx, dy - r, dx, dy + r), fill=col, width=2)
                ld.line((dx - r * 0.4, dy - r * 0.4, dx + r * 0.4, dy + r * 0.4), fill=col[:3] + (int(160 * k),))
                ld.line((dx - r * 0.4, dy + r * 0.4, dx + r * 0.4, dy - r * 0.4), fill=col[:3] + (int(160 * k),))
                ld.ellipse((dx - 4 * k, dy - 4 * k, dx + 4 * k, dy + 4 * k), fill=(255, 255, 255, int(255 * k)))
        img = Image.alpha_composite(Image.alpha_composite(img, layer), parts["over"])
        yield img.convert("RGB").tobytes()


def render_video(grid: dict, title: str, palette: int, seed: str, seconds: float = SECONDS) -> bytes:
    """MP4 1080×1350 с музыкой. Только для форм (cards.SHAPES); классическая сетка остаётся картинкой."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "grid.mp4"
        args = [ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                "-r", str(FPS), "-i", "-"]
        if MUSIC.exists():
            args += ["-stream_loop", "-1", "-i", str(MUSIC), "-af",
                     f"afade=in:st=0:d=1,afade=out:st={seconds - 1.8}:d=1.8", "-c:a", "aac", "-b:a", "128k"]
        args += ["-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(args, stdin=subprocess.PIPE)
        try:
            for frame in frames(grid, title, palette, seed, seconds):
                proc.stdin.write(frame)
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg не собрал видео матрицы")
        return out.read_bytes()
