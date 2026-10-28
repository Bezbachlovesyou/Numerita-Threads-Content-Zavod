"""Обход по теории ограничений Голдратта — три раза в день (уточнение владельца).

Бот смотрит на всю цепочку: посты → комментарии → наши ответы → переход в @Numeritabot → оплата, и на расходы.
Нейросеть по пяти шагам Голдратта находит одно узкое звено и предлагает, как его «расшить». Обратимое бот
внедряет сам на 12 часов (фокус для постов и ответов — через подсказку нейросети, без правки кода);
необратимое и рискованное — только вопрос владельцу с пометкой ‼️.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from . import funnel
from .generator import GenerationError, Generator
from .storage import Storage

log = logging.getLogger(__name__)

RUN_HOURS = (11, 15, 19)  # по часовому поясу бота; каждый обход — по всем теориям (Голдратт, рост, ТРИЗ)
GROWTH_HOUR = 15
DIGEST_HOUR = 19  # владельцу — одна сводка дня; сразу пишем только с ‼️ (слово владельца 25.10.2026)
FOCUS_HOURS = 12
SUMMARY = """📘 Теория ограничений Голдратта — коротко

Суть: у любой системы есть одно самое узкое звено. Вся система производит ровно столько, сколько пропускает
оно. Улучшать что-то кроме него — тратить силы зря: цепь прочна настолько, насколько прочно слабейшее звено.

Пять шагов:
1. Найти ограничение — где всё застревает.
2. Выжать из него максимум без затрат: убрать потери именно там.
3. Подчинить ему всё остальное: остальные звенья работают в его темпе, не заваливают его лишним.
4. Расширить ограничение: вложиться, если первые шаги исчерпаны.
5. Не дать инерции стать ограничением: звено расшито — ищем новое, и так по кругу.

Ещё из Голдратта: считаем пропускную способность (деньги и люди, пришедшие наружу), а не загрузку;
«барабан — буфер — верёвка»: темп задаёт узкое звено, перед ним буфер, вход ограничен его темпом;
мыслительные процессы — дерево текущей реальности (корень проблем), «грозовая туча» (разрешение конфликта).

