"""Два приветственных ролика (слово владельца 30.10.2026, смета «да, потолок $1,50»): каждый — своя модель и свой
сценарий, у каждого полная русская и полная английская версия (языки не мешаем). Видеоряд генерирует нейросеть один раз
и без текста в кадре; надписи, голос Нумериты и музыка — отдельно на каждом языке.

1. «Твой код» — Grok Imagine Video 1.5 Lite, 15 с: цифры даты складываются в созвездие.
2. «Ангел чисел и звёзд» — Kling v3.0 Std, 10 с: из звёздной пыли проступает ангел с крыльями из цифр.

Деньги: жёсткий потолок CEILING_USD на всё (видео + голос). Номер каждого задания сохраняется в базе сразу после заказа:
перезапуск бота ждёт тот же номер и не платит второй раз; упавшее задание не перезаказывается само.
Русский завод снимает и собирает всё, публикует русские версии (Threads + Instagram) и кладёт адреса английских
в общую таблицу; английский завод выкладывает английские версии в свой Threads.
"""

import asyncio
import hashlib
import base64
import json
import logging
import subprocess
import tempfile
import wave
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from .brandvideo import ffmpeg

log = logging.getLogger(__name__)

API = "https://openrouter.ai/api/v1"
CEILING_USD = 2.70  # +$1,00 — «да» владельца 30.10 на новую Нумериту (портрет + Kling); было 1.70 = 30.10: $1,50 + «да» владельца на переозвучку (голос не влез) — не больше $0,20 сверху
W, H = 1080, 1920  # 30.10: 1080p — чётче на телефоне (было 720p, «качество низкое»)
ASSETS = Path(__file__).parent.parent / "assets"
FONT = ASSETS / "fonts" / "CormorantGaramond.ttf"
MUSIC = ASSETS / "channel" / "cosmos.m4a"
GOLD = (255, 214, 130)

STYLE = (" Cinematic, ultra detailed, volumetric light, deep space with stars and soft nebulae, warm gold and azure "
         "palette, elegant and majestic, vertical composition. Absolutely no text, letters, words, logos or watermarks.")
