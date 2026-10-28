"""Роза Венеры (слово владельца 28.10.2026: «на основе событий по Венере — красивая генерация и пост»).

Настоящие положения Венеры из Swiss Ephemeris за 8 лет: угол — эклиптическая долгота, радиус — расстояние от Земли.
Путь планеты, видимый с Земли, складывается в пятилепестковую розу: за 8 земных лет Венера делает 13 оборотов
вокруг Солнца и 5 раз проходит между Землёй и Солнцем. Линия рисуется светящимися цифрами, точки нижних соединений
(когда Венера ближе всего к Земле) вспыхивают золотом. Это астрономия, а не символ; символическая часть — в тексте поста.
"""

import math
import random
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFilter

from .cards import H, W, _font, _gradient, digit_tile
from .gridvideo import FPS, MUSIC, ffmpeg

START = datetime(2018, 10, 26, tzinfo=timezone.utc)  # нижнее соединение 2018 — роза замыкается к осени 2026
YEARS = 8
STEPS = 900
CX, CY, R = W / 2, H / 2 + 30, 430


def path() -> list[tuple[float, float, float, datetime]]:
    """(x, y, расстояние в а. е., дата) — геоцентрический путь Венеры."""
    import swisseph as swe
    out = []
    for k in range(STEPS):
        d = START + timedelta(days=YEARS * 365.25 * k / STEPS)
        jd = swe.julday(d.year, d.month, d.day, d.hour + d.minute / 60)
        lon, _, dist = swe.calc_ut(jd, swe.VENUS)[0][:3]
        r = R * dist / 1.74  # 1,74 а. е. — дальше Венера от Земли не бывает
        a = math.radians(lon)
        out.append((CX + r * math.cos(a), CY - r * math.sin(a), dist, d))
    return out


def render_video(seconds: float = 13.0, seed: str = "venus") -> bytes:
    import subprocess
    import tempfile
    from pathlib import Path
    rng = random.Random(seed)
    pts = path()
    near = [i for i in range(1, len(pts) - 1) if pts[i][2] < pts[i - 1][2] and pts[i][2] < pts[i + 1][2]]
    digits = [str(rng.randrange(10)) for _ in pts]
    bg = _gradient((10, 8, 30), (52, 20, 70)).convert("RGBA")
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((CX - 260, CY - 260, CX + 260, CY + 260), fill=(255, 200, 150, 50))
    bg = Image.alpha_composite(bg, halo.filter(ImageFilter.GaussianBlur(110)))
    stars = [(rng.randrange(W), rng.randrange(H), rng.choice((1, 1, 2)), rng.randrange(60, 200),
              rng.uniform(0.3, 0.9), rng.uniform(0, 6.3)) for _ in range(170)]
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    d.text((W / 2, 70), "Роза Венеры", font=_font("PlayfairDisplay.ttf", 64, "SemiBold"), fill=(255, 255, 255), anchor="ma")
    d.text((W / 2, 150), "8 лет · 5 лепестков · настоящие положения планеты",
           font=_font("Montserrat.ttf", 30, "Medium"), fill=(235, 220, 245), anchor="ma")
    d.text((W / 2, H - 120), "Swiss Ephemeris · 2018–2026 · @numerita.ai",
           font=_font("Montserrat.ttf", 28, "Medium"), fill=(220, 205, 235), anchor="ma")
    cache: dict = {}
    total = int(seconds * FPS)
    draw_until = int(total * 0.72)  # три четверти времени роза рисуется, потом сияет целиком

    def frame(k: int) -> bytes:
        t = k / FPS
        img = bg.copy()
        sky = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sky)
        for x, y, r, a, sp, ph in stars:
            tw = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(2 * math.pi * sp * t + ph))
            sd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, int(a * tw)))
        img = Image.alpha_composite(img, sky)
        n = min(len(pts), int(len(pts) * min(1.0, k / draw_until)) + 1)
        trail = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td = ImageDraw.Draw(trail)
        for (x0, y0, *_), (x1, y1, *_) in zip(pts[:n], pts[1:n]):
            td.line((x0, y0, x1, y1), fill=(255, 196, 140, 150), width=3)
        img = Image.alpha_composite(img, trail.filter(ImageFilter.GaussianBlur(6)))
        img = Image.alpha_composite(img, trail)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for i in range(0, n, 6):  # цифры по линии, по ним бежит свет
            x, y = pts[i][0], pts[i][1]
            light = 0.55 + 0.45 * math.sin(2 * math.pi * (0.5 * t - i / 120))
            tile = digit_tile(digits[i], 24, (255, 235, 210, int(255 * light)), 0, cache)
            layer.alpha_composite(tile, (int(x - tile.width / 2), int(y - tile.height / 2)))
        for i in near:  # нижние соединения — пять золотых вспышек
            if i < n:
                x, y = pts[i][0], pts[i][1]
                pulse = 14 + 6 * math.sin(2 * math.pi * 1.2 * t)
                ImageDraw.Draw(layer).ellipse((x - pulse, y - pulse, x + pulse, y + pulse), fill=(255, 215, 120, 200))
        x, y = pts[n - 1][0], pts[n - 1][1]  # сама Венера — яркая точка на конце линии
        ImageDraw.Draw(layer).ellipse((x - 11, y - 11, x + 11, y + 11), fill=(255, 250, 235, 255))
        ImageDraw.Draw(layer).ellipse((CX - 9, CY - 9, CX + 9, CY + 9), fill=(120, 190, 255, 255))  # Земля
        img = Image.alpha_composite(Image.alpha_composite(img, layer), over)
        return img.convert("RGB").tobytes()

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "venus.mp4"
        args = [ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                "-r", str(FPS), "-i", "-"]
        if MUSIC.exists():
            args += ["-stream_loop", "-1", "-i", str(MUSIC), "-af",
                     f"afade=in:st=0:d=1,afade=out:st={seconds - 1.8}:d=1.8", "-c:a", "aac", "-b:a", "128k"]
        args += ["-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(args, stdin=subprocess.PIPE)
        try:
            for k in range(total):
                proc.stdin.write(frame(k))
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg не собрал розу Венеры")
        return out.read_bytes()
