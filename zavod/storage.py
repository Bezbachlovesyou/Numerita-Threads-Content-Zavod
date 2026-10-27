from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiosqlite
import asyncpg

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS dialogue_messages (
    target_id TEXT NOT NULL,
    root_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    parent_id TEXT,
    author_id TEXT NOT NULL,
    author TEXT NOT NULL,
    role TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (target_id, message_id)
);
CREATE INDEX IF NOT EXISTS dialogue_root_idx ON dialogue_messages(target_id, root_id, created_at);
"""

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
    tg_message_id TEXT,  -- сообщение в Telegram-канале
    rubric       TEXT,  -- рубрика контент-плана (для самоулучшения)
    first_comment TEXT,  -- первый комментарий под постом (ссылка с меткой)
    card         TEXT,  -- что нарисовать на картинке (JSON)
    image_url    TEXT,  -- загруженная картинка поста
    error        TEXT,
    created_at   TEXT NOT NULL
);

-- Слоты автопостинга, которые уже отработали (защита от дублей после перезапуска).
CREATE TABLE IF NOT EXISTS autopost_slots (
    slot    TEXT PRIMARY KEY,
    post_id INTEGER
);
-- Комментарии в Threads, на которые бот уже ответил или решил не отвечать.
CREATE TABLE IF NOT EXISTS comment_replies (
    comment_id TEXT PRIMARY KEY,
    post_id    INTEGER,
    author     TEXT,
    comment    TEXT,
    reply      TEXT,
    status     TEXT NOT NULL,  -- replied | skipped
    created_at TEXT NOT NULL
);
-- Самоулучшение: лайки и показы постов, переписанные рубрики, временные замены рубрик.
CREATE TABLE IF NOT EXISTS post_metrics (
    post_id     INTEGER PRIMARY KEY,
    likes       INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rubric_overrides (
    key        TEXT PRIMARY KEY,
    text       TEXT NOT NULL,
    previous   TEXT NOT NULL,
    baseline   REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_swaps (
    key         TEXT PRIMARY KEY,
    replacement TEXT NOT NULL,
    until       TEXT NOT NULL
);
-- Состояние автопостинга и самоулучшения (время следующего поста, веса рубрик и часов).
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Рубрики, которые бот придумал сам: trial — на проверке, kept — оставлены, dropped — убраны.
CREATE TABLE IF NOT EXISTS custom_rubrics (
    key        TEXT PRIMARY KEY,
    cta        TEXT NOT NULL,
    text       TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at TEXT NOT NULL
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
    tg_message_id: str | None
    rubric: str | None
    first_comment: str | None
    card: str | None
    image_url: str | None
    error: str | None
    link_mode: str | None = None  # эксперимент со ссылкой: text | comment | profile
    published_at: datetime | None = None


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
        tg_message_id=row["tg_message_id"],
        rubric=row.get("rubric"),
        first_comment=row.get("first_comment"),
        card=row.get("card"),
        image_url=row.get("image_url"),
        error=row["error"],
        link_mode=row.get("link_mode"),
        published_at=datetime.fromisoformat(row["published_at"]) if row.get("published_at") else None,
    )


class Storage:
    def __init__(self, path: str):
        self.path = path

    async def _execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(sql, params)
            await db.commit()
            return cursor

    async def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def _fetch(self, sql: str, params: tuple = ()) -> list[Post]:
        return [_row_to_post(row) for row in await self._rows(sql, params)]

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA + MEMORY_SCHEMA)
            for column in ("tg_message_id", "rubric", "first_comment", "card", "image_url", "link_mode"):  # базы, созданные до этих колонок
                try:
                    await db.execute(f"ALTER TABLE posts ADD COLUMN {column} TEXT")
                except aiosqlite.OperationalError:
                    pass
            await db.commit()

    async def remember_message(self, target, root, message_id, parent, author_id, author, role, body, created):
        try:
            stamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            created = stamp.astimezone(timezone.utc).isoformat()
        except (ValueError, AttributeError):
            created = _now()
        await self._execute(
            "INSERT INTO dialogue_messages "
            "(target_id,root_id,message_id,parent_id,author_id,author,role,body,created_at,observed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT (target_id,message_id) DO UPDATE SET "
            "body=excluded.body, author=excluded.author",
            (target,root,message_id,parent,author_id,author,role,body,created,_now()),
        )

    async def dialogue_message(self, target, message_id):
        rows = await self._rows(
            "SELECT * FROM dialogue_messages WHERE target_id=? AND message_id=?", (target,message_id))
        return rows[0] if rows else None

    async def dialogue_history(self, target, root):
        return await self._rows(
            "SELECT * FROM dialogue_messages WHERE target_id=? AND root_id=? ORDER BY created_at,message_id",
            (target,root))

    async def active_dialogue_targets(self, since):
        return await self._rows(
            "SELECT target_id FROM dialogue_messages WHERE observed_at>=? "
            "GROUP BY target_id ORDER BY MAX(observed_at) DESC LIMIT 100",
            (since.astimezone(timezone.utc).isoformat(),))

    async def add_draft(
        self, topic: str, text: str, rubric: str | None = None, first_comment: str | None = None,
        card: str | None = None,
    ) -> int:
        cursor = await self._execute(
            "INSERT INTO posts (topic, text, created_at, rubric, first_comment, card) VALUES (?, ?, ?, ?, ?, ?)",
            (topic, text, _now(), rubric, first_comment, card),
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

    async def set_image(self, post_id: int, url: str) -> None:
        await self._execute("UPDATE posts SET image_url = ? WHERE id = ?", (url, post_id))

    async def set_threads_id(self, post_id: int, threads_id: str) -> None:
        await self._execute("UPDATE posts SET threads_id = ? WHERE id = ?", (threads_id, post_id))

    async def set_link_mode(self, post_id: int, mode: str) -> None:
        await self._execute("UPDATE posts SET link_mode = ? WHERE id = ?", (mode, post_id))

    async def set_tg_message_id(self, post_id: int, message_id: str) -> None:
        await self._execute("UPDATE posts SET tg_message_id = ? WHERE id = ?", (message_id, post_id))

    async def mark_published(self, post_id: int) -> None:
        await self._execute(
            "UPDATE posts SET status = 'published', published_at = ?, error = NULL WHERE id = ?",
            (_now(), post_id),
        )

    async def mark_failed(self, post_id: int, error: str) -> None:
        await self._execute(
            "UPDATE posts SET status = 'failed', error = ? WHERE id = ?", (error, post_id)
        )

    async def find_published(self, fragment: str, since: datetime) -> list[Post]:
        """Опубликованные посты, где в тексте или фразе картинки есть этот кусок."""
        like = f"%{fragment}%"
        return await self._fetch(
            "SELECT * FROM posts WHERE status = 'published' AND published_at >= ? AND threads_id IS NOT NULL"
            " AND (text LIKE ? OR card LIKE ?)", (since.astimezone(timezone.utc).isoformat(), like, like),
        )

    async def delete(self, post_id: int) -> None:
        await self._execute("UPDATE posts SET status = 'deleted' WHERE id = ?", (post_id,))

    async def has_post_near(self, when: datetime, gap: timedelta) -> bool:
        """Есть ли запланированный или опубликованный пост ближе gap к этому времени."""
        lo = (when - gap).astimezone(timezone.utc).isoformat()
        hi = (when + gap).astimezone(timezone.utc).isoformat()
        posts = await self._fetch(
            "SELECT * FROM posts WHERE status IN ('scheduled', 'published')"
            " AND COALESCE(scheduled_at, published_at) BETWEEN ? AND ?",
            (lo, hi),
        )
        return bool(posts)

    async def claim_slot(self, slot: str) -> bool:
        """Отмечает слот автопостинга. False — слот уже был отработан."""
        cursor = await self._execute("INSERT OR IGNORE INTO autopost_slots (slot) VALUES (?)", (slot,))
        return cursor.rowcount == 1

    async def recent_published(self, since: datetime) -> list[Post]:
        """Посты, опубликованные в Threads после since, — под ними ищем комментарии."""
        return await self._fetch(
            "SELECT * FROM posts WHERE status = 'published' AND published_at >= ?"
            " AND threads_id IS NOT NULL AND threads_id <> 'published' ORDER BY published_at DESC",
            (since.astimezone(timezone.utc).isoformat(),),
        )

    async def handled_comments(self, comment_ids: list[str]) -> set[str]:
        if not comment_ids:
            return set()
        marks = ", ".join("?" for _ in comment_ids)
        rows = await self._rows(f"SELECT comment_id FROM comment_replies WHERE comment_id IN ({marks})", tuple(comment_ids))
        return {row["comment_id"] for row in rows}

    async def record_comment(
        self, comment_id: str, post_id: int, author: str, comment: str, reply: str, status: str
    ) -> None:
        await self._execute(
            "INSERT INTO comment_replies (comment_id, post_id, author, comment, reply, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (comment_id, post_id, author, comment, reply, status, _now()),
        )

    async def replies_since(self, since: datetime) -> int:
        rows = await self._rows(
            "SELECT COUNT(*) AS n FROM comment_replies WHERE status = 'replied' AND created_at >= ?",
            (since.astimezone(timezone.utc).isoformat(),),
        )
        return int(rows[0]["n"])

    async def replies_to_author(self, author: str, since: datetime) -> int:
        rows = await self._rows(
            "SELECT COUNT(*) AS n FROM comment_replies WHERE status = 'replied' AND author = ? AND created_at >= ?",
            (author, since.astimezone(timezone.utc).isoformat()),
        )
        return int(rows[0]["n"])

    async def forget_comment(self, comment_id: str) -> None:
        """Снова считать комментарий неотвеченным (например, наш ответ на него оказался обрывком и удалён)."""
        await self._execute("DELETE FROM comment_replies WHERE comment_id = ?", (comment_id,))

    async def link_replies(self, since: datetime, author: str | None = None, pattern: str = "%t.me/%") -> int:
        """Сколько ответов со ссылкой отправлено (всего или одному человеку; pattern — например, по метке)."""
        sql = "SELECT COUNT(*) AS n FROM comment_replies WHERE status = 'replied' AND reply LIKE ? AND created_at >= ?"
        params: tuple = (pattern, since.astimezone(timezone.utc).isoformat())
        if author:
            sql += " AND author = ?"
            params += (author,)
        rows = await self._rows(sql, params)
        return int(rows[0]["n"])

    async def recent_comments(self, limit: int) -> list[dict]:
        return await self._rows(
            "SELECT * FROM comment_replies ORDER BY created_at DESC LIMIT ?", (limit,)
        )

    async def engagement(self, since: datetime) -> list[dict]:
        """Опубликованные посты с рубрикой: сколько комментариев и лайков собрали."""
        return await self._rows(
            "SELECT p.id AS id, p.rubric AS rubric, p.text AS text, p.topic AS topic, p.published_at AS published_at,"
            " p.card AS card, p.link_mode AS link_mode,"
            " (SELECT COUNT(*) FROM comment_replies c WHERE c.post_id = p.id) AS comments,"
            " COALESCE((SELECT m.likes FROM post_metrics m WHERE m.post_id = p.id), 0) AS likes,"
            " COALESCE((SELECT m.impressions FROM post_metrics m WHERE m.post_id = p.id), 0) AS views"
            " FROM posts p WHERE p.status = 'published' AND p.rubric IS NOT NULL AND p.published_at >= ?",
            (since.astimezone(timezone.utc).isoformat(),),
        )

    async def save_metrics(self, post_id: int, likes: int, impressions: int) -> None:
        await self._execute(
            "INSERT OR REPLACE INTO post_metrics (post_id, likes, impressions, updated_at) VALUES (?, ?, ?, ?)",
            (post_id, likes, impressions, _now()),
        )

    async def overrides(self) -> list[dict]:
        return await self._rows("SELECT * FROM rubric_overrides")

    async def set_override(self, key: str, text: str, previous: str, baseline: float) -> None:
        await self._execute("DELETE FROM rubric_overrides WHERE key = ?", (key,))
        await self._execute(
            "INSERT INTO rubric_overrides (key, text, previous, baseline, created_at) VALUES (?, ?, ?, ?, ?)",
            (key, text, previous, baseline, _now()),
        )

    async def drop_override(self, key: str) -> None:
        await self._execute("DELETE FROM rubric_overrides WHERE key = ?", (key,))

    async def swaps(self, now: datetime) -> dict[str, str]:
        rows = await self._rows(
            "SELECT key, replacement FROM plan_swaps WHERE until > ?", (now.astimezone(timezone.utc).isoformat(),)
        )
        return {row["key"]: row["replacement"] for row in rows}

    async def set_swap(self, key: str, replacement: str, until: datetime) -> None:
        await self._execute("DELETE FROM plan_swaps WHERE key = ?", (key,))
        await self._execute(
            "INSERT INTO plan_swaps (key, replacement, until) VALUES (?, ?, ?)",
            (key, replacement, until.astimezone(timezone.utc).isoformat()),
        )

    async def last_published_at(self) -> datetime | None:
        rows = await self._rows("SELECT MAX(published_at) AS last FROM posts WHERE status = 'published'")
        return datetime.fromisoformat(rows[0]["last"]) if rows and rows[0]["last"] else None

    async def kv_get(self, key: str) -> str | None:
        rows = await self._rows("SELECT value FROM kv WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    async def kv_set(self, key: str, value: str) -> None:
        await self._execute("DELETE FROM kv WHERE key = ?", (key,))
        await self._execute("INSERT INTO kv (key, value) VALUES (?, ?)", (key, value))

    async def recent_rubrics(self, limit: int) -> list[str]:
        """Рубрики последних опубликованных постов, свежие первыми."""
        rows = await self._rows(
            "SELECT rubric FROM posts WHERE status = 'published' AND rubric IS NOT NULL"
            " ORDER BY published_at DESC LIMIT ?",
            (limit,),
        )
        return [row["rubric"] for row in rows]

    async def next_queued(self) -> Post | None:
        """Следующий готовый текст из очереди."""
        posts = await self._fetch("SELECT * FROM posts WHERE status = 'queued' ORDER BY id LIMIT 1")
        return posts[0] if posts else None

    async def queue_post(self, post_id: int) -> None:
        await self._execute("UPDATE posts SET status = 'queued' WHERE id = ?", (post_id,))

    async def drop_credited_posts(self) -> None:
        """Готовые посты «по мотивам» чужих авторов и их схем не выпускаем: слово владельца 24.10.2026."""
        await self._execute(
            "UPDATE posts SET status = 'deleted' WHERE rubric = 'script' AND status IN ('queued', 'failed', 'scheduled')"
            " AND threads_id IS NULL AND (text LIKE ? OR text LIKE ? OR text LIKE ?)",
            ("%по мотивам%", "%keyto%", "%кармический урок по дню рождения%")
        )

    async def requeue_scheduled_scripts(self) -> None:
        """Готовые тексты, стоявшие на точное время, переводим в очередь — время решает бот."""
        await self._execute("UPDATE posts SET status = 'queued' WHERE rubric = 'script' AND status = 'scheduled'")

    async def custom_rubrics(self, statuses: tuple[str, ...]) -> list[dict]:
        marks = ", ".join("?" for _ in statuses)
        return await self._rows(f"SELECT * FROM custom_rubrics WHERE status IN ({marks}) ORDER BY created_at", statuses)

    async def add_custom_rubric(self, key: str, cta: str, text: str) -> None:
        await self._execute(
            "INSERT INTO custom_rubrics (key, cta, text, status, created_at) VALUES (?, ?, ?, 'trial', ?)",
            (key, cta, text, _now()),
        )

    async def set_custom_status(self, key: str, status: str) -> None:
        await self._execute("UPDATE custom_rubrics SET status = ? WHERE key = ?", (status, key))

    async def due(self) -> list[Post]:
        return await self._fetch(
            "SELECT * FROM posts WHERE status = 'scheduled' AND scheduled_at <= ?"
            " ORDER BY scheduled_at",
            (_now(),),
        )

    async def queue(self) -> list[Post]:
        return await self._fetch(
            "SELECT * FROM posts WHERE status IN ('draft', 'scheduled', 'queued', 'failed')"
            " ORDER BY COALESCE(scheduled_at, created_at)"
        )


PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id           SERIAL PRIMARY KEY,
    topic        TEXT NOT NULL,
    text         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft',
    scheduled_at TEXT,
    published_at TEXT,
    threads_id   TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autopost_slots (
    slot    TEXT PRIMARY KEY,
    post_id INTEGER
);
-- Комментарии в Threads, на которые бот уже ответил или решил не отвечать.
CREATE TABLE IF NOT EXISTS comment_replies (
    comment_id TEXT PRIMARY KEY,
    post_id    INTEGER,
    author     TEXT,
    comment    TEXT,
    reply      TEXT,
    status     TEXT NOT NULL,  -- replied | skipped
    created_at TEXT NOT NULL
);
-- Самоулучшение: лайки и показы постов, переписанные рубрики, временные замены рубрик.
CREATE TABLE IF NOT EXISTS post_metrics (
    post_id     INTEGER PRIMARY KEY,
    likes       INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rubric_overrides (
    key        TEXT PRIMARY KEY,
    text       TEXT NOT NULL,
    previous   TEXT NOT NULL,
    baseline   REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_swaps (
    key         TEXT PRIMARY KEY,
    replacement TEXT NOT NULL,
    until       TEXT NOT NULL
);
-- Состояние автопостинга и самоулучшения (время следующего поста, веса рубрик и часов).
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Рубрики, которые бот придумал сам: trial — на проверке, kept — оставлены, dropped — убраны.
CREATE TABLE IF NOT EXISTS custom_rubrics (
    key        TEXT PRIMARY KEY,
    cta        TEXT NOT NULL,
    text       TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class PgStorage(Storage):
    """То же хранилище поверх Postgres (например, база в проекте Railway).

    SQL общий с SQLite: плейсхолдеры `?` переводятся в `$1, $2, …`.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    @staticmethod
    def _sql(sql: str) -> str:
        parts = sql.split("?")
        return parts[0] + "".join(f"${i}{part}" for i, part in enumerate(parts[1:], start=1))

    async def init(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        await self.pool.execute(PG_SCHEMA + MEMORY_SCHEMA)
        await self.pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS tg_message_id TEXT")
        await self.pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS rubric TEXT")
        await self.pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS first_comment TEXT")
        await self.pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS card TEXT")
        await self.pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS image_url TEXT")
        await self.pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS link_mode TEXT")

    async def _execute(self, sql: str, params: tuple = ()) -> None:
        await self.pool.execute(self._sql(sql), *params)

    async def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(row) for row in await self.pool.fetch(self._sql(sql), *params)]

    async def claim_slot(self, slot: str) -> bool:
        claimed = await self.pool.fetchval(
            "INSERT INTO autopost_slots (slot) VALUES ($1) ON CONFLICT DO NOTHING RETURNING slot", slot
        )
        return claimed is not None

    async def add_draft(
        self, topic: str, text: str, rubric: str | None = None, first_comment: str | None = None,
        card: str | None = None,
    ) -> int:
        return await self.pool.fetchval(
            "INSERT INTO posts (topic, text, created_at, rubric, first_comment, card)"
            " VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            topic, text, _now(), rubric, first_comment, card,
        )

    async def save_metrics(self, post_id: int, likes: int, impressions: int) -> None:
        await self.pool.execute(
            "INSERT INTO post_metrics (post_id, likes, impressions, updated_at) VALUES ($1, $2, $3, $4)"
            " ON CONFLICT (post_id) DO UPDATE SET likes = $2, impressions = $3, updated_at = $4",
            post_id, likes, impressions, _now(),
        )


