"""Живая обложка Facebook: настоящий снимок МКС (NASA: Млечный Путь, Солнце над краем Земли, свечение атмосферы), $0, без Нумериты (она на аватарке).
Звёздное небо плавно вращается над неподвижным краем Земли, звёзды мерцают, солнечная звезда пульсирует, изредка летит метеор; зацикл без шва.
Запуск: python tools/sky_cover.py --src iss073e0982823.jpg --out DIR [--seconds 24] [--still-only]. Кредит: «Фото: NASA / МКС»."""
import argparse, math, subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

W, H, FPS = 1920, 1080, 24
BW = 2520  # рабочая ширина (запас на вращение и сдвиг)


def prep(src):
    im = Image.open(src).convert("RGB")
    Image.MAX_IMAGE_PIXELS = None
    im = im.crop((0, 860, im.width, im.height))  # 8256×4644, 16:9
    bh = int(im.height * BW / im.width)
    im = im.resize((BW, bh), Image.LANCZOS)
    im = im.filter(ImageFilter.GaussianBlur(0.7))
    a = np.asarray(im, np.float32) / 255
    a = np.clip((a - 0.02) * 1.0, 0, 1) ** 1.08
    return im, a


def stars_of(a):
    lum = a.mean(axis=2)
    h = lum.shape[0]
    ys, xs = np.where(lum[: int(h * 0.55)] > 0.55)
    rng = np.random.default_rng(3)
    idx = rng.choice(len(ys), min(300, len(ys)), replace=False)
    return [(int(xs[i]), int(ys[i]), rng.random() * 6.28, 0.4 + rng.random()) for i in idx]


def make_mask(bh):
    y = np.arange(bh, dtype=np.float32)[:, None, None] / bh
    t = np.clip((0.78 - y) / 0.28, 0, 1)  # 1 — небо (вращается), 0 — край Земли (стоит)
    return t * t * (3 - 2 * t)


def frame(t, T, im, a, stars, mask, sun):
    ph = 2 * math.pi * t / T
    bh = a.shape[0]
    rot = im.rotate(math.degrees(0.040 * math.sin(ph)), resample=Image.BICUBIC, center=(BW * 0.5, bh * 0.98))
    r = np.asarray(rot, np.float32) / 255
    r = np.clip((r - 0.02) * 1.0, 0, 1) ** 1.08
    f = r * mask + a * (1 - mask)
    # мерцание звёзд (в системе вращающегося неба)
    c, s = math.cos(0.040 * math.sin(ph)), math.sin(0.040 * math.sin(ph))
    px0, py0 = BW * 0.5, bh * 0.98
    yy, xx = np.mgrid[-8:9, -8:9]
    for sx, sy, p, amp in stars:
        dx, dy = sx - px0, sy - py0
        x, y = int(px0 + dx * c + dy * s), int(py0 - dx * s + dy * c)
        if 9 <= x < BW - 9 and 9 <= y < bh - 9:
            k = 0.5 + 0.5 * math.sin(ph * 4 + p)
            g = np.exp(-(xx ** 2 + yy ** 2) / (2 * (1.1 + 0.9 * k) ** 2)) * k * amp * 0.5
            f[y - 8:y + 9, x - 8:x + 9] += g[..., None] * np.array([0.9, 0.95, 1.0], np.float32)
    # пульс солнечной звезды
    sx, sy = sun
    dx, dy = sx - px0, sy - py0
    X, Y = int(px0 + dx * c + dy * s), int(py0 - dx * s + dy * c)
    k = 0.85 + 0.15 * math.sin(ph * 2)
    y0, y1, x0, x1 = max(0, Y - 380), min(bh, Y + 380), max(0, X - 380), min(BW, X + 380)
    gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    d2 = (gx - X) ** 2 + (gy - Y) ** 2
    glow = np.exp(-d2 / (2 * 150 ** 2)) * 0.04 * k + np.exp(-d2 / (2 * 45 ** 2)) * 0.0 * k
    f[y0:y1, x0:x1] += glow[..., None] * np.array([0.8, 0.9, 1.0], np.float32)
    # метеор раз в ~8 с
    for m in range(3):
        u = (t / T * 3 - m) % 3 if False else ((t / T) * 3 + 0.17 * m) % 1.0
        if u < 0.09:
            q = u / 0.09
            sx0, sy0 = BW * (0.25 + 0.2 * m), bh * (0.12 + 0.07 * m)
            L = 220
            for i in range(60):
                s_ = q * 1.0 - i / 60 * 0.35
                if s_ < 0:
                    continue
                x = int(sx0 + s_ * 420 * (1 + .1 * m)); y = int(sy0 + s_ * 150)
                if 2 <= x < BW - 2 and 2 <= y < bh - 2:
                    f[y - 1:y + 2, x - 1:x + 2] += (1 - i / 60) * math.sin(math.pi * q) * 0.7
    # окно кадра с плавным дрейфом
    cx = (BW - W) / 2 + math.sin(ph) * 60
    cy = (bh - H) - 40 + math.cos(ph) * 25
    fr = f[int(cy):int(cy) + 1418 * 0 + int(H * 1.0), :]
    return f, int(cx), int(cy)


def render(t, T, im, a, stars, mask, sun):
    f, cx, cy = frame(t, T, im, a, stars, mask, sun)
    win = f[cy:cy + H, cx:cx + W]
    return (np.clip(win, 0, 1) * 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=int, default=24); ap.add_argument("--still-only", action="store_true")
    o = ap.parse_args()
    Image.MAX_IMAGE_PIXELS = None
    out = Path(o.out); out.mkdir(parents=True, exist_ok=True)
    im, a = prep(o.src)
    bh = a.shape[0]
    stars = stars_of(a); mask = make_mask(bh)
    sun = (int(BW * 2260 / 8256 * 0 + 160 / 585 * BW), int((185 / 390 * 5504 - 860) / 4644 * bh))
    T = o.seconds
    s = render(T * 0.2, T, im, a, stars, mask, sun)
    Image.fromarray(s).save(out / "numerita_fb_cover_16x9.jpg", quality=96, subsampling=0)
    Image.fromarray(s[175:905]).save(out / "numerita_fb_cover_wide_1920x730.jpg", quality=96, subsampling=0)
    if o.still_only:
        return
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-crf", "14", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out / "numerita_fb_cover_loop.mp4")], stdin=subprocess.PIPE)
    for i in range(T * FPS):
        p.stdin.write(render(i / FPS, T, im, a, stars, mask, sun).tobytes())
    p.stdin.close(); p.wait()


if __name__ == "__main__":
    main()
