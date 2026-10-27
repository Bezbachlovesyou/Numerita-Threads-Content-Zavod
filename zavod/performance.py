"""Platform observations; missing data stays missing, comparisons use 24–26h samples."""
import json
import math
from datetime import datetime, timedelta, timezone

from .threads_api import ThreadsError

HORIZONS = {1: 1.5, 24: 26, 72: 75}


def stamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def number(value):
    return int(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def parse(payload):
    if not payload or payload.get('syncStatus') == 'pending':
        return None
    parts = payload.get('platformAnalytics') or []
    thread = next((p for p in parts if p.get('platform') == 'threads'), None)
    if parts and thread is None:
        return None
    if thread and thread.get('syncStatus') in ('pending', 'failed'):
        return None
    a = (thread or payload).get('analytics') or {}
    if not isinstance(a, dict):
        return None
    # Do not substitute impressions for views: these are different measurements.
    result = {k: number(a.get(k)) for k in ('likes', 'comments', 'views', 'impressions', 'shares', 'reposts')}
    if all(v is None for v in result.values()):
        return None
    result['source_updated_at'] = a.get('lastUpdated')
    result['url'] = (thread or payload).get('platformPostUrl')
    return result


async def collect(db, threads, now):
    """At most one bounded pass/30min; no LLM calls and no new paid subscription."""
    last = await db.kv_get('performance:last_attempt')
    if last and now - stamp(last) < timedelta(minutes=30):
        return 0
    await db.kv_set('performance:last_attempt', now.isoformat())
    updated = attempted = 0
    posts = await db.recent_published(now - timedelta(days=7))
    for post in reversed(posts):
        if attempted >= 20:
            break
        published = post.published_at
        age = (now - published).total_seconds()/3600
        due = [h for h, end in HORIZONS.items() if h <= age <= end
               and not await db.kv_get(f'performance:{post.id}:{h}')]
        if not due:
            continue
        attempted += 1
        try:
            result = parse(await threads.post_stats(post.threads_id))
        except ThreadsError:
            await db.kv_set('performance:status', 'Статистика Zernio недоступна; это не нулевые реакции.')
            break
        if result is None:
            await db.kv_set('performance:status', 'Часть статистики ещё не получена; пропуски не равны нулю.')
            continue
        result.update(observed_at=now.isoformat(), age_hours=round(age, 3), source='zernio:threads')
        await db.kv_set(f'performance:{post.id}:latest', json.dumps(result))
        source_age = age
        if result.get('source_updated_at'):
            try:
                source_age = (stamp(result['source_updated_at'])-published).total_seconds()/3600
            except (ValueError, TypeError):
                source_age = -1
        for h in due:
            if h <= source_age <= HORIZONS[h]:
                await db.kv_set(f'performance:{post.id}:{h}', json.dumps(result))
        updated += 1
    await db.kv_set('performance:last_count', str(updated))
    return updated


async def comparable(db, since):
    rows = await db.engagement(since)
    result = []
    for row in rows:
        raw = await db.kv_get(f"performance:{row['id']}:24")
        if not raw:
            continue
        sample = json.loads(raw)
        if sample.get('likes') is None or sample.get('comments') is None:
            continue
        row = dict(row, likes=sample['likes'], comments=sample['comments'],
                   views=sample.get('views'), observed_at=sample['observed_at'],
                   metric_source=sample['source'])
        result.append(row)
    return result


async def report(db, now):
    posts = await db.recent_published(now-timedelta(days=7))
    lines = ['📊 Мониторинг постов: замеры через 1, 24 и 72 часа.',
             'Пропуск — данных нет. Комментарии — счётчик платформы, включая возможные ответы аккаунта.']
    for post in posts[:15]:
        raw = await db.kv_get(f'performance:{post.id}:latest')
        sample = json.loads(raw) if raw else {}
        metric = lambda k: str(sample[k]) if sample.get(k) is not None else 'нет данных'
        lines.append(f"#{post.id} · {post.rubric or 'без рубрики'} · {post.published_at:%d.%m %H:%M} UTC\n"
                     f"{post.text[:90]}\nЛайки {metric('likes')}; комментарии {metric('comments')}; "
                     f"просмотры {metric('views')} · возраст замера {sample.get('age_hours', '—')} ч")
    if not posts:
        lines.append('В локальной базе пока нет подтверждённых публикаций за неделю.')
    status = await db.kv_get('performance:status')
    if status:
        lines.append(status)
    return '\n\n'.join(lines)[:3900]
