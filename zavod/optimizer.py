"""Самоулучшение контента: раз в сутки бот сам разбирает, что работает, и меняет свой план.

1. Собирает лайки и просмотры постов из Zernio, ответы — из своей базы автоответов.
2. Очки поста = ответы + 0,2 × лайки + просмотры / 500. Считает средние очки рубрик за 7 дней.
3. Веса рубрик: сильные выходят чаще, слабые реже (но не пропадают совсем).
4. Веса часов: в окна, где реакция лучше, бот постит чаще, в слабые — реже.
5. Самую слабую рубрику переписывает нейросетью по примерам лучших постов; через 3 дня
   сравнивает и, если стало хуже, возвращает прежний текст.
6. Новшества: раз в 2 дня придумывает новую рубрику и проверяет её на реакции —
   удачную оставляет, неудачную убирает.
"""

import json
import logging
import re
import statistics
from datetime import datetime, timedelta, timezone

from .autopost import CTAS, ContentPlan, Rubric, hour_bucket
from .generator import GenerationError, Generator
from .storage import Storage
from .threads_api import ThreadsClient, ThreadsError

log = logging.getLogger(__name__)

WINDOW = timedelta(days=7)
MIN_POSTS = 3
LINK_WINDOW = timedelta(days=14)
MIN_LINK_POSTS = 4
MIN_COMPARE = 6  # постов со ссылкой и без — прежде чем решать, вредит ли ссылка  # столько постов каждого способа подачи ссылки, прежде чем делать вывод
TRIAL = timedelta(days=3)
EXPERIMENT_EVERY = timedelta(days=2)
PLACEHOLDERS = {"part_of_day", "weekday", "day_number", "tomorrow_number", "digit", "group", "n", "a", "b", "arcana", "gender", "digit_word", "emotion", "when"}
PLACEHOLDER_HELP = (
    "{digit} — число 1–9, {group} — дни рождения с этим числом души, {n} — день рождения 1–31, "
    "{a} и {b} — пара чисел, {arcana} — аркан 1–22, {weekday} — день недели, {part_of_day} — время суток, "
    "{day_number} — число дня, {tomorrow_number} — число завтрашнего дня, {gender} — «Женщина»/«Парень»…, "
    "{digit_word} — «восьмёрка» для {digit}, {emotion} — вопрос-эмоция для переклички («Какая мелочь в людях выводит "
    "вас из себя?»)"
)

IMPROVE_SYSTEM = (
    "Ты редактор контент-плана Threads-аккаунта Нумериты (@numerita.ai). Цель постов — ответы под постом, "
    "переходы в профиль и в @Numeritabot, а дальше — покупка Premium. Тебе дают задание слабой рубрики и посты "
    "с лучшей реакцией. Перепиши задание так, чтобы посты получали больше ответов: сильнее крючок в первой строке, "
    "понятный повод ответить. Сохрани тему рубрики, честность (нумерология — язык символов, не наука), "
    "без обещаний и давления. Подстановки в фигурных скобках можно использовать только такие: "
    + PLACEHOLDER_HELP + ". Ссылки и призыв в конце не описывай: их добавляет бот. "
    "Верни только новый текст задания, одной строкой, до 500 символов."
)

INVENT_SYSTEM = (
    "Ты придумываешь новые рубрики для Threads-аккаунта Нумериты (@numerita.ai): нумерология, планеты, арканы, "
    "Бхагавад-гита, самопознание. Цель — ответы под постами и переходы в @Numeritabot. Придумай ОДНУ новую рубрику, "
    "непохожую на существующие, с сильным крючком. Честно: нумерология — язык символов, не наука; без обещаний "
    "и давления; полную дату рождения публично не просим, только число дня рождения. Подстановки: "
    + PLACEHOLDER_HELP + ". Ответ — ровно одна строка в формате: <призыв> <ключ>: <задание для автора поста>. "
    "Призыв — одно из: reply (зовём ответить в комментариях), link (бот добавит ссылку на бота), "
    "profile (зовём в профиль), none. Ключ — одно английское слово строчными буквами, 3–12 букв."
)


