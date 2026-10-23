"""База знаний Numerita (/kb.json из проекта My-1st-telegram-bot).

Раз в сутки скачиваем её и к каждому посту прикладываем только нужное: правила
расчёта, голос бренда и трактовки чисел из темы. Если база недоступна, бот
работает на последней скачанной версии или без неё.
"""

import json
import logging
import re
import time

import httpx

log = logging.getLogger(__name__)

REFRESH_SECONDS = 24 * 60 * 60
NUMBER_RE = re.compile(r"(?<!\d)(\d{1,4})(?!\d)")  # 1–31, пары и сочетания вроде 777, 1212


def reduce_number(n: int) -> int:
    while n > 9:
        n = sum(int(d) for d in str(n))
    return n


class KnowledgeBase:
    def __init__(self, url: str):
        self.url = url
        self.data: dict | None = None
        self.loaded_at = 0.0

    async def _refresh(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                response = await http.get(self.url)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Не удалось скачать базу знаний %s: %s", self.url, e)
            self.loaded_at = time.monotonic() - REFRESH_SECONDS + 15 * 60  # повторим через 15 минут
            return
        self.data = data
        self.loaded_at = time.monotonic()
        log.info("База знаний Numerita загружена, версия %s", data.get("version"))

    async def excerpt(self, topic: str) -> str:
        """Выдержка из базы для темы поста или пустая строка, если базы нет."""
        if not self.url:
            return ""
        if self.data is None or time.monotonic() - self.loaded_at > REFRESH_SECONDS:
            await self._refresh()
        if self.data is None:
            return ""

        kb = self.data
        part: dict = {key: kb[key] for key in ("usage", "calc", "voice") if key in kb}
        numbers = kb.get("numbers", {})
        compound = kb.get("compound", {})

        found = [int(m) for m in NUMBER_RE.findall(topic) if 1 <= int(m) <= 9999][:12]
        if found:
            single: set[int] = set()
            for n in found:
                if n > 9:
                    single.update(int(d) for d in str(n) if d != "0")
                single.add(reduce_number(n))
            part["numbers"] = {str(n): numbers[str(n)] for n in sorted(single) if str(n) in numbers}
            doubles = {str(n): compound[str(n)] for n in found if str(n) in compound}
            if doubles:
                part["compound"] = doubles
            lowered = topic.lower()
            if "аркан" in lowered:
                arcana = kb.get("arcana", {})
                part["arcana"] = {str(n): arcana[str(n)] for n in found if str(n) in arcana}
            if ("совмест" in lowered or "пар" in lowered) and len(found) >= 2:
                a, b = sorted(reduce_number(n) for n in found[:2])
                pair = kb.get("pairs", {}).get(f"{a}-{b}")
                if pair:
                    part["pairs"] = {f"{a}-{b}": pair}
        else:
            # Тема без числа: краткая шпаргалка по всем числам 1–9.
            part["numbers"] = {
                key: {k: value[k] for k in ("name", "planet", "qualities") if k in value}
                for key, value in numbers.items()
            }
        return json.dumps(part, ensure_ascii=False)
