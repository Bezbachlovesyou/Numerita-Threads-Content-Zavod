"""Автоответы на комментарии под нашими постами в Threads.

Половина постов зовёт ответить числом дня рождения — бот отвечает каждому лично
по базе знаний Нумериты, иногда со ссылкой на полный разбор в @Numeritabot.
"""

import asyncio
import json
import logging
import random
import re
import zlib
from datetime import datetime, timedelta, timezone

from .autopost import BOT_LINK, strip_credits
from .cards import grid_hint
from .textguard import reply_problem
from .lang import is_en
from .codereply import find_birth, find_pair, pair_reply, reply as code_reply
from .constraint import focus
from .dialogue import archive_comments, conversation_context, fair_queue, walk_comments
from .generator import GenerationError, Generator
from . import reply_cooldown
from .storage import Storage
from .threads_api import ThreadsClient, ThreadsError
from .publishing_wait import defer_publishing, publication_ready

log = logging.getLogger(__name__)

LOOKBACK = timedelta(days=3)  # под какими постами смотрим комментарии
# Правила присутствия (prompts/threads_rules.md): отвечаем как живой человек, а не как спам-бот.
# Разовые потолки на день: 25.10 до полудня доллар съела дорогая модель — после перехода на дешёвую
# продолжаем отвечать тем, кто пишет (слово владельца 25.10.2026).
BUDGET_DAYS = {"2026-10-25": 1.6}
MAX_GENERATIONS_PER_RUN = 6  # включая переписывания; 28.10.2026 — спокойный темп после повторных 403/80016
FRESH_WINDOW = timedelta(minutes=30)
DAILY_REPLY_CAP = 250  # Локальный потолок (28.10.2026: было 900); не измерение остатка реальной квоты Meta.
HOUR_REPLY_CAP = 25  # не чаще, чем пишет живой человек, сколько бы ни стояло в AUTOREPLY_PER_HOUR
PAUSE = (45, 100)  # секунд между ответами внутри одного прохода (было 10–30)
# Ссылка в ответе — только если человек сам попросил (не навязываемся): не больше 3 в час на всех
# и не чаще раза в неделю одному человеку. Остальных зовём «в шапку профиля» или не зовём вовсе.
LINKS_PER_HOUR = 4
# Стена в комментариях (слово владельца 28.10.2026: «дали ценность — потом обмениваем на деньги, иначе разоримся»):
# человеку FREE_PER_DAY ответов за сутки; последний — польза и приглашение в @Numeritabot, дальше до завтра молчим.
# Когда потрачено больше TIGHT_SPEND дневного бюджета ответов — стена ниже (TIGHT_PER_DAY).
FREE_PER_DAY = 5
TIGHT_PER_DAY = 3
TIGHT_SPEND = 0.7
LINKS_PER_DAY = 20  # ответов со ссылкой за сутки на всех — далеко от поведения спамера (слово владельца 25.10.2026)
ASKS_LINK = re.compile(
    r"ссылк|линк|\blink|где\b[^?]{0,40}(бот|сайт|канал|сервис|записаться|купить)"
    r"|есть\s+(?:ли\s+)?(?:у\s+вас\s+)?(?:бот|сайт|канал)|куда\s+(писать|перейти)"
    r"|как\s+(?:мне\s+)?(?:зайти|перейти|попасть)\s+(?:в|на)\s+(?:ваш\s+)?(?:бот|сайт|сервис)"
    # 28.10.2026: «Без подписки не могу написать» — человек хочет написать лично, а личные сообщения Threads закрыты
    # без взаимной подписки: это явная просьба о связи, отвечаем по сути и даём путь в бота.
    r"|не\s+(?:могу|получается)\s+написать|в\s+(?:личк|директ|лс\b)|личн\w*\s+сообщ|без\s+подписки", re.I,
)


# С 26.10 ссылки — только по явной просьбе. Исторические метки _p остаются в статистике.
LINK_PAUSE = timedelta(days=7)


def asks_link(message: str) -> bool:
    """Явная просьба о доступе; вопрос о расчёте сам по себе не просьба о продаже."""
    if re.search(r"(?:без|не\s+надо|не\s+нуж\w*|не\s+присылай\w*)\s+(?:мне\s+)?(?:ссыл|линк)|не\s+зови", message, re.I):
        return False
    return bool(ASKS_LINK.search(message))