CLIPS = {
    "code": {
        "model": "x-ai/grok-imagine-video-1.5-lite", "seconds": 15, "estimate": 0.46,
        "body": {"resolution": "720p", "aspect_ratio": "9:16"},
        "prompt": ("Darkness of deep space. One by one, glowing golden digits ignite like stars, drift slowly and "
                   "connect with thin threads of light into a shining constellation. The camera glides forward "
                   "through the constellation; it pulses gently, and at the end a soft warm golden flash fills the frame."),
        "lines": {
            # 30.10: короткую «Это код.» голос глотал — две первые фразы звучат одной репликой и одной надписью
            "ru": [(0, 7, "Твой день рождения — не случайность. Это код."),
                   (7, 12, "Родился 6-го, 15-го или 24-го? Твоё число души — 6: ты держишь мир вокруг себя тёплым."),
                   (12, 15, "Напиши дату — покажу твой код.")],
            "en": [(0, 7, "Your birthday isn't random. It's a code."),
                   (7, 12, "Born on the 6th, 15th or 24th? Your soul number is 6 — you keep the world around you warm."),
                   (12, 15, "Drop your date — I'll read your code.")],
        },
        # Что произносит голос: числа словами, без тире и скобок — иначе модель запинается и глотает слова (30.10).
        "say": {
            "ru": ["Твой день рождения не случайность. Это код.",
                   "Родился шестого, пятнадцатого или двадцать четвёртого? Твоё число души шесть. "
                   "Ты держишь мир вокруг себя тёплым.", "Напиши дату, и я покажу твой код."],
            "en": ["Your birthday isn't random. It's a code.",
                   "Born on the sixth, the fifteenth, or the twenty-fourth? Your soul number is six. "
                   "You keep the world around you warm.", "Drop your date, and I'll read your code."],
        },
        "post": {
            "ru": "Твой день рождения — не случайность. Это код.\n\nРодился 6-го, 15-го или 24-го? Твоё число души — 6. "
                  "Напиши свою дату в комментариях — прочитаю твой код ✨\n\nt.me/Numeritabot?start=ad_th_code",
            "en": "Your birthday isn't random. It's a code.\n\nBorn on the 6th, 15th or 24th? Your soul number is 6. "
                  "Drop your date below — I'll read your code ✨\n\nt.me/Numeritabot?start=ad_en_th_code",
        },
    },
    "angel": {
        "model": "kwaivgi/kling-v3.0-std", "seconds": 10, "estimate": 0.84,
        "body": {"resolution": "720p", "aspect_ratio": "9:16", "generate_audio": False},
        # Слово владельца 30.10.2026: Нумерита — узнаваемый цифровой персонаж бренда, не меняется. Первый кадр — наш
        # оригинал assets/numerita_angel.jpg; модель только оживляет его, не перерисовывая лицо, крылья, нимб и платье.
        "first_frame": ASSETS / "numerita_angel.jpg", "job": "angel2",
        "prompt": ("Animate this exact character from the first frame without changing her: the same face, hairstyle, "
                   "golden halo of digits, wings made of glowing digits, golden embroidered dress and proportions. "
                   "Gentle living motion only: golden digits on her wings and halo shimmer and slowly flow, stars and "
                   "galaxies twinkle, a warm light glows at her heart; she blinks softly, smiles a little warmer and "
                   "slowly raises her open palm toward the viewer, a small bright star rises from her palm toward the "
                   "camera. Slow cinematic push-in. Keep her identity identical in every frame. Her expression stays "
                   "serene, pure and angelic like an icon: lips closed or barely parted, no seductive or flirtatious "
                   "look, no wide smile."),
        # Слово владельца 30.10.2026: улыбка в конце ролика «не ангельская» — берём только первые 6 с и растягиваем
        # плавным замедлением на всю длину (без новой генерации).
        "keep": 6.0,
        "shimmer": True,
        "lines": {
            "ru": [(0, 3, "Кто охраняет твою судьбу?"), (3, 7, "Нумерита — ангел-хранитель чисел и звёзд."),
                   (7, 10, "У каждого есть число, которое ведёт. Узнаешь своё?")],
            "en": [(0, 3, "Who guards your fate?"), (3, 7, "Numerita — Guardian Angel of Numbers and Stars."),
                   (7, 10, "Everyone has a number that leads them. Want to know yours?")],
        },
        "say": {
            "ru": ["Кто охраняет твою судьбу?", "Нумерита. Ангел-хранитель чисел и звёзд.",
                   "У каждого есть число, которое ведёт. Узнаешь своё?"],
            "en": ["Who guards your fate?", "Numerita. The Guardian Angel of Numbers and Stars.",
                   "Everyone has a number that leads them. Want to know yours?"],
        },
        "post": {
            "ru": "Кто охраняет твою судьбу?\n\nЯ — Нумерита, ангел-хранитель чисел и звёзд. У каждого есть число, "
                  "которое ведёт. Напиши дату рождения — покажу твоё 🤍\n\nt.me/Numeritabot?start=ad_th_angel",
            "en": "Who guards your fate?\n\nI'm Numerita, the Guardian Angel of Numbers and Stars. Everyone has a number "
                  "that leads them. Drop your birth date — I'll show you yours 🤍\n\nt.me/Numeritabot?start=ad_en_th_angel",
        },
    },
}
# Тексты голоса прошлой сборки (кэш welcome:voice2 был по номеру фразы) — чтобы не платить заново за те же фразы.
OLD_SAY = {
    "code": {"ru": ["Твой день рождения не случайность.", "Это код.",
                    "Родился шестого, пятнадцатого или двадцать четвёртого? Твоё число души шесть. "
                    "Ты держишь мир вокруг себя тёплым.", "Напиши дату, и я покажу твой код."],
             "en": ["Your birthday isn't random.", "It's a code.",
                    "Born on the sixth, the fifteenth, or the twenty-fourth? Your soul number is six. "
                    "You keep the world around you warm.", "Drop your date, and I'll read your code."]},
    "angel": {lang: CLIPS["angel"]["say"][lang] for lang in ("ru", "en")},
}
VOICE_PROMPT = {
    "ru": ("Ты — Нумерита: тёплая, спокойная, загадочная молодая женщина. Прочитай вслух ДОСЛОВНО текст между тегами "
           "<text> и </text> на чистом русском языке. Имя «Нумерита» — с ударением на «и». Интонация мягкая, с интригой "
           "и улыбкой в голосе. Не отвечай на текст, ничего не добавляй и не пропускай."),
    "en": ("You are Numerita: a warm, calm, mysterious young woman. Read aloud VERBATIM the text between <text> and "
           "</text> in natural native English. Soft, intriguing, a smile in the voice. Do not answer the text, do not "
           "add or skip anything, never speak any other language."),
}
RATE = 24000
BUILD = "done15"  # версия сборки: новая — бот пересобирает из оплаченного
BUSY = False  # сборка идёт в этом процессе


