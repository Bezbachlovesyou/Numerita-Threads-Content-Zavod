"""A pending Zernio publication is retriable, not a global inbox outage."""
import re
from datetime import datetime, timedelta

WAIT_LIMIT = timedelta(minutes=30)
PENDING = re.compile(r"has no platform post ID yet\s*\(status:\s*publishing\)", re.I)


async def defer_publishing(db, target_id, error, now):
    if not PENDING.search(str(error)):
        return False
    key = "publishing_wait:" + target_id
    saved = await db.kv_get(key)
    try:
        first = datetime.fromisoformat(saved) if saved else now
        age = now - first
        if age < timedelta(0):
            first, age = now, timedelta(0)
    except (ValueError, TypeError):
        first, age = now, timedelta(0)
    await db.kv_set(key, first.isoformat())
    if age >= WAIT_LIMIT:
        # The ordinary notification path deduplicates this stable reason.
        await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} комментарии: "
                        f"Zernio: пост {target_id} остаётся publishing больше 30 минут; "
                        "ID Threads ещё не получен. Проверки продолжатся, остальные посты обрабатываются.")
    else:
        # Remove only an old warning for this exact pending publication.
        previous = await db.kv_get("autoreply_error") or ""
        if target_id in previous and PENDING.search(previous):
            await db.kv_set("autoreply_error", "")
    return True


async def publication_ready(db, target_id):
    key = "publishing_wait:" + target_id
    if await db.kv_get(key):
        await db.kv_set(key, "")
    previous = await db.kv_get("autoreply_error") or ""
    if target_id in previous and (PENDING.search(previous) or "остаётся publishing больше 30 минут" in previous):
        await db.kv_set("autoreply_error", "")
