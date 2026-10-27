"""Durable reply cooldown only for a confirmed HTTP 429 from Zernio."""
import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KEY = 'autoreply:cooldown:v1'

async def blocked(db, now):
    try:
        state = json.loads(await db.kv_get(KEY) or '{}')
        return datetime.fromisoformat(state['until']) > now
    except (ValueError, TypeError, KeyError):
        return False

async def defer(db, error, now):
    if getattr(error, 'http_status', None) != 429:
        return False
    try: state = json.loads(await db.kv_get(KEY) or '{}')
    except (ValueError, TypeError): state = {}
    attempts = min(int(state.get('attempts', 0)) + 1, 6)
    delay = min(300 * 2 ** (attempts-1), 3600)
    value = getattr(error, 'retry_after', None)
    try: retry = float(value)
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
            retry = (date.astimezone(timezone.utc)-now).total_seconds()
        except (TypeError, ValueError, AttributeError): retry = 0
    if retry > 0: delay = max(delay, min(retry, 86400))
    until = now + timedelta(seconds=delay)
    await db.kv_set(KEY, json.dumps({'until':until.isoformat(),'attempts':attempts}))
    await db.kv_set('autoreply_error', f'{now:%d.%m %H:%M} ответ: Zernio HTTP 429; '
                    f'запросы автоответов отложены до {until:%H:%M UTC}. '
                    'Источник ограничения внутри цепочки Zernio/Threads не установлен.')
    return True

async def success(db, now):
    await db.kv_set(KEY, '')
    await db.kv_set('autoreply:last_success', now.isoformat())
