"""Pace API calls, keep a reserve and expose observed quotas, never a ban score."""
import asyncio
import json
import math
import time
from datetime import datetime, timezone

class RequestBudget:
    def __init__(self, storage=None, clock=time.time, sleep=asyncio.sleep):
        self.storage, self.clock, self.sleep = storage, clock, sleep
        self.next_at = 0
        self.lock = asyncio.Lock()

    async def before(self):
        async with self.lock:
            if self.storage:
                try: self.next_at = max(self.next_at, float(await self.storage.kv_get('api:next_request') or 0))
                except ValueError: pass
            delay = self.next_at-self.clock()
            if delay > 0: await self.sleep(delay)
            self.next_at = self.clock()+3  # At most 20 requests/minute in this worker.
            if self.storage:
                await self.storage.kv_set('api:next_request',str(self.next_at))

    async def observe(self, response, method, path):
        now = self.clock()
        def number(header):
            try:
                value = float(response.headers[header])
                return value if math.isfinite(value) and value >= 0 else None
            except (KeyError, TypeError, ValueError): return None
        limit, remaining, reset = (number(k) for k in ['X-RateLimit-Limit','X-RateLimit-Remaining','X-RateLimit-Reset'])
        analytics = path.startswith('/analytics')
        reserve = max(1 if analytics else 5, int((limit or 0)*.2))
        if remaining is not None and remaining <= reserve and reset is not None:
            self.next_at = max(self.next_at, reset+1)
        if response.status_code == 429:
            retry = number('Retry-After')
            self.next_at = max(self.next_at,now+max(60,retry or 0))
        if not self.storage: return
        await self.storage.kv_set('api:next_request',str(self.next_at))
        layer = 'unknown'
        if response.status_code == 429:
            try: payload = response.json()
            except ValueError: payload = {}
            if not isinstance(payload,dict): payload = {}
            details = payload.get('details') or {}
            if isinstance(details,dict) and 'currentCount' in details and 'limit' in details:
                layer = 'zernio_request_window'
            elif payload.get('code') == 'rate_limited':
                layer = 'upstream_' + ('threads' if payload.get('platform') == 'threads' else 'unspecified')
        kind = ('read_comments' if method == 'GET' and path.startswith('/inbox/comments') else
                'reply' if method == 'POST' and path.startswith('/inbox/comments') else
                'analytics' if analytics else 'other')
        snapshot = {'at':datetime.fromtimestamp(now,timezone.utc).isoformat(),
                    'status':response.status_code,'kind':kind,'limit':limit,'remaining':remaining,
                    'reset':reset,'reserve':reserve,'layer':layer}
        await self.storage.kv_set('api:quota:'+('analytics' if analytics else 'general'),json.dumps(snapshot))
        if response.status_code == 429:
            await self.storage.kv_set('api:last_429',json.dumps(snapshot))
        key = 'api:day:'+datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%d')
        try: counts = json.loads(await self.storage.kv_get(key) or '{}')
        except ValueError: counts = {}
        counts['requests'] = counts.get('requests',0)+1
        counts[kind] = counts.get(kind,0)+1
        if response.status_code == 429: counts['http_429'] = counts.get('http_429',0)+1
        await self.storage.kv_set(key,json.dumps(counts))

async def report(db, now):
    lines = ['Состояние API и автоответов',
             'Процент вероятности блокировки Threads недоступен; квота запросов не является такой вероятностью.']
    for key,label in [('api:quota:general','Запросы/минута'),('api:quota:analytics','Аналитика/секунда')]:
        raw = await db.kv_get(key)
        if raw:
            d=json.loads(raw)
            lines.append(f"{label}: осталось {d.get('remaining')} из {d.get('limit')}; снимок {d['at']}.")
        else: lines.append(label+': наблюдений ещё нет.')
    counts=json.loads(await db.kv_get('api:day:'+now.strftime('%Y-%m-%d')) or '{}')
    lines.append(f"С UTC-полуночи: запросов {counts.get('requests',0)}, чтение комментариев {counts.get('read_comments',0)}, HTTP 429 {counts.get('http_429',0)}. Учёт с выпуска мониторинга.")
    last=await db.kv_get('api:last_429')
    if last:
        d=json.loads(last);lines.append(f"Последний 429: {d['at']}, операция {d['kind']}, источник {d['layer']}.")
    lines.append('Остаток реальной квоты публикаций/ответов Meta и статус рекомендаций через это подключение не получены.')
    return '\n\n'.join(lines)
