"""Обложка для страницы Нумериты в Facebook: живая Вселенная кодом ($0), слово владельца 31.10.2026.

Галактика с рукавами, чёрная дыра с аккреционным диском, планеты с кольцами и спутниками, полярное сияние, кометы, звёздные скопления,
созвездия (Большая Медведица, Кассиопея, Орион, Лев, Скорпион, Телец, Близнецы, Стрелец, Лебедь) — без надписей, один файл на любой язык.
Маленькая Нумерита из нашего оригинала (assets/numerita_angel.jpg, канон образа неизменен) плывёт слева направо и обратно, светится из сердца
и третьего глаза; цифры на ней переливаются. Слои двигаются с разной скоростью (параллакс), ролик зациклен без шва.
Размер: 1920×1080 (16:9, как просит видео-обложка Facebook); важное — в центральной полосе 2,63:1 (её показывает ПК), мобильная версия
показывает весь кадр.

Запуск: python tools/cosmos_cover.py --out DIR [--scale 0.5] [--still-only] [--seconds 24]"""

import argparse
import math
from functools import lru_cache
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ANGEL = ROOT / "assets" / "numerita_angel.jpg"
FPS = 24
BASE_W, BASE_H = 1920, 1080


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def value_noise(h, w, rng, cells):
    """Гладкий шум значений: ячейки cells по ширине, интерполяция quintic (решётки не видно)."""
    gh = max(2, int(math.ceil(cells * h / w)) + 2)
    grid = rng.random((gh, cells + 2)).astype(np.float32)
    fx = np.linspace(0, cells, w, dtype=np.float32)
    fy = np.linspace(0, cells * h / w, h, dtype=np.float32)
    ix, iy = np.minimum(fx.astype(np.int32), cells), np.minimum(fy.astype(np.int32), gh - 2)
    tx, ty = fx - ix, fy - iy
    tx, ty = tx ** 3 * (tx * (tx * 6 - 15) + 10), ty ** 3 * (ty * (ty * 6 - 15) + 10)
    g00, g10 = grid[iy][:, ix], grid[iy][:, ix + 1]
    g01, g11 = grid[iy + 1][:, ix], grid[iy + 1][:, ix + 1]
    top = g00 + (g10 - g00) * tx[None, :]
    bot = g01 + (g11 - g01) * tx[None, :]
    return top + (bot - top) * ty[:, None]


def fbm(h, w, rng, octaves=6, base=3, persistence=0.55):
    out, amp, total = np.zeros((h, w), np.float32), 1.0, 0.0
    for o in range(octaves):
        out += amp * value_noise(h, w, rng, base * 2 ** o)
        total += amp
        amp *= persistence
    return out / total


@lru_cache(maxsize=512)
def gauss_sprite(r, power=2.0):
    r = int(r)
    n = int(r * 2 + 1)
    y, x = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    d = np.sqrt(x * x + y * y) / max(r, 1)
    return np.clip(1 - d, 0, 1) ** power