MAX_REPLY_LENGTH = 500


NOISE_RE = re.compile(r"^(\+|спасибо|спс|благодарю|пасиб[оа]?|ок|окей|лол|ха)+$", re.I)


def is_noise(message: str, post: str = "") -> bool:
    """Реплика без содержания («+», «спасибо», точки, одни смайлики): на неё не тратим нейросеть.
    Числа, даты, «да/нет» и вопросы — содержание; смайлик — только если пост сам просил ответить эмодзи."""
    text = re.sub(r"[\s.,!…)(\-—]+", "", (message or "").lower())
    if not text or NOISE_RE.match(text):
        return True
    emoji_only = not re.search(r"\w", text)
    return emoji_only and not re.search(r"эмодзи|смайл|эмоци", post, re.I)


def reply_model_for(author: str, main: str, ab: str | None, share: float) -> str:
    """A/B качества ответов: один и тот же человек всегда говорит с одной моделью (по хэшу ника)."""
    if not ab or share <= 0:
        return main
    return ab if zlib.crc32(author.encode()) % 100 < share * 100 else main


def smart_arm(author: str) -> str:
    """A/B «умный ответ или ответ кодом» на комментарии с датой (слово владельца 25.10.2026: «Нумерита должна быть
    умной, но нужно понять, работает ли»): половина людей (по нику, всегда одна и та же) — ответ кодом по базе ($0),
    половина — ответ нейросети. Итог — в /costs: кто продолжил разговор и кто перешёл в бота по ссылке."""
    return "code" if zlib.crc32(f"smart:{author}".encode()) % 100 < CODE_SHARE * 100 else "ai"


# Ответы кодом выключены (слово владельца 28.10.2026: «тупейше отвечает на нормальные вопросы»):
# шаблон по дате не заменяет живой ответ. Каждому, кто получил такой шаблон, redo_code_replies отвечает заново.
CODE_SHARE = 0.0


async def spent_on_replies(db: Storage, tz) -> float:
    data = json.loads(await db.kv_get(f"cost:{datetime.now(tz).date().isoformat()}") or "{}")
    return sum(row[1] for kind, row in data.items() if kind.startswith(("reply", "summary")))


async def spend_lines(db: Storage, tz) -> str:
    """Куда ушли деньги ответов: «haiku 410 отв. $0.55, sonnet 30 отв. $0.45»."""
    data = json.loads(await db.kv_get(f"cost:{datetime.now(tz).date().isoformat()}") or "{}")
    rows = [(k.split("·")[-1].replace("claude-", ""), k.split("·")[0], v) for k, v in data.items()
            if k.startswith(("reply", "summary"))]
    return ", ".join(f"{'сводки ' if kind == 'summary' else ''}{m}: {v[0]} запр. ${v[1]:.2f}"
                     for m, kind, v in sorted(rows, key=lambda r: -r[2][1]))


