from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"


class GenerationError(Exception):
    pass


class Generator:
    def __init__(self, api_key: str, voice_path: Path):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.system = voice_path.read_text(encoding="utf-8")

    async def write_post(self, topic: str, previous: str | None = None) -> str:
        prompt = f"Тема поста: {topic}"
        if previous:
            prompt += (
                "\n\nВот предыдущий вариант, он не подошёл. "
                f"Напиши заметно другой пост на ту же тему:\n\n{previous}"
            )

        try:
            response = await self.client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=self.system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "medium"},
                # Если модель откажется по соображениям безопасности,
                # API сам повторит запрос на подходящей запасной модели.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            raise GenerationError("Превышен лимит запросов к Claude, попробуйте через минуту.") from e
        except anthropic.APIStatusError as e:
            raise GenerationError(f"Ошибка Claude API: {e.status_code} {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise GenerationError("Не удалось связаться с Claude API.") from e

        if response.stop_reason == "refusal":
            raise GenerationError("Claude отказался писать пост на эту тему.")

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise GenerationError("Claude вернул пустой ответ.")
        return text
