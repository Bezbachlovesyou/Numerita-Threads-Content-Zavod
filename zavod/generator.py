"""Генерация постов через OpenRouter (OpenAI-совместимый Chat Completions API).

https://openrouter.ai/docs/api-reference/chat-completion
"""

import logging
from pathlib import Path

import httpx

from .knowledge import KnowledgeBase

API_URL = "https://openrouter.ai/api/v1/chat/completions"
KEY_URL = "https://openrouter.ai/api/v1/key"

log = logging.getLogger(__name__)


def clean_key(raw: str) -> str:
    """Убирает то, что часто попадает в ключ при копировании: пробелы, кавычки, «Bearer »."""
    key = raw.strip().strip("'\"").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def mask_key(key: str) -> str:
    return f"{key[:12]}…{key[-4:]} ({len(key)} симв.)" if len(key) > 16 else f"({len(key)} симв.)"


class GenerationError(Exception):
    pass


class Generator:
    def __init__(self, api_key: str, model: str, voice_path: Path, knowledge: KnowledgeBase):
        self.api_key = clean_key(api_key)
        self.model = model
        self.system = voice_path.read_text(encoding="utf-8")
        playbook = voice_path.with_name("playbook.md")  # хуки, сторителлинг, что заходит в Threads
        if playbook.exists():
            self.system += "\n\n" + playbook.read_text(encoding="utf-8")
        reply_path = voice_path.with_name("reply_voice.md")
        self.reply_system = reply_path.read_text(encoding="utf-8") if reply_path.exists() else self.system
        self.knowledge = knowledge

    async def _with_knowledge(self, prompt: str, about: str) -> str:
        excerpt = await self.knowledge.excerpt(about)
        if not excerpt:
            return prompt
        return (
            "База знаний Numerita (выдержка). Трактовки, расчёт и правила голоса бери только отсюда:\n"
            f"{excerpt}\n\n{prompt}"
        )

    async def improve(self, system: str, prompt: str) -> str:
        """Свободный запрос к модели (самоулучшение контент-плана)."""
        return await self._complete(system, prompt)

    async def write_reply(self, post: str, comment: str, author: str, with_link: bool) -> str:
        """Ответ на комментарий под постом. «SKIP» — отвечать не нужно."""
        prompt = (
            f"Наш пост:\n{post}\n\nКомментарий от @{author}:\n{comment}\n\n"
            + ("В последней строке поставь только маркер {LINK} — бот заменит его ссылкой на полный разбор."
               if with_link else "Без ссылок и без упоминания бота.")
        )
        return await self._complete(self.reply_system, await self._with_knowledge(prompt, comment))

    async def check_key(self) -> None:
        """Проверяет ключ при запуске и пишет результат в логи Railway."""
        if not self.api_key.startswith("sk-or-"):
            log.error("OPENROUTER_API_KEY не похож на ключ OpenRouter (должен начинаться с sk-or-v1-): %s",
                      mask_key(self.api_key))
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                response = await http.get(KEY_URL, headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as e:
            log.warning("Не удалось проверить ключ OpenRouter: %s", e)
            return
        if response.is_success:
            log.info("Ключ OpenRouter принят: %s", mask_key(self.api_key))
        else:
            log.error("OpenRouter НЕ принял ключ %s: %s %s",
                      mask_key(self.api_key), response.status_code, response.text[:200])

    async def write_post(self, topic: str, previous: str | None = None) -> str:
        prompt = await self._with_knowledge(f"Тема поста: {topic}", topic)
        if previous:
            prompt += (
                "\n\nВот предыдущий вариант, он не подошёл. "
                f"Напиши заметно другой пост на ту же тему:\n\n{previous}"
            )
        return await self._complete(self.system, prompt)

    async def _complete(self, system: str, prompt: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=180) as http:
                response = await http.post(
                    API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "X-Title": "Numerita Threads Content Zavod",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
        except httpx.HTTPError as e:
            raise GenerationError("Не удалось связаться с OpenRouter.") from e

        try:
            payload = response.json()
        except ValueError:
            raise GenerationError(f"OpenRouter вернул ошибку {response.status_code}.")
        if response.is_error or "error" in payload:
            message = payload.get("error", {}).get("message", response.text)
            if response.status_code == 429:
                message = "превышен лимит запросов, попробуйте через минуту"
            elif response.status_code == 401:
                message = (f"ключ не принят ({message}). Проверьте OPENROUTER_API_KEY на Railway: "
                           f"сейчас бот видит {mask_key(self.api_key)}")
            elif response.status_code == 402:
                message = "закончились деньги на балансе OpenRouter"
            raise GenerationError(f"Ошибка OpenRouter: {message}")

        text = (payload["choices"][0]["message"].get("content") or "").strip()
        if not text:
            raise GenerationError("Модель вернула пустой ответ.")
        return text
