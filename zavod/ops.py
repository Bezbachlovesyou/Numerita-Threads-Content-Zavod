"""Пульт владельца (слово владельца 30.10.2026: «я говорю тебе здесь — и ты сразу делаешь на всех площадках»).

Claude записывает поручение в ops/commands.json в main. Бот раз в 5 минут читает файл с GitHub (без перезапуска),
выполняет каждую команду один раз (claim ops:<id>) на своей площадке и присылает владельцу одну строку-квитанцию.
Команды: {"id": "...", "account": "ru" | "en" | "tg", "action": "post" | "grid" | "unpublish", ...}
  post      — {"text": "..."}: пост в Threads (ru/en) или в канал (tg); тексты проходят обычные проверки на границе.
  grid      — {"shape": "spiral" | "heart" | "dna" | ...}: следующая живая матрица этой формы.
  unpublish — {"fragment": "..."}: снять пост Threads с этим куском текста.
  circle_preview — {"seed": "..."}: ролик «Найди числа от 1 до 31» только владельцу в Telegram, без публикации.
  approve_spend — {"label": "...", "usd": 1.5} и/или {"loss_budget": 5}: «да» владельца на сумму опыта / потолок убытка (контролёр прибыли).
  idea      — {"title": "...", "text": "..."|"file": "docs/ideas.md"}: записать идею владельца (напоминания раз в 7 дней) и прислать в Telegram.
  idea_done — {"idea_id": "..."}: снять идею с учёта.
  resend_clips — прислать владельцу 4 приветственных ролика заново с подписями и инструкцией для Instagram.
  ig_carousel — {"set": "quarrel|ok|love", "publish": false}: карусель Instagram своего языка; без publish — превью только владельцу.
  send_assets — {"files": ["assets/cover/…"], "text": "..."}: файлы обложек владельцу документами (без пережатия).
  accounts_check — какие площадки подключены в Zernio (названия и числа), в том числе Facebook.
  asap      — {"asap": true} у post/thread: выйти сразу, без паузы после последнего поста (флагманский пост владельца).
  video_post — {"media": "channel/….mp4", "text": "...", "items": [...], "rubric": "..."}: готовый ролик из assets/ в Threads, items — продолжение ветки.
  link_under — {"fragment": "...", "text": "... ссылка"}: наш комментарий со ссылкой под уже вышедшим постом.
  after     — {"after": "2026-11-12T18:30:00+03:00"} у любой команды: выполнить не раньше этого времени (со смещением пояса).
  replies_off / replies_on — пауза / возобновление автоответов на комментарии (ответ владельца reply_to идёт).
  posts_off / posts_on — пауза / возобновление всех постов в Threads своего языка (ответы на комментарии идут; посты из пульта ждут).
  post + account tg + media_url — ролик с www.numerita.ru/m/…mp4 в канал, text — подпись (до 1024 знаков).
  notify_digest / notify_live — владельцу сводка раз в день в 19:30 (по умолчанию) / все сообщения сразу; ‼️ и 🆘 — всегда сразу.
  tell      — {"text": "..."} или {"file": "knowledge/…"}: длинный текст только владельцу в Telegram (без Threads, $0).
"""

import asyncio
import json
import logging
import time

import httpx

log = logging.getLogger(__name__)
RAW = "https://raw.githubusercontent.com/bezbachlovesyou/numerita-threads-content-zavod/main"
URL = f"{RAW}/ops/commands.json"
EVERY = 300
_last: float | None = None


