"""Owner-requested durable backlog audit. Sending remains in normal autoreply limits.

No report of completion on API errors, truncated pagination or missing account state.
The final receipt covers comments observed in the named sweep; new arrivals keep using
normal autoreplies. Historical link counts count confirmed local sends, not profile hints.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from . import lang, reply_cooldown
from .dialogue import walk_comments

KEY = 'owner:reply_closure:v1'
URL = re.compile(r'(?:https?://)?(?:www\.)?t\.me/numeritabot(?=[/?#\s.,!;:)]|$)[^\s<>]*|tg://resolve\?domain=numeritabot(?:&[^\s<>]*)?', re.I)
MENTION = re.compile(r'(?<!\w)@numeritabot\b', re.I)
BIO = re.compile(r'шапк|ссылк.{0,30}профил|link.{0,30}(?:bio|profile)', re.I)

def count_links(rows):
    urls = [URL.findall(r['reply'] or '') for r in rows]
    return {'confirmed_answers': len(rows), 'answers_with_url': sum(bool(x) for x in urls),
            'url_occurrences': sum(map(len, urls)),
            'mentions_without_url': sum(bool(MENTION.search(r['reply'] or '')) and not u for r,u in zip(rows,urls)),
            'profile_hints': sum(bool(BIO.search(r['reply'] or '')) for r in rows)}

async def load(db):
    return json.loads(await db.kv_get(KEY) or '{}')

async def save(db, state):
    await db.kv_set(KEY, json.dumps(state, ensure_ascii=False))

async def extra_targets(db):
    state = await load(db)
    if not os.getenv('COMMENTS_CLOSURE_JOB') or state.get('job') != os.getenv('COMMENTS_CLOSURE_JOB'):
        return []
    return [tuple(t) for t in state.get('targets', [])] if state and not state.get('complete') else []

async def notify_once(db, state, bot, cfg, text):
    if state.get('notice'):
        return
    # Reserve before Telegram: ambiguous network failures are not blindly repeated.
    state['notice'] = 'reserved'
    await save(db,state)
    recipients=cfg.admin_ids
    if os.getenv('COMMENTS_CLOSURE_REPORT_CHAT_ID'):
        recipient=int(os.environ['COMMENTS_CLOSURE_REPORT_CHAT_ID'])
        if recipient not in cfg.admin_ids:
            raise ValueError('Report recipient is not an administrator')
        recipients={recipient}
    elif len(recipients) != 1:
        raise ValueError('One explicit report recipient required')
    receipts=[]
    for recipient in sorted(recipients):
        message=await bot.send_message(recipient,text)
        receipts.append({'recipient':recipient,'message_id':message.message_id})
    state['notice']='sent'; state['receipts']=receipts
    await save(db,state)

async def combined_report(db, state, bot, cfg, mirror):
    if lang.is_en() or not state.get('complete') or state.get('notice'):
        return
    # Production shares the database across public and en schemas. Read only.
    if not getattr(db,'pool',None):
        return
    raw=await db.pool.fetchval("SELECT value FROM en.kv WHERE key=$1",KEY)
    other=json.loads(raw or '{}')
    if other.get('job') != state['job'] or not other.get('complete'):
        return
    lines=['✅ Threads: обход завершён, ожидающих ответа комментариев в проверенных ветках нет.']
    for label,s in [('RU @numerita.ai',state),('EN @numerita.love',other)]:
        lines.append(f"{label}: проверено {len(s['targets'])} постов; новых ответов за выполнение — {s['sent_during_job']}; пропусков — {s['skipped_during_job']}.")
    a,b=state['links72h'],other['links72h']
    lines.append(f"За 72 часа перед началом задания: {a['url_occurrences']+b['url_occurrences']} прямых ссылок на Telegram в {a['answers_with_url']+b['answers_with_url']} ответах (RU {a['url_occurrences']}, EN {b['url_occurrences']}).")
    lines.append(f"Отдельно: упоминаний @Numeritabot без URL — {a['mentions_without_url']+b['mentions_without_url']}; приглашений через профиль — {a['profile_hints']+b['profile_hints']}.")
    lines.append('Ссылки — по журналу подтверждённых отправок; пропуски (например, спам/эмодзи) не считаются ответами. Новые поступления обрабатываются дальше.')
    await notify_once(db,state,bot,cfg,'\n'.join(lines))
    await mirror('Завершение очереди комментариев: отчёт отправлен; '+json.dumps({'job':state['job'],'receipts':state['receipts']}))

async def tick(db, threads, bot, cfg, mirror):
    job=os.getenv('COMMENTS_CLOSURE_JOB','').strip()
    if not job or threads is None:
        return
    now=datetime.now(timezone.utc)
    state=await load(db)
    if state.get('job') != job:
        start=now.isoformat()
        rows=await db._rows("SELECT reply FROM comment_replies WHERE status='replied' AND created_at>=? AND created_at<?",((now-timedelta(hours=72)).isoformat(),start))
        state={'job':job,'started':start,'links72h':count_links(rows),'targets':[], 'observed':{},'complete':False}
        await save(db,state)
        await mirror('Ссылки за 72 часа '+('en' if lang.is_en() else 'ru')+': '+json.dumps({'from':(now-timedelta(hours=72)).isoformat(),'to':start,**state['links72h']}))
    if state.get('complete'):
        await combined_report(db,state,bot,cfg,mirror)
        return
    if now.timestamp() < state.get('next',0) or await reply_cooldown.blocked(db,now):
        return
    state['next']=now.timestamp()+180
    await save(db,state)
    try:
        if not state.get('discovered'):
            rows=await db._rows("SELECT id,threads_id,text FROM posts WHERE status='published' AND threads_id IS NOT NULL AND threads_id!='published'")
            targets={r['threads_id']:[r['threads_id'],r['id'],r['text']] for r in rows}
            # Includes posts published before database integration, not just the last 3 days.
            for item in await threads.commented_posts(datetime(1970,1,1,tzinfo=timezone.utc),all_pages=True):
                if item.get('id'):
                    content=item.get('content') or ''
                    # API may name the same post by its platform id rather than provider id.
                    if content and any(content==t[2] for t in targets.values()):
                        continue
                    targets.setdefault(item['id'],[item['id'],None,content])
            state['targets']=list(targets.values()); state['discovered']=now.isoformat()
        from .autoreply import reply_candidates
        pending=[t for t in state['targets'] if state['observed'].get(t[0],{}).get('pending',1)>0]
        if pending:
            target=min(pending,key=lambda t:state['observed'].get(t[0],{}).get('at',''))
            comments=await threads.comments(target[0])
            candidates=[item['id'] for item,_ in reply_candidates(comments)]
            handled=await db.handled_comments(candidates)
            unreplyable=sum(bool(item.get('message')) and not (item.get('from') or {}).get('isOwner') and item.get('canReply') is False for item,_,_ in walk_comments(comments))
            state['observed'][target[0]]={'at':now.isoformat(),'pending':len(set(candidates)-handled)+unreplyable,'unreplyable':unreplyable}
        unknown=[t for t in state['targets'] if t[0] not in state['observed']]
        waiting=sum(v['pending'] for v in state['observed'].values())
        state['pending']=waiting;state['unchecked']=len(unknown);state.pop('error',None)
        if not unknown and not waiting:
            state['complete']=now.isoformat()
            totals=await db._rows("SELECT status,COUNT(*) AS n FROM comment_replies WHERE created_at>=? GROUP BY status",(state['started'],))
            counts={r['status']:r['n'] for r in totals}
            state['sent_during_job']=counts.get('replied',0);state['skipped_during_job']=counts.get('skipped',0)
        await save(db,state)
        await mirror('Очередь комментариев '+('en' if lang.is_en() else 'ru')+': '+json.dumps({k:state.get(k) for k in ('job','complete','pending','unchecked','error')}))
        await combined_report(db,state,bot,cfg,mirror)
    except Exception as exc:
        from .threads_api import ThreadsError
        if isinstance(exc,ThreadsError):
            await reply_cooldown.defer(db,exc,now)
        state['error']=type(exc).__name__+': '+str(exc)[:200]
        await save(db,state)
        await mirror('Проверка очереди не завершена: '+state['error'])