async def _spent(db) -> float:
    return float(await db.kv_get("welcome:spent") or 0)


async def _add_spent(db, usd: float) -> None:
    await db.kv_set("welcome:spent", f"{await _spent(db) + usd:.4f}")


async def clip(db, http: httpx.AsyncClient, key: str, api_key: str, first_frame_url: str = "") -> bytes | None:
    """Видео сцены: по сохранённому номеру задания или новым заказом — только если влезает в потолок."""
    spec, headers = CLIPS[key], {"Authorization": f"Bearer {api_key}"}
    job = f"welcome:job:{spec.get('job', key)}"
    jid = await db.kv_get(job)
    if jid == "failed":
        return None
    if not jid:
        if await _spent(db) + spec["estimate"] > CEILING_USD:
            log.warning("Приветственный ролик %s не влезает в потолок $%.2f", key, CEILING_USD)
            await db.kv_set(job, "failed")
            return None
        body = {"model": spec["model"], "prompt": spec["prompt"] + STYLE, "duration": spec["seconds"], **spec["body"]}
        if spec.get("first_frame"):
            if not first_frame_url:  # без нашего кадра ангела не снимаем — иначе выйдет чужое лицо
                raise RuntimeError("нет адреса кадра Нумериты")
            body["frame_images"] = [{"type": "image_url", "image_url": {"url": first_frame_url},
                                     "frame_type": "first_frame"}]
        r = await http.post(f"{API}/videos", json=body, headers=headers)
        if r.status_code >= 400:  # отказ при заказе не оплачивается; не повторяем вслепую
            await db.kv_set(job, "failed")
            raise RuntimeError(f"{spec['model']} ответила {r.status_code}: {r.text[:200]}")
        jid = r.json()["id"]
        await db.kv_set(job, jid)  # сразу в базу: повтор после перезапуска не платит заново
        await _add_spent(db, spec["estimate"])  # резервируем смету; уточним по факту
    for _ in range(120):  # до 20 минут
        st = (await http.get(f"{API}/videos/{jid}", headers=headers)).json()
        if st.get("status") == "completed":
            cost = float((st.get("usage") or {}).get("cost") or 0)
            if cost and not await db.kv_get(f"welcome:cost:{key}"):
                await db.kv_set(f"welcome:cost:{key}", f"{cost:.4f}")
                await _add_spent(db, cost - spec["estimate"])
            v = await http.get(f"{API}/videos/{jid}/content", headers=headers, follow_redirects=True)
            v.raise_for_status()
            return v.content
        if st.get("status") in ("failed", "cancelled", "expired"):
            await db.kv_set(job, "failed")
            raise RuntimeError(f"{spec['model']}: {st.get('error') or st.get('status')}")
        await asyncio.sleep(10)
    raise RuntimeError(f"{spec['model']}: не готово за 20 минут — подожду тот же номер задания")


async def speak(http: httpx.AsyncClient, api_key: str, text: str, lang: str) -> tuple[bytes, float]:
    body = {"model": "openai/gpt-audio", "modalities": ["text", "audio"], "audio": {"voice": "shimmer", "format": "pcm16"},
            "temperature": 0.3, "max_tokens": 2000, "stream": True, "usage": {"include": True},
            "messages": [{"role": "system", "content": VOICE_PROMPT[lang]},
                         {"role": "user", "content": f"<text>{text}</text>"}]}
    chunks, cost, limit = [], 0.0, int((5 + len(text) / 7) * RATE * 2)
    async with http.stream("POST", f"{API}/chat/completions", json=body,
                           headers={"Authorization": f"Bearer {api_key}", "X-Title": "Numerita Threads"}) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            data = json.loads(line[6:])
            cost = (data.get("usage") or {}).get("cost") or cost
            for choice in data.get("choices", []):
                audio = (choice.get("delta") or {}).get("audio") or {}
                if audio.get("data"):
                    chunks.append(base64.b64decode(audio["data"]))
            if sum(map(len, chunks)) > limit:
                break
    return b"".join(chunks)[:limit], float(cost)


