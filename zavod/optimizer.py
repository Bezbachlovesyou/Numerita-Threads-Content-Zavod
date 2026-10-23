"""Самоулучшение контента: раз в сутки бот сам разбирает, какие рубрики работают, и меняет план.

1. Собирает лайки постов из Zernio, комментарии — из своей базы автоответов.
2. Считает очки рубрики за 7 дней: в среднем комментарии + 0,2 × лайки на пост.
3. Слабую рубрику (меньше половины лучшей с тем же призывом) на 3 дня заменяет лучшей.
4. Самую слабую рубрику переписывает нейросетью по примерам лучших постов.
5. Если переписанная рубрика через 3 дня стала хуже — возвращает прежний текст.
"""

import logging
import re
from datetime import datetime, timedelta

from .autopost import ContentPlan
from .generator import GenerationError, Generator
from .storage import Storage
from .threads_api import ThreadsClient, ThreadsError

log = logging.getLogger(__name__)

WINDOW = timedelta(days=7)
MIN_POSTS = 3
SWAP_DAYS = 3
TRIAL = timedelta(days=3)
PLACEHOLDERS = {"part_of_day", "weekday", "day_number", "tomorrow_number", "digit", "group", "n", "a", "b", "arcana"}

IMPROVE_SYSTEM = (
    "Ты редактор контент-плана Threads-аккаунта Нумериты (@numerita.ai). Цель постов — ответы под постом, "
    "переходы в профиль и в @Numeritabot. Тебе дают задание слабой рубрики и посты лучших рубрик с реакцией. "
    "Перепиши задание слабой рубрики так, чтобы посты получали больше ответов: сильнее крючок в первой строке, "
    "понятный повод ответить. Сохрани тему рубрики, честность (нумерология — язык символов, не наука), "
    "без обещаний и давления. Можно использовать подстановки {digit}, {group}, {n}, {a}, {b}, {arcana}, "
    "{weekday}, {part_of_day}, {day_number}, {tomorrow_number} — только их, в фигурных скобках. Ссылки и призыв в конце "
    "не описывай: их добавляет бот. Верни только новый текст задания, одной строкой, до 500 символов."
)


def score_rubrics(rows: list[dict]) -> dict[str, tuple[int, float]]:
    """{рубрика: (сколько постов, средние очки на пост)}."""
    totals: dict[str, list[float]] = {}
    for row in rows:
        totals.setdefault(row["rubric"], []).append(post_score(row))
    return {key: (len(values), sum(values) / len(values)) for key, values in totals.items()}


def post_score(row: dict) -> float:
    """Очки поста: ответы важнее всего, лайки и просмотры — дополнительно."""
    return row["comments"] + 0.2 * row["likes"] + row.get("views", 0) / 500


def valid_rubric_text(text: str) -> bool:
    used = set(re.findall(r"\{(\w+)\}", text))
    return 40 <= len(text) <= 600 and used <= PLACEHOLDERS and "\n" not in text.strip() and "{LINK}" not in text


async def refresh_metrics(db: Storage, threads: ThreadsClient, now: datetime) -> int:
    """Лайки и показы постов за неделю из статистики Zernio. 0 — статистика недоступна."""
    updated = 0
    for post in await db.recent_published(now - WINDOW):
        try:
            stats = await threads.post_stats(post.threads_id)
        except ThreadsError as e:
            log.info("Статистика Zernio недоступна: %s", e)
            return updated
        analytics = (stats or {}).get("analytics") or {}
        likes = analytics.get("likes")
        impressions = analytics.get("views", analytics.get("impressions"))  # у Threads — просмотры
        if isinstance(likes, (int, float)):
            await db.save_metrics(post.id, int(likes), int(impressions or 0))
            updated += 1
    return updated


async def apply_state(db: Storage, plan: ContentPlan, now: datetime) -> None:
    """Подтягивает в план переписанные рубрики и действующие замены из базы."""
    plan.overrides = {row["key"]: row["text"] for row in await db.overrides()}
    plan.swaps = await db.swaps(now)


