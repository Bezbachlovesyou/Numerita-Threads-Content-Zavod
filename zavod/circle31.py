"""Круг-головоломка «Найди все числа до конца видео» (слово владельца 31.10.2026, референс: «Найди числа от 1 до 50»).

Круг из 31 ячейки произвольной формы (ячейки Вороного) — все дни рождения 1–31, то есть все варианты числа души (сознания)
и «двойных энергий» (10–31). Круг медленно вращается: оборот за минуту (6°/с). Ролик 30 с — задание «успеть найти все числа
до конца видео». В кадре нет слов, только цифры и @Numeritabot внизу, поэтому один файл годится для русского и английского
аккаунтов. Фон — фирменный цифровой дождь, звёзды мерцают; музыка наша (assets/channel/cosmos.m4a). Всё кодом, $0.
"""

import math
import random
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .cards import FOOTER, H, LOGO, W, _font, _gradient
from .gridvideo import FPS, MUSIC, ffmpeg
from .matrixrain import Rain

CELLS = 31  # все дни рождения 1–31
SECONDS = 30
DEG_PER_SEC = 6.0  # полный оборот за минуту
R = 470  # радиус круга в пикселях
CENTER = (W // 2, 640)
INK = (46, 30, 22)
CREAM = (247, 232, 196)


def _labels(seeds: np.ndarray, size: int) -> np.ndarray:
    """Для каждой точки круга — номер ближайшего зерна (-1 вне круга)."""
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    inside = (xs - size / 2 + 0.5) ** 2 + (ys - size / 2 + 0.5) ** 2 <= R ** 2
    out = np.empty((size, size), np.int16)
    for y0 in range(0, size, 96):  # кусками, чтобы не раздувать память
        dx = xs[y0:y0 + 96, :, None] - seeds[None, None, :, 0]
        dy = ys[y0:y0 + 96, :, None] - seeds[None, None, :, 1]
        out[y0:y0 + 96] = np.argmin(dx * dx + dy * dy, axis=2)
    out[~inside] = -1
    return out


def assign_numbers(seed: str) -> list[int]:
    """Какое число в какой ячейке: все дни 1–31, каждый ровно один раз, порядок от зерна."""
    numbers = list(range(1, CELLS + 1))
    random.Random(seed + "numbers").shuffle(numbers)
    return numbers


def build_disc(seed: str) -> Image.Image:
    """Круг 2R×2R: 31 ячейка, в каждой своё число; ячейки разного размера, как в образце."""
    rng = random.Random(seed)
    size = 2 * R
    seeds = []
    while len(seeds) < CELLS:  # зёрна без слипания
        x, y = rng.uniform(0, size), rng.uniform(0, size)
        if (x - R) ** 2 + (y - R) ** 2 <= (R - 30) ** 2 and all((x - a) ** 2 + (y - b) ** 2 > 70 ** 2 for a, b in seeds):
            seeds.append((x, y))
    pts = np.array(seeds, np.float32)
    for _ in range(2):  # две подвижки к центрам: ячейки ровнее, но размеры остаются разными
        lab = _labels(pts, size)
        for i in range(CELLS):
            ys, xs = np.nonzero(lab == i)
            if len(xs):
                pts[i] = (xs.mean() * 0.7 + pts[i, 0] * 0.3, ys.mean() * 0.7 + pts[i, 1] * 0.3)
    lab = _labels(pts, size)
    border = np.zeros(lab.shape, bool)
    for shift in ((0, 1), (1, 0)):
        border |= lab != np.roll(lab, shift, axis=(0, 1))
    edge = Image.fromarray((border * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))
    gap = np.asarray(edge) > 0
    solid = ((lab >= 0) & ~gap)
    bevel = Image.fromarray((solid * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(7))
    shade = 0.78 + 0.22 * (np.asarray(bevel, np.float32) / 255)
    rgb = np.stack([np.asarray(CREAM[c], np.float32) * shade for c in range(3)], axis=2).astype(np.uint8)
    disc = Image.fromarray(rgb, "RGB").convert("RGBA")
    disc.putalpha(Image.fromarray((solid * 255).astype(np.uint8)))
    numbers = assign_numbers(seed)
    draw = ImageDraw.Draw(disc)
    for i, number in enumerate(numbers):
        ys, xs = np.nonzero(lab == i)
        area = len(xs)
        font = _font("Montserrat.ttf", int(max(30, min(78, 0.46 * math.sqrt(area)))), "Bold")
        draw.text((xs.mean(), ys.mean()), str(number), font=font, fill=INK, anchor="mm")
    return disc


def _footer() -> Image.Image:
    """Внизу: значок Telegram и @Numeritabot на мягкой тёмной плашке, чтобы дождь из цифр не мешал читать (канон, 30.10.2026)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = _font("Montserrat.ttf", 34, "SemiBold")
    tw = d.textlength(FOOTER, font=font)
    size, cx, y = 44, W / 2, H - 68
    x0 = cx - (tw + size + 14) / 2
    d.rounded_rectangle((x0 - 26, y - 34, x0 + size + 14 + tw + 26, y + 34), radius=34, fill=(8, 6, 26, 170))
    try:
        logo = Image.open(LOGO).convert("RGBA").resize((size, size), Image.LANCZOS)
        img.paste(logo, (int(x0), int(y - size / 2)), logo)
    except Exception:
        d.ellipse((x0, y - size / 2, x0 + size, y + size / 2), fill=(42, 171, 238, 255))
    d.text((x0 + size + 14, y), FOOTER, font=font, fill=(255, 255, 255, 240), anchor="lm")
    return img


def frames(seed: str, seconds: float = SECONDS):
    """Кадры RGB (bytes): дождь из цифр, звёзды, вращающийся круг, полоска «до конца видео»."""
    disc = build_disc(seed)
    rng = random.Random(seed + "sky")
    stars = [(rng.uniform(0, W), rng.uniform(0, H), rng.choice((1, 1, 2)), rng.randint(120, 230),
              rng.uniform(0.3, 1.0), rng.uniform(0, 6.28)) for _ in range(110)]
    bg = _gradient((10, 8, 34), (30, 12, 52)).convert("RGBA")
    rain = Rain(W, H, seed=seed + "rain", size=30, density=0.7)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((CENTER[0] - R - 24, CENTER[1] - R - 24, CENTER[0] + R + 24, CENTER[1] + R + 24),
                                 fill=(255, 205, 120, 255))
    glow = glow.filter(ImageFilter.GaussianBlur(46))
    footer = _footer()
    total = int(seconds * FPS)
    for k in range(total):
        t = k / FPS
        img = bg.copy()
        sky = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sky)
        for x, y, r, a, speed, phase in stars:
            tw = 0.2 + 0.8 * (0.5 + 0.5 * math.sin(2 * math.pi * 2.2 * speed * t + phase))
            sd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, int(a * tw)))
        img = Image.alpha_composite(img, sky)
        img = Image.alpha_composite(img, rain.layer(t, 0.55))
        breath = 0.5 + 0.2 * math.sin(2 * math.pi * 0.25 * t)
        g = glow.copy()
        g.putalpha(g.getchannel("A").point(lambda v, b=breath: int(v * b)))
        img = Image.alpha_composite(img, g)
        spun = disc.rotate(-DEG_PER_SEC * t, resample=Image.BICUBIC)
        img.alpha_composite(spun, (CENTER[0] - R, CENTER[1] - R))
        bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))  # тонкая полоска: сколько осталось до конца видео
        bd = ImageDraw.Draw(bar)
        bar_y, bar_w = 1226, 640
        x0 = (W - bar_w) // 2
        bd.rounded_rectangle((x0, bar_y, x0 + bar_w, bar_y + 8), radius=4, fill=(255, 255, 255, 50))
        bd.rounded_rectangle((x0, bar_y, x0 + max(8, int(bar_w * t / seconds)), bar_y + 8), radius=4, fill=(255, 205, 120, 255))
        img = Image.alpha_composite(Image.alpha_composite(img, bar), footer)
        yield img.convert("RGB").tobytes()


def render_video(seed: str, seconds: float = SECONDS) -> bytes:
    """MP4 1080×1350 с музыкой."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "circle31.mp4"
        args = [ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                "-r", str(FPS), "-i", "-"]
        if MUSIC.exists():
            args += ["-stream_loop", "-1", "-i", str(MUSIC), "-af",
                     f"afade=in:st=0:d=1,afade=out:st={seconds - 1.8}:d=1.8", "-c:a", "aac", "-b:a", "128k"]
        args += ["-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(args, stdin=subprocess.PIPE)
        try:
            for frame in frames(seed, seconds):
                proc.stdin.write(frame)
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg не собрал видео круга")
        return out.read_bytes()