def add(layer, sprite, x, y, color, gain=1.0, alpha=0.0):
    """Прибавить спрайт (h×w) цвета color в слой (premult RGB + A) с центром в x, y."""
    h, w = sprite.shape[:2]
    x0, y0 = int(round(x)) - w // 2, int(round(y)) - h // 2
    X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + w, layer.shape[1]), min(y0 + h, layer.shape[0])
    if X0 >= X1 or Y0 >= Y1:
        return
    s = sprite[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    for c in range(3):
        layer[Y0:Y1, X0:X1, c] += s * color[c] / 255.0 * gain
    if alpha:
        layer[Y0:Y1, X0:X1, 3] = np.maximum(layer[Y0:Y1, X0:X1, 3], s * alpha)


def over(layer, rgb, a, x, y):
    """Слой поверх: rgb — h×w×3 (0..1, не premult), a — h×w (0..1)."""
    h, w = a.shape
    x0, y0 = int(round(x)) - w // 2, int(round(y)) - h // 2
    X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + w, layer.shape[1]), min(y0 + h, layer.shape[0])
    if X0 >= X1 or Y0 >= Y1:
        return
    aa = a[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    cc = rgb[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    dst = layer[Y0:Y1, X0:X1]
    dst[..., :3] = dst[..., :3] * (1 - aa[..., None]) + cc * aa[..., None]
    dst[..., 3] = dst[..., 3] * (1 - aa) + aa


def composite(dst, rgb, a, x, y, hide=1.0):
    """dst (H×W×3, HDR) = dst·(1 − a·hide) + rgb·a в окне вокруг x, y (спрайт поверх кадра)."""
    h, w = a.shape
    x0, y0 = int(round(x)) - w // 2, int(round(y)) - h // 2
    X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + w, dst.shape[1]), min(y0 + h, dst.shape[0])
    if X0 >= X1 or Y0 >= Y1:
        return
    aa = a[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0, None]
    dst[Y0:Y1, X0:X1] = dst[Y0:Y1, X0:X1] * (1 - aa * hide) + rgb[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0] * aa


def occlude_add(layer, rgb_premult, alpha, x, y):
    """В слой (premult RGB + A): закрыть фон альфой и добавить свет rgb_premult (h×w×3)."""
    h, w = alpha.shape
    x0, y0 = int(round(x)) - w // 2, int(round(y)) - h // 2
    X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + w, layer.shape[1]), min(y0 + h, layer.shape[0])
    if X0 >= X1 or Y0 >= Y1:
        return
    a = alpha[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    reg = layer[Y0:Y1, X0:X1]
    reg[..., :3] = reg[..., :3] * (1 - a[..., None]) + rgb_premult[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    reg[..., 3] = reg[..., 3] * (1 - a) + a


class Scene:
    def __init__(self, scale: float, seed: int = 7):
        self.S = scale
        self.W, self.H = int(BASE_W * scale), int(BASE_H * scale)
        self.rng = np.random.default_rng(seed)
        self.pad = {"far": int(70 * scale), "mid": int(130 * scale), "near": int(200 * scale)}
        self.layers = {k: np.zeros((self.H, self.W + 2 * p, 4), np.float32) for k, p in self.pad.items()}
        self.amp = {"far": 40 * scale, "mid": 90 * scale, "near": 150 * scale}
        self.bg = np.zeros((self.H, self.W, 3), np.float32)
        self.twinkle = []
        yy, xx = np.mgrid[0:self.H, 0:self.W].astype(np.float32)
        self.vig = 1 - 0.38 * smooth(0.55, 1.25, np.sqrt(((xx - self.W / 2) / (self.W / 2)) ** 2 + ((yy - self.H / 2) / (self.H / 2)) ** 2))
        self.build()

    def P(self, v):
        return v * self.S

    # ---------- фон: туманности ----------
    def build_background(self):
        H, W, rng = self.H, self.W, self.rng
        y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
        base = np.zeros((H, W, 3), np.float32)
        base[..., 0] = 0.010 + 0.030 * y
        base[..., 1] = 0.012 + 0.012 * y
        base[..., 2] = 0.045 + 0.060 * (1 - y)
        clouds = ((0.95, 0.18, 0.62), (0.15, 0.55, 0.95), (0.95, 0.62, 0.15), (0.45, 0.2, 0.9))
        for i, col in enumerate(clouds):
            n = fbm(H, W, rng, octaves=6, base=2 + i)
            m = smooth(0.46, 0.82, n) ** 1.6
            m *= smooth(0.0, 1.0, fbm(H, W, rng, octaves=3, base=2)) * 0.9
            for c in range(3):
                base[..., c] += m * col[c] * (0.62 if i != 2 else 0.4)
        dust = smooth(0.55, 0.85, fbm(H, W, rng, octaves=5, base=3))
        base *= (1 - 0.45 * dust)[..., None]
        # Млечный Путь: наклонная полоса свечения с пылевыми прожилками
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        u = xx / W
        centre = (0.80 - 0.62 * u + 0.05 * np.sin(u * 7)) * H
        d = (yy - centre) / (0.15 * H)
        band = np.exp(-d * d) * (0.35 + 1.0 * fbm(H, W, rng, octaves=6, base=4))
        lanes = smooth(0.5, 0.8, fbm(H, W, rng, octaves=6, base=7)) * np.exp(-d * d * 0.7)
        glow = band * (1 - 0.7 * lanes)
        for c, v in enumerate((0.95, 0.78, 0.62)):
            base[..., c] += glow * v * 0.42
        base[..., 2] += glow * 0.12
        self.milky = band
        self.bg = base

    # ---------- звёзды ----------
    def stars(self, layer, n, rmax, gain, glow=False, key=None):
        H, W = layer.shape[:2]
        palette = [(255, 246, 235), (190, 212, 255), (255, 214, 170), (255, 235, 200)]
        for _ in range(n):
            x, y = self.rng.uniform(0, W), self.rng.uniform(0, H)
            r = max(1, int(rmax * self.rng.random() ** 3.0 + 1))
            col = palette[self.rng.integers(len(palette))]
            add(layer, gauss_sprite(r, 1.6), x, y, col, gain * (0.4 + 0.6 * self.rng.random()), alpha=0.0)
        if glow:
            for _ in range(max(6, n // 60)):
                x, y = self.rng.uniform(0, W), self.rng.uniform(0, H)
                r = int(self.P(14))
                add(layer, gauss_sprite(r, 2.2), x, y, (200, 220, 255), 0.55)
                add(layer, gauss_sprite(max(1, r // 4), 1.4), x, y, (255, 255, 255), 1.0)
                if key:
                    self.twinkle.append((x, y, key))
                for ang in (0, 90):  # лучики дифракции
                    ln = np.zeros((3, r * 4 + 1), np.float32)
                    ln[1] = np.clip(1 - np.abs(np.linspace(-1, 1, r * 4 + 1)), 0, 1) ** 2.4
                    spike = ln if ang == 0 else ln.T
                    add(layer, spike, x, y, (230, 240, 255), 0.85)

    # ---------- спиральная галактика ----------
    def galaxy_sprite(self, size, arms=2, incl=0.45, rot=0.0, twist=3.4, warm=(255, 222, 170), cool=(150, 190, 255)):
        rng = self.rng
        y, x = np.mgrid[-1:1:complex(0, size), -1:1:complex(0, size)].astype(np.float32)
        u, v = x, y / max(incl, 0.05)
        r = np.sqrt(u * u + v * v) + 1e-4
        th = np.arctan2(v, u)
        arm = (0.5 + 0.5 * np.cos(arms * (th - twist * np.log(r + 0.12)))) ** 2.6
        clump = fbm(size, size, rng, octaves=5, base=6)
        disk = np.exp(-r * 2.4) * smooth(0.98, 0.62, r)
        inten = disk * (0.22 + 1.5 * arm * (0.55 + 0.9 * clump))
        core = np.exp(-r * 13) * 1.9
        rgb = np.zeros((size, size, 3), np.float32)
        for c in range(3):
            rgb[..., c] = inten * (cool[c] / 255) * (1 - np.exp(-r * 5)) + (inten * 0.7 + core) * (warm[c] / 255) * np.exp(-r * 2.2)
        pink = smooth(0.78, 0.95, clump) * arm * disk * 2.0
        rgb[..., 0] += pink * 0.9
        rgb[..., 2] += pink * 0.45
        im = Image.fromarray(np.clip(rgb * 255, 0, 255).astype(np.uint8)).rotate(rot, resample=Image.BICUBIC, expand=True)
        return np.asarray(im, np.float32) / 255.0

    def add_rgb(self, layer, rgb, x, y, gain=1.0):
        h, w = rgb.shape[:2]
        x0, y0 = int(round(x)) - w // 2, int(round(y)) - h // 2
        X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + w, layer.shape[1]), min(y0 + h, layer.shape[0])
        if X0 < X1 and Y0 < Y1:
            layer[Y0:Y1, X0:X1, :3] += rgb[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0] * gain

    # ---------- планета ----------
    def planet_sprite(self, r, kind, light=(-0.62, -0.5, 0.6)):
        n = int(r * 2 + 8)
        y, x = np.mgrid[-1:1:complex(0, n), -1:1:complex(0, n)].astype(np.float32)
        x, y = x * (n / (2 * r)), y * (n / (2 * r))
        rr = np.sqrt(x * x + y * y)
        z = np.sqrt(np.clip(1 - rr * rr, 0, 1))
        L = np.array(light, np.float32)
        L /= np.linalg.norm(L)
        diff = np.clip(0.85 * (x * L[0] + y * L[1] + z * L[2]) + 0.2, 0, 1)
        tex = fbm(n, n, self.rng, octaves=5, base=4)
        if kind == "gas":
            band = 0.5 + 0.5 * np.sin(y * 11 + 2.4 * tex)
            pal = np.array([(0.95, 0.74, 0.46), (0.78, 0.5, 0.34), (0.98, 0.9, 0.7)], np.float32)
            idx = band[..., None] * 2
            col = pal[0] * (1 - np.clip(idx, 0, 1)) + pal[1] * np.clip(idx, 0, 1)
            col = col * (1 - 0.35 * smooth(0.6, 0.9, tex)[..., None]) + pal[2] * 0.35 * smooth(0.6, 0.9, tex)[..., None]
            atmo = np.array([1.0, 0.8, 0.55], np.float32)
        elif kind == "earth":
            def norm(a):
                return (a - a.mean()) / (a.std() + 1e-6)
            tex2 = norm(fbm(n, n, self.rng, octaves=6, base=3, persistence=0.52))
            land = smooth(0.0, 0.35, tex2)[..., None]
            height = smooth(-1.5, 2.0, norm(fbm(n, n, self.rng, octaves=5, base=6)))[..., None]
            ocean = np.array([0.02, 0.14, 0.40], np.float32) * (0.85 + 0.35 * (tex2[..., None] * 0.3 + 0.5))
            shallow = np.array([0.05, 0.40, 0.58], np.float32)
            ground = np.array([0.15, 0.42, 0.15], np.float32) * (1 - height) + np.array([0.60, 0.50, 0.30], np.float32) * height
            coast = smooth(-0.35, 0.0, tex2)[..., None] * (1 - land)
            sea = ocean * (1 - coast) + shallow * coast
            cn = norm(fbm(n, n, self.rng, octaves=6, base=3, persistence=0.55))
            cloud = smooth(0.35, 1.3, cn)[..., None] * 0.92
            col = sea * (1 - land) + ground * land
            col = col * (1 - cloud) + np.array([0.97, 0.98, 1.0], np.float32) * cloud
            lat = np.abs(y) + 0.10 * norm(fbm(n, n, self.rng, octaves=4, base=5))
            polar = smooth(0.80, 0.97, lat)[..., None]
            col = col * (1 - polar) + np.array([0.93, 0.96, 1.0], np.float32) * polar
            atmo = np.array([0.30, 0.62, 1.0], np.float32)
            night_lights = (smooth(0.2, 0.5, tex2) * smooth(0.8, 1.6, norm(fbm(n, n, self.rng, octaves=4, base=12))))[..., None]
        else:  # ice
            col = np.array([0.7, 0.88, 1.0], np.float32) * (0.75 + 0.5 * tex[..., None])
            atmo = np.array([0.6, 0.85, 1.0], np.float32)
        shade = 0.06 + 1.1 * diff[..., None] ** 0.85
        rim = ((1 - z) ** 2.6)[..., None] * atmo * (0.30 + 1.3 * diff[..., None])
        rgb = col * shade + rim
        if kind == "earth":  # огни городов на ночной стороне
            rgb += night_lights * (1 - np.clip(diff[..., None] * 3, 0, 1)) * np.array([1.0, 0.8, 0.45], np.float32) * 0.9
        alpha = np.clip((1 - rr) * r * 0.6, 0, 1)
        return np.clip(rgb, 0, 1.4), alpha

    def ring_masks(self, r, tilt=0.30, inner=1.28, outer=2.35, size=None):
        size = size or int(r * 2 * outer + 8)
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        c = size / 2
        u, v = (xx - c) / r, (yy - c) / (r * tilt)
        rho = np.sqrt(u * u + v * v)
        bands = 0.55 + 0.45 * np.sin(rho * 38) * np.sin(rho * 9 + 1)
        a = smooth(inner, inner + 0.04, rho) * smooth(outer, outer - 0.06, rho) * bands
        a *= 1 - 0.85 * smooth(1.78, 1.80, rho) * smooth(1.90, 1.88, rho)  # деление Кассини
        col = np.stack([0.95 * np.ones_like(rho), 0.86 - 0.1 * (rho - inner), 0.66 - 0.12 * (rho - inner)], -1)
        back = a * (yy < c)
        front = a * (yy >= c)
        return np.clip(col, 0, 1), back * 0.92, front * 0.92

    # ---------- чёрная дыра ----------
    def black_hole(self, layer, cx, cy, R):
        n = int(R * 9)
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
        c = n / 2
        u, v = (xx - c) / R, (yy - c) / R
        rho = np.sqrt(u * u + v * v)
        out = np.zeros((n, n, 3), np.float32)
        warm = np.array([1.0, 0.62, 0.25], np.float32)
        white = np.array([1.0, 0.92, 0.8], np.float32)
        # диск, видимый почти с ребра: узкий эллипс
        dv = v / 0.13
        dr = np.sqrt(u * u + dv * dv)
        disk = smooth(1.15, 1.35, dr) * smooth(3.6, 2.2, dr)
        beam = 0.55 + 0.45 * np.clip(-u / 3.5 + 0.6, 0, 1.4)  # доплеровское усиление слева
        heat = np.exp(-(dr - 1.2) * 0.7)
        d = disk * beam * heat
        out += d[..., None] * (warm * 0.9 + white * 0.4 * np.clip(heat - 0.4, 0, 1)[..., None]) * 1.8
        # линзирование: изображение дальней части диска изгибается над и под тенью
        ring_v = np.abs(np.sqrt(u * u + v * v) - 1.5)
        lens = np.exp(-(ring_v / 0.22) ** 2) * smooth(0.0, 0.9, np.abs(v) * 1.2 + 0.1)
        out += lens[..., None] * (warm * 0.8 + white * 0.25) * (0.5 + 0.7 * beam[..., None]) * 1.2
        photon = np.exp(-((rho - 1.04) / 0.035) ** 2)
        out += photon[..., None] * white * 1.5
        shadow = smooth(1.02, 0.96, rho)
        out *= (1 - shadow[..., None])
        glow = np.exp(-rho * 1.1) * 0.12
        out += glow[..., None] * warm
        occlude_add(layer, np.clip(out, 0, 1.6), np.clip(shadow, 0, 1), cx, cy)

    # ---------- созвездия ----------
    CONST = {
        "dipper": ({"Dubhe": (11.062, 61.75), "Merak": (11.031, 56.38), "Phecda": (11.897, 53.69), "Megrez": (12.257, 57.03),
                    "Alioth": (12.900, 55.96), "Mizar": (13.399, 54.93), "Alkaid": (13.792, 49.31)},
                   [("Dubhe", "Merak"), ("Merak", "Phecda"), ("Phecda", "Megrez"), ("Megrez", "Dubhe"), ("Megrez", "Alioth"),
                    ("Alioth", "Mizar"), ("Mizar", "Alkaid")]),
        "cassiopeia": ({"Caph": (0.153, 59.15), "Schedar": (0.675, 56.54), "Gamma": (0.945, 60.72), "Ruchbah": (1.430, 60.24),
                        "Segin": (1.907, 63.67)},
                       [("Caph", "Schedar"), ("Schedar", "Gamma"), ("Gamma", "Ruchbah"), ("Ruchbah", "Segin")]),
        "orion": ({"Betelgeuse": (5.919, 7.41), "Bellatrix": (5.419, 6.35), "Meissa": (5.585, 9.93), "Alnitak": (5.679, -1.94),
                   "Alnilam": (5.603, -1.20), "Mintaka": (5.533, -0.30), "Saiph": (5.796, -9.67), "Rigel": (5.242, -8.20)},
                  [("Betelgeuse", "Meissa"), ("Meissa", "Bellatrix"), ("Betelgeuse", "Alnitak"), ("Bellatrix", "Mintaka"),
                   ("Mintaka", "Alnilam"), ("Alnilam", "Alnitak"), ("Alnitak", "Saiph"), ("Mintaka", "Rigel")]),
        "leo": ({"Regulus": (10.139, 11.97), "Eta": (10.122, 16.76), "Algieba": (10.333, 19.84), "Adhafera": (10.278, 23.42),
                 "Mu": (9.879, 26.01), "Epsilon": (9.764, 23.77), "Zosma": (11.235, 20.52), "Chertan": (11.237, 15.43),
                 "Denebola": (11.818, 14.57)},
                [("Regulus", "Eta"), ("Eta", "Algieba"), ("Algieba", "Adhafera"), ("Adhafera", "Mu"), ("Mu", "Epsilon"),
                 ("Algieba", "Zosma"), ("Zosma", "Denebola"), ("Denebola", "Chertan"), ("Chertan", "Zosma"), ("Chertan", "Regulus")]),
        "scorpius": ({"Acrab": (16.091, -19.81), "Dschubba": (16.006, -22.62), "Pi": (15.981, -26.11), "Sigma": (16.353, -25.59),
                      "Antares": (16.490, -26.43), "Tau": (16.598, -28.22), "Epsilon": (16.836, -34.29), "Mu": (16.865, -38.05),
                      "Zeta": (16.909, -42.36), "Eta": (17.203, -43.24), "Theta": (17.622, -42.99), "Iota": (17.793, -40.13),
                      "Kappa": (17.708, -39.03), "Lambda": (17.560, -37.10)},
                     [("Acrab", "Dschubba"), ("Dschubba", "Pi"), ("Dschubba", "Sigma"), ("Sigma", "Antares"), ("Antares", "Tau"),
                      ("Tau", "Epsilon"), ("Epsilon", "Mu"), ("Mu", "Zeta"), ("Zeta", "Eta"), ("Eta", "Theta"), ("Theta", "Iota"),
                      ("Iota", "Kappa"), ("Kappa", "Lambda")]),
        "taurus": ({"Aldebaran": (4.599, 16.51), "Elnath": (5.438, 28.61), "Zeta": (5.627, 21.14), "Ain": (4.477, 19.18),
                    "Theta": (4.478, 15.87), "Gamma": (4.330, 15.63), "Delta": (4.382, 17.54)},
                   [("Gamma", "Delta"), ("Delta", "Ain"), ("Gamma", "Theta"), ("Theta", "Aldebaran"), ("Delta", "Aldebaran"),
                    ("Aldebaran", "Zeta"), ("Ain", "Elnath")]),
        "gemini": ({"Castor": (7.577, 31.89), "Pollux": (7.755, 28.03), "Alhena": (6.629, 16.40), "Mebsuta": (6.732, 25.13),
                    "Tejat": (6.383, 22.51), "Wasat": (7.335, 21.98), "Mekbuda": (7.069, 20.57)},
                   [("Castor", "Mebsuta"), ("Mebsuta", "Tejat"), ("Pollux", "Wasat"), ("Wasat", "Mekbuda"), ("Mekbuda", "Alhena"),
                    ("Mebsuta", "Mekbuda"), ("Castor", "Pollux")]),
        "sagittarius": ({"KausAus": (18.403, -34.38), "KausMed": (18.350, -29.83), "KausBor": (18.466, -25.42), "Phi": (18.761, -26.99),
                         "Nunki": (18.921, -26.30), "Ascella": (19.043, -29.88), "Tau": (19.116, -27.67), "Alnasl": (18.097, -30.42)},
                        [("Alnasl", "KausMed"), ("KausMed", "KausAus"), ("KausAus", "Ascella"), ("Ascella", "Tau"), ("Tau", "Nunki"),
                         ("Nunki", "Phi"), ("Phi", "KausBor"), ("KausBor", "KausMed"), ("Phi", "Ascella")]),
        "cygnus": ({"Deneb": (20.690, 45.28), "Sadr": (20.370, 40.26), "Albireo": (19.512, 27.96), "Gienah": (20.770, 33.97),
                    "Delta": (19.750, 45.13)},
                   [("Deneb", "Sadr"), ("Sadr", "Albireo"), ("Delta", "Sadr"), ("Sadr", "Gienah")]),
    }

    def constellation(self, layer, name, cx, cy, k):
        stars, lines = self.CONST[name]
        ras, decs = [v[0] * 15 for v in stars.values()], [v[1] for v in stars.values()]
        ra0, dec0 = sum(ras) / len(ras), sum(decs) / len(decs)
        k = self.P(k)
        pts = {n: (cx - (v[0] * 15 - ra0) * math.cos(math.radians(dec0)) * k, cy - (v[1] - dec0) * k) for n, v in stars.items()}
        ss = 3
        size = int(self.P(520))
        im = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        ox, oy = cx - size / 2, cy - size / 2
        for a, b in lines:
            (x1, y1), (x2, y2) = pts[a], pts[b]
            d.line(((x1 - ox) * ss, (y1 - oy) * ss, (x2 - ox) * ss, (y2 - oy) * ss), fill=(170, 205, 255, 150), width=max(1, int(1.6 * ss * self.S)))
        im = im.resize((size, size), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6))
        arr = np.asarray(im, np.float32) / 255.0
        self.add_rgb(layer, arr[..., :3] * arr[..., 3:4], cx, cy, gain=1.0)
        for n, (x, y) in pts.items():
            big = n in ("Betelgeuse", "Rigel", "Antares", "Aldebaran", "Regulus", "Deneb", "Castor", "Pollux", "Dubhe", "Schedar")
            r = int(self.P(15 if big else 8))
            add(layer, gauss_sprite(r, 2.0), x, y, (200, 225, 255), 0.9 if big else 0.55)
            add(layer, gauss_sprite(max(1, int(self.P(3.2 if big else 2.2))), 1.2), x, y, (255, 255, 255), 1.0)
            if big:
                self.twinkle.append((x, y, "mid"))

    # ---------- сборка статических слоёв ----------
    def build(self):
        S, rng = self.S, self.rng
        self.build_background()
        far, mid, near = self.layers["far"], self.layers["mid"], self.layers["near"]
        self.stars(far, int(2600 * S * S + 800), 2.4, 0.9)
        self.stars(far, int(60 * S + 20), 3, 1.0, glow=True, key="far")
        mp = self.milky
        for _ in range(int(3200 * S * S + 600)):
            x, y = rng.uniform(0, self.W), rng.uniform(0, self.H)
            if rng.random() < min(1.0, mp[int(y), int(x)] * 1.2):
                add(far, gauss_sprite(1, 1.2), x + self.pad["far"], y, (255, 240, 225), 0.5 + 0.7 * rng.random())
        # далёкие галактики
        for _ in range(9):
            sp = self.galaxy_sprite(int(S * rng.integers(60, 130)), arms=int(rng.integers(2, 4)), incl=rng.uniform(0.18, 0.7), rot=rng.uniform(0, 180),
                                    twist=rng.uniform(2.6, 4.2), warm=(255, 215, 170), cool=(170, 190, 255))
            self.add_rgb(far, sp, rng.uniform(0, far.shape[1]), rng.uniform(0, far.shape[0]), gain=0.38)
        # большая спиральная галактика
        g = self.galaxy_sprite(int(S * 760), arms=2, incl=0.42, rot=-24)
        self.add_rgb(mid, g, self.P(640) + self.pad["mid"], self.P(470), gain=1.3)
        g2 = self.galaxy_sprite(int(S * 300), arms=3, incl=0.8, rot=40, warm=(255, 200, 160), cool=(190, 160, 255))
        self.add_rgb(mid, g2, self.P(1230) + self.pad["mid"], self.P(450), gain=1.2)
        # шаровое скопление и Плеяды
        for _ in range(420):
            a, r = rng.uniform(0, 2 * math.pi), abs(rng.normal(0, self.P(26)))
            add(mid, gauss_sprite(max(1, int(self.P(2.4))), 1.4), self.P(1790) + self.pad["mid"] + r * math.cos(a), self.P(250) + r * math.sin(a),
                (255, 232, 190), 0.8)
        add(mid, gauss_sprite(int(self.P(60)), 2.0), self.P(1790) + self.pad["mid"], self.P(250), (255, 215, 160), 0.35)
        for _ in range(9):
            a, r = rng.uniform(0, 2 * math.pi), abs(rng.normal(0, self.P(30)))
            x, y = self.P(1408) + self.pad["mid"] + r * math.cos(a), self.P(240) + r * math.sin(a)
            add(mid, gauss_sprite(int(self.P(20)), 2.0), x, y, (140, 180, 255), 0.55)
            add(mid, gauss_sprite(int(self.P(4)), 1.2), x, y, (230, 240, 255), 1.0)
        # созвездия
        pm = self.pad["mid"]
        for name, x, y, k in (("dipper", 230, 250, 9), ("cassiopeia", 1600, 215, 12), ("orion", 1010, 270, 11), ("leo", 1090, 590, 9),
                              ("scorpius", 190, 520, 8), ("taurus", 1280, 280, 10), ("gemini", 760, 225, 8), ("sagittarius", 1180, 800, 10),
                              ("cygnus", 1810, 520, 9)):
            self.constellation(mid, name, self.P(x) + pm, self.P(y), k)
        self.black_hole(mid, self.P(1670) + pm, self.P(360), self.P(52))
        # планеты (ближний слой)
        pn = self.pad["near"]
        self.planets = {}
        specs = (("earth", 400, 740, 140), ("gas", 1560, 730, 108), ("ice", 820, 830, 58))
        for kind, px, py, pr in specs:
            r = int(self.P(pr))
            rgb, alpha = self.planet_sprite(r, kind)
            cx, cy = self.P(px) + pn, self.P(py)
            halo = {"earth": (80, 150, 255), "gas": (255, 190, 120), "ice": (170, 220, 255)}[kind]
            add(near, gauss_sprite(int(r * 1.7), 2.6), cx, cy, halo, 0.55)
            if kind == "gas":
                col, back, front = self.ring_masks(r)
                over(near, col, back, cx, cy)
                over(near, rgb, alpha, cx, cy)
                over(near, col, front, cx, cy)
            else:
                over(near, rgb, alpha, cx, cy)
            self.planets[kind] = (px, py, pr)
        self.stars(near, int(26 * S + 10), 3, 1.0, glow=True, key="near")
        for key, lay in self.layers.items():
            self.bloom(lay)
        self.angel = self.angel_sprite()

    def bloom(self, layer):
        """Мягкое свечение ярких мест (звёзды, ядра галактик): пирамида из уменьшенных копий."""
        rgb = layer[..., :3]
        hi = np.clip(rgb - 0.55, 0, None)
        h, w = hi.shape[:2]
        acc = np.zeros_like(rgb)
        for div, gain in ((6, 0.9), (16, 0.7)):
            small = [np.asarray(Image.fromarray(np.ascontiguousarray(hi[..., c])).resize((max(2, w // div), max(2, h // div)), Image.BOX))
                     for c in range(3)]
            for c in range(3):
                acc[..., c] += np.asarray(Image.fromarray(small[c]).resize((w, h), Image.BICUBIC)) * gain
        layer[..., :3] += acc * 1.1

    # ---------- Нумерита (наш оригинал) ----------
    def angel_sprite(self):
        im = Image.open(ANGEL).convert("RGB").crop((0, 30, 720, 570))
        a = np.asarray(im, np.float32) / 255.0
        warm = np.clip((a[..., 0] - a[..., 2]) * 3.2 + 0.1, 0, 1)
        lum = a.mean(-1)
        m = np.clip(warm * 0.9 + smooth(0.45, 0.8, lum) * 0.5, 0, 1)
        h, w = m.shape
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        feather = smooth(1.0, 0.45, np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h * 0.42) / (h * 0.58)) ** 2))
        m = m * feather * smooth(0.0, 0.16, xx / w) * smooth(1.0, 0.84, xx / w)
        m *= 1 - smooth(h * 0.74, h * 0.98, yy)  # платье растворяется в космосе
        sw = int(self.P(360))
        sh = int(sw * h / w)
        rgb = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize((sw, sh), Image.LANCZOS), np.float32) / 255.0
        mask = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((sw, sh), Image.LANCZOS), np.float32) / 255.0
        self.angel_wh = (sw, sh)
        self.heart = (370 / w * sw, (495 - 30) / h * sh)
        self.third_eye = (328 / w * sw, (232 - 30) / h * sh)
        return rgb, mask

    # ---------- кадр ----------
    def frame(self, t, T):
        S, W, H = self.S, self.W, self.H
        ph = 2 * math.pi * t / T
        out = self.bg.copy()
        offs = {}
        for key in ("far", "mid", "near"):
            off = int(round(self.amp[key] * math.sin(ph)))
            offs[key] = off
            p = self.pad[key]
            L = self.layers[key][:, p + off:p + off + W]
            out = out * (1 - L[..., 3:4]) + L[..., :3]
        # звёздное мерцание
        tw = np.zeros((H, W, 3), np.float32)
        for i, (x, y, key) in enumerate(self.twinkle):
            a = 0.35 + 0.65 * (0.5 + 0.5 * math.sin((2 + i % 3) * ph + i * 1.7))
            add(tw, gauss_sprite(int(self.P(26)), 2.4), x - self.pad[key] - offs[key], y, (210, 230, 255), 0.55 * a)
        out += tw
        # полярное сияние у голубой планеты
        px, py, pr = self.planets["earth"]
        self.aurora(out, self.P(px) - offs["near"], self.P(py), self.P(pr), ph)
        # спутники планет
        for kind, rad_k, spd, tilt, mr, col in (("earth", 1.9, 3, 0.35, 11, (230, 230, 235)), ("earth", 2.7, -2, 0.35, 6, (200, 190, 175)),
                                                   ("gas", 3.0, 2, 0.30, 9, (190, 210, 255)), ("gas", 3.6, -3, 0.30, 7, (255, 200, 160)),
                                                   ("ice", 2.2, 4, 0.4, 6, (220, 235, 255))):
            px, py, pr = self.planets[kind]
            cx = self.P(px) - offs["near"]
            a = spd * ph + rad_k * 2
            mx, my = cx + self.P(pr) * rad_k * math.cos(a), self.P(py) + self.P(pr) * rad_k * tilt * math.sin(a)
            behind = math.sin(a) < 0 and abs(mx - cx) < self.P(pr)
            if not behind:
                r = int(self.P(mr))
                add(out, gauss_sprite(r, 0.7), mx, my, col, 1.1)
                add(out, gauss_sprite(int(r * 2.2), 2.4), mx, my, col, 0.22)
        # кометы
        for k, (x0, y0, x1, y1, off) in enumerate(((1900, -60, 450, 820, 0.0), (1500, -80, 120, 520, 0.5))):
            u = (t / T + off) % 1.0
            fade = math.sin(math.pi * u) ** 1.5
            hx, hy = self.P(x0 + (x1 - x0) * u), self.P(y0 + (y1 - y0) * u)
            dx, dy = (x0 - x1), (y0 - y1)
            n = math.hypot(dx, dy)
            dx, dy = dx / n, dy / n
            for j in range(110):
                f = j / 110
                add(out, gauss_sprite(max(1, int(self.P(11 * (1 - f) ** 0.8 + 1.5))), 1.6), hx + dx * f * self.P(460), hy + dy * f * self.P(460),
                    (255, 245, 230) if f < 0.25 else (150, 215, 255), 0.30 * (1 - f) ** 1.7 * fade)
                if j % 3 == 0:  # второй, пылевой хвост чуть в сторону
                    add(out, gauss_sprite(max(1, int(self.P(9 * (1 - f) + 2))), 1.6), hx + dx * f * self.P(380) - dy * f * self.P(40),
                        hy + dy * f * self.P(380) + dx * f * self.P(40), (255, 200, 150), 0.14 * (1 - f) ** 1.5 * fade)
            add(out, gauss_sprite(int(self.P(16)), 2.0), hx, hy, (255, 255, 255), 0.95 * fade)
        # Нумерита: плывёт влево-вправо
        self.draw_angel(out, t, T, ph)
        # виньетка и мягкая тональная кривая
        out = (1 - np.exp(-1.45 * out)) * self.vig[..., None]
        return (np.clip(out, 0, 1) * 255).astype(np.uint8)

    def aurora(self, out, cx, cy, R, ph):
        size = int(R * 3.4)
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        x, y = xx - size / 2, yy - size / 2
        rho = np.sqrt(x * x + y * y)
        phi = np.arctan2(x, -y)  # 0 — на север (вверх)
        h = np.maximum(rho - R, 0) / R
        # две неровные ленты: форма и яркость меняются по дуге и во времени (целое число периодов за цикл)
        a1 = 0.5 + 0.5 * np.sin(phi * 3.1 + ph)
        a2 = 0.5 + 0.5 * np.sin(phi * 7.3 - 2 * ph + 1.0)
        fold = a1 * (0.35 + 0.65 * a2)
        rays = 0.55 + 0.45 * np.sin(phi * 37 + 2.3 * np.sin(phi * 13 + ph)) * np.sin(phi * 19 - 2 * ph + 0.7)
        env = np.exp(-((phi - 0.1) / 0.78) ** 2)
        top = 0.04 + 0.2 * fold
        shape = np.exp(-(h / top) ** 1.35) * (1 - np.exp(-h * 70))
        curtain = env * (0.2 + 0.9 * fold) * rays * shape * (rho > R) * smooth(0.5, 0.25, h)
        g = np.clip(1 - h / (top * 1.4), 0, 1)
        col = np.stack([0.15 + 0.95 * (1 - g) ** 2.2, 0.35 + 0.65 * g, 0.55 + 0.4 * (1 - g)], -1)
        glow = (np.clip(curtain, 0, None)[..., None] * col * 3.4).astype(np.float32)
        X0, Y0 = int(cx - size / 2), int(cy - size / 2)
        sx0, sy0, sx1, sy1 = max(X0, 0), max(Y0, 0), min(X0 + size, self.W), min(Y0 + size, self.H)
        if sx0 < sx1 and sy0 < sy1:
            out[sy0:sy1, sx0:sx1] += glow[sy0 - Y0:sy1 - Y0, sx0 - X0:sx1 - X0]

    def draw_angel(self, out, t, T, ph):
        rgb, mask = self.angel
        sw, sh = self.angel_wh
        # путь: влево-вправо через всю сцену, лёгкое парение
        ax = self.W * 0.5 + self.W * 0.30 * math.sin(ph + 1.1)
        ay = self.H * 0.46 + self.P(34) * math.sin(2 * ph) - self.P(10)
        pulse = 0.86 + 0.14 * math.sin(4 * ph)
        # сияние за ней
        add(out, gauss_sprite(int(self.P(240)), 2.4), ax, ay, (255, 210, 140), 0.55 * pulse)
        # переливающийся блик по цифрам (бегущая волна света)
        yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
        wave = np.clip(np.sin((xx / sw * 3.2 - ph * 2) * math.pi) * 0.5 + 0.5, 0, 1) ** 4
        lit = rgb * (1.05 + 1.35 * wave[..., None] * np.clip(rgb.mean(-1, keepdims=True) * 1.6, 0, 1))
        composite(out, np.clip(lit, 0, 1.6), mask, ax, ay, hide=0.55)
        # сердце и третий глаз
        hx, hy = ax - sw / 2 + self.heart[0], ay - sh / 2 + self.heart[1]
        ex, ey = ax - sw / 2 + self.third_eye[0], ay - sh / 2 + self.third_eye[1]
        beat = 0.8 + 0.2 * math.sin(6 * ph)
        add(out, gauss_sprite(int(self.P(80)), 2.2), hx, hy, (255, 215, 150), 0.9 * beat)
        add(out, gauss_sprite(int(self.P(18)), 1.4), hx, hy, (255, 255, 240), 1.0 * beat)
        add(out, gauss_sprite(int(self.P(28)), 2.4), ex, ey, (255, 235, 190), 0.75 * (0.7 + 0.3 * math.sin(5 * ph + 1)))
        add(out, gauss_sprite(int(self.P(7)), 1.2), ex, ey, (255, 255, 255), 0.95)


def encode(frames_iter, path, W, H, seconds):
    args = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "slow", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
    proc = subprocess.Popen(args, stdin=subprocess.PIPE)
    try:
        for f in frames_iter:
            proc.stdin.write(f.tobytes())
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg не собрал обложку")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--seconds", type=float, default=24.0)
    ap.add_argument("--still-only", action="store_true")
    ap.add_argument("--still-at", type=float, default=0.0)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    scene = Scene(a.scale)
    still = scene.frame(a.still_at * a.seconds, a.seconds)
    Image.fromarray(still).save(out / "cover_still.png")
    print("still saved", still.shape, flush=True)
    if a.still_only:
        return
    n = int(a.seconds * FPS)
    encode((scene.frame(i / FPS, a.seconds) for i in range(n)), out / "cover_loop.mp4", scene.W, scene.H, a.seconds)
    print("video saved", flush=True)


if __name__ == "__main__":
    sys.exit(main())