def gave_number(message: str) -> bool:
    """В комментарии есть число дня рождения (1–31) или дата."""
    return any(1 <= int(n) <= 31 for n in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", message))


LINK_RE = re.compile(r"(https?://\S+|t\.me/\S+|@Numeritabot\b)", re.I)


# Threads скрывает от младших и считает нарушением ответы с отсылками к самоповреждению, РПП, мату (урок 29.10.2026:
# поддерживающий ответ «извиняться за «зае…» не нужно … сил почти не остаётся?» скрыли). Такие слова в наш ответ не пускаем.
RISKY_REPLY = re.compile(
    r"зае(?:\.\.\.|…|б)|за[её]б|\b(?:вы|у|от|на|по)?[её]б(?:а|у|ну|л)|ху[йёи]|пизд|\bбля|\bсук[аи]\b|"
    r"суицид|самоуб|покончить|умереть|\bсмерт|не\s+хочу\s+жить|порез|"
    r"резать\s+себ|навредить\s+себ|сил[ауы]?\s+(?:\S+\s+){0,4}(?:почти\s+)?не\s+оста|нет\s+сил|держись|выматыва|"
    r"голода|не\s+есть|рвот|анорекс|булими|похуде|весить|таблетк", re.IGNORECASE)
# Комментарий о желании умереть или навредить себе: не разбираем публично, а коротко и бережно даём опору.
CRISIS_COMMENT = re.compile(
    r"суицид|самоуб|покончить\s+с\s+собой|не\s+хочу\s+жить|не\s+хочется\s+жить|убить\s+себя|"
    r"навредить\s+себе|порезать\s+себя|резать\s+себя|лучше\s+бы\s+меня\s+не\s+было", re.IGNORECASE)
CRISIS_REPLY = ("Слышу тебя 🤍 Если сейчас очень тяжело, позвони близкому человеку или на бесплатную линию "
                "8-800-2000-122 — там выслушают и помогут.")
if __import__("zavod.lang", fromlist=["is_en"]).is_en():
    CRISIS_REPLY = ("I hear you 🤍 If things feel very heavy right now, please reach out to someone close or a local "
                    "crisis line — in the US you can call or text 988, they listen and help.")
    CRISIS_COMMENT = re.compile(CRISIS_COMMENT.pattern + r"|suicid|kill myself|end my life|don'?t want to live|"
                                r"hurt myself|self[- ]harm", re.IGNORECASE)


def risky_reply(text: str) -> bool:
    return bool(RISKY_REPLY.search(text or ""))


def finish_reply(text: str) -> str:
    """Обрезает слишком длинный ответ и вычищает любые ссылки — в ответах их быть не должно."""
    body = re.sub(r"[ \t]{2,}", " ", LINK_RE.sub("", strip_credits(text.replace("{LINK}", "")))).strip()
    if len(body) > MAX_REPLY_LENGTH:
        body = body[: MAX_REPLY_LENGTH - 1].rsplit(" ", 1)[0] + "…"
    return body


async def reply_targets(db: Storage, threads: ThreadsClient, now: datetime) -> list[tuple[str, int | None, str]]:
    """Под какими постами смотреть комментарии: (id поста для Zernio, наш номер поста или None, текст поста).

    Берём и свои посты из базы, и все посты аккаунта с комментариями из Zernio — так бот отвечает
    и под постами, опубликованными до подключения базы или вручную.
    """
    targets: dict[str, tuple[str, int | None, str]] = {}
    ours = await db.recent_published(now - LOOKBACK)
    for post in ours:
        targets[post.threads_id] = (post.threads_id, post.id, post.text + grid_hint(post.card))
    try:
        for item in await threads.commented_posts(now - LOOKBACK):
            if not item.get("id") or item["id"] in targets:
                continue
            content = item.get("content") or ""
            match = next((p for p in ours if content and p.text[:60] == content[:60]), None)
            if match and match.threads_id in targets:
                continue  # тот же пост, который уже есть в базе под id Zernio
            targets[item["id"]] = (item["id"], match.id if match else None, content)
    except ThreadsError as e:
        if await reply_cooldown.defer(db, e, now):
            return []
        await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} список постов с комментариями: {e}")
    # Keep following recently active discussions after the original post ages out.
    for row in await db.active_dialogue_targets(now - timedelta(days=7)):
        target = row["target_id"]
        if target not in targets:
            targets[target] = (target, None, "Продолжение ранее начатой дискуссии.")
    gone = set(json.loads(await db.kv_get("gone_posts") or "[]"))  # удалённые или недоступные посты
    return [t for t in targets.values() if t[0] not in gone]


GONE_RE = re.compile(r"does not exist|cannot be loaded|Unsupported get request|not found|404", re.I)


def is_gone(error: Exception) -> bool:
    """Пост или комментарий удалён, скрыт или недоступен — это не поломка, а обычная жизнь соцсети."""
    return bool(GONE_RE.search(str(error)))


FRAGMENT_END = re.compile(r"[.!?…)»✨🌙💫🔥🤍😊🙂]\s*$")


def is_fragment(text: str) -> bool:
    """Оборванный ответ вроде «5 — это»: короткий и без законченного конца."""
    text = (text or "").strip()
    return len(text) < 25 and not FRAGMENT_END.search(text)