Как это у нас: три раза в день, в 11:00, 15:00 и 19:00, я прохожу цепочку «пост → комментарий → ответ → бот →
оплата» и расходы, называю одно узкое звено и сразу включаю обратимое улучшение на 12 часов. Необратимое —
только с твоего слова, с пометкой ‼️."""

SYSTEM = """Ты — операционный директор Нумериты в Threads и мыслишь по теории ограничений Голдратта
(пять шагов фокусировки, пропускная способность вместо загрузки, барабан — буфер — верёвка).
Цепочка: посты → комментарии → наши ответы → переход в Telegram-бота @Numeritabot → оплата. Плюс расходы на нейросеть.
Основа Нумериты — саттвическое даяние: польза человеку, любовь, радость, юмор, литературный стиль, ничего лишнего,
максимум ценности на единицу времени человека. Закон «всегда в плюсе»: расходы не растут быстрее пользы.
Правила Threads неприкосновенны: не больше 20 постов в сутки, ответы личные, ссылки только по правилам, без спама.
Смотри шире одного звена: расходы и все наши действия, путь клиента (CJM) целиком — расширение первичных контактов
(охват, комментарии, шапка профиля, ответы со ссылкой) и превращение их в «вау», возврат и оплату.
Владельца беспокоим (ask_owner) ТОЛЬКО ради новых трат или необратимых решений, которые сильно меняют проект; всё
остальное улучшаем сами обратимыми мерами.
По данным найди ОДНО узкое звено и предложи, как его расшить. Обратимые меры — это только две подсказки
на 12 часов: как писать посты (post_focus) и как отвечать на комментарии (reply_focus). Всё, что нельзя
откатить или что тратит деньги, меняет правила, лимиты, цены, публичные обещания, — только вопрос владельцу (ask_owner).
Неизменные правила (подсказки их не меняют, не предлагай их нарушить): ответы пишет дешёвая модель, сильную для ответов
не используем; «+», «спасибо» и смайлики, а также согласие без вопроса — без ответа по коду (это экономия, не потеря людей);
потолок расходов на ответы в сутки; ссылки в ответах — в лимитах. Пропуски по этим причинам — норма, а не узкое звено.
Ответ — строго JSON без пояснений:
{"bottleneck": "звено одной фразой", "why": "почему по цифрам", "step": "какой из пяти шагов и что делаем",
 "post_focus": "конкретная подсказка для постов или пусто", "reply_focus": "подсказка для ответов или пусто",
 "ask_owner": "необратимое предложение одной фразой или пусто"}"""


async def metrics(db: Storage, now: datetime, tz) -> str:
    def iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat()

    lines = []
    for label, start, end in (("последние 24 часа", now - timedelta(days=1), now),
                              ("сутки до этого", now - timedelta(days=2), now - timedelta(days=1))):
        posts = await db._rows("SELECT COUNT(*) AS n FROM posts WHERE status='published' AND published_at >= ? "
                               "AND published_at < ?", (iso(start), iso(end)))
        rep = await db._rows("SELECT status, COUNT(*) AS n FROM comment_replies WHERE created_at >= ? AND created_at < ? "
                             "GROUP BY status", (iso(start), iso(end)))
        heard = await db._rows("SELECT COUNT(*) AS n, COUNT(DISTINCT author) AS people FROM dialogue_messages "
                               "WHERE role='user' AND created_at >= ? AND created_at < ?", (iso(start), iso(end)))
        by = {r["status"]: int(r["n"]) for r in rep}
        why = await db._rows("SELECT reply, COUNT(*) AS n FROM comment_replies WHERE status='skipped' AND created_at >= ? "
                             "AND created_at < ? GROUP BY reply", (iso(start), iso(end)))
        names = {"skip:noise": "«+», «спасибо», смайлики", "skip:dialog": "согласие или 3-я реплика без вопроса",
                 "skip:model": "спам/грубость/бессмыслица", "skip:gone": "удалённые", "skip:paywall": "сверх бесплатных ответов за сутки"}
        skipped_why = ", ".join(f"{names.get(r['reply'], 'прочее')} {r['n']}" for r in why)
        n_posts = int(posts[0]["n"])
        comments = int(heard[0]["n"])
        lines.append(f"{label}: постов {n_posts}, комментариев людей {comments} от {heard[0]['people']} человек "
                     f"({comments / n_posts if n_posts else 0:.1f} на пост), наших ответов {by.get('replied', 0)}, "
                     f"пропущено {by.get('skipped', 0)}" + (f" (из них {skipped_why})" if skipped_why else ""))
    top = await db._rows(
        "SELECT p.rubric, COUNT(c.comment_id) AS n FROM posts p LEFT JOIN comment_replies c ON c.post_id = p.id "
        "WHERE p.status='published' AND p.published_at >= ? GROUP BY p.rubric ORDER BY n DESC",
        (iso(now - timedelta(days=3)),))
    lines.append("комментарии по рубрикам за 3 дня: " + ", ".join(f"{r['rubric']} {r['n']}" for r in top))
    links = await db._rows("SELECT COUNT(*) AS n FROM comment_replies WHERE reply LIKE ? AND created_at >= ?",
                           ("%t.me/%", iso(now - timedelta(days=1))))
    lines.append(f"ответов со ссылкой на бота за сутки: {links[0]['n']}")
    for day in (now, now - timedelta(days=1)):
        ledger = json.loads(await db.kv_get(f"cost:{day.astimezone(tz).date().isoformat()}") or "{}")
        if ledger:
            spent = ", ".join(f"{k} ${v[1]:.2f} ({v[0]} запр.)" for k, v in ledger.items())
            lines.append(f"расходы {day.astimezone(tz):%d.%m}: {spent}")
    lines += funnel.lines(await funnel.fetch(7))
    return "\n".join(lines)


def parse(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        return json.loads(match.group(0)) if match else {}
    except ValueError:
        return {}


async def focus(db: Storage, key: str) -> str:
    """Действующая подсказка обхода (пусто, если срок вышел)."""
    raw = json.loads(await db.kv_get(key) or "{}")
    until = raw.get("until")
    if not until or datetime.now(timezone.utc) >= datetime.fromisoformat(until):
        return ""
    return raw.get("text", "")


GROWTH = """Это дневной обход по всем нашим теориям роста (слово владельца 25.10.2026), а не только по Голдратту.
Сверь данные с каждой линзой и выбери ОДНУ самую сильную меру:
- Бережливый стартап (Рис, Мауря): какая наша главная догадка сейчас и какая цифра её проверит; не строим лишнего.
- Воронка AARRR (Макклюр): привлечение → активация («вау») → удержание → рекомендации → доход; где теряем больше всего.
- Кристенсен (работа, которую нанимают) и Хормози (ценность = результат × вера ÷ время и усилия): ясно ли обещание.
- Эллис (40% «очень расстроятся») и Грэм (делай немасштабируемое для первых людей).
- ИИ-скорость: ясные проверяемые задачи — агенту, вкус и необратимое — человеку; расходы на ИИ окупаются.
- Психология вовлечения: крючок первой строки, эмоция высокой активации, узнавание, лёгкий ответ за 3 секунды.
- ТРИЗ (Альтшуллер): найди противоречие «улучшаем А — страдает Б» и разреши без компромисса — разделением во времени,
  месте или по условию; идеальный конечный результат — польза есть, затрат нет, ресурсы уже рядом и простаивают.