async def fetch(fresh: bool = False) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.get(URL, params={"t": int(time.time()) if fresh else int(time.time() // EVERY)})
    if r.status_code != 200:
        return []
    data = r.json()
    return [c for c in data if isinstance(c, dict) and c.get("id")] if isinstance(data, list) else []


async def publication_receipts(db, threads, ids: list[str]) -> list[str]:
    """Только чтение: точечные квитанции порученных публикаций, без повторной отправки."""
    out = ["Публикации: пауза=" + str(await db.kv_get("posts:paused") or "0")]
    for ident in ids[:10]:
        rows = await db._rows("SELECT id FROM posts WHERE topic = ? ORDER BY id DESC LIMIT 1", ("ops:" + ident,))
        if not rows:
            out.append(f"{ident}: запись ещё не создана")
            continue
        post = await db.get(rows[0]["id"])
        line = f"{ident}: локально={post.status}"
        if post.threads_id and post.threads_id != "published" and threads:
            try:
                status, link, error = await asyncio.wait_for(threads.post_status(post.threads_id), 20)
                line += f"; Threads={status}; {link or error or 'ссылки пока нет'}"
            except Exception as e:
                line += "; квитанция недоступна: " + type(e).__name__
        elif post.error:
            line += "; " + post.error[:180]
        out.append(line)
    return out


async def receipt_probe(db, threads, account: str, mirror) -> None:
    """Запрошенное чтение квитанций не ждёт автоматических постов и не исполняет команды публикации."""
    try:
        for cmd in await fetch():
            if cmd.get("action") != "publication_receipts" or cmd.get("account", "ru") != account:
                continue
            if not await db.claim_slot(f"ops:{cmd['id']}"):
                continue
            await mirror("Диагностика квитанций: " + account + "; следующий API-запрос="
                         + str(await db.kv_get("api:next_request") or "сейчас"))
            for line in await publication_receipts(db, threads, [str(i) for i in cmd.get("ids", [])]):
                await mirror(line)
    except Exception:
        log.exception("Чтение запрошенных квитанций не завершено")


async def startup_snapshot(dsn: str, account: str, mirror) -> None:
    """Только SELECT через отдельное соединение: диагностика доступна даже при ожидании миграции."""
    import asyncpg
    conn = None
    try:
        commands = [c for c in await fetch(fresh=True) if c.get("action") == "publication_receipts"
                    and c.get("account", "ru") == account and c.get("startup_snapshot")]
        if not commands or not dsn:
            return
        conn = await asyncpg.connect(dsn, timeout=15, command_timeout=15)
        schema = "en" if account == "en" else "public"
        async with conn.transaction(readonly=True):
            waiting = await conn.fetch("SELECT pid, state, wait_event_type, wait_event, pg_blocking_pids(pid) AS blockers "
                                       "FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'")
            await mirror("Ожидание блокировок БД: " + json.dumps([dict(r) for r in waiting], default=str))
            quota = await conn.fetch(f"SELECT key,value FROM {schema}.kv WHERE key IN "
                                     "('api:next_request','api:quota:general','api:quota:analytics')")
            await mirror("Ожидание API: " + json.dumps([dict(r) for r in quota], ensure_ascii=False)[:650])
            for cmd in commands:
                for ident in [str(i) for i in cmd.get("ids", [])][:10]:
                    row = await conn.fetchrow(f"SELECT id,status,threads_id,error FROM {schema}.posts "
                                             "WHERE topic=$1 ORDER BY id DESC LIMIT 1", "ops:" + ident)
                    await mirror("Снимок публикации " + ident + ": " + json.dumps(dict(row) if row else {}, ensure_ascii=False))
                    if cmd.get("reply_audit"):
                        keys = ('replies:paused', 'autoreply_error', 'autoreply:last_success',
                                'autoreply:cooldown:v1', 'reply_links_paused_until')
                        state = await conn.fetch(f"SELECT key,value FROM {schema}.kv WHERE key=ANY($1::text[])", list(keys))
                        await mirror("Аудит ответов " + account + ": " + json.dumps([dict(r) for r in state], ensure_ascii=False)[:650])
                        if row:
                            scans = await conn.fetchval(f"SELECT value FROM {schema}.kv WHERE key='comments:last_scans'")
                            scan = json.loads(scans or '{}').get(row['threads_id'])
                            counters = await conn.fetchrow(f"SELECT COUNT(*) AS archived, "
                                f"COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM {schema}.comment_replies r "
                                "WHERE r.comment_id=m.message_id)) AS unhandled "
                                f"FROM {schema}.dialogue_messages m WHERE target_id=$1 AND role='user'", row['threads_id'])
                            replies = await conn.fetch(f"SELECT status,COUNT(*) AS n,MAX(created_at) AS last "
                                                       f"FROM {schema}.comment_replies WHERE post_id=$1 GROUP BY status", row['id'])
                            await mirror("Ответы под хитом " + account + ": " + json.dumps({
                                'scan': scan, 'archive': dict(counters), 'replies': [dict(r) for r in replies]}, ensure_ascii=False))
                            samples = await conn.fetch(f"SELECT reply,created_at FROM {schema}.comment_replies "
                                                       "WHERE post_id=$1 AND status='replied' ORDER BY created_at DESC LIMIT 2", row['id'])
                            for sample in samples:
                                await mirror("Пример ответа " + account + " " + sample['created_at'] + ": " + sample['reply'][:480])
        # Разовый GET по отдельному поручению: проверка чтения нового поста, без отправки и сброса пауз.
        for cmd in commands:
            if not cmd.get('probe_comments'):
                continue
            from .storage import PgStorage
            from .threads_api import ThreadsClient
            from .dialogue import walk_comments
            import os
            db = PgStorage(dsn, schema=schema)
            db.pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1,
                server_settings={'search_path': schema}, command_timeout=20)
            try:
                if not await db.claim_slot('ops:comment-probe:' + cmd['id']):
                    continue
                client = ThreadsClient(os.getenv('ZERNIO_API_KEY', '').strip(), os.getenv('ZERNIO_ACCOUNT_ID', '').strip(), db)
                for ident in cmd.get('ids', [])[:1]:
                    rows = await db._rows('SELECT threads_id FROM posts WHERE topic=? ORDER BY id DESC LIMIT 1', ('ops:' + str(ident),))
                    if not rows:
                        continue
                    try:
                        comments = await asyncio.wait_for(client.comments(rows[0]['threads_id'], max_pages=1), 45)
                        incoming = [c for c, _, _ in walk_comments(comments) if not (c.get('from') or {}).get('isOwner')]
                        await mirror('Проверка чтения комментариев ' + account + ': доступно; реплик читателей на первой странице=' + str(len(incoming))
                                     + '; защитная пауза отправки не изменялась')
                    except Exception as e:
                        await mirror('Проверка чтения комментариев ' + account + ': ' + type(e).__name__ + ' ' + str(e)[:220])
            finally:
                await db.pool.close()
    except Exception as e:
        await mirror("Снимок публикации недоступен: " + type(e).__name__)
    finally:
        if conn:
            await conn.close()


async def tick(db, account: str, run, ready=None) -> None:
    """account — «ru» или «en» (канал tg выполняет русский экземпляр). run(command) -> строка квитанции.
    ready(command) -> False: команда пока ждёт (не занята), вернётся на следующем проходе — так посты из пульта не идут пачкой."""
    global _last
    if _last is not None and time.monotonic() - _last < EVERY:
        return
    _last = time.monotonic()
    try:
        commands = await fetch()
    except Exception as e:
        log.warning("Пульт: файл команд не прочитан: %s", e)
        return
    for cmd in commands:
        target = cmd.get("account", "ru")
        if target != account and not (target == "tg" and account == "ru"):
            continue
        if ready is not None and not await ready(cmd):
            continue
        if not await db.claim_slot(f"ops:{cmd['id']}"):
            continue
        try:
            await run(cmd)
        except Exception as e:
            log.exception("Пульт: команда %s не выполнена", cmd["id"])
            await run({"action": "_error", "id": cmd["id"], "error": f"{type(e).__name__}: {e}"})
