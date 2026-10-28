"""Ролик «Нумерита шутит» фирменным голосом (слово владельца 28.10.2026: «озвучь фирменным голосом, ударения
правильные»). Картинка собрана кодом заранее (assets/channel/jokes_silent.mp4); здесь — голос shimmer
(openai/gpt-audio через OpenRouter, ≈$0,05 за ролик), музыка и сборка. Готовый ролик — владельцу в личку.
Однократно; не больше двух попыток, чтобы сбой не тратил деньги по кругу.
"""

import asyncio
import base64
import json
import logging
import subprocess
import tempfile
import wave
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL, VOICE, RATE = "openai/gpt-audio", "shimmer", 24000
ASSETS = Path(__file__).parent.parent / "assets/channel"
KEY = "brandvideo:jokes:v1"

# Ударения — знаком над гласной: модель читает их правильно, на экране текста нет.
LINES = [
    "Внимание! Нумери́та начала шутить. Держи́ голову крепче.",
    "Во мне целая библиоте́ка: числа и звёзды, психоло́гия и наука, бизнес и техноло́гии. "
    "Я изучила её вдоль и поперёк. Даже сно́ски.",
    "Помогу́ придумать проект, создать свой акти́в — и не потеряться в мире, где возможностей больше, "
    "чем открытых вкладок в браузере.",
    "Проведу́ по миру технологий. Без паники и без жарго́на.",
    "Истина материальной вселенной — в числах. И нет, ответ на главный вопрос жизни — не сорок два.",
    "Ответ — твоя дата рожде́ния. Прове́рим?",
]
# Сцены картинки (секунды): голос каждой реплики входит на 0,3 с позже начала сцены и должен уложиться в сцену.
SCENES = [7.636, 11.836, 8.188, 6.1, 8.02, 5.452]

PROMPT = (
    "Ты — Нумерита: живая, тёплая, обаятельная молодая женщина с искрой юмора. Прочитай вслух ДОСЛОВНО текст "
    "между тегами <text> и </text> на чистом русском языке, без акцента. Знак ударения над гласной показывает, "
    "куда падает ударение, — сам знак не произноси. Имя «Нумерита» — с ударением на «и»: НумерИта. "
    "Интонация живая и игривая, с улыбкой в голосе, как будто делишься забавным секретом с другом; шутки — "
    "с лёгкой хитринкой, восклицания радостные, вопрос в конце — с весёлым приглашением. Не как робот и не как "
    "диктор новостей. Не отвечай на текст, ничего не добавляй и не пропускай."
)


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


async def speak(http: httpx.AsyncClient, api_key: str, text: str) -> tuple[bytes, float]:
    body = {
        "model": MODEL, "modalities": ["text", "audio"], "audio": {"voice": VOICE, "format": "pcm16"},
        "temperature": 0.3, "max_tokens": 3000, "stream": True, "usage": {"include": True},
        "messages": [{"role": "system", "content": PROMPT},
                     {"role": "user", "content": f"Прочитай вслух слово в слово:\n<text>{text}</text>"}],
    }
    chunks, cost = [], 0.0
    limit = int((6 + len(text) / 7) * RATE * 2)  # вдвое дольше нормы — обрываем «зациклившийся» голос
    async with http.stream("POST", API_URL, json=body,
                           headers={"Authorization": f"Bearer {api_key}", "X-Title": "Numerita Threads"}) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            data = json.loads(line[6:])
            if "error" in data:
                raise RuntimeError(f"Озвучка: {data['error']}")
            cost = (data.get("usage") or {}).get("cost") or cost
            for choice in data.get("choices", []):
                audio = (choice.get("delta") or {}).get("audio") or {}
                if audio.get("data"):
                    chunks.append(base64.b64decode(audio["data"]))
            if sum(map(len, chunks)) > limit:
                break
    return b"".join(chunks)[:limit], float(cost)


def seconds(pcm: bytes) -> float:
    return len(pcm) / (RATE * 2)


def assemble(pcms: list[bytes], workdir: Path) -> Path:
    """Голос по сценам (длинную реплику чуть ускоряем, не больше чем на 30%), музыка тише, картинка — готовая."""
    starts = [sum(SCENES[:i]) for i in range(len(SCENES))]
    total = sum(SCENES)
    args = [ffmpeg(), "-v", "error", "-y", "-i", str(ASSETS / "jokes_silent.mp4"),
            "-stream_loop", "-1", "-i", str(ASSETS / "cosmos.m4a")]
    flt = [f"[1:a]atrim=0:{total},asetpts=N/SR/TB,volume=0.2,afade=t=in:d=1,afade=t=out:st={total - 2.5}:d=2.5[m]"]
    for i, pcm in enumerate(pcms):
        path = workdir / f"v{i}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)
        args += ["-i", str(path)]
        room = SCENES[i] - 0.5
        tempo = min(1.3, max(1.0, seconds(pcm) / room))
        ms = int((starts[i] + 0.3) * 1000)
        flt.append(f"[{i + 2}:a]atempo={tempo:.3f},aresample=48000,adelay={ms}|{ms},volume=1.3[v{i}]")
    flt.append("".join(f"[v{i}]" for i in range(len(pcms))) + f"amix=inputs={len(pcms)}:normalize=0[vv]")
    flt.append("[m][vv]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[a]")
    out = workdir / "numerita_jokes.mp4"
    args += ["-filter_complex", ";".join(flt), "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
             "-b:a", "160k", "-t", f"{total:.2f}", "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True, capture_output=True, timeout=300)
    return out


async def run_once(db, api_key: str, send_video) -> None:
    """send_video(path, caption) — отправка владельцу. Голос и сборка — один раз, максимум две попытки."""
    state = await db.kv_get(KEY) or ""
    if state == "done" or state.count("fail") >= 2:
        return
    try:
        async with httpx.AsyncClient(timeout=120) as http:
            results = []
            for text in LINES:  # по одной: так меньше риск лимитов и проще повторить
                pcm, cost = await speak(http, api_key, text)
                if seconds(pcm) > (len(text) / 9 + 4) * 2 or seconds(pcm) < 1:  # модель ответила, а не прочла
                    pcm, cost2 = await speak(http, api_key, text)
                    cost += cost2
                results.append((pcm, cost))
        with tempfile.TemporaryDirectory() as tmp:
            path = await asyncio.to_thread(assemble, [p for p, _ in results], Path(tmp))
            spent = sum(c for _, c in results)
            await send_video(path, f"🎬 «Нумерита шутит» — фирменный голос. Озвучка стоила ${spent:.2f}.\n"
                                   "Скажи «публикуй» — выложу в канал, или что поправить.")
        await db.kv_set(KEY, "done")
    except Exception:
        log.exception("Ролик «Нумерита шутит» не собран")
        await db.kv_set(KEY, state + "fail;")