async def repair_fragments(db: Storage, threads: ThreadsClient, target_id: str, comments: list[dict]) -> None:
    """Наши оборванные ответы удаляем, а комментарий человека снова ставим в очередь — он получит нормальный ответ."""
    for item, parent, _ in walk_comments(comments):
        if not (item.get("from") or {}).get("isOwner") or not parent or not is_fragment(item.get("message") or ""):
            continue
        try:
            await threads.delete_comment(target_id, item["id"])
        except ThreadsError as e:
            log.warning("Не удалось удалить оборванный ответ %s: %s", item["id"], e)
            continue
        await db.forget_comment(parent)
        item["from"] = {}  # в этом проходе считаем, что нашего ответа нет
        item["message"] = ""
        log.info("Удалён оборванный ответ %s, комментарий %s снова в очереди", item["id"], parent)


def reply_candidates(comments: list[dict]) -> list[tuple[dict, str | None]]:
    """На что отвечать: комментарий без нашего ответа — и ответы людей, пришедшие после нашего последнего
    ответа в этой ветке (с текстом нашего ответа, чтобы продолжить разговор)."""
    def ok(c: dict) -> bool:
        return bool(c.get("id") and c.get("message")) and not (c.get("from") or {}).get("isOwner") \
            and c.get("canReply", True)

    out = []
    for item, _, _ in walk_comments(comments):
        # Existing direct owner replies mean this particular message was handled.
        # Descendant user messages are independent candidates.
        if ok(item) and not any((r.get("from") or {}).get("isOwner")
                               for r in item.get("replies") or []):
            out.append((item, None))
    return out