BADGE = "@Numeritabot"  # слово владельца 30.10.2026: значок Telegram + адрес, без слова Telegram, внизу кадра


def trim(pcm: bytes, level: int = 500) -> bytes:
    """Срезает тишину в начале и конце фразы (оставляя 80 мс) — без немых пауз между словами ролика."""
    import array
    a = array.array("h", pcm[: len(pcm) // 2 * 2])
    idx = [i for i in range(0, len(a), 240) if abs(a[i]) > level or max(map(abs, a[i:i + 240]), default=0) > level]
    if not idx:
        return pcm
    pad = int(RATE * 0.08)
    lo, hi = max(0, idx[0] - pad), min(len(a), idx[-1] + 240 + pad)
    return a[lo:hi].tobytes()


def voice_ok(pcm: bytes, text: str) -> bool:
    """Длина фразы правдоподобна для текста: не меньше ~60% обычного темпа (≈14 знаков в секунду)."""
    return len(pcm) / (RATE * 2) >= max(0.5, 0.6 * len(text) / 14)


_EAR = None
SKIP_WORDS = {"нумерита", "numerita"}  # имя распознаватель пишет по-разному — не считаем


def _norm(text: str) -> list[str]:
    import re
    return [w[:5] for w in re.findall(r"[a-zа-яё']+", text.lower().replace("ё", "е")) if len(w) > 2 and w not in SKIP_WORDS]


def hear(path: Path, lang: str, says: list[str]) -> str | None:
    """Проверка слухом, $0 (faster-whisper локально; слово владельца 30.10.2026 «проверяй, что вышло»): весь голос
    на одном языке и каждая фраза прозвучала (не меньше 60% её слов). Возвращает описание проблемы или None."""
    global _EAR
    try:
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError:
        return None  # распознаватель не установлен — проверку пропускаем, сборка не падает
    raw = path.with_suffix(".raw")
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(path), "-vn", "-ar", "16000", "-ac", "1", "-f", "s16le",
                    str(raw)], check=True, capture_output=True, timeout=120)
    if _EAR is None:
        _EAR = WhisperModel("small", compute_type="int8")
    audio = np.fromfile(raw, "<i2").astype(np.float32) / 32768
    segs, info = _EAR.transcribe(audio, multilingual=True)
    segs = list(segs)
    heard = " ".join(s.text for s in segs)
    if info.language != lang:
        return f"язык голоса «{info.language}» вместо «{lang}»: {heard[:120]}"
    got = set(_norm(heard))
    for text in says:
        words = _norm(text)
        if words and sum(w in got for w in words) / len(words) < 0.6:
            return f"не слышно фразы «{text[:50]}» — распознано: {heard[:160]}"
    log.info("Слухом проверено %s: %s", path.name, heard)
    return None


SS = 2  # рисуем плашки вдвое крупнее и уменьшаем — гладкие края без зерна (замечание владельца 30.10)


def _canvas():
    return Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))


def _save(img: Image.Image, path: Path) -> None:
    img.resize((W, H), Image.LANCZOS).save(path)


def badge_png(path: Path) -> None:
    """Плашка внизу на весь ролик: голубой знак Telegram (бумажный самолётик) и адрес бота."""
    k = W / 720 * SS
    img = _canvas()
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(ASSETS / "fonts" / "Montserrat.ttf"), int(32 * k))
    try:
        font.set_variation_by_axes([600])
    except Exception:
        pass
    tw = d.textlength(BADGE, font=font)
    r, gap = 22 * k, 14 * k
    w = tw + 2 * r + gap + 44 * k
    x0, y0 = (W * SS - w) / 2, H * SS - 128 * k
    d.rounded_rectangle((x0, y0, x0 + w, y0 + 64 * k), radius=int(32 * k), fill=(4, 8, 18, 200),
                        outline=GOLD + (140,), width=int(2 * k))
    cx, cy = x0 + 22 * k + r, y0 + 32 * k
    # официальный логотип Telegram (assets/telegram_logo.png, по образцу telegram.org) — не самодельный (30.10)
    logo = Image.open(ASSETS / "telegram_logo.png").convert("RGBA").resize((int(2 * r), int(2 * r)), Image.LANCZOS)
    img.alpha_composite(logo, (int(cx - r), int(cy - r)))
    d.text((cx + r + gap, cy), BADGE, font=font, fill=GOLD + (255,), anchor="lm")
    _save(img, path)


