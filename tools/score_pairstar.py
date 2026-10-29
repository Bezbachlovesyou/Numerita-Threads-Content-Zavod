"""Партитура «Звезды пары» (15 с), синтез кодом — numpy, без чужих треков и прав.

0–4 с: тёплый пад (ре мажор, расстроенные пилы через фильтр) и медленный «пульс» в низах; колокольчики-искры.
4,0 с: подъём (riser) и вдох → вспышка «14»: мягкий удар и шорох.
7,4–10 с: мерцающее арпеджио (1 и 4 кружат), нарастание.
10,0 с: удар рождения звезды — суббас, тарелочный шелест, колокол-аккорд; дальше светлый мажорный финал.
Всё через реверберацию (свёртка с синтетическим залом). Запуск: python tools/score_pairstar.py → assets/channel/pairstar_score.wav
"""
import math
import wave
from pathlib import Path

import numpy as np

SR = 44100
T = 15.0
N = int(SR * T)
t = np.arange(N) / SR
rng = np.random.default_rng(7)


def env(start, attack, hold, release):
    e = np.zeros(N)
    a0, a1 = int(start * SR), int((start + attack) * SR)
    h1 = int((start + attack + hold) * SR)
    r1 = min(N, int((start + attack + hold + release) * SR))
    e[a0:a1] = np.linspace(0, 1, max(1, a1 - a0))
    e[a1:h1] = 1
    if r1 > h1:
        e[h1:r1] = np.linspace(1, 0, r1 - h1) ** 2
    return e


def saw(f, detune=0.0):
    ph = (t * f * (1 + detune)) % 1.0
    return 2 * ph - 1


def lowpass(x, cutoff):
    a = math.exp(-2 * math.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):  # однополюсный фильтр, дважды — мягче
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


def lp(x, cutoff):
    # быстрый фильтр через FFT (плавная АЧХ)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / np.sqrt(1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))


def bell(f, start, dur=3.0, amp=0.25):
    e = np.zeros(N)
    s = int(start * SR)
    n = min(N - s, int(dur * SR))
    tt = np.arange(n) / SR
    tone = (np.sin(2 * np.pi * f * tt) + 0.5 * np.sin(2 * np.pi * f * 2.76 * tt) * np.exp(-tt * 3)
            + 0.25 * np.sin(2 * np.pi * f * 5.4 * tt) * np.exp(-tt * 6))
    e[s:s + n] = tone * np.exp(-tt * (2.2 / dur * 2)) * amp
    return e


def note(name):
    names = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4, "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}
    n, octave = name[:-1], int(name[-1])
    return 440 * 2 ** ((names[n] + 12 * (octave - 4)) / 12)


mix = np.zeros(N)
# пад: D мажор → Bm → G → A → D (по 3 с), три расстроенные пилы на голос
chords = [("D3", "F#3", "A3", "D4"), ("B2", "F#3", "B3", "D4"), ("G2", "D3", "B3", "D4"), ("A2", "E3", "A3", "C#4"),
          ("D3", "A3", "D4", "F#4")]
for k, chord in enumerate(chords):
    s = k * 3.0
    e = env(max(0, s - 0.4), 1.2, 2.0, 1.6)
    for nm in chord:
        f = note(nm)
        mix += e * (saw(f, -0.004) + saw(f, 0.0) + saw(f, 0.005)) * 0.035
mix = lp(mix, 1400)
# пульс в низах (сердце пары), до вспышки
for beat in np.arange(0.5, 4.0, 0.9):
    s = int(beat * SR)
    n = int(0.35 * SR)
    tt = np.arange(n) / SR
    mix[s:s + n] += np.sin(2 * np.pi * (55 + 30 * np.exp(-tt * 20)) * tt) * np.exp(-tt * 9) * 0.35
# искры-колокольчики в начале
for i, st in enumerate([0.3, 1.1, 1.9, 2.6, 3.2]):
    mix += bell(note(["A5", "F#5", "D6", "A5", "E6"][i]), st, 2.5, 0.08)
# подъём к вспышке 14
r = env(2.2, 1.8, 0.0, 0.25) * np.sin(2 * np.pi * (200 + 900 * np.clip((t - 2.2) / 1.8, 0, 1) ** 2) * t)
noise = rng.standard_normal(N)
mix += r * 0.05 + lp(noise, 3000) * env(2.6, 1.4, 0.0, 0.3) * 0.08
# мягкий удар «14»
s = int(4.0 * SR); n = int(1.2 * SR); tt = np.arange(n) / SR
mix[s:s + n] += np.sin(2 * np.pi * (70 + 60 * np.exp(-tt * 15)) * tt) * np.exp(-tt * 4) * 0.5
mix += bell(note("D5"), 4.0, 4.0, 0.18) + bell(note("A5"), 4.02, 4.0, 0.12)
# арпеджио 1 и 4 (7,4–10 с), ускоряется
times = [7.4]
while times[-1] < 9.9:
    times.append(times[-1] + max(0.09, 0.28 - 0.07 * (times[-1] - 7.4)))
seq = ["D5", "F#5", "A5", "D6", "A5", "F#5"]
for i, st in enumerate(times):
    mix += bell(note(seq[i % len(seq)]), st, 0.9, 0.07)
mix += lp(noise, 6000) * env(8.6, 1.4, 0.0, 0.2) * 0.05  # шелест перед рождением
# рождение звезды: суббас, удар, колокол-аккорд
s = int(10.0 * SR); n = int(3.5 * SR); tt = np.arange(n) / SR
mix[s:s + n] += np.sin(2 * np.pi * (45 + 80 * np.exp(-tt * 10)) * tt) * np.exp(-tt * 1.6) * 0.7
mix[s:s + n] += lp(rng.standard_normal(n), 8000)[:n] * np.exp(-tt * 3) * 0.12
for nm, a in [("D4", 0.2), ("F#4", 0.15), ("A4", 0.15), ("D5", 0.15), ("A5", 0.1), ("D6", 0.08)]:
    mix += bell(note(nm), 10.0, 5.0, a)
for i, st in enumerate(np.arange(10.6, 14.2, 0.45)):  # финальные искры
    mix += bell(note(["F#6", "A6", "D6", "E6", "A6", "F#6", "D7", "A6"][i % 8]), st, 1.5, 0.04)

# реверберация: свёртка с затухающим шумом (зал ~2,8 с)
ir_n = int(2.8 * SR)
ir = rng.standard_normal(ir_n) * np.exp(-np.arange(ir_n) / SR * 2.4)
ir = lp(ir, 5000)
ir /= np.sqrt(np.sum(ir ** 2))
size = 1 << int(np.ceil(np.log2(N + ir_n)))
wet = np.fft.irfft(np.fft.rfft(mix, size) * np.fft.rfft(ir, size), size)[:N]
out = 0.62 * mix + 0.55 * wet
out *= env(0, 0.6, T - 2.4, 1.8)
out = np.tanh(out * 1.4) / np.tanh(1.4)
out /= np.max(np.abs(out)) * 1.08
left = out
right = np.roll(out, int(0.011 * SR)) * 0.96 + 0.04 * wet / (np.max(np.abs(wet)) + 1e-9)
stereo = np.stack([left, right], axis=1)
path = Path(__file__).resolve().parent.parent / "assets" / "channel" / "pairstar_score.wav"
with wave.open(str(path), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((stereo * 32000).astype("<i2").tobytes())
print(path)