async def answer_comments(
    db: Storage,
    threads: ThreadsClient,
    generator: Generator,
    per_hour: int,
    per_run: int,
    daily_usd: float = 0,
    ab_model: str | None = None,
    ab_share: float = 0,
    tz=None,
) -> int:
    """Отвечает на новые комментарии. Возвращает, сколько ответов отправлено за этот прогон."""
    now = datetime.now(timezone.utc)
    if await reply_cooldown.blocked(db, now):
        return 0
    daily_usd = BUDGET_DAYS.get(datetime.now(tz).date().isoformat(), daily_usd) if daily_usd else daily_usd
    if daily_usd and await spent_on_replies(db, tz) >= daily_usd:
        # Закон «всегда в плюсе»: дневной бюджет ответов исчерпан — ждём завтра, владельцу одна строка.
        if await db.claim_slot(f"reply budget {datetime.now(tz).date().isoformat()} {daily_usd}"):
            await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} бюджет: ответы на сегодня "
                                               f"исчерпали ${daily_usd:.2f} ({await spend_lines(db, tz)}), продолжу завтра")
        return 0
    per_hour = min(per_hour, HOUR_REPLY_CAP)
    budget = min(per_run, per_hour - await db.replies_since(now - timedelta(hours=1)),
                 DAILY_REPLY_CAP - await db.replies_since(now - timedelta(days=1)))
    if budget <= 0:
        return 0

    # Собираем всё, на что ещё не ответили, со всех постов: и новые комментарии, и ответы людей
    # на наши ответы (живой диалог). Свежие — первыми: первые 15–30 минут решают охват поста.
    queue: list[tuple[str, int | None, str, dict]] = []
    targets = await reply_targets(db, threads, now)
    try: scans = json.loads(await db.kv_get('comments:last_scans') or '{}')
    except ValueError: scans = {}
    # Least recently checked first. Bound each pass without abandoning older threads.
    selected = sorted(targets,key=lambda t:scans.get(t[0],''))[:6]
    for target_id, post_id, post_text in selected:
        try:
            comments = await threads.comments(target_id)
        except ThreadsError as e:
            if await reply_cooldown.defer(db, e, now):
                return 0
            if await defer_publishing(db, target_id, e, now):
                log.info("Пост %s ещё публикуется в Zernio; проверим позднее", target_id)
                continue
            log.warning("Не удалось получить комментарии к посту %s: %s", target_id, e)
            if is_gone(e):  # пост удалён или недоступен — больше не спрашиваем, тревогу не поднимаем
                gone = json.loads(await db.kv_get("gone_posts") or "[]")
                await db.kv_set("gone_posts", json.dumps((gone + [target_id])[-500:]))
            else:
                await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} комментарии: {e}")
            continue
        await publication_ready(db, target_id)
        await archive_comments(db, target_id, comments)
        scans[target_id] = now.isoformat()
        await db.kv_set('comments:last_scans',json.dumps({k:scans[k] for k,_,_ in targets if k in scans}))
        await repair_fragments(db, threads, target_id, comments)
        for item, our_last in reply_candidates(comments):
            context = post_text + (f"\n\nТвой прошлый ответ этому человеку в ветке:\n{our_last}" if our_last else "")
            queue.append((target_id, post_id, context, item))
    handled = await db.handled_comments([item["id"] for *_, item in queue])
    queue = [q for q in queue if q[3]["id"] not in handled]
    # Пустые реплики («+», смайлики, «спасибо») нейросети не отдаём — это бесплатно отсеивает код.
    for q in [q for q in queue if is_noise(q[3]["message"], q[2])]:
        author = (q[3].get("from") or {}).get("username") or "?"
        await db.record_comment(q[3]["id"], q[1], author, q[3]["message"], "skip:noise", "skipped")
        queue.remove(q)
    # Порядок: сначала совсем свежие (до 30 минут — окно, когда Threads решает про охват), затем все остальные
    # от самых давно ждущих — чтобы под популярным постом никто не застревал навсегда за новыми комментариями.
    fresh_after = (now - FRESH_WINDOW).isoformat().replace("+00:00", "Z")
    fresh = sorted((q for q in queue if (q[3].get("createdTime") or "") >= fresh_after),
                   key=lambda q: q[3].get("createdTime") or "", reverse=True)
    waiting = sorted((q for q in queue if (q[3].get("createdTime") or "") < fresh_after),
                     key=lambda q: q[3].get("createdTime") or "")
    # Посты — по кругу: гора старых комментариев под популярным постом не должна задерживать остальные посты.
    by_post: dict[str, list] = {}
    for q in waiting:
        by_post.setdefault(q[0], []).append(q)
    rounds = []
    while any(by_post.values()):
        for items in by_post.values():
            if items:
                rounds.append(items.pop(0))
    queue = fresh + rounds

    queue = fair_queue(queue)
    # Содержательные продолжения важны наравне с первым вопросом или датой.
    queue.sort(key=lambda q: 0 if gave_number(q[3]["message"]) or "?" in q[3]["message"]
               or "Твой прошлый ответ" in q[2] else 1)
    tight = bool(daily_usd) and await spent_on_replies(db, tz) >= TIGHT_SPEND * daily_usd
    free_per_day = TIGHT_PER_DAY if tight else FREE_PER_DAY
    reply_focus = await focus(db, "reply_focus")  # обход по Голдратту: фокус ответов на 12 часов
    generated = 0
    sent = 0
    for target_id, post_id, post_text, comment in queue:
        author = (comment.get("from") or {}).get("username") or (comment.get("from") or {}).get("name") or "?"
        if generated >= MAX_GENERATIONS_PER_RUN:
            break
        # Не обрываем разговор по длине реплики или отсутствию вопросительного знака.
        # Новую деталь и желание завершить беседу оценивает модель по памяти ветки.
        memory = await conversation_context(db, generator, target_id, comment["id"])
        post_text += memory + (f"\n\nФокус на сегодня: {reply_focus}" if reply_focus else "")
        # Польза в комментариях прежде перехода в сервис (указание владельца 26.10).
        mode = "plain"
        paused = await db.kv_get("reply_links_paused_until")
        links_ok = (
            not (paused and now < datetime.fromisoformat(paused))
            and await db.link_replies(now - timedelta(hours=1)) < LINKS_PER_HOUR
            and await db.link_replies(now - timedelta(days=1)) < LINKS_PER_DAY
            and not await db.link_replies(now - timedelta(days=7), author)
        )
        if links_ok and asks_link(comment["message"]):
            mode = "link"
        elif (links_ok and is_en() and re.search(r"\d", comment["message"] or "")
              and not await db.link_replies(now - timedelta(days=30), author)):
            # Английский аккаунт (слово владельца 30.10.2026): в начале чаще даём ссылку — человек прислал дату/число,
            # отвечаем по сути и одной фразой зовём за полным разбором. Общие лимиты ссылок и стоп-кран прежние,
            # одному человеку — раз в 30 дней.
            mode = "offer"
        given = await db.replies_to_author(author, now - timedelta(days=1))
        if given > free_per_day:  # бесплатные ответы на сегодня закончились
            await db.record_comment(comment["id"], post_id, author, comment["message"], "skip:paywall", "skipped")
            continue
        if given == free_per_day:
            mode = "paywall" if links_ok else "paywall_bio"
        # 25.10.2026 (слово владельца): дата или день рождения без вопроса — ответ кодом по базе, без нейросети ($0)
        kb = getattr(getattr(generator, "knowledge", None), "data", None)
        arm = smart_arm(author) if (find_birth(comment["message"]) or find_pair(comment["message"])) \
            and not memory.strip() else ""
        model = reply_model_for(author, getattr(generator, "reply_model", None), ab_model, ab_share)
        seed = zlib.crc32(str(comment["id"]).encode())
        text = (code_reply(comment["message"], kb, seed=seed) or pair_reply(comment["message"], kb, seed=seed)) \
            if arm == "code" and mode in ("plain", "profile") else None
        if text:
            await db.kv_set("code_replies", str(int(await db.kv_get("code_replies") or 0) + 1))
        if not text and CRISIS_COMMENT.search(comment["message"] or ""):
            text = CRISIS_REPLY
            mode = "plain"
        try:
            if not text:
                generated += 1
                text = (await generator.write_reply(post_text, comment["message"], author, mode, model)).strip()
        except GenerationError as e:
            log.warning("Не удалось написать ответ на комментарий %s: %s", comment["id"], e)
            await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} нейросеть: {e}")
            return sent

        if text.upper().strip(" .!\"'«»") == "SKIP":
            await db.record_comment(comment["id"], post_id, author, comment["message"], "skip:model", "skipped")
            continue
        text = finish_reply(text)
        if text != CRISIS_REPLY and risky_reply(text):  # одна переписка без опасных слов, иначе молчим
            if generated >= MAX_GENERATIONS_PER_RUN:
                break
            try:
                generated += 1
                text = finish_reply(await generator.write_reply(
                    post_text, comment["message"], author, mode, model, careful=True))
            except GenerationError:
                continue
            if risky_reply(text):
                await db.record_comment(comment["id"], post_id, author, comment["message"], "skip:sensitive", "skipped")
                continue
        # Одинаковые ответы Threads считает спамом: похожий на недавний — переписываем или пропускаем.
        # Контролёр ответа (урок Влада 29.10.2026): тройки слов против последних ответов и служебный мусор.
        recent_replies = [r.get("reply") or "" for r in await db.recent_comments(50)]
        recent = {r[:60] for r in recent_replies}
        if text != CRISIS_REPLY and (text[:60] in recent or reply_problem(text, recent_replies)):
            if generated >= MAX_GENERATIONS_PER_RUN:
                break
            try:
                generated += 1
                text = finish_reply(await generator.write_reply(post_text, comment["message"], author, mode, model))
            except GenerationError:
                continue
            if text[:60] in recent or reply_problem(text, recent_replies):
                await db.record_comment(comment["id"], post_id, author, comment["message"], "skip:duplicate",
                                        "skipped")
                continue
        if not text or text.upper().strip(" .!") == "SKIP":
            continue
        if len(text) < 25 and not re.search(r"[.!?…)»✨🌙💫🔥🤍😊🙂]\s*$", text):  # обрывок вроде «5 — это» — не отправляем
            log.warning("Слишком короткий ответ на %s: %r — не отправляю", comment["id"], text)
            continue
        if mode in ("link", "paywall", "offer"):
            text = (f"{text[: MAX_REPLY_LENGTH - 45]}\n{BOT_LINK}r{post_id or 0}_"
                    f"{ {'link': 'a', 'paywall': 'w', 'offer': 'o'}[mode] }"
                    + (arm[0] if arm else ""))  # метка ветки A/B: …_pc — ответ кодом, …_pi — ответ нейросети
        if sent:
            await asyncio.sleep(random.uniform(*PAUSE))

        try:
            await threads.reply(target_id, comment["id"], text)
        except ThreadsError as e:
            log.warning("Не удалось ответить на комментарий %s: %s", comment["id"], e)
            if await reply_cooldown.defer(db, e, now):
                return sent
            if is_gone(e):  # комментарий удалили или скрыли — просто пропускаем
                await db.record_comment(comment["id"], post_id, author, comment["message"], "skip:gone", "skipped")
                continue
            if mode in ("link", "paywall", "offer"):  # стоп-кран: Threads не принял ответ со ссылкой
                await db.kv_set("reply_links_paused_until", (now + LINK_PAUSE).isoformat())
                e = ThreadsError(f"{e} — ссылки в ответах выключил на 7 дней")
            await db.kv_set("autoreply_error", f"{now:%d.%m %H:%M} ответ: {e}")
            continue
        current = await db.dialogue_message(target_id, comment["id"])
        await db.remember_message(
            target_id, current["root_id"], "local-reply:" + comment["id"], comment["id"],
            "numerita", "numerita.ai", "assistant", text, datetime.now(timezone.utc).isoformat(),
        )
        await db.record_comment(comment["id"], post_id, author, comment["message"], text, "replied")
        await reply_cooldown.success(db, datetime.now(timezone.utc))
        await db.kv_set("autoreply_error", "")
        log.info("Ответ @%s под постом %s", author, target_id)
        sent += 1
        if sent >= budget:
            return sent
    return sent


