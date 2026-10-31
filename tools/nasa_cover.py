"""Обложка Facebook Нумериты из настоящей фотографии телескопа Уэбба (NASA, ESA, CSA, STScI — «Космические утёсы», туманность Киля)
и оригинального образа (assets/numerita_angel.jpg, канон неизменен). Бесплатно ($0). Фон дышит и плывёт (параллакс), звёзды мерцают,
золотой свет из сердца пульсирует; ролик зациклен без шва (всё — периодические функции времени).

Запуск: python tools/nasa_cover.py --bg PATH_TO_carina.png --out DIR [--seconds 24] [--still-only]
Кредит при публикации: «Фон: NASA, ESA, CSA, STScI»."""
import argparse
import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ANGEL = ROOT / "assets" / "numerita_angel.jpg"
W, H, FPS = 1920, 1080, 24


def prep(bg_path):
    bg = Image.open(bg_path).convert("RGB")
    s = 1.22 * max(W / bg.width, H / bg.height) * 1.25  # запас на движение
    bg = bg.resize((int(bg.width * s), int(bg.height * s)), Image.LANCZOS).filter(ImageFilter.UnsharpMask(2, 80, 2))
    bg = np.asarray(bg, np.float32) / 255
    bg = np.clip((bg - 0.02) * 1.15, 0, 1) ** 0.95  # глубже тени, чуть контраста
    ang = Image.open(ANGEL).convert("RGB")
    aw = 1040
    ang = ang.resize((aw, int(ang.height * aw / ang.width)), Image.LANCZOS)
    ang = np.asarray(ang, np.float32) / 255
    h, w = ang.shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    fx = np.minimum(x, w - 1 - x) / 200
    fy = (h - 1 - y) / 330  # низ растворяется
    ft = y / 40
    m = np.clip(np.minimum(np.minimum(fx, fy), ft + 1), 0, 1)
    m = m * m * (3 - 2 * m)
    return bg, ang, m


def stars_from(bg):
    lum = bg.mean(axis=2)
    ys, xs = np.where(lum > 0.88)
    rng = np.random.default_rng(7)
    idx = rng.choice(len(ys), min(260, len(ys)), replace=False)
    return [(int(xs[i]), int(ys[i]), rng.random() * 6.28, 0.5 + rng.random()) for i in idx]


def frame(t, bg, ang, m, stars, T):
    ph = 2 * math.pi * t / T
    bh, bw = bg.shape[:2]
    cx = (bw - W) / 2 + math.sin(ph) * (bw - W) * 0.4
    cy = (bh - H) / 2 + math.cos(ph) * (bh - H) * 0.3
    x0, y0 = int(cx), int(cy)
    f = bg[y0:y0 + H, x0:x0 + W].copy()
    f *= 0.78 + 0.04 * math.sin(ph)  # фон тише образа
    # звёзды мерцают
    yy, xx = np.mgrid[-9:10, -9:10]
    for sx, sy, p, a in stars:
        px, py = sx - x0, sy - y0
        if 10 <= px < W - 10 and 10 <= py < H - 10:
            k = 0.5 + 0.5 * math.sin(ph * 3 + p)
            g = np.exp(-(xx ** 2 + yy ** 2) / (2 * (1.6 + 1.2 * k) ** 2)) * k * a * 0.55
            f[py - 9:py + 10, px - 9:px + 10] += g[..., None] * np.array([1, 0.93, 0.8], np.float32)
            if k > 0.8:  # лучи
                f[py, px - 9:px + 10] += (np.abs(np.arange(-9, 10)) < 9)[:, None] * 0.12 * (1 - np.abs(np.arange(-9, 10)) / 9)[:, None]
    # образ дышит
    ah, aw = ang.shape[:2]
    ox = (W - aw) // 2 + int(8 * math.sin(ph))
    oy = -30 + int(6 * math.sin(ph + 1.2))
    sl_y0, sl_y1 = max(0, -oy), min(ah, H - oy)
    reg = f[oy + sl_y0:oy + sl_y1, ox:ox + aw]
    mm = m[sl_y0:sl_y1, :, None]
    a = ang[sl_y0:sl_y1]
    reg[:] = reg * (1 - mm) + a * mm
    # золотой свет сердца и ореол
    hx, hy = ox + 368 * aw / 720, oy + 495 * aw / 720
    yy2, xx2 = np.mgrid[0:H, 0:W].astype(np.float32)
    d2 = (xx2 - hx) ** 2 + (yy2 - hy) ** 2
    k = 0.75 + 0.25 * math.sin(ph * 2)
    f += (np.exp(-d2 / (2 * 70 ** 2)) * 0.30 * k)[..., None] * np.array([1, 0.78, 0.35], np.float32)
    hx2, hy2 = ox + 330 * aw / 720, oy + 230 * aw / 720
    d3 = (xx2 - hx2) ** 2 + (yy2 - hy2) ** 2
    f += (np.exp(-d3 / (2 * 260 ** 2)) * 0.10 * (0.8 + 0.2 * math.sin(ph * 2 + 1)))[..., None] * np.array([1, 0.85, 0.5], np.float32)
    # виньетка
    v = 1 - 0.38 * np.clip(((xx2 / W - 0.5) ** 2 * 2.2 + (yy2 / H - 0.5) ** 2 * 1.2), 0, 1)
    f *= v[..., None]
    return (np.clip(f, 0, 1) * 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bg", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=int, default=24)
    ap.add_argument("--still-only", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bg, ang, m = prep(a.bg)
    stars = stars_from(bg)
    T = a.seconds
    still = frame(T * 0.18, bg, ang, m, stars, T)
    Image.fromarray(still).save(out / "numerita_fb_cover_16x9.jpg", quality=95, subsampling=0)
    Image.fromarray(still[175:905]).save(out / "numerita_fb_cover_wide_1920x730.jpg", quality=95, subsampling=0)
    if a.still_only:
        return
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out / "numerita_fb_cover_loop.mp4")],
                         stdin=subprocess.PIPE)
    for i in range(T * FPS):
        p.stdin.write(frame(i / FPS, bg, ang, m, stars, T).tobytes())
    p.stdin.close()
    p.wait()


if __name__ == "__main__":
    main()
