import hashlib
import json
"""Публикация постов в Threads и их статистика через Zernio.

Zernio сам ходит в Threads API, поэтому приложение Meta не нужно.
https://docs.zernio.com
"""

from datetime import datetime

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
                headers = {"Authorization": f"Bearer {self.api_key}", **kwargs.pop("headers", {})}
                response = await http.request(method, API_URL + path, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            raise ThreadsError(f"Не удалось связаться с Zernio: {e}") from e

        try:
            payload = response.json()
        except ValueError:
            raise ThreadsError(f"Zernio вернул ошибку {response.status_code}.")
        if response.is_error:
            if payload.get("code") == "analytics_addon_required":
                raise ThreadsError("В тарифе Zernio нет статистики (нужен Analytics add-on).")
            if response.status_code == 403 and "inbox" in json.dumps(payload).lower():
                raise ThreadsError("В тарифе Zernio нет комментариев (нужен Inbox add-on).")
            error = payload.get("error") or payload.get("message") or response.text
            if isinstance(error, dict):
                error = error.get("message", error)
            raise ThreadsError(f"Zernio: {error}")
        return response.status_code, payload

    async def upload_image(self, data: bytes, filename: str, content_type: str = "image/jpeg") -> str:
        """Загружает картинку (или видео) в хранилище Zernio, возвращает публичный адрес для mediaItems."""
        _, presigned = await self._request(
            "POST", "/media/presign", json={"filename": filename, "contentType": content_type, "size": len(data)}
        )
        try:
            async with httpx.AsyncClient(timeout=180) as http:
                response = await http.put(presigned["uploadUrl"], content=data, headers={"Content-Type": content_type})
        except httpx.HTTPError as e:
            raise ThreadsError(f"Не удалось загрузить файл: {e}") from e
        if response.is_error:
            raise ThreadsError(f"Хранилище Zernio не приняло файл: {response.status_code}")
        return presigned["publicUrl"]

    async def publish_text(
        self, text: str, topic_tag: str | None = None, first_comment: str | None = None,
        image_urls: list[str] | None = None, video_url: str | None = None,
    ) -> str:
        """Публикует пост. topic_tag — тема Threads (показ подписчикам темы), first_comment — первый комментарий."""
        if len(text) > MAX_LENGTH:
            raise ThreadsError(f"Пост длиннее {MAX_LENGTH} символов ({len(text)}).")
        platform: dict = {"platform": "threads", "accountId": self.account_id}
        extra = {}
        if topic_tag:
            extra["topic_tag"] = topic_tag
        if first_comment:
            extra["firstComment"] = first_comment[:MAX_LENGTH]
        if extra:
            platform["platformSpecificData"] = extra
        body: dict = {"content": text, "platforms": [platform], "publishNow": True}
        if video_url:
            body["mediaItems"] = [{"type": "video", "url": video_url}]
        elif image_urls:  # одна картинка или карусель до 10
            body["mediaItems"] = [{"type": "image", "url": url} for url in image_urls[:10]]
        _, payload = await self._request("POST", "/posts", json=body)
        post = payload.get("post") or {}
        # Threads может отказать, а Zernio ответит 207 — это тоже ошибка публикации.
        if post.get("status") == "failed":
            reasons = [p.get("errorMessage") for p in post.get("platforms") or [] if p.get("errorMessage")]
            raise ThreadsError("Threads отклонил пост: " + ("; ".join(reasons) or payload.get("error", "без причины")))
        return post.get("_id", "")

    async def delete_comment(self, post_id: str, comment_id: str) -> None:
        """Удаляет комментарий (наш собственный ответ) под постом."""
        await self._request("DELETE", f"/inbox/comments/{post_id}",
                            params={"accountId": self.account_id, "commentId": comment_id})

    async def unpublish(self, post_id: str) -> None:
        """Снимает пост из Threads (запись в Zernio остаётся со статусом cancelled)."""
        await self._request("POST", f"/posts/{post_id}/unpublish", json={"platform": "threads"})

    async def find_post(self, text: str, since: datetime) -> str | None:
        """Есть ли уже в Zernio пост с этим текстом (после сбоя связи) — чтобы не опубликовать дважды."""
        _, payload = await self._request("GET", "/posts", params={
            "limit": 20, "accountId": self.account_id, "fromDate": since.date().isoformat(),
            "search": text.strip()[:40], "fields": "content,status",
        })
        for post in payload.get("posts") or []:
            if (post.get("content") or "").strip()[:80] == text.strip()[:80] and post.get("status") != "failed":
                return post.get("_id") or "published"
        return None

    async def commented_posts(self, since: datetime) -> list[dict]:
        """Все посты аккаунта в Threads, под которыми есть комментарии (в том числе опубликованные не ботом)."""
        _, payload = await self._request(
            "GET",
            "/inbox/comments",
            params={
                "platform": "threads", "accountId": self.account_id, "minComments": 1,
                "since": since.isoformat(), "limit": 50,
            },
        )
        return payload.get("data") or []

    async def comments(self, post_id: str, max_pages: int = 10) -> list[dict]:
        """Все комментарии под постом (ответы людей в Threads) — постранично, до 500."""
        out: list[dict] = []
        cursor = None
        for _ in range(max_pages):
            params = {"accountId": self.account_id, "limit": 50}
            if cursor:
                params["cursor"] = cursor
            _, payload = await self._request("GET", f"/inbox/comments/{post_id}", params=params)
            out += payload.get("comments") or []
            page = payload.get("pagination") or {}
            cursor = page.get("cursor")
            if not page.get("hasMore") or not cursor:
                break
        return out

    async def reply(self, post_id: str, comment_id: str, message: str) -> None:
        """Отвечает на комментарий. Ключ идемпотентности не даст ответить дважды при повторе."""
        await self._request(
            "POST",
            f"/inbox/comments/{post_id}",
            json={"accountId": self.account_id, "commentId": comment_id, "message": message},
            # ключ зависит и от текста: повтор того же ответа не задвоится, а новый текст не ловит «ключ уже занят»
            headers={"Idempotency-Key": f"reply-{comment_id}-{hashlib.sha1(message.encode()).hexdigest()[:12]}"},
        )

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
