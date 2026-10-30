"""Owner-authorized zero-reaction cleanup; unknown data always preserves a post."""
import json
import logging
from datetime import timedelta

from . import performance, reply_cooldown
from .threads_api import ThreadsError

# Слово владельца 29.10.2026: пост без лайков и комментариев через 6 ч — «мертвечина», снимаем (было 24 ч).
MIN_AGE = timedelta(hours=4 if __import__('zavod.lang', fromlist=['is_en']).is_en() else 6)  # EN: 4 ч (слово владельца 30.10.2026)
# Слово владельца 29.10.2026: «старые посты без лайков и комментариев — мертвечина, удали». Смотрим 60 дней назад,
# до 10 удалений в сутки, не чаще раза в 20 минут; аналитика Zernio по старым постам обновляется реже — свежесть 6 ч.
LOOKBACK = timedelta(days=60)
DAILY_CAP = 30  # 30.10: владелец просит убрать все пустые посты — быстрее разбираем накопленное
SCAN_EVERY = timedelta(minutes=10)
FRESH = timedelta(hours=6)

log = logging.getLogger(__name__)


def single_target(payload, account_id):
    post = payload.get('post', payload)
    if not isinstance(post, dict):
        return None
    platforms = post.get('platforms') or []
    if len(platforms) != 1 or any('thread' in k.lower() for k in post):
        return None
    target = platforms[0]
    account = target.get('accountId')
    ident = account.get('_id') if isinstance(account, dict) else account
    specific = target.get('platformSpecificData') or {}
    if target.get('platform') != 'threads' or ident != account_id:
        return None
    if not isinstance(specific, dict) or any('thread' in k.lower() for k in specific):
        return None
    return post, target


def fresh_zero(payload, now):
    if not isinstance(payload, dict) or payload.get('syncStatus') in ('pending', 'failed'):
        return False
    parts = payload.get('platformAnalytics') or []
    if len(parts) != 1 or parts[0].get('platform') != 'threads' or parts[0].get('syncStatus') != 'synced':
        return False
    metrics = parts[0].get('analytics') or {}
    if any(type(metrics.get(k)) not in (int, float) or metrics[k] != 0 for k in ('likes', 'comments')):
        return False
    try:
        age = now - performance.stamp(metrics['lastUpdated'])
    except (ValueError, TypeError, KeyError):
        return False
    return -timedelta(minutes=1) <= age <= FRESH