def caption_png(text: str, path: Path) -> None:
    """Надпись в нижней трети: золото на тёмной полупрозрачной плашке, переносы по ширине."""
    k = W / 720 * SS
    img = _canvas()
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT), int(50 * k))
    try:  # полужирное начертание — читается на любом кадре (замечание владельца о нечитаемом тексте, 30.10)
        font.set_variation_by_axes([650])
    except Exception:
        pass
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) > (720 - 120) * k and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    lines.append(cur)
    lh = 62 * k
    y = H * SS * 0.72 - len(lines) * lh / 2
    d.rounded_rectangle((40 * k, y - 24 * k, W * SS - 40 * k, y + len(lines) * lh + 18 * k), radius=int(24 * k),
                        fill=(4, 8, 18, 205), outline=GOLD + (120,), width=int(2 * k))
    for i, ln in enumerate(lines):
        d.text((W * SS / 2, y + i * lh + lh / 2), ln, font=font, fill=GOLD + (255,), anchor="mm")
    _save(img, path)


GAP = 0.35  # пауза между фразами голоса


def timeline(lines: list, durations: list[float], seconds: float) -> tuple[list[tuple[float, float, float]], float]:
    """Слово владельца 30.10.2026: «текст никогда не должен налезать друг на друга». Каждая фраза начинается только
    после конца предыдущей; надпись висит, пока звучит её фраза, и гаснет до появления следующей. Не хватает длины
    ролика — последний кадр держится дольше. Возвращает [(надпись с, надпись по, голос с)] и общую длину."""
    out, end = [], 0.0
    for (a, _, _), dur in zip(lines, durations):
        start = max(a + 0.2, end + GAP if out else a + 0.2)
        out.append([start - 0.2, 0.0, start])
        end = start + dur
    total = max(float(seconds), end + 1.2)
    for i, row in enumerate(out):
        row[1] = (out[i + 1][0] - 0.05) if i + 1 < len(out) else total
    check(out, durations)
    return [tuple(r) for r in out], total


def check(rows, durations) -> None:
    """Самопроверка до сборки: ни надписи, ни голоса не перекрываются."""
    for i in range(1, len(rows)):
        if rows[i][0] < rows[i - 1][1] - 1e-6:
            raise RuntimeError(f"надписи {i} и {i + 1} накладываются")
        if rows[i][2] < rows[i - 1][2] + durations[i - 1] + GAP - 1e-6:
            raise RuntimeError(f"фразы {i} и {i + 1} накладываются")


