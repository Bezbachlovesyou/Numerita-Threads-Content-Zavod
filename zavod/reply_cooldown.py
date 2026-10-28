"""Durable cooldown for confirmed throttling and repeated provider access denials."""
import json
import re
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
    status = getattr(error, 'http_status', None)
    denied = status == 403 and re.search(r'\b80016\b', str(error)) is not None
    if status != 429 and not denied:
        return False
    history_key = 'autoreply:failures:' + ('403-80016' if denied else '429')
    try:
        history = json.loads(await db.kv_get(history_key) or '{}')
        recent = (now - datetime.fromisoformat(history['at'])).total_seconds() < 21600
    except (ValueError, TypeError, KeyError):
        history, recent = {}, False
    attempts = min(int(history.get('attempts', 0)) + 1, 6) if recent else 1
    await db.kv_set(history_key, json.dumps({'at': now.isoformat(), 'attempts': attempts}))
    delay = min((1800 if denied else 300) * 2 ** (attempts-1), 21600 if denied else 3600)
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
    reason = ('Zernio HTTP 403: Platform error: 80016' if denied else 'Zernio HTTP 429')
    await db.kv_set('autoreply_error', f'{now:%d.%m %H:%M} ответ: {reason}; '
                    f'запросы автоответов отложены до {until:%H:%M UTC}. '
                    'Причина внутри цепочки Zernio/Threads не установлена.')
    return True

async def success(db, now):
    await db.kv_set(KEY, '')
    await db.kv_set('autoreply:last_success', now.isoformat())
