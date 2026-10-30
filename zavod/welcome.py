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
CEILING_USD = 1.50
W, H = 720, 1280
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
            "ru": [(0, 3, "Твой день рождения — не случайность."), (3, 7, "Это код."),
                   (7, 12, "Родился 6-го, 15-го или 24-го? Твоё число души — 6: ты держишь мир вокруг себя тёплым."),
                   (12, 15, "Напиши дату — покажу твой код.")],
            "en": [(0, 3, "Your birthday isn't random."), (3, 7, "It's a code."),
                   (7, 12, "Born on the 6th, 15th or 24th? Your soul number is 6 — you keep the world around you warm."),
                   (12, 15, "Drop your date — I'll read your code.")],
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
        "prompt": ("From shimmering stardust the silhouette of a serene young angel woman slowly appears. Her large wings "
                   "are woven from glowing golden digits, a halo of small stars circles above her head, her body is "
                   "translucent light. Calm, kind face like an icon, lips gently closed. She opens her eyes, looks at "
                   "the viewer and extends her open palm; a bright star rises from her palm toward the camera. "
                   "Chaste, elegant, cinematic lighting, gold and azure."),
        "lines": {
            "ru": [(0, 3, "Кто охраняет твою судьбу?"), (3, 7, "Нумерита — ангел-хранитель чисел и звёзд."),
                   (7, 10, "У каждого есть число, которое ведёт. Узнаешь своё?")],
            "en": [(0, 3, "Who guards your fate?"), (3, 7, "Numerita — Guardian Angel of Numbers and Stars."),
                   (7, 10, "Everyone has a number that leads them. Want to know yours?")],
        },
        "post": {
            "ru": "Кто охраняет твою судьбу?\n\nЯ — Нумерита, ангел-хранитель чисел и звёзд. У каждого есть число, "
                  "которое ведёт. Напиши дату рождения — покажу твоё 🤍\n\nt.me/Numeritabot?start=ad_th_angel",
            "en": "Who guards your fate?\n\nI'm Numerita, the Guardian Angel of Numbers and Stars. Everyone has a number "
                  "that leads them. Drop your birth date — I'll show you yours 🤍\n\nt.me/Numeritabot?start=ad_en_th_angel",
        },
    },
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
BUSY = False  # сборка идёт в этом процессе


async def _spent(db) -> float:
    return float(await db.kv_get("welcome:spent") or 0)


async def _add_spent(db, usd: float) -> None:
    await db.kv_set("welcome:spent", f"{await _spent(db) + usd:.4f}")


async def clip(db, http: httpx.AsyncClient, key: str, api_key: str) -> bytes | None:
    """Видео сцены: по сохранённому номеру задания или новым заказом — только если влезает в потолок."""
    spec, headers = CLIPS[key], {"Authorization": f"Bearer {api_key}"}
    jid = await db.kv_get(f"welcome:job:{key}")
    if jid == "failed":
        return None
    if not jid:
        if await _spent(db) + spec["estimate"] > CEILING_USD:
            log.warning("Приветственный ролик %s не влезает в потолок $%.2f", key, CEILING_USD)
            await db.kv_set(f"welcome:job:{key}", "failed")
            return None
        body = {"model": spec["model"], "prompt": spec["prompt"] + STYLE, "duration": spec["seconds"], **spec["body"]}
        r = await http.post(f"{API}/videos", json=body, headers=headers)
        if r.status_code >= 400:  # отказ при заказе не оплачивается; не повторяем вслепую
            await db.kv_set(f"welcome:job:{key}", "failed")
            raise RuntimeError(f"{spec['model']} ответила {r.status_code}: {r.text[:200]}")
        jid = r.json()["id"]
        await db.kv_set(f"welcome:job:{key}", jid)  # сразу в базу: повтор после перезапуска не платит заново
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
            await db.kv_set(f"welcome:job:{key}", "failed")
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


