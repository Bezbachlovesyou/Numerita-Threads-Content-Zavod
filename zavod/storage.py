from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT NOT NULL,
    text         TEXT NOT NULL,
    -- draft | scheduled | published | failed | deleted
    status       TEXT NOT NULL DEFAULT 'draft',
    scheduled_at TEXT,  -- UTC ISO
    published_at TEXT,  -- UTC ISO
    threads_id   TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL
);
"""


@dataclass
class Post:
    id: int
    topic: str
    text: str
    status: str
    scheduled_at: datetime | None
    threads_id: str | None
    error: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_post(row: aiosqlite.Row) -> Post:
    return Post(
        id=row["id"],
        topic=row["topic"],
        text=row["text"],
        status=row["status"],
        scheduled_at=datetime.fromisoformat(row["scheduled_at"]) if row["scheduled_at"] else None,
        threads_id=row["threads_id"],
        error=row["error"],
    )


class Storage:
    def __init__(self, path: str):
        self.path = path

    async def _execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(sql, params)
            await db.commit()
            return cursor

    async def _fetch(self, sql: str, params: tuple = ()) -> list[Post]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                return [_row_to_post(row) for row in await cursor.fetchall()]

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    async def add_draft(self, topic: str, text: str) -> int:
        cursor = await self._execute(
            "INSERT INTO posts (topic, text, created_at) VALUES (?, ?, ?)",
            (topic, text, _now()),
        )
        return cursor.lastrowid

    async def get(self, post_id: int) -> Post | None:
        posts = await self._fetch("SELECT * FROM posts WHERE id = ?", (post_id,))
        return posts[0] if posts else None

    async def update_text(self, post_id: int, text: str) -> None:
        await self._execute("UPDATE posts SET text = ? WHERE id = ?", (text, post_id))

    async def schedule(self, post_id: int, when: datetime) -> None:
        await self._execute(
            "UPDATE posts SET status = 'scheduled', scheduled_at = ? WHERE id = ?",
            (when.astimezone(timezone.utc).isoformat(), post_id),
        )

    async def mark_published(self, post_id: int, threads_id: str | None) -> None:
        await self._execute(
            "UPDATE posts SET status = 'published', published_at = ?, threads_id = ?, error = NULL"
            " WHERE id = ?",
            (_now(), threads_id, post_id),
        )

    async def mark_failed(self, post_id: int, error: str) -> None:
        await self._execute(
            "UPDATE posts SET status = 'failed', error = ? WHERE id = ?", (error, post_id)
        )

    async def delete(self, post_id: int) -> None:
        await self._execute("UPDATE posts SET status = 'deleted' WHERE id = ?", (post_id,))

    async def due(self) -> list[Post]:
        return await self._fetch(
            "SELECT * FROM posts WHERE status = 'scheduled' AND scheduled_at <= ?"
            " ORDER BY scheduled_at",
            (_now(),),
        )

    async def queue(self) -> list[Post]:
        return await self._fetch(
            "SELECT * FROM posts WHERE status IN ('draft', 'scheduled', 'failed')"
            " ORDER BY COALESCE(scheduled_at, created_at)"
        )