RUBRIC_NAMES = {
    "mood": "настроение часа", "hello": "«напиши число дня рождения»", "soul": "число души",
    "debate": "спор про судьбу", "love": "любовь и отношения", "pair": "совместимость пары",
    "money": "работа и деньги", "wisdom": "мудрость дня", "offer": "приглашение в бота", "day": "число дня",
    "story": "истории", "unpopular": "непопулярное мнение", "list": "списки «сохрани»", "humor": "юмор",
    "carousel": "карусель 9 чисел", "grid": "головоломка из цифр", "callout": "«Есть тут рождённые…?»",
    "ex": "«кто-то из прошлого вернулся»", "emotion": "перекличка с эмоцией", "jackpot": "«не подарок — джекпот»", "video": "видео с Нумеритой", "news": "добрые новости", "abundance": "изобилие и богатство",
}


def rubric_name(key: str, plan: ContentPlan) -> str:
    """Понятное название рубрики для отчёта владельцу."""
    if key in RUBRIC_NAMES:
        return RUBRIC_NAMES[key]
    rubric = next((r for r in plan.all_rubrics() if r.key == key), None)
    words = (plan.effective(rubric).text if rubric else key).split()
    return "новый формат «" + readable(" ".join(words[:6])) + "…»"


def readable(text: str) -> str:
    """Задание рубрики без подстановок — для отчёта владельцу."""
    words = {"digit": "N", "group": "дни рождения", "a": "A", "b": "B", "digit_word": "N",
             "gender": "Женщина/Парень", "arcana": "аркан", "n": "N"}
    return re.sub(r"\{(\w+)\}", lambda m: words.get(m.group(1), "…"), text)


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def post_score(row: dict) -> float:
    """Очки поста: ответы важнее всего, лайки и просмотры — дополнительно."""
    return row["comments"] + 0.2 * row["likes"] + row.get("views", 0) / 500


def score_rubrics(rows: list[dict]) -> dict[str, tuple[int, float]]:
    """{рубрика: (сколько постов, средние очки на пост)}."""
    totals: dict[str, list[float]] = {}
    for row in rows:
        totals.setdefault(row["rubric"], []).append(post_score(row))
    return {key: (len(values), sum(values) / len(values)) for key, values in totals.items()}


def valid_rubric_text(text: str) -> bool:
    used = set(re.findall(r"\{(\w+)\}", text))
    return 40 <= len(text) <= 600 and used <= PLACEHOLDERS and "\n" not in text.strip() and "{LINK}" not in text


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


async def refresh_metrics(db: Storage, threads: ThreadsClient, now: datetime) -> int:
    """Лайки и просмотры постов за неделю из статистики Zernio. 0 — статистика недоступна."""
    updated = 0
    for post in await db.recent_published(now - WINDOW):
        try:
            stats = await threads.post_stats(post.threads_id)
        except ThreadsError as e:
            log.info("Статистика Zernio недоступна: %s", e)
            return updated
        analytics = (stats or {}).get("analytics") or {}
        likes = analytics.get("likes")
        views = analytics.get("views", analytics.get("impressions"))  # у Threads — просмотры
        if isinstance(likes, (int, float)):
            await db.save_metrics(post.id, int(likes), int(views or 0))
            updated += 1
    return updated


async def apply_state(db: Storage, plan: ContentPlan, now: datetime) -> None:
    """Подтягивает в план всё, что самоулучшение сохранило в базе."""
    plan.overrides = {row["key"]: row["text"] for row in await db.overrides()}
    plan.weights = json.loads(await db.kv_get("rubric_weights") or "{}")
    plan.hour_weights = json.loads(await db.kv_get("hour_weights") or "{}")
    plan.custom = [Rubric(r["cta"], r["key"], r["text"]) for r in await db.custom_rubrics(("trial", "kept"))]
    plan.card_weights = json.loads(await db.kv_get("card_weights") or "{}")


