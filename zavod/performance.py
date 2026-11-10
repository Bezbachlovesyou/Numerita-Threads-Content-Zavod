"""Platform observations; missing data stays missing, comparisons use 24–26h samples."""
import json
import math
from datetime import date, datetime, timedelta, timezone

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
        from .optimizer import short_name
        lines.append(f"#{post.id} · {short_name(post.rubric)} · {post.published_at:%d.%m %H:%M} UTC\n"
                     f"{post.text[:90]}\nЛайки {metric('likes')}; комментарии {metric('comments')}; "
                     f"просмотры {metric('views')} · возраст замера {sample.get('age_hours', '—')} ч")
    if not posts:
        lines.append('В локальной базе пока нет подтверждённых публикаций за неделю.')
    status = await db.kv_get('performance:status')
    if status:
        lines.append(status)
    ab = await grid_ab(db, posts)
    if ab:
        lines.insert(2, ab)
    return '\n\n'.join(lines)[:3900]


async def grid_ab(db, posts):
    """Живая матрица против картинки (проба 28.10.2026): средние лайки и комментарии по последнему замеру."""
    groups = {True: [], False: []}
    for post in posts:
        if post.rubric != 'grid' or not post.card:
            continue
        try:
            anim = json.loads(post.card).get('anim')
        except ValueError:
            continue
        raw = await db.kv_get(f'performance:{post.id}:latest')
        sample = json.loads(raw) if raw else {}
        if anim is None or sample.get('likes') is None:
            continue
        groups[bool(anim)].append((sample.get('likes') or 0, sample.get('comments') or 0))
    if not groups[True] and not groups[False]:
        return ''
    def avg(rows, k):
        return f"{sum(r[k] for r in rows) / len(rows):.1f}" if rows else '—'
    return ("🎬 Матрица: видео с музыкой — постов {}, лайков {}, комментариев {} в среднем; "
            "картинка — постов {}, лайков {}, комментариев {}.").format(
        len(groups[True]), avg(groups[True], 0), avg(groups[True], 1),
        len(groups[False]), avg(groups[False], 0), avg(groups[False], 1))


def _find_followers(obj, depth=0, account_id=None):
    """Число подписчиков ЭТОГО аккаунта из ответа аналитики Zernio (формат не закреплён: не угадываем).
    Если в словаре указан accountId и он чужой, пропускаем (EN не должен получить число RU); поля «прирост» пропускаем."""
    if depth > 4:
        return None
    if isinstance(obj, dict):
        acc = obj.get('accountId') or obj.get('account_id')
        if acc and account_id and str(acc) != str(account_id):
            return None
        for k, v in obj.items():
            name = str(k).lower().replace('_', '')
            if 'follower' in name and not any(w in name for w in ('gain', 'growth', 'new', 'change', 'lost', 'delta')) and number(v) is not None:
                return number(v)
        for v in obj.values():
            got = _find_followers(v, depth + 1, account_id)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _find_followers(v, depth + 1, account_id)
            if got is not None:
                return got
    return None


async def daily_summary(db, client, now):
    """Ежедневная сводка (слово владельца 02.11.2026), коротко (04.11.2026: «много информации, глаза устают»): подписчики и посты без реакции в трёх строках."""
    from . import zero_cleanup
    from .optimizer import short_name
    followers = None
    try:
        followers = _find_followers(await client.account_stats(limit=1), account_id=getattr(client, 'account_id', None))
    except Exception:
        followers = None
    today = now.date().isoformat()
    if followers is None:
        head = 'Подписчики: Zernio не отдал число — пришлите скриншот профиля, посчитаю по нему.'
    else:
        prev = await db.kv_get(f'followers:{(now.date() - timedelta(days=1)).isoformat()}')
        if prev and prev.isdigit() and abs(followers - int(prev)) > max(20, int(prev) * 0.3):
            head = (f'Подписчики: площадка отдала {followers}, вчера было {prev}. Скачок слишком большой, '
                    'не верю и не записываю: пришлите скриншот профиля, сверю.')
        else:
            await db.kv_set(f'followers:{today}', str(followers))
            parts = [f'Подписчики сейчас: {followers}']
            for days, name in ((1, 'вчера'), (7, '7 дней назад')):
                old = await db.kv_get(f'followers:{(now.date() - timedelta(days=days)).isoformat()}')
                if old and old.isdigit():
                    parts.append(f'{name} было {int(old)} (разница {followers - int(old):+d})')
            head = parts[0] + (' · ' + '; '.join(parts[1:]) if len(parts) > 1 else ' (сравнить пока не с чем: счёт начат сегодня)')
    if followers is not None:
        # слово владельца 10.11.2026: Zernio застрял на 105 (в Threads уже 127) — устаревшее число нельзя выдавать за факт
        same = 0
        for back in range(1, 6):
            old = await db.kv_get(f'followers:{(now.date() - timedelta(days=back)).isoformat()}')
            if old and old.isdigit() and int(old) == followers:
                same += 1
            else:
                break
        head += (f' (источник: Zernio; число не меняется уже {same + 1} дн., скорее всего устарело; реальное смотрите в профиле Threads или пришлите мне скриншот)'
                 if same >= 2 else ' (источник: Zernio, число может отставать от Threads на сутки и больше)')
    manual = (await db.kv_get('followers:manual') or '').split('|')  # слово владельца 09.11.2026: бот показал 105, в Threads было 110 — истина только то, что видит владелец
    if len(manual) == 2 and manual[0].isdigit() and (now.date() - date.fromisoformat(manual[1])).days <= 7:
        zernio = f'; Zernio показывает {followers}, разница {int(manual[0]) - followers:+d}' if followers is not None else ''
        head = f'Подписчики по вашему замеру {date.fromisoformat(manual[1]):%d.%m}: {manual[0]}{zernio}'
    posts = await db.recent_published(now - timedelta(days=7))
    zero, nodata, young, total = [], 0, 0, 0
    for post in posts:
        total += 1
        if not post.published_at or now - post.published_at < zero_cleanup.MIN_AGE:
            young += 1
            continue
        sample = json.loads(await db.kv_get(f'performance:{post.id}:latest') or '{}')
        if sample.get('likes') is None or sample.get('comments') is None:
            nodata += 1
        elif sample['likes'] <= zero_cleanup.MAX_LIKES and sample['comments'] == 0:
            zero.append(post)
    removed = 0
    for i in range(7):
        removed += int(await db.kv_get('zero_cleanup:day:' + (now.date() - timedelta(days=i)).isoformat()) or 0)
    mature = total - young
    share = f' ({100 * len(zero) // max(1, mature)}% от {mature})' if mature else ''
    line = (f'Посты за 7 дней: вышло {total}. Из тех, что старше суток ({mature}): без лайков и комментариев {len(zero)}{share}. '
            f'Нашей уборкой удалено пустых за 7 дней: {removed}.')
    if nodata:
        line += f' Нет данных от площадки: {nodata} (не считаю их пустыми).'
    out = ['📈 ' + head, line]
    if zero:
        by = {}
        for post in zero:
            by[short_name(post.rubric)] = by.get(short_name(post.rubric), 0) + 1
        out.append('Чаще пустые: ' + ', '.join(f'{k} ({v})' for k, v in sorted(by.items(), key=lambda kv: -kv[1])[:3]))
    try:
        from .costs import vibe_ab
        vibe = await vibe_ab(db, now)
        if vibe:
            out.append('Стиль ответов за 7 дней: ' + '; '.join(x.lstrip('• ') for x in vibe))
    except Exception:
        pass
    return '\n'.join(out)