def caption_png(text: str, path: Path) -> None:
    """Надпись в нижней трети: золото на тёмной полупрозрачной плашке, переносы по ширине."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT), 50)
    try:  # полужирное начертание — читается на любом кадре (замечание владельца о нечитаемом тексте, 30.10)
        font.set_variation_by_axes([650])
    except Exception:
        pass
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) > W - 120 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    lines.append(cur)
    lh = 62
    y = int(H * 0.72) - len(lines) * lh // 2
    d.rounded_rectangle((40, y - 24, W - 40, y + len(lines) * lh + 18), radius=24, fill=(4, 8, 18, 205),
                        outline=GOLD + (120,), width=2)
    for i, ln in enumerate(lines):
        d.text((W / 2, y + i * lh + lh / 2), ln, font=font, fill=GOLD + (255,), anchor="mm")
    img.save(path)


def assemble(video: bytes, lines: list, voices: list[bytes], seconds: int, workdir: Path, name: str) -> Path:
    src = workdir / f"{name}_src.mp4"
    src.write_bytes(video)
    args = [ffmpeg(), "-v", "error", "-y", "-i", str(src), "-stream_loop", "-1", "-i", str(MUSIC)]
    vf, af = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[b0]"], []
    n = 2
    for i, (a, b, text) in enumerate(lines):
        png = workdir / f"{name}_t{i}.png"
        caption_png(text, png)
        args += ["-loop", "1", "-t", str(seconds), "-framerate", "24", "-i", str(png)]
        vf.append(f"[{n}:v]format=rgba,fade=t=in:st={a}:d=0.4:alpha=1,fade=t=out:st={b - 0.4}:d=0.4:alpha=1[t{i}]")
        vf.append(f"[b{i}][t{i}]overlay=0:0:enable='between(t,{a},{b})'[b{i + 1}]")
        n += 1
    af.append(f"[1:a]atrim=0:{seconds},asetpts=N/SR/TB,volume=0.22,afade=t=in:d=1,"
              f"afade=t=out:st={seconds - 1.5}:d=1.5[m]")
    for i, ((a, b, _), pcm) in enumerate(zip(lines, voices)):
        wav = workdir / f"{name}_v{i}.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)
        args += ["-i", str(wav)]
        tempo = min(1.3, max(1.0, len(pcm) / (RATE * 2) / max(0.8, b - a - 0.4)))
        ms = int((a + 0.2) * 1000)
        af.append(f"[{n}:a]atempo={tempo:.3f},aresample=48000,adelay={ms}|{ms},volume=1.3[v{i}]")
        n += 1
    af.append("".join(f"[v{i}]" for i in range(len(voices))) + f"amix=inputs={len(voices)}:normalize=0[vv]")
    af.append("[m][vv]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[a]")
    out = workdir / f"{name}.mp4"
    args += ["-filter_complex", ";".join(vf + af), "-map", f"[b{len(lines)}]", "-map", "[a]",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
             "-t", str(seconds), "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True, capture_output=True, timeout=600)
    return out


async def build(db, api_key: str) -> dict[str, Path]:
    """Снимает (или берёт оплаченное) и собирает 4 версии. Возвращает {"code_ru": path, ...}."""
    out, workdir = {}, Path(tempfile.mkdtemp(prefix="welcome_"))
    async with httpx.AsyncClient(timeout=180) as http:
        videos = await asyncio.gather(*(clip(db, http, k, api_key) for k in CLIPS), return_exceptions=True)
        for key, video in zip(CLIPS, videos):
            if isinstance(video, Exception) or not video:
                log.warning("Приветственный ролик %s не снят: %s", key, video)
                continue
            spec = CLIPS[key]
            for lang in ("ru", "en"):
                voices = []
                for _, _, text in spec["lines"][lang]:
                    if await _spent(db) + 0.02 > CEILING_USD:
                        voices.append(b"")
                        continue
                    pcm, cost = await speak(http, api_key, text, lang)
                    await _add_spent(db, cost or 0.01)
                    voices.append(pcm or b"\0\0" * (RATE // 10))
                voices = [v or b"\0\0" * (RATE // 10) for v in voices]
                out[f"{key}_{lang}"] = await asyncio.to_thread(
                    assemble, video, spec["lines"][lang], voices, spec["seconds"], workdir, f"{key}_{lang}")
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


async def publish_due(db, threads, now, lang: str, publish, notify) -> None:
    """Выкладывает следующую готовую версию своего языка: publish(key, url) -> строка-квитанция."""
    urls = json.loads((await (_public_kv(db, "welcome:urls") if lang == "en" else db.kv_get("welcome:urls"))) or "{}")
    last = await db.kv_get("welcome:last_post")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < GAP_HOURS * 3600:
        return
    for key in ORDER:
        url = urls.get(f"{key}_{lang}")
        if not url or await db.kv_get(f"welcome:posted:{key}"):
            continue
        await db.kv_set(f"welcome:posted:{key}", "1")  # до отправки: сбой не приведёт к дублю
        await db.kv_set("welcome:last_post", now.isoformat())
        await notify(await publish(key, url))
        return


async def run_build(db, api_key: str, threads, send_video, notify) -> None:
    """Русский завод: один раз снять и собрать, загрузить 4 версии в Zernio, отправить владельцу."""
    global BUSY
    if await db.kv_get("welcome:urls") or await db.kv_get("welcome:build") == "done" or BUSY:
        return
    BUSY = True
    try:
        paths = await build(db, api_key)
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
    await db.kv_set("welcome:build", "done")
    missing = [k for k in CLIPS if f"{k}_ru" not in paths]
    await notify(f"🎬 Приветственные ролики собраны: {len(paths)} из 4. Потрачено ${await _spent(db):.2f} из "
                 f"${CEILING_USD:.2f}." + (f"\n⚠️ Не снялись: {', '.join(missing)} — повторно не заказываю." if missing else "")
                 + "\nВыкладываю по очереди: сначала «Ангел», через 3 часа — «Твой код».")