async def optimize(
    db: Storage, threads: ThreadsClient | None, generator: Generator, plan: ContentPlan, now: datetime
) -> list[str]:
    """Один ежедневный проход. Возвращает строки отчёта."""
    report: list[str] = []  # что изменил — попадает в раздел «Что я поменял»
    if threads is not None:
        await refresh_metrics(db, threads, now)
    rows = await db.engagement(now - WINDOW)
    scores = score_rubrics([r for r in rows if r["rubric"] != "script"])
    by_key = {r.key: r for r in plan.all_rubrics()}
    ranked = sorted(((k, v) for k, v in scores.items() if k in by_key), key=lambda item: -item[1][1])
    name = lambda key: rubric_name(key, plan)  # noqa: E731
    confident = {k: v for k, (n, v) in scores.items() if n >= MIN_POSTS and k in by_key}
    base_scores = [v for k, v in confident.items() if not k.startswith("x")]
    median = statistics.median(base_scores) if base_scores else None

    # 1. Переписанные рубрики, прожившие пробный срок: закрепляем или откатываем.
    #    Закреплённая версия хранится с previous == text: откатывать её уже не к чему.
    for row in await db.overrides():
        created = datetime.fromisoformat(row["created_at"])
        if row["previous"] == row["text"] or now - created < TRIAL:
            continue
        after = score_rubrics([r for r in rows if r["rubric"] == row["key"] and r["published_at"] >= row["created_at"]])
        count, value = after.get(row["key"], (0, 0.0))
        if count < MIN_POSTS:
            continue
        if value < row["baseline"]:
            original = next((r.text for r in plan.all_rubrics() if r.key == row["key"]), None)
            if row["previous"] == original:
                await db.drop_override(row["key"])
            else:
                await db.set_override(row["key"], row["previous"], row["previous"], row["baseline"])
            report.append(f"↩️ {row['key']}: новая версия хуже ({value:.1f} < {row['baseline']:.1f}) — вернул прежнюю.")
        else:
            await db.set_override(row["key"], row["text"], row["text"], value)
            report.append(f"✅ {row['key']}: новая версия лучше ({value:.1f}) — оставил.")

    # 2. Эксперименты, набравшие достаточно постов: оставляем или убираем.
    for row in await db.custom_rubrics(("trial",)):
        count, value = scores.get(row["key"], (0, 0.0))
        if count < MIN_POSTS or median is None:
            continue
        status = "kept" if value >= median else "dropped"
        await db.set_custom_status(row["key"], status)
        verdict = "оставляю" if status == "kept" else "убираю"
        better = "лучше" if status == "kept" else "хуже"
        report.append(f"🧪 Проверка нового формата {name(row['key'])} закончена: он работает {better} среднего — {verdict}.")

    # 3. Веса рубрик: сильные чаще, слабые реже; рубрики на проверке — с запасом.
    weights: dict[str, float] = {}
    if median:
        for key, value in confident.items():
            weights[key] = round(clamp(value / median, 0.3, 2.5), 2)
    for row in await db.custom_rubrics(("trial",)):
        weights[row["key"]] = 1.5
    await db.kv_set("rubric_weights", json.dumps(weights))
    strong = [k for k, w in weights.items() if w >= 1.3]
    weak = [k for k, w in weights.items() if w <= 0.7]
    if strong or weak:
        if strong:
            report.append("⬆️ Чаще ставлю: " + ", ".join(map(name, strong)) + " — на них больше реакций.")
        if weak:
            report.append("⬇️ Реже ставлю: " + ", ".join(map(name, weak)) + " — реагируют слабее.")

    # 4. Веса часов: где реакция лучше — постим чаще (интервал короче), но не чаще раза в час.
    buckets: dict[str, list[float]] = {}
    for row in rows:
        hour = datetime.fromisoformat(row["published_at"]).astimezone(now.tzinfo).hour
        buckets.setdefault(hour_bucket(hour), []).append(post_score(row))
    usable = {b: sum(v) / len(v) for b, v in buckets.items() if len(v) >= MIN_POSTS}
    hour_weights = {}
    if len(usable) >= 2 and statistics.mean(usable.values()) > 0:
        mean = statistics.mean(usable.values())
        hour_weights = {b: round(clamp(v / mean, 0.75, 1.35), 2) for b, v in usable.items()}
        best = max(hour_weights, key=hour_weights.get)
        report.append(f"🕐 Лучше всего реагируют с {best}:00 до {int(best) + 3}:00 — в эти часы буду постить чаще.")
    await db.kv_set("hour_weights", json.dumps(hour_weights))

    # 4б. Картинки: какие палитры и стиль фразы дают больше реакции.
    variants: dict[str, list[float]] = {}
    for row in rows:
        card = json.loads(row.get("card") or "null") or {}
        for key in (f"palette:{card.get('palette')}", f"style:{card.get('style')}"):
            if not key.endswith(":None"):
                variants.setdefault(key, []).append(post_score(row))
    card_avg = {k: sum(v) / len(v) for k, v in variants.items() if len(v) >= MIN_POSTS}
    card_weights = {}
    if card_avg and statistics.mean(card_avg.values()) > 0:
        mean = statistics.mean(card_avg.values())
        card_weights = {k: round(clamp(v / mean, 0.5, 2.0), 2) for k, v in card_avg.items()}
        best_style = max((k for k in card_weights if k.startswith("style:")), key=card_weights.get, default=None)
        best_palette = max((k for k in card_weights if k.startswith("palette:")), key=card_weights.get, default=None)
        names = {"style:intrigue": "интрига", "style:question": "вопрос"}
        report.append(
            "🎨 На картинках лучше работает "
            + ", ".join(x for x in (names.get(best_style), best_palette and f"палитра {best_palette[8:]}") if x)
            + " — буду использовать чаще."
        )
    await db.kv_set("card_weights", json.dumps(card_weights))

    # 4б2. Правда ли на посты со ссылкой отвечают меньше? Сравниваем ответы на пост за 2 недели.
    #      Если со ссылкой заметно хуже (меньше 70% от постов без ссылки) — посты пишем без ссылок
    #      (только «ссылка в профиле»), оставив 10% на контроль; если выровнялось — возвращаем.
    ctas = {r.key: r.cta for r in plan.all_rubrics()}
    all_rows = [r for r in await db.engagement(now - LINK_WINDOW) if r["rubric"] not in ("video", "script")]
    with_link = [r for r in all_rows if r.get("link_mode") in ("text", "comment")
                 or (not r.get("link_mode") and ctas.get(r["rubric"]) == "link")]
    no_link = [r for r in all_rows if r not in with_link]
    if len(with_link) >= MIN_COMPARE and len(no_link) >= MIN_COMPARE:
        avg_link = sum(r["comments"] for r in with_link) / len(with_link)
        avg_plain = sum(r["comments"] for r in no_link) / len(no_link)
        was_off = await db.kv_get("links_in_posts") == "off"
        if avg_plain > 0 and avg_link < 0.7 * avg_plain:
            await db.kv_set("links_in_posts", "off")
            report.append(
                f"🔗 Проверил: на посты со ссылкой отвечают меньше — {avg_link:.1f} ответа против {avg_plain:.1f} "
                f"без ссылки ({len(with_link)} и {len(no_link)} постов). "
                + ("Посты и дальше без ссылок" if was_off else "Перехожу на посты без ссылок")
                + " — зову «по ссылке в профиле», 1 пост из 10 оставляю со ссылкой для контроля."
            )
        elif was_off and avg_link >= 0.9 * avg_plain:
            await db.kv_set("links_in_posts", "on")
            report.append(f"🔗 Посты со ссылкой снова собирают ответы не хуже ({avg_link:.1f} против {avg_plain:.1f}) "
                          "— возвращаю ссылки.")
        elif not was_off:
            report.append(f"🔗 Проверил: со ссылкой и без ответов почти поровну ({avg_link:.1f} против "
                          f"{avg_plain:.1f}) — ссылки оставляю.")

    # 4в. Эксперимент «где ставить ссылку»: в тексте, первым комментарием или «в профиле».
    link_rows = [r for r in await db.engagement(now - LINK_WINDOW) if r.get("link_mode")]
    modes: dict[str, list[float]] = {}
    for row in link_rows:
        modes.setdefault(row["link_mode"], []).append(post_score(row))
    if len(modes) == 3 and min(len(v) for v in modes.values()) >= MIN_LINK_POSTS:
        avg = {m: sum(v) / len(v) for m, v in modes.items()}
        mean = statistics.mean(avg.values())
        if mean > 0:
            link_weights = {m: round(clamp(v / mean, 0.3, 2.5), 2) for m, v in avg.items()}
            await db.kv_set("link_mode_weights", json.dumps(link_weights))
            best = max(avg, key=avg.get)
            names = {"text": "ссылка в тексте поста", "comment": "ссылка первым комментарием",
                     "profile": "только ссылка в профиле"}
            report.append(
                f"🔗 Где ставить ссылку: больше всего реакций, когда «{names[best]}». "
                "Буду делать так чаще, остальные способы — реже, но продолжу проверять."
            )

    # 5. Переписываем самую слабую рубрику (если её сейчас не проверяем).
    testing = {row["key"] for row in await db.overrides() if row["previous"] != row["text"]}
    candidates = [(k, v) for k, v in confident.items() if k not in testing]
    if len(candidates) >= 2:
        weakest, weak_value = min(candidates, key=lambda item: item[1])
        top = sorted(rows, key=lambda r: -post_score(r))[:3]
        examples = "\n\n".join(
            f"[{r['rubric']}, ответов {r['comments']}, лайков {r['likes']}]\n{r['text']}" for r in top
        )
        current = plan.overrides.get(weakest, by_key[weakest].text)
        try:
            new_text = (await generator.improve(
                IMPROVE_SYSTEM, f"Задание слабой рубрики «{weakest}»:\n{current}\n\nЛучшие посты:\n{examples}", kind="optimizer"
            )).strip().strip("«»\"")
        except GenerationError as e:
            report.append(f"⚠️ Не смог переписать рубрику {name(weakest)}: {e}")
        else:
            if valid_rubric_text(new_text) and new_text != current:
                await db.set_override(weakest, new_text, current, weak_value)
                report.append(f"✍️ Рубрика {name(weakest)} собирала меньше всего реакций — написал для неё новое задание. "
                              "Через 3 дня сравню и оставлю ту версию, что лучше.")
            else:
                log.info("Новая версия рубрики %s не прошла проверку", weakest)

    # 6. Новшество: новая рубрика раз в 2 дня, если сейчас ничего не проверяем.
    last = await db.kv_get("last_experiment")
    trials = await db.custom_rubrics(("trial",))
    if not trials and (last is None or now - datetime.fromisoformat(last) >= EXPERIMENT_EVERY):
        existing = "\n".join(f"- {r.cta} {r.key}: {plan.effective(r).text}" for r in plan.all_rubrics())
        try:
            line = (await generator.improve(INVENT_SYSTEM, f"Существующие рубрики:\n{existing}", kind="optimizer")).strip()
        except GenerationError as e:
            report.append(f"⚠️ Не смог придумать новый формат: {e}")
        else:
            match = re.match(r"^-?\s*(\w+)\s+([a-z]{3,12}):\s*(.+)$", line.splitlines()[0] if line else "")
            known = {r.key for r in plan.all_rubrics()} | {r["key"] for r in await db.custom_rubrics(("dropped",))}
            if match and match.group(1) in CTAS and valid_rubric_text(match.group(3)) and "x" + match.group(2) not in known:
                key = "x" + match.group(2)
                await db.add_custom_rubric(key, match.group(1), match.group(3).strip())
                await db.kv_set("last_experiment", now.isoformat())
                report.append(f"🧪 Запускаю на проверку новый формат постов:\n«{readable(match.group(3).strip())}»\n"
                              "Если наберёт больше реакций, чем обычно, — оставлю.")
            else:
                log.info("Придуманная рубрика не прошла проверку: %s", line[:200])

    await apply_state(db, plan, now)
    stats = summary(rows, ranked, name) + await conversations(db, now) + emotion_stats(rows)
    asked = await db.link_replies(now - timedelta(days=1), pattern="%_a")
    offered = await db.link_replies(now - timedelta(days=1), pattern="%_p")
    paused = await db.kv_get("reply_links_paused_until")
    if asked or offered:
        stats.append(f"\n🔗 Ссылки в ответах за сутки: по просьбе — {asked}, сами предложили — {offered}. "
                     "Переходы по ним видно в @Numeritabot по меткам _a и _p.")
    if paused and now < datetime.fromisoformat(paused):
        stats.append(f"⛔ Ссылки в ответах на паузе до {datetime.fromisoformat(paused):%d.%m}: Threads не принял ответ со ссылкой.")
    return stats + ["", "🔧 Что я поменял:"] + (report or ["Пока ничего — жду больше реакций."])


