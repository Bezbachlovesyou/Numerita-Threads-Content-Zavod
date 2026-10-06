"""Публикация постов в Threads через Zernio.

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

    async def publish_text(self, text: str) -> str:
        if len(text) > MAX_LENGTH:
            raise ThreadsError(f"Пост длиннее {MAX_LENGTH} символов ({len(text)}).")

        try:
            async with httpx.AsyncClient(timeout=60) as http:
                response = await http.post(
                    f"{API_URL}/posts",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "content": text,
                        "platforms": [{"platform": "threads", "accountId": self.account_id}],
                        "publishNow": True,
                    },
                )
        except httpx.HTTPError as e:
            raise ThreadsError(f"Не удалось связаться с Zernio: {e}") from e

        try:
            payload = response.json()
        except ValueError:
            raise ThreadsError(f"Zernio вернул ошибку {response.status_code}.")
        if response.is_error:
            error = payload.get("error") or payload.get("message") or response.text
            if isinstance(error, dict):
                error = error.get("message", error)
            raise ThreadsError(f"Zernio: {error}")
        return payload.get("post", {}).get("_id", "")
