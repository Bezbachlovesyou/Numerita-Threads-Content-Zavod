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
from datetime import datetime, timedelta

from .autopost import CTAS, ContentPlan, Rubric, hour_bucket
from .generator import GenerationError, Generator
from .storage import Storage
from .threads_api import ThreadsClient, ThreadsError

log = logging.getLogger(__name__)

WINDOW = timedelta(days=7)
MIN_POSTS = 3
TRIAL = timedelta(days=3)
EXPERIMENT_EVERY = timedelta(days=2)
PLACEHOLDERS = {"part_of_day", "weekday", "day_number", "tomorrow_number", "digit", "group", "n", "a", "b", "arcana"}
PLACEHOLDER_HELP = (
    "{digit} — число 1–9, {group} — дни рождения с этим числом души, {n} — день рождения 1–31, "
    "{a} и {b} — пара чисел, {arcana} — аркан 1–22, {weekday} — день недели, {part_of_day} — время суток, "
    "{day_number} — число дня, {tomorrow_number} — число завтрашнего дня"
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


async def optimize(
    db: Storage, threads: ThreadsClient | None, generator: Generator, plan: ContentPlan, now: datetime
) -> list[str]:
    """Один ежедневный проход. Возвращает строки отчёта."""
    report: list[str] = []
    if threads is not None:
        await refresh_metrics(db, threads, now)
    rows = await db.engagement(now - WINDOW)
    scores = score_rubrics([r for r in rows if r["rubric"] != "script"])
    by_key = {r.key: r for r in plan.all_rubrics()}
    ranked = sorted(((k, v) for k, v in scores.items() if k in by_key), key=lambda item: -item[1][1])
    if ranked:
        report.append("Рубрики за 7 дней (очки на пост = ответы + 0,2 × лайки + просмотры / 500):")
        report += [f"• {key}: {value:.1f} ({count} пост.)" for key, (count, value) in ranked]
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
        report.append(f"🧪 Новая рубрика {row['key']}: {value:.1f} против медианы {median:.1f} — {verdict}.")

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
        report.append(f"⚖️ Чаще: {', '.join(strong) or '—'}; реже: {', '.join(weak) or '—'}.")

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
        report.append(f"🕐 Лучшее время: {best}:00–{int(best) + 3}:00 — там посты будут выходить чаще.")
    await db.kv_set("hour_weights", json.dumps(hour_weights))

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
                IMPROVE_SYSTEM, f"Задание слабой рубрики «{weakest}»:\n{current}\n\nЛучшие посты:\n{examples}"
            )).strip().strip("«»\"")
        except GenerationError as e:
            report.append(f"⚠️ Не смог переписать {weakest}: {e}")
        else:
            if valid_rubric_text(new_text) and new_text != current:
                await db.set_override(weakest, new_text, current, weak_value)
                report.append(f"✍️ Переписал рубрику {weakest} ({weak_value:.1f}), проверю через 3 дня:\n{new_text}")
            else:
                report.append(f"⚠️ Новая версия рубрики {weakest} не прошла проверку, оставил прежнюю.")

    # 6. Новшество: новая рубрика раз в 2 дня, если сейчас ничего не проверяем.
    last = await db.kv_get("last_experiment")
    trials = await db.custom_rubrics(("trial",))
    if not trials and (last is None or now - datetime.fromisoformat(last) >= EXPERIMENT_EVERY):
        existing = "\n".join(f"- {r.cta} {r.key}: {plan.effective(r).text}" for r in plan.all_rubrics())
        try:
            line = (await generator.improve(INVENT_SYSTEM, f"Существующие рубрики:\n{existing}")).strip()
        except GenerationError as e:
            report.append(f"⚠️ Не смог придумать новую рубрику: {e}")
        else:
            match = re.match(r"^-?\s*(\w+)\s+([a-z]{3,12}):\s*(.+)$", line.splitlines()[0] if line else "")
            known = {r.key for r in plan.all_rubrics()} | {r["key"] for r in await db.custom_rubrics(("dropped",))}
            if match and match.group(1) in CTAS and valid_rubric_text(match.group(3)) and "x" + match.group(2) not in known:
                key = "x" + match.group(2)
                await db.add_custom_rubric(key, match.group(1), match.group(3).strip())
                await db.kv_set("last_experiment", now.isoformat())
                report.append(f"🧪 Новая рубрика на проверку — {key} ({match.group(1)}):\n{match.group(3).strip()}")
            else:
                report.append("⚠️ Придуманная рубрика не прошла проверку, попробую завтра.")

    await apply_state(db, plan, now)
    if not ranked:
        report.append("Пока мало данных: нужны опубликованные автопосты и реакции на них.")
    return report