async def tick(db, client, now):
    """One candidate/hour, max three removal attempts/day; no LLM calls.

    Wait 24 hours for ordinary engagement. Back up before mutation. An unknown
    POST result is reconciled by GET, never retried blindly, even after restart.
    """
    if await reply_cooldown.blocked(db, now):
        return
    last = await db.kv_get('zero_cleanup:last_scan')
    if last and now - performance.stamp(last) < SCAN_EVERY:
        return
    day_key = 'zero_cleanup:day:' + now.date().isoformat()
    if int(await db.kv_get(day_key) or 0) >= DAILY_CAP:
        return
    posts = await db.recent_published(now-LOOKBACK)
    candidates = []
    for post in posts:
        scanned = await db.kv_get(f'zero_cleanup:checked:{post.id}') or ''
        candidates.append((scanned, post))
    for _, post in sorted(candidates, key=lambda row: row[0]):
        key = f'zero_cleanup:post:{post.id}'
        saved = json.loads(await db.kv_get(key) or '{}')
        if saved.get('status') == 'deleted_confirmed':
            await db.delete(post.id)
            continue
        if saved.get('status') == 'requires_review':
            continue
        reconcile = saved.get('status') in ('attempting', 'unknown')
        if not reconcile:
            if not post.published_at or now-post.published_at < MIN_AGE:
                continue
            sample = json.loads(await db.kv_get(f'performance:{post.id}:latest') or '{}')
            if sample.get('likes') != 0 or sample.get('comments') != 0:
                continue
        await db.kv_set('zero_cleanup:last_scan', now.isoformat())
        await db.kv_set(f'zero_cleanup:checked:{post.id}', now.isoformat())
        try:
            _, payload = await client._request('GET', f'/posts/{post.threads_id}')
            checked = single_target(payload, client.account_id)
            if checked is None:
                return
            remote, target = checked
            if reconcile:
                if target.get('status') == 'cancelled':
                    saved.update(status='deleted_confirmed', reconciled_at=now.isoformat())
                    await db.kv_set(key, json.dumps(saved, ensure_ascii=False))
                    await db.delete(post.id)
                else:
                    saved['status'] = 'requires_review'
                    await db.kv_set(key, json.dumps(saved, ensure_ascii=False))
                # Published is not proof that the previous POST failed; do not repeat.
                return
            if remote.get('status') != 'published' or target.get('status') != 'published':
                return
            metrics = await client.post_stats(post.threads_id)
            if not fresh_zero(metrics, now):
                return
            _, comments = await client._request('GET', f'/inbox/comments/{post.threads_id}',
                                               params={'accountId':client.account_id, 'limit':50})
            if not isinstance(comments.get('comments'), list) or comments['comments']:
                return
            if (comments.get('pagination') or {}).get('hasMore'):
                return
            saved = {'status':'attempting', 'id':post.id, 'remote_id':post.threads_id,
                     'account_id':client.account_id, 'text':remote.get('content'),
                     'local_text':post.text, 'rubric':post.rubric,
                     'url':target.get('platformPostUrl'), 'published_at':post.published_at.isoformat(),
                     'metrics':metrics['platformAnalytics'][0]['analytics'], 'checked_at':now.isoformat()}
            await db.kv_set(key, json.dumps(saved, ensure_ascii=False))
            # An atomic fence makes a repeat POST impossible across worker restarts.
            if not await db.claim_slot(f'zero_cleanup:unpublish:{post.threads_id}'):
                return
            await db.kv_set(day_key, str(int(await db.kv_get(day_key) or 0)+1))
            await client.unpublish(post.threads_id)
            _, payload = await client._request('GET', f'/posts/{post.threads_id}')
            checked = single_target(payload, client.account_id)
            confirmed = checked is not None and checked[1].get('status') == 'cancelled'
            saved['status'] = 'deleted_confirmed' if confirmed else 'unknown'
            await db.kv_set(key, json.dumps(saved, ensure_ascii=False))
            if confirmed:
                await db.delete(post.id)
                log.info('Zero-reaction removal confirmed local_post=%s', post.id)
            return
        except ThreadsError as error:
            if saved.get('status') == 'attempting':
                saved['status'] = 'unknown'
                await db.kv_set(key, json.dumps(saved, ensure_ascii=False))
            await reply_cooldown.defer(db, error, now)
            log.warning('Zero cleanup paused: HTTP %s', error.http_status)
            return


async def report(db, now):
    attempts = int(await db.kv_get('zero_cleanup:day:'+now.date().isoformat()) or 0)
    rows = await db._rows("SELECT key, value FROM kv WHERE key LIKE ? ORDER BY key DESC LIMIT 50",
                          ('zero_cleanup:post:%',))
    lines = [f'🧹 Очистка: попыток удаления сегодня {attempts}/3.',
             'Пост старше суток; только свежие подтверждённые нули и отсутствие комментариев.',
             'Архивы последних по ключу 50 записей; неизвестный исход повторно не удаляем.']
    labels = {'deleted_confirmed':'удаление подтверждено', 'unknown':'исход неизвестен, ждёт сверки',
              'attempting':'попытка начата', 'requires_review':'не подтверждено; повтор выключен'}
    for row in rows[:12]:
        entry = json.loads(row['value'])
        lines.append(f"#{entry['id']}: {labels.get(entry.get('status'),'нет результата')}.")
    return '\n'.join(lines)