async def conversations(db: Storage, now: datetime) -> list[str]:
    """Разговоры в Threads за сутки: сколько людей получили ответ и сколько продолжили диалог."""
    since = (now - timedelta(days=1)).astimezone(timezone.utc).isoformat()
    rows = [r for r in await db.recent_comments(2000) if r["created_at"] >= since]
    replied = [r for r in rows if r["status"] == "replied"]
    if not rows:
        return ["", "💬 Разговоры за сутки: новых комментариев не было."]
    people = {r["author"] for r in replied}
    talks = {a for a in people if sum(r["author"] == a for r in replied) >= 2}
    skipped = len(rows) - len(replied)
    line = (f"💬 Разговоры за сутки: Нумерита ответила {plural(len(replied), 'раз', 'раза', 'раз')} — "
            f"{plural(len(people), 'человеку', 'людям', 'людям')}")
    line += f"; живой диалог (человек ответил снова) — с {len(talks)}" if talks else ""
    line += f". Пропущено {skipped} (спам, смайлики, удалённые)." if skipped else "."
    return ["", line]


def emotion_stats(rows: list[dict]) -> list[str]:
    """Какие эмоции в перекличках собирают больше ответов (пометка «[эмоция: …]» в теме поста)."""
    by: dict[str, list[int]] = {}
    for row in rows:
        match = re.search(r"\[эмоция: ([^\]]+)\]", row.get("topic") or "")
        if match:
            by.setdefault(match.group(1), []).append(row["comments"])
    avg = {e: sum(v) / len(v) for e, v in by.items() if len(v) >= 2}
    if len(avg) < 2:
        return []
    order = sorted(avg, key=avg.get, reverse=True)
    return ["", f"🎭 Эмоции в перекличках: больше всего ответов — «{order[0]}» ({avg[order[0]]:.0f} на пост), "
                f"меньше всего — «{order[-1]}» ({avg[order[-1]]:.0f})."]


