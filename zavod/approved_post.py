"""Owner-approved one-off. Never replaces art with a generated card or retries an ambiguous POST."""
import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path

from .threads_api import ThreadsError
from .performance import stamp

KEY = 'approved:six-love:v1'
TEXT = 'Узнаёте себя? 🤍\n\nШестёрки, откликнитесь — сделаю разбор.'
ASSET = Path(__file__).resolve().parent.parent / 'assets' / 'approved-six-love.png'


async def tick(db, threads, now, notify):
    """True blocks random autopost until the approved one-off has a confirmed outcome."""
    # This repository also has unrelated Railway deployments; never run the owner's job there.
    project = os.getenv('RAILWAY_PROJECT_ID')
    service = os.getenv('RAILWAY_SERVICE_ID')
    if project and project != 'aae9ee4d-e392-46a9-892a-f656adc80955':
        return False
    if service and service != '16642ca8-b73e-4685-aeaa-37f4cdc422b6':
        return False
    raw = await db.kv_get(KEY)
    state = json.loads(raw) if raw else {}
    if state.get('done'):
        return False
    if threads is None:
        return True
    if state.get('next') and now < stamp(state['next']):
        return True
    state['next'] = (now+timedelta(minutes=5)).isoformat()
    await db.kv_set(KEY, json.dumps(state))
    async def note(code, text):
        if await db.claim_slot(KEY+':notice:'+code):
            await notify(text)
    # Existing durable post id lets a restarted worker only poll the outcome.
    if state.get('remote'):
        _, payload = await threads._request('GET', '/posts/'+state['remote'])
        remote = payload.get('post') or payload
        targets = [p for p in remote.get('platforms', []) if p.get('platform') == 'threads']
        target = next((p for p in targets if p.get('status') == 'published'), None)
        if target:
            await db.set_threads_id(state['local'], state['remote'])
            await db.mark_published(state['local'])
            state['done'] = True
            state['url'] = target.get('platformPostUrl')
            await db.kv_set(KEY, json.dumps(state))
            await note('done', '✅ Согласованный стакан опубликован в Threads.\n'+
                       (state['url'] or 'Zernio подтвердил статус published; публичная ссылка не получена.'))
            return False
        if remote.get('status') in ('failed', 'partial') or any(p.get('status') == 'failed' for p in targets):
            await note('failed', '⚠️ Согласованный стакан не получил подтверждения публикации в Threads. '
                       'Повтор автоматически не отправляю; нужно проверить отказ Zernio.')
        return True
    if state.get('attempted'):
        # Check before retrying: an interrupted response may have created the post.
        found = await threads.find_post(TEXT, now-timedelta(days=30))
        if found:
            state['remote'] = found
            await db.kv_set(KEY, json.dumps(state))
        else:
            await note('unknown', '⚠️ Результат отправки стакана не установлен. '
                       'Автоматический повтор остановлен, чтобы не создать дубль. Нужна сверка в Zernio.')
        return True
    # Preserve existing pacing/cap even for a priority publication.
    if len(await db.recent_published(now-timedelta(days=1))) >= 20:
        return True
    last = await db.last_published_at()
    if last and now-last < timedelta(hours=1):
        return True
    if not state.get('local'):
        # Exact local match recovers a crash between inserting the draft and saving state.
        rows = await db._rows('SELECT id FROM posts WHERE topic = ? ORDER BY id LIMIT 1', (KEY,))
        state['local'] = rows[0]['id'] if rows else await db.add_draft(KEY, TEXT, 'approved_six_love')
        await db.kv_set(KEY, json.dumps(state))
    if not state.get('image'):
        try:
            data = ASSET.read_bytes()
        except OSError as e:
            raise ThreadsError('Утверждённая картинка стакана недоступна; публикация без неё запрещена.') from e
        state['image'] = await threads.upload_image(data, 'numerita-six-love-approved.png', 'image/png')
        state['sha256'] = hashlib.sha256(data).hexdigest()
        await db.set_image(state['local'], state['image'])
        await db.kv_set(KEY, json.dumps(state))
    # Search existing posts before first submission as well.
    found = await threads.find_post(TEXT, now-timedelta(days=30))
    if found:
        state['remote'] = found
        await db.kv_set(KEY, json.dumps(state))
        return True
    # Durable single-flight fence, shared across workers, before the non-idempotent network operation.
    if not await db.claim_slot(KEY+':submit'):
        state['attempted'] = True
        await db.kv_set(KEY, json.dumps(state))
        return True
    state['attempted'] = True
    await db.kv_set(KEY, json.dumps(state))
    remote = await threads.publish_text(TEXT, image_urls=[state['image']])
    if remote:
        state['remote'] = remote
        await db.kv_set(KEY, json.dumps(state))
        await note('accepted', '🕒 Стакан отправлен в Zernio с утверждённой картинкой. '
                   'Жду подтверждения публикации и ссылки Threads.')
    return True
