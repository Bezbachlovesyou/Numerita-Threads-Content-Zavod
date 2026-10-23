"""Публикация постов в Threads и их статистика через Zernio.

Zernio сам ходит в Threads API, поэтому приложение Meta не нужно.
https://docs.zernio.com
"""

import httpx

API_URL = "https://zernio.com/api/v1"
MAX_LENGTH = 500


class ThreadsError(Exception):
    pass


class ThreadsClient:
    def __init__(self, api_key: str, account_id: str):
        self.api_key = api_key
        self.account_id = account_id

    async def _request(self, method: str, path: str, **kwargs) -> tuple[int, dict]:
        try:
            async with httpx.AsyncClient(timeout=60) as http:
                response = await http.request(
                    method,
                    API_URL + path,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    **kwargs,
                )
        except httpx.HTTPError as e:
            raise ThreadsError(f"Не удалось связаться с Zernio: {e}") from e

        try:
            payload = response.json()
        except ValueError:
            raise ThreadsError(f"Zernio вернул ошибку {response.status_code}.")
        if response.is_error:
            if payload.get("code") == "analytics_addon_required":
                raise ThreadsError("В тарифе Zernio нет статистики (нужен Analytics add-on).")
            error = payload.get("error") or payload.get("message") or response.text
            if isinstance(error, dict):
                error = error.get("message", error)
            raise ThreadsError(f"Zernio: {error}")
        return response.status_code, payload

    async def publish_text(self, text: str) -> str:
        if len(text) > MAX_LENGTH:
            raise ThreadsError(f"Пост длиннее {MAX_LENGTH} символов ({len(text)}).")
        _, payload = await self._request(
            "POST",
            "/posts",
            json={
                "content": text,
                "platforms": [{"platform": "threads", "accountId": self.account_id}],
                "publishNow": True,
            },
        )
        return payload.get("post", {}).get("_id", "")

    async def account_stats(self, limit: int = 10) -> dict:
        """Сводка и последние посты аккаунта: {"overview": {...}, "posts": [...]}."""
        _, payload = await self._request(
            "GET",
            "/analytics",
            params={"platform": "threads", "accountId": self.account_id, "limit": limit},
        )
        return payload

    async def post_stats(self, post_id: str) -> dict | None:
        """Статистика одного поста. None — Zernio ещё собирает данные (ответ 202)."""
        status, payload = await self._request("GET", "/analytics", params={"postId": post_id})
        if status == 202 or payload.get("syncStatus") == "pending":
            return None
        return payload