def summary(rows: list[dict], ranked: list, name) -> list[str]:
    """Первая часть отчёта: сколько вышло и что заходит лучше всего — обычными словами."""
    if not rows:
        return ["За неделю ещё нет опубликованных постов с реакциями — выводы будут позже."]
    comments, likes = sum(r["comments"] for r in rows), sum(r["likes"] for r in rows)
    views = sum(r.get("views", 0) for r in rows)
    lines = [
        f"📊 За 7 дней: {plural(len(rows), 'пост', 'поста', 'постов')}, "
        f"{plural(comments, 'комментарий', 'комментария', 'комментариев')}, "
        f"{plural(likes, 'лайк', 'лайка', 'лайков')}, {plural(views, 'просмотр', 'просмотра', 'просмотров')}."
    ]
    if ranked:
        lines += ["", "🏆 Что заходит лучше всего (в среднем на один пост):"]
        for i, (key, (count, _)) in enumerate(ranked[:5], 1):
            own = [r for r in rows if r["rubric"] == key]
            c, l = sum(r["comments"] for r in own) / count, sum(r["likes"] for r in own) / count
            title = name(key)
            lines.append(f"{i}. {title[:1].upper() + title[1:]} — "
                         f"{c:.0f} комм., {l:.0f} лайк. ({plural(count, 'пост', 'поста', 'постов')})")
    if not ranked or min(count for _, (count, _) in ranked) < MIN_POSTS:
        lines.append("\nДанных пока мало — уверенные выводы будут, когда каждый вид постов выйдет хотя бы 2–3 раза.")
    return lines
