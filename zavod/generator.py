"""Генерация постов через OpenRouter (OpenAI-совместимый Chat Completions API).

https://openrouter.ai/docs/api-reference/chat-completion
"""

from pathlib import Path

import httpx

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class GenerationError(Exception):
    pass


class Generator:
    def __init__(self, api_key: str, model: str, voice_path: Path):
        self.api_key = api_key
        self.model = model
        self.system = voice_path.read_text(encoding="utf-8")

    async def write_post(self, topic: str, previous: str | None = None) -> str:
        prompt = f"Тема поста: {topic}"
        if previous:
            prompt += (
                "\n\nВот предыдущий вариант, он не подошёл. "
                f"Напиши заметно другой пост на ту же тему:\n\n{previous}"
            )

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
                            {"role": "system", "content": self.system},
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
            raise GenerationError(f"Ошибка OpenRouter: {message}")

        text = (payload["choices"][0]["message"].get("content") or "").strip()
        if not text:
            raise GenerationError("Модель вернула пустой ответ.")
        return text