REDO_SINCE = datetime(2026, 10, 25, tzinfo=timezone.utc)
REDO_PER_RUN = 3
APOLOGY = "Прости, мой прошлый ответ вышел шаблонным — отвечаю по-настоящему. "


def is_code_reply(reply: str) -> bool:
    """Шаблонный ответ кодом узнаём по его началу и вопросу в конце (codereply.py)."""
    from .codereply import OPENINGS, PAIR_ASK, PAIR_OPEN, QUESTIONS
    text = (reply or "").strip()
    return text.startswith(tuple(OPENINGS + PAIR_OPEN)) and text.endswith(tuple(QUESTIONS + PAIR_ASK))


async def redo_code_replies(db: Storage, threads: ThreadsClient, generator: Generator, per_hour: int) -> int:
    """Тем, кто получил шаблонный ответ кодом, — живой ответ нейросети в той же ветке с коротким извинением.
    По REDO_PER_RUN за проход, в общих лимитах и паузах автоответов; каждому один раз (kv redo:<id>)."""
    now = datetime.now(timezone.utc)
    if await reply_cooldown.blocked(db, now):
        return 0
    budget = min(REDO_PER_RUN, per_hour - await db.replies_since(now - timedelta(hours=1)))
    sent = 0
    for row in await db.replied_since(REDO_SINCE):
        if sent >= budget:
            break
        if not is_code_reply(row["reply"]) or await db.kv_get(f"redo:{row['comment_id']}"):
            continue
        target = await db.reply_target(row["comment_id"])
        if not target:
            await db.kv_set(f"redo:{row['comment_id']}", "no-target")
            continue
        post = await db.get(row["post_id"]) if row.get("post_id") else None
        context = ((post.text if post else "") + "\n\nТвой прошлый ответ этому человеку был шаблоном, собранным "
                   f"без понимания вопроса:\n{row['reply']}\nТеперь ответь по существу его комментария.")
        try:
            text = finish_reply(await generator.write_reply(context, row["comment"], row["author"], "plain"))
        except GenerationError as e:
            log.warning("Переответ на %s не написан: %s", row["comment_id"], e)
            return sent
        if not text or text.upper().strip(" .!\"'«»") == "SKIP" or len(text) < 25:
            await db.kv_set(f"redo:{row['comment_id']}", "skip")
            continue
        text = finish_reply(APOLOGY + text)
        if sent:
            await asyncio.sleep(random.uniform(*PAUSE))
        await db.kv_set(f"redo:{row['comment_id']}", "sending")  # сбой не повторяем бесконечно
        try:
            await threads.reply(target, row["comment_id"], text)
        except ThreadsError as e:
            log.warning("Переответ на %s не отправлен: %s", row["comment_id"], e)
            if await reply_cooldown.defer(db, e, now):
                return sent
            continue
        current = await db.dialogue_message(target, row["comment_id"])
        root = current["root_id"] if current else row["comment_id"]
        await db.remember_message(target, root, "local-redo:" + row["comment_id"], row["comment_id"], "numerita",
                                  "numerita.ai", "assistant", text, datetime.now(timezone.utc).isoformat())
        await db.record_comment("redo:" + row["comment_id"], row["post_id"], row["author"], row["comment"], text,
                                "replied")
        await db.kv_set(f"redo:{row['comment_id']}", "done")
        await reply_cooldown.success(db, datetime.now(timezone.utc))
        sent += 1
    return sent