async def optimize(
    db: Storage, threads: ThreadsClient | None, generator: Generator, plan: ContentPlan, now: datetime
) -> list[str]:
    """Один ежедневный проход. Возвращает строки отчёта."""
    report = []
    if threads is not None:
        await refresh_metrics(db, threads, now)
    rows = await db.engagement(now - WINDOW)
    scores = score_rubrics(rows)
    by_key = {r.key: r for r in plan.rubrics}
    ranked = sorted(((k, v) for k, v in scores.items() if k in by_key), key=lambda item: -item[1][1])
    if ranked:
        report.append("Рубрики за 7 дней (очки на пост = ответы + 0,2 × лайки + просмотры / 500):")
        report += [f"• {key}: {value:.1f} ({count} пост.)" for key, (count, value) in ranked]

    # Откат или закрепление переписанных рубрик, которые прожили пробный срок.
    # Закреплённая версия хранится с previous == text: откатывать её уже не к чему.
    for row in await db.overrides():
        created = datetime.fromisoformat(row["created_at"])
        if row["previous"] == row["text"] or now - created < TRIAL:
            continue
        after = score_rubrics([r for r in rows if r["rubric"] == row["key"] and r["published_at"] >= row["created_at"]])
        count, value = after.get(row["key"], (0, 0.0))
        if count < MIN_POSTS:
            continue
        if value < row["baseline"]:
            if row["previous"] == next((r.text for r in plan.rubrics if r.key == row["key"]), None):
                await db.drop_override(row["key"])
            else:
                await db.set_override(row["key"], row["previous"], row["previous"], row["baseline"])
            report.append(f"↩️ {row['key']}: новая версия хуже ({value:.1f} < {row['baseline']:.1f}) — вернул прежнюю.")
        else:
            await db.set_override(row["key"], row["text"], row["text"], value)
            report.append(f"✅ {row['key']}: новая версия лучше ({value:.1f}) — оставил.")

    # Переписываем самую слабую рубрику (если её сейчас не тестируем).
    testing = {row["key"] for row in await db.overrides() if row["previous"] != row["text"]}
    confident = {k: v for k, (n, v) in scores.items() if n >= MIN_POSTS and k in by_key}
    candidates = [(k, v) for k, v in confident.items() if k not in testing]
    if len(candidates) >= 2:
        weakest, weak_value = min(candidates, key=lambda item: item[1])
        top = sorted(rows, key=lambda r: -post_score(r))[:3]
        examples = "\n\n".join(
            f"[{r['rubric']}, комментариев {r['comments']}, лайков {r['likes']}]\n{r['text']}" for r in top
        )
        current = plan.overrides.get(weakest, by_key[weakest].text)
        prompt = f"Задание слабой рубрики «{weakest}»:\n{current}\n\nЛучшие посты:\n{examples}"
        try:
            new_text = (await generator.improve(IMPROVE_SYSTEM, prompt)).strip().strip("«»\"")
        except GenerationError as e:
            report.append(f"⚠️ Не смог переписать {weakest}: {e}")
        else:
            if valid_rubric_text(new_text) and new_text != current:
                await db.set_override(weakest, new_text, current, weak_value)
                testing.add(weakest)
                await db.set_swap(weakest, weakest, now)  # снимаем замену, чтобы новая версия выходила
                report.append(f"✍️ Переписал рубрику {weakest} ({weak_value:.1f}), проверю через 3 дня:\n{new_text}")
            else:
                report.append(f"⚠️ Новая версия рубрики {weakest} не прошла проверку, оставил прежнюю.")

    # Временные замены слабых рубрик лучшими с тем же призывом (кроме тех, чью новую версию проверяем).
    for cta in {r.cta for r in plan.rubrics}:
        group = {k: v for k, v in confident.items() if by_key[k].cta == cta}
        if len(group) < 2:
            continue
        best = max(group, key=group.get)
        for key, value in group.items():
            if key != best and key not in testing and value < 0.5 * group[best]:
                await db.set_swap(key, best, now + timedelta(days=SWAP_DAYS))
                report.append(f"🔁 {key} ({value:.1f}) на {SWAP_DAYS} дня заменяю на {best} ({group[best]:.1f}).")

    await apply_state(db, plan, now)
    if not ranked:
        report.append("Пока мало данных: нужны опубликованные автопосты и реакции на них.")
    return report