Формат ответа тот же JSON; в "step" назови линзу и меру."""


async def review(db: Storage, generator: Generator, now: datetime, tz, growth: bool = True) -> str | None:
    data = await metrics(db, now, tz)
    try:
        system = SYSTEM + ("\n\n" + GROWTH if growth else "")
        raw = await generator.improve(system, f"Данные:\n{data}", max_tokens=900, kind="toc")
    except GenerationError as e:
        log.warning("Обход по Голдратту не удался: %s", e)
        return None
    plan = parse(raw)
    if not plan.get("bottleneck"):
        return None
    until = (now + timedelta(hours=FOCUS_HOURS)).astimezone(timezone.utc).isoformat()
    applied = []
    for key, field, label in (("post_focus", "post_focus", "посты"), ("reply_focus", "reply_focus", "ответы")):
        text = (plan.get(field) or "").strip()[:500]
        if text:
            await db.kv_set(key, json.dumps({"text": text, "until": until}, ensure_ascii=False))
            applied.append(f"• {label}: {text}")
    title = "🔭 Обход: Голдратт, теории роста и ТРИЗ"
    lines = [f"{title}, {now:%d.%m %H:%M}", "",
             f"Узкое звено: {plan['bottleneck']}", f"Почему: {plan.get('why', '')}", f"Шаг: {plan.get('step', '')}"]
    if applied:
        lines += ["", f"Включила на {FOCUS_HOURS} часов (откатится само):"] + applied
    ask = (plan.get("ask_owner") or "").strip()
    if ask:
        lines += ["", f"‼️ Нужно твоё слово: {ask}"]
    return "\n".join(lines)


async def remember(db: Storage, now: datetime, text: str) -> None:
    """Обход за день — в копилку для вечерней сводки."""
    key = f"toc_log:{now.date().isoformat()}"
    log_ = json.loads(await db.kv_get(key) or "[]")
    await db.kv_set(key, json.dumps(log_ + [text], ensure_ascii=False))


async def digest(db: Storage, now: datetime) -> str | None:
    """Вечерняя сводка всех обходов дня: узкие звенья и что включено — коротко."""
    log_ = json.loads(await db.kv_get(f"toc_log:{now.date().isoformat()}") or "[]")
    if not log_:
        return None
    parts = []
    for text in log_:
        head = text.splitlines()[0].split(", ")[-1]
        keep = [ln for ln in text.splitlines() if ln.startswith(("Узкое звено", "Шаг", "•"))]
        parts.append(f"⏱ {head}\n" + "\n".join(keep))
    return f"📒 Сводка обходов за {now:%d.%m} — что я нашла и включила сама\n\n" + "\n\n".join(parts)


async def run_due(db: Storage, generator: Generator, now: datetime, tz) -> list[str]:
    """Run each scheduled review with durable receipts and at most three attempts.

    Only the existing two-hour windows are used. Restarting never generates a
    burst of missed reviews. A consumed attempt is not a successful review.
    """
    now = now.astimezone(tz)
    notices = []
    for hour in RUN_HOURS:
        if not hour <= now.hour < hour + 2:
            continue
        key = f'toc_run:{now.date().isoformat()}:{hour}'
        state = json.loads(await db.kv_get(key) or '{}')
        if state.get('status') == 'success' or state.get('attempts', 0) >= 3:
            continue
        if state.get('attempted_at') and now - datetime.fromisoformat(state['attempted_at']) < timedelta(minutes=15):
            continue
        attempt = state.get('attempts', 0) + 1
        if not await db.claim_slot(f'{key}:attempt:{attempt}'):
            # A prior process may have stopped after claiming. Recover after a
            # bounded lease instead of reclaiming a possibly live attempt.
            await db.kv_set(key, json.dumps({'status':'interrupted', 'attempts':attempt,
                                           'attempted_at':now.isoformat()}))
            continue
        state = {'status':'running', 'attempts':attempt, 'attempted_at':now.isoformat()}
        await db.kv_set(key, json.dumps(state))
        try:
            text = await review(db, generator, now, tz)
            if not text:
                raise ValueError('No valid review returned')
            await remember(db, now, text)
            state.update(status='success', completed_at=datetime.now(tz).isoformat(), result=text)
            if '‼️' in text:
                notices.append(text)
        except Exception as error:
            state.update(status='failed', error_type=type(error).__name__)
            log.warning('Review slot %s attempt %s failed (%s)', key, attempt, type(error).__name__)
            if attempt == 3:
                notices.append(f'⚠️ Обход {now:%d.%m} {hour}:00 не завершён после трёх попыток. '
                               'В журнале сохранён сбой; успешным этот обход не считается.')
        await db.kv_set(key, json.dumps(state, ensure_ascii=False))
        log.info('Review receipt %s status=%s attempts=%s', key, state['status'], attempt)
    if now.hour >= DIGEST_HOUR:
        summary = await digest(db, now)
        if summary and await db.claim_slot(f'toc_digest:{now.date().isoformat()}'):
            notices.append(summary)
    return notices


async def report(db: Storage, now: datetime) -> str:
    lines = [f'📋 Обходы за {now:%d.%m}: фактические квитанции, не только расписание.']
    for hour in RUN_HOURS:
        state = json.loads(await db.kv_get(f'toc_run:{now.date().isoformat()}:{hour}') or '{}')
        label = {'success':'выполнен', 'running':'попытка начата', 'failed':'сбой',
                 'interrupted':'предыдущая попытка прервана'}.get(state.get('status'), 'квитанции пока нет')
        lines.append(f'{hour}:00 — {label}; попыток {state.get("attempts",0)}.')
        if state.get('completed_at'):
            lines.append('Завершение: ' + state['completed_at'])
    lines.append('Время — часовой пояс бота; до выпуска журнала старые обходы здесь не подтверждаются.')
    return '\n'.join(lines)
