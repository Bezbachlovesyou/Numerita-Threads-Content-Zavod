"""Пульт владельца (слово владельца 30.10.2026: «я говорю тебе здесь — и ты сразу делаешь на всех площадках»).

Claude записывает поручение в ops/commands.json в main. Бот раз в 5 минут читает файл с GitHub (без перезапуска),
выполняет каждую команду один раз (claim ops:<id>) на своей площадке и присылает владельцу одну строку-квитанцию.
Команды: {"id": "...", "account": "ru" | "en" | "tg", "action": "post" | "grid" | "unpublish", ...}
  post      — {"text": "..."}: пост в Threads (ru/en) или в канал (tg); тексты проходят обычные проверки на границе.
  grid      — {"shape": "spiral" | "heart" | "dna" | ...}: следующая живая матрица этой формы.
  unpublish — {"fragment": "..."}: снять пост Threads с этим куском текста.
  tell      — {"text": "..."} или {"file": "knowledge/…"}: длинный текст только владельцу в Telegram (без Threads, $0).
"""

import json
import logging
import time

import httpx

log = logging.getLogger(__name__)
RAW = "https://raw.githubusercontent.com/bezbachlovesyou/numerita-threads-content-zavod/main"
URL = f"{RAW}/ops/commands.json"
EVERY = 300
_last: float | None = None


async def fetch() -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.get(URL, params={"t": int(time.time() // EVERY)})  # обходим кэш CDN
    if r.status_code != 200:
        return []
    data = r.json()
    return [c for c in data if isinstance(c, dict) and c.get("id")] if isinstance(data, list) else []


async def tick(db, account: str, run) -> None:
    """account — «ru» или «en» (канал tg выполняет русский экземпляр). run(command) -> строка квитанции."""
    global _last
    if _last is not None and time.monotonic() - _last < EVERY:
        return
    _last = time.monotonic()
    try:
        commands = await fetch()
    except Exception as e:
        log.warning("Пульт: файл команд не прочитан: %s", e)
        return
    for cmd in commands:
        target = cmd.get("account", "ru")
        if target != account and not (target == "tg" and account == "ru"):
            continue
        if not await db.claim_slot(f"ops:{cmd['id']}"):
            continue
        try:
            await run(cmd)
        except Exception as e:
            log.exception("Пульт: команда %s не выполнена", cmd["id"])
            await run({"action": "_error", "id": cmd["id"], "error": f"{type(e).__name__}: {e}"})
