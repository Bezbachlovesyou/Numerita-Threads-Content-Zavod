"""Ролик по команде пульта {"action": "reel", ...} (слово владельца 09.11.2026: «ты сама генерируешь через OpenRouter, мне ничего копировать не надо»).
Grok Imagine Video (OpenRouter) из канонического кадра Нумерты: речь и звук модели, 9:16, 480p. Результат — владельцу в Telegram на проверку (публикуем по его слову).
Деньги: смета seconds × PRICE_PER_SEC; жёсткий потолок CEILING_USD на команду; номер задания сохраняется сразу, повтор после перезапуска не платит заново."""
import asyncio
import logging
import random
import subprocess
import tempfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)
API = "https://openrouter.ai/api/v1"
MODEL = "x-ai/grok-imagine-video-1.5-lite"
PRICE_PER_SEC = 0.031  # по смете приветственных роликов: $0,46 за 15 с
CEILING_USD = 0.20
ASSETS = Path(__file__).resolve().parent.parent / "assets"
ACUTE = "\u0301"
VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"


def unstressed_words(prompt: str) -> list[str]:
    """Слова русской речи в кавычках промпта, где есть 2+ гласных, но нет знака ударения (слово владельца 09.11.2026: ударение в промптах всегда).
    Слова с «ё» ударение уже несут."""
    import re
    bad = []
    for quote in re.findall(r"\"([^\"]*[А-Яа-яЁё][^\"]*)\"", prompt):
        for word in re.findall(r"[А-Яа-яЁё\u0301-]+", quote):
            if sum(c in VOWELS for c in word) >= 2 and ACUTE not in word and "ё" not in word.lower():
                bad.append(word)
    return bad


async def make(db, api_key: str, threads, cmd: dict, send_video, notify) -> None:
    key = f"reel:job:{cmd['id']}"
    seconds = max(3, min(int(cmd.get("seconds") or 5), 8))
    estimate = seconds * PRICE_PER_SEC
    if estimate > CEILING_USD:
        await notify(f"⚠️ Ролик не заказан: смета ${estimate:.2f} выше потолка ${CEILING_USD:.2f}.")
        return
    if not cmd.get("no_stress_check"):
        bad = unstressed_words(cmd["prompt"])
        if bad:
            await notify(f"⚠️ Ролик не заказан: в тексте речи нет ударений у слов: {', '.join(bad[:8])}. Правило владельца: ударение в промптах всегда.")
            return
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=120) as http:
        jid = await db.kv_get(key)
        if jid == "failed":
            await notify("ℹ️ Этот ролик уже не получился, повторно не заказываю.")
            return
        if not jid:
            frame = (ASSETS / (cmd.get("image") or "numerita_angel.jpg")).read_bytes()
            frame_url = await threads.upload_image(frame, "reel_frame.jpg")
            body = {"model": cmd.get("model") or MODEL, "prompt": cmd["prompt"], "duration": seconds,
                    "resolution": cmd.get("resolution") or "480p", "aspect_ratio": "9:16",
                    "frame_images": [{"type": "image_url", "image_url": {"url": frame_url}, "frame_type": "first_frame"}]}
            r = await http.post(f"{API}/videos", json=body, headers=headers)
            if r.status_code >= 400:
                await db.kv_set(key, "failed")
                await notify(f"⚠️ Ролик не заказан: {r.status_code} {r.text[:200]}")
                return
            jid = r.json()["id"]
            await db.kv_set(key, jid)  # сразу: повтор после перезапуска не платит заново
            await notify(f"🎬 Ролик заказан: {seconds} с, 480p, смета ≈${estimate:.2f}. Пришлю сюда, когда будет готов (минуты).")
        for _ in range(90):
            st = (await http.get(f"{API}/videos/{jid}", headers=headers)).json()
            if st.get("status") == "completed":
                cost = float((st.get("usage") or {}).get("cost") or estimate)
                v = await http.get(f"{API}/videos/{jid}/content", headers=headers, follow_redirects=True)
                v.raise_for_status()
                final = await asyncio.to_thread(add_digits, v.content) if cmd.get("digits", True) else v.content
                check = await asyncio.to_thread(hear_check, v.content, cmd["say"], cmd.get("lang") or "ru") if cmd.get("say") else ""
                await send_video(final, f"🎬 Ролик готов. Стоимость по факту ${cost:.2f}. {check}\nЛицо, свет глаз и цифры — как вам? «Выкладывай» или «переделай».")
                return
            if st.get("status") in ("failed", "cancelled", "expired"):
                await db.kv_set(key, "failed")
                await notify(f"⚠️ Ролик не получился: {st.get('error') or st.get('status')}")
                return
            await asyncio.sleep(10)
    await notify("⚠️ Ролик не готов за 15 минут; номер задания сохранён, заберу при следующем запуске команды.")


FONT = ASSETS / "fonts" / "CormorantGaramond.ttf"


