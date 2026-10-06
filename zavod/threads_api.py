"""Публикация текстовых постов через Threads API (Meta).

Публикация идёт в два шага: создать контейнер, затем опубликовать его.
https://developers.facebook.com/docs/threads/posts
"""

import httpx

API_URL = "https://graph.threads.net/v1.0"
MAX_LENGTH = 500


class ThreadsError(Exception):
    pass


class ThreadsClient:
    def __init__(self, user_id: str, access_token: str):
        self.user_id = user_id
        self.access_token = access_token

    async def publish_text(self, text: str) -> str:
        if len(text) > MAX_LENGTH:
            raise ThreadsError(f"Пост длиннее {MAX_LENGTH} символов ({len(text)}).")

        async with httpx.AsyncClient(timeout=30) as http:
            container = await self._post(
                http,
                f"/{self.user_id}/threads",
                {"media_type": "TEXT", "text": text},
            )
            published = await self._post(
                http,
                f"/{self.user_id}/threads_publish",
                {"creation_id": container["id"]},
            )
        return published["id"]

    async def _post(self, http: httpx.AsyncClient, path: str, data: dict) -> dict:
        try:
            response = await http.post(
                API_URL + path, data={**data, "access_token": self.access_token}
            )
        except httpx.HTTPError as e:
            raise ThreadsError(f"Не удалось связаться с Threads: {e}") from e
        payload = response.json()
        if response.is_error or "error" in payload:
            message = payload.get("error", {}).get("message", response.text)
            raise ThreadsError(f"Threads API: {message}")
        return payload