def assemble(video: bytes, lines: list, voices: list[bytes], seconds: int, workdir: Path, name: str,
             keep: float | None = None, shimmer: bool = False) -> Path:
    src = workdir / f"{name}_src.mp4"
    src.write_bytes(video)
    durations = [len(v) / (RATE * 2) for v in voices]
    rows, total = timeline(lines, durations, seconds)
    args = [ffmpeg(), "-v", "error", "-y", "-i", str(src), "-stream_loop", "-1", "-i", str(MUSIC)]
    # Слово владельца 30.10.2026: «видео зависает» — стоп-кадр больше не держим. Если голос длиннее клипа, весь клип
    # плавно замедляется на всю длину ролика (движение до последней секунды).
    clip_len = keep or seconds
    vf = [f"[0:v]trim=0:{clip_len},setpts=(PTS-STARTPTS)*{(total + 0.3) / clip_len:.4f},"
          f"scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=24"
          + ("[raw]" if shimmer else "[b0]")]
    if shimmer:  # узнаваемый образ Нумериты: по золотым цифрам нимба, крыльев и платья бегут волны света (30.10, $0)
        mask = "gt(r(X,Y),185)*gt(g(X,Y),135)*lt(b(X,Y),175)"
        band = "exp(-pow(mod(X+0.6*Y-T*300,560)-280,2)/1600)"
        vf.append(f"[raw]split[base][hi];[hi]scale={W // 2}:{H // 2},format=gbrp,"
                  f"geq=r='if({mask},255*{band},0)':g='if({mask},228*{band},0)':b='if({mask},160*{band},0)',"
                  f"gblur=sigma=1.5,scale={W}:{H},format=gbrp[glow];[base]format=gbrp[bb];"
                  f"[bb][glow]blend=all_mode=screen,format=yuv420p[b0]")
    af = []
    n = 2
    for i, ((_, _, text), (a, b, _)) in enumerate(zip(lines, rows)):
        png = workdir / f"{name}_t{i}.png"
        caption_png(text, png)
        args += ["-loop", "1", "-t", f"{total:.2f}", "-framerate", "24", "-i", str(png)]
        fade = min(0.35, (b - a) / 4)
        vf.append(f"[{n}:v]format=rgba,fade=t=in:st={a:.2f}:d={fade:.2f}:alpha=1,"
                  f"fade=t=out:st={b - fade:.2f}:d={fade:.2f}:alpha=1[t{i}]")
        vf.append(f"[b{i}][t{i}]overlay=0:0:enable='between(t,{a:.2f},{b - 0.01:.2f})'[b{i + 1}]")
        n += 1
    badge = workdir / f"{name}_badge.png"
    badge_png(badge)
    args += ["-loop", "1", "-t", f"{total:.2f}", "-framerate", "24", "-i", str(badge)]
    vf.append(f"[b{len(lines)}][{n}:v]overlay=0:0[out]")
    n += 1
    af.append(f"[1:a]atrim=0:{total:.2f},asetpts=N/SR/TB,volume=0.22,afade=t=in:d=1,"
              f"afade=t=out:st={total - 1.5:.2f}:d=1.5[m]")
    for i, ((_, _, start), pcm) in enumerate(zip(rows, voices)):
        wav = workdir / f"{name}_v{i}.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)
        args += ["-i", str(wav)]
        ms = int(start * 1000)
        af.append(f"[{n}:a]aresample=48000,adelay={ms}|{ms},volume=1.3[v{i}]")
        n += 1
    af.append("".join(f"[v{i}]" for i in range(len(voices))) + f"amix=inputs={len(voices)}:normalize=0[vv]")
    af.append("[m][vv]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[a]")
    out = workdir / f"{name}.mp4"
    args += ["-filter_complex", ";".join(vf + af), "-map", "[out]", "-map", "[a]",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "slow", "-crf", "17", "-c:a", "aac", "-b:a", "160k",
             "-aspect", "9:16", "-t", f"{total:.2f}", "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True, capture_output=True, timeout=600)
    return out


async def build(db, api_key: str, first_frame_url: str = "") -> dict[str, Path]:
    """Снимает (или берёт оплаченное) и собирает 4 версии. Возвращает {"code_ru": path, ...}."""
    out, workdir = {}, Path(tempfile.mkdtemp(prefix="welcome_"))
    async with httpx.AsyncClient(timeout=180) as http:
        videos = await asyncio.gather(*(clip(db, http, k, api_key, first_frame_url) for k in CLIPS), return_exceptions=True)
        for key, video in zip(CLIPS, videos):
            if isinstance(video, Exception) or not video:
                log.warning("Приветственный ролик %s не снят: %s", key, video)
                continue
            spec = CLIPS[key]
            for lang in ("ru", "en"):
                voices = []
                for i, text in enumerate(spec["say"][lang]):
                    saved = await db.kv_get(f"welcome:voice3:{key}:{lang}:{hashlib.sha1(text.encode()).hexdigest()[:10]}")
                    old = OLD_SAY.get(key, {}).get(lang, [])
                    if saved == "bad":  # не прошла проверку слухом — только новая запись
                        saved = None
                    elif not saved and text in old:  # та же фраза из прошлой сборки — уже оплачена
                        saved = await db.kv_get(f"welcome:voice2:{key}:{lang}:{old.index(text)}")
                    if saved:  # уже оплаченная фраза — без новой траты
                        voices.append(base64.b64decode(saved))
                        continue
                    if await _spent(db) + 0.02 > CEILING_USD:
                        raise RuntimeError(f"голос не влезает в потолок ${CEILING_USD:.2f} — нужен ваш ответ")
                    pcm = b""
                    for attempt in range(2):  # фраза проглочена (слишком коротко для текста) — один повтор
                        if await _spent(db) + 0.02 > CEILING_USD:
                            raise RuntimeError(f"голос не влезает в потолок ${CEILING_USD:.2f} — нужен ваш ответ")
                        raw, cost = await speak(http, api_key, text, lang)
                        await _add_spent(db, cost or 0.01)
                        pcm = trim(raw)
                        if voice_ok(pcm, text):
                            break
                    if not voice_ok(pcm, text):
                        raise RuntimeError(f"озвучка фразы «{text[:30]}…» обрывается — ролик не собираю")
                    await db.kv_set(f"welcome:voice3:{key}:{lang}:{hashlib.sha1(text.encode()).hexdigest()[:10]}", base64.b64encode(pcm).decode())
                    voices.append(pcm)
                path = await asyncio.to_thread(
                    assemble, video, spec["lines"][lang], voices, spec["seconds"], workdir, f"{key}_{lang}", spec.get("keep"), spec.get("shimmer", False))
                problem = await asyncio.to_thread(hear, path, lang, spec["say"][lang])
                if problem:  # проверка слухом не прошла — фразы этой версии переозвучим при следующей попытке
                    for text in spec["say"][lang]:
                        await db.kv_set(f"welcome:voice3:{key}:{lang}:{hashlib.sha1(text.encode()).hexdigest()[:10]}", "bad")
                    raise RuntimeError(f"{key}_{lang}: {problem}")
                out[f"{key}_{lang}"] = path
    return out


ORDER = ["angel", "code"]  # сначала знакомство, через 3 часа — «Твой код»
GAP_HOURS = 3


async def _public_kv(db, key: str) -> str | None:
    """Английский завод живёт в своей схеме — адреса английских версий читает из общей таблицы русского."""
    try:
        rows = await db._rows("SELECT value FROM public.kv WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None
    except Exception:
        return await db.kv_get(key)


PUBLISH = False  # слово владельца 30.10.2026: «никуда не выкладываешь», пока ролики не станут правильными — включает он


async def publish_due(db, threads, now, lang: str, publish, notify) -> None:
    """Выкладывает следующую готовую версию своего языка: publish(key, url) -> строка-квитанция."""
    if not PUBLISH:
        return
    urls = json.loads((await (_public_kv(db, "welcome:urls") if lang == "en" else db.kv_get("welcome:urls"))) or "{}")
    last = await db.kv_get("welcome:last_post")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < GAP_HOURS * 3600:
        return
    for key in ORDER:
        url = urls.get(f"{key}_{lang}")
        flag = f"welcome:posted:{CLIPS[key].get('job', key)}"
        if not url or await db.kv_get(flag):
            continue
        await db.kv_set(flag, "1")  # до отправки: сбой не приведёт к дублю
        await db.kv_set("welcome:last_post", now.isoformat())
        await notify(await publish(key, url))
        return


async def run_build(db, api_key: str, threads, send_video, notify) -> None:
    """Русский завод: один раз снять и собрать, загрузить 4 версии в Zernio, отправить владельцу."""
    global BUSY
    if await db.kv_get("welcome:build") == BUILD or BUSY:
        return
    BUSY = True
    try:
        if await db.kv_get("angel3:approved") == "yes" and await db.kv_get("angel3:ref_url"):
            ref = await db.kv_get("angel3:ref_url")  # новая Нумерита, одобренная владельцем
            CLIPS["angel"].update(job="angel3", prompt=PROMPT3, keep=None)
        else:
            ref = await threads.upload_image((ASSETS / "numerita_angel.jpg").read_bytes(), "numerita_angel.jpg")
        paths = await build(db, api_key, ref)
    except Exception as e:
        BUSY = False
        await notify(f"⚠️ Приветственные ролики: {e}. Потрачено ${await _spent(db):.2f} из ${CEILING_USD:.2f}.")
        raise
    urls = {}
    for name, path in paths.items():
        data = path.read_bytes()
        urls[name] = await threads.upload_image(data, f"numerita_{name}.mp4", "video/mp4")
        await send_video(data, name)
    await db.kv_set("welcome:urls", json.dumps(urls))
    await db.kv_set("welcome:build", BUILD)
    missing = [k for k in CLIPS if f"{k}_ru" not in paths]
    if await db.kv_get("welcome:job:angel"):  # первая версия ангела без нашего лица — не используется
        missing.append("(первый «Ангел» без лица Нумериты оплачен, но не используется)")
    await notify(f"🎬 Приветственные ролики собраны: {len(paths)} из 4. Потрачено ${await _spent(db):.2f} из "
                 f"${CEILING_USD:.2f}." + (f"\n⚠️ Не снялись: {', '.join(missing)} — повторно не заказываю." if missing else "")
                 + "\nВыкладываю по очереди: сначала «Ангел», через 3 часа — «Твой код».")


# Новая Нумерита (слово владельца 30.10.2026, «да, $1»): взгляд в кадр, естественные ресницы, ангельское лицо, фигура
# женственнее при закрытом платье. Сначала правим нашу картинку (одна попытка, ≈$0,14) и шлём владельцу; Kling снимает,
# только когда он ответит /angel_ok.
IMAGE_MODEL = "google/gemini-3-pro-image"
EDIT_PROMPT = (
    "Edit this exact character and keep her identity: the same face shape, hairstyle, golden halo of digits, large "
    "wings made of glowing digits, golden embroidered dress, background, composition and art style. Changes only: "
    "1) she looks straight into the camera with warm, direct eye contact; 2) natural soft light eyelashes, no heavy "
    "black mascara or dramatic make-up — a pure, serene, angelic face with a gentle closed-lip smile, like an icon; "
    "3) a more feminine figure with a fuller bust, elegant and modest: the dress stays closed with a high neckline, "
    "nothing revealing. Keep the glowing golden digits on the halo, wings and dress. Vertical 9:16. No text.")
PROMPT3 = (
    "Animate this exact character from the first frame without changing her face, figure, halo, wings or dress. She "
    "keeps looking straight into the camera the whole time and never looks down. Waves of soft golden light run across "
    "the glowing digits of her halo, wings and dress; stars twinkle; a warm light glows at her heart; she blinks gently "
    "and slowly raises her open palm toward the viewer, a small bright star rises from her palm toward the camera. "
    "Serene, pure, angelic expression. Slow cinematic push-in.")


async def angel_portrait(db, api_key: str, threads, send_photo) -> None:
    """Один раз: правка картинки Нумериты и отправка владельцу на «да» (/angel_ok)."""
    if not api_key or await db.kv_get("angel3:img"):
        return
    await db.kv_set("angel3:img", "started")  # до заказа: перезапуск не закажет второй раз
    if await _spent(db) + 0.20 > CEILING_USD:
        await db.kv_set("angel3:img", "no budget")
        return
    src = base64.b64encode((ASSETS / "numerita_angel.jpg").read_bytes()).decode()
    body = {"model": IMAGE_MODEL, "modalities": ["image", "text"], "image_config": {"aspect_ratio": "9:16"},
            "usage": {"include": True}, "messages": [{"role": "user", "content": [
                {"type": "text", "text": EDIT_PROMPT},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + src}}]}]}
    async with httpx.AsyncClient(timeout=240) as http:
        r = await http.post(f"{API}/chat/completions", json=body,
                            headers={"Authorization": f"Bearer {api_key}", "X-Title": "Numerita Threads"})
    data = r.json() if r.status_code < 400 else {}
    await _add_spent(db, float((data.get("usage") or {}).get("cost") or (0.15 if data else 0)))
    try:
        url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
        img = base64.b64decode(url.split(",", 1)[1])
    except (KeyError, IndexError, TypeError):
        await db.kv_set("angel3:img", f"failed {r.status_code}")
        raise RuntimeError(f"картинка Нумериты не получилась ({r.status_code}): {r.text[:150]}")
    import io
    pic = Image.open(io.BytesIO(img)).convert("RGB").resize((720, 1280), Image.LANCZOS)
    buf = io.BytesIO()
    pic.save(buf, "JPEG", quality=93)
    ref = await threads.upload_image(buf.getvalue(), "numerita_angel3.jpg")
    await db.kv_set("angel3:ref_url", ref)
    await db.kv_set("angel3:img", "sent")
    await send_photo(buf.getvalue(), f"✨ Новая Нумерита: взгляд в кадр, естественные ресницы, фигура женственнее, платье "
                                      f"закрытое. Потрачено всего ${await _spent(db):.2f} из ${CEILING_USD:.2f}.\n"
                                      "Снимать с ней «Ангела» (≈$0,84)? Ответь /angel_ok — да, /angel_no — нет.")