def digits_filter(seed: int = 7, count: int = 26) -> str:
    """Чёткий золотой цифровой дождь поверх ролика (канон образа, слово владельца 09.11.2026: модель рисует цифры «непонятными штуками»,
    поэтому цифры дорисовываем сами крупным шрифтом по краям кадра, не закрывая лицо). Глубина: дальние мельче, тусклее и медленнее."""
    rng = random.Random(seed)
    parts = []
    for i in range(count):
        depth = rng.random()
        size = f"h*{0.022 + 0.04 * depth:.4f}"
        alpha = 0.35 + 0.6 * depth
        speed = f"h*{0.06 + 0.16 * depth:.4f}"
        side = rng.random() < 0.5
        xfrac = rng.uniform(0.02, 0.24) if side else rng.uniform(0.76, 0.96)
        off = f"h*{rng.random():.4f}"
        digit = str(rng.randint(0, 9))
        parts.append(f"drawtext=fontfile='{FONT}':text='{digit}':fontsize={size}:fontcolor=0xFFD682@{alpha:.2f}:"
                     f"x=w*{xfrac:.3f}:y='mod(t*{speed}+{off},h*1.1)-h*0.05':shadowcolor=0xB8860B@0.6:shadowx=1:shadowy=1")
    return ",".join(parts)


def add_digits(video: bytes) -> bytes:
    """Возвращает видео с цифровым дождём; при любой ошибке отдаёт исходное (ролик важнее украшения)."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "in.mp4", Path(tmp) / "out.mp4"
            src.write_bytes(video)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", digits_filter(), "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "copy", str(out)], check=True, capture_output=True, timeout=240)
            return out.read_bytes()
    except Exception as e:  # noqa: BLE001
        log.warning("Цифры поверх ролика не наложились: %s", e)
        return video


def hear_check(video: bytes, said: str, lang: str = "ru") -> str:
    """Проверка слухом ($0, faster-whisper, если установлен): те ли слова произнесены. Возвращает строку для подписи."""
    try:
        from . import welcome
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.mp4"
            path.write_bytes(video)
            problem = welcome.hear(path, lang, [said])
        return "✅ слова произнесены верно (проверено слухом)" if problem is None else "⚠️ " + problem
    except Exception as e:  # noqa: BLE001
        return f"(проверка слухом не выполнена: {type(e).__name__})"


async def revoice(db, api_key: str, cmd: dict, send_video, notify) -> None:
    """Пересобрать ЗВУК готового ролика, не заказывая видео заново (слово владельца 09.11.2026: «нужно было просто пересобрать звук»).
    Берём видео по сохранённому номеру задания (скачивание бесплатно), озвучиваем текст с ударениями голосом Нумериты (≈$0,02),
    кладём музыку и цифровой дождь. Губы остаются от первой озвучки, поэтому текст должен быть близкой длины к исходному."""
    import wave
    from . import welcome
    src_id, text = cmd.get("from"), cmd.get("text") or ""
    jid = await db.kv_get(f"reel:job:{src_id}")
    if not jid or jid == "failed":
        await notify(f"⚠️ Звук не пересобран: у ролика {src_id} нет сохранённого задания.")
        return
    bad = unstressed_words(f'"{text}"')
    if bad and not cmd.get("no_stress_check"):
        await notify(f"⚠️ Звук не пересобран: в тексте нет ударений у слов: {', '.join(bad[:8])}.")
        return
    async with httpx.AsyncClient(timeout=240) as http:
        v = await http.get(f"{API}/videos/{jid}/content", headers={"Authorization": f"Bearer {api_key}"}, follow_redirects=True)
        v.raise_for_status()
        pcm, cost = await welcome.speak(http, api_key, text, "ru")
    pcm = welcome.trim(pcm)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "in.mp4").write_bytes(v.content)
        with wave.open(str(tmp / "v.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(welcome.RATE)
            w.writeframes(pcm)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp / "in.mp4"), "-stream_loop", "-1", "-i", str(welcome.MUSIC),
                        "-i", str(tmp / "v.wav"), "-filter_complex",
                        "[1:a]volume=0.22,afade=t=in:d=0.5[m];[2:a]aresample=48000,adelay=300|300,volume=1.3[v];"
                        "[m][v]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(tmp / "out.mp4")],
                       check=True, capture_output=True, timeout=240)
        out = (tmp / "out.mp4").read_bytes()
    out = await asyncio.to_thread(add_digits, out) if cmd.get("digits", True) else out
    check = await asyncio.to_thread(hear_check, out, cmd.get("say") or text.replace(ACUTE, ""))
    await send_video(out, f"🎬 Звук пересобран (≈${cost:.2f}), видео прежнее. {check}\nУдарения как вам? «Выкладывай» или скажите, какое слово поправить.")


async def fetch_video(db, api_key: str, src_id: str) -> bytes | None:
    """Готовое видео по сохранённому номеру задания (скачивание бесплатно)."""
    jid = await db.kv_get(f"reel:job:{src_id}")
    if not jid or jid == "failed":
        return None
    async with httpx.AsyncClient(timeout=240) as http:
        v = await http.get(f"{API}/videos/{jid}/content", headers={"Authorization": f"Bearer {api_key}"}, follow_redirects=True)
        v.raise_for_status()
        return v.content
