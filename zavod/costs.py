"""Учёт расходов на нейросеть: каждый запрос пишет свою цену (OpenRouter возвращает её в usage.cost),
по статьям — ответы, посты, огранка, сводки диалогов, самоулучшение, видео. Отчёт владельцу простыми словами.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

KINDS = {
    "reply": "Ответы на комментарии и диалоги",
    "summary": "Сводки длинных диалогов",
    "post": "Новые посты",
    "sharpen": "Огранка готовых постов",
    "hookcheck": "Проверка крючка постов",
    "toc": "Обход по Голдратту (2 раза в день)",
    "strengthen": "Переписывание постов без крючка",
    "optimizer": "Самоулучшение (раз в сутки)",
    "video": "Сценарии видео",
    "other": "Прочее",
}
CHARS_PER_TOKEN = 2.7  # русский текст: примерно столько знаков на токен


def day_key(now: datetime) -> str:
    return f"cost:{now.date().isoformat()}"


def make_sink(db, tz):
    async def sink(kind: str, usd: float, tin: int, tout: int, cached: int) -> None:
        key = day_key(datetime.now(tz))
        data = json.loads(await db.kv_get(key) or "{}")
        row = data.setdefault(kind, [0, 0.0, 0, 0, 0])
        for i, v in enumerate((1, usd, tin, tout, cached)):
            row[i] += v
        await db.kv_set(key, json.dumps(data))
    return sink


async def _get(http: httpx.AsyncClient, url: str, key: str) -> dict:
    try:
        r = await http.get(url, headers={"Authorization": f"Bearer {key}"})
        return (r.json().get("data") or {}) if r.is_success else {}
    except (httpx.HTTPError, ValueError):
        return {}


async def openrouter_state(api_key: str, model: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as http:
        key = await _get(http, "https://openrouter.ai/api/v1/key", api_key)
        credits = await _get(http, "https://openrouter.ai/api/v1/credits", api_key)
        price = {}
        try:
            r = await http.get("https://openrouter.ai/api/v1/models")
            for m in r.json().get("data", []):
                if m.get("id") == model:
                    price = m.get("pricing") or {}
        except (httpx.HTTPError, ValueError):
            pass
    return {"key": key, "credits": credits, "price": price}


def money(x: float) -> str:
    return f"${x:.2f}"


async def report(db, generator, tz) -> str:
    now = datetime.now(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = midnight.astimezone(timezone.utc).isoformat()
    state = await openrouter_state(generator.api_key, generator.model)
    lines = [f"💸 Расходы на нейросеть за {now:%d.%m} (до {now:%H:%M})", ""]

    credits, key = state["credits"], state["key"]
    if credits:
        left = float(credits.get("total_credits") or 0) - float(credits.get("total_usage") or 0)
        lines.append(f"Баланс OpenRouter сейчас: {money(left)}")
    if key.get("usage_daily") is not None:
        lines.append(f"Ключ бота Threads потратил сегодня: {money(float(key['usage_daily']))}"
                     f" (за неделю {money(float(key.get('usage_weekly') or 0))})")
        lines.append("Если баланс упал сильнее — разницу съели другие ключи того же счёта "
                     "(бот Нумериты, пробы разработки). OpenRouter считает сутки по UTC.")
    lines.append(f"Модель: {generator.model}")

    ledger = json.loads(await db.kv_get(day_key(now)) or "{}")
    if ledger:
        lines += ["", "Точный учёт по статьям (с момента включения учёта):"]
        for kind, (n, usd, tin, tout, cached) in sorted(ledger.items(), key=lambda kv: -kv[1][1]):
            per = usd / n if n else 0
            share = f", из кэша {round(100 * cached / tin)}%" if tin and cached else ""
            base, _, model = kind.partition("·")
            label = KINDS.get(base, base) + (f" ({model})" if model else "")
            lines.append(f"• {label}: {n} запр. — {money(usd)} (≈{money(per)} за запрос{share})")

    # Что бот сделал сегодня — по базе (это видно и за часы до включения учёта).
    posts = await db._rows("SELECT rubric, COUNT(*) AS n FROM posts WHERE created_at >= ? GROUP BY rubric", (since,))
    replies = await db._rows(
        "SELECT status, COUNT(*) AS n FROM comment_replies WHERE created_at >= ? GROUP BY status", (since,))
    n_posts = sum(int(r["n"]) for r in posts)
    by_status = {r["status"]: int(r["n"]) for r in replies}
    lines += ["", "Что бот сделал сегодня:",
              f"• ответов в Threads: {by_status.get('replied', 0)}, пропущено комментариев: {by_status.get('skipped', 0)}",
              f"• постов написано: {n_posts}"]

    spent = sum(v[1] for k, v in ledger.items() if k.startswith(("reply", "summary")))
    sent = by_status.get("replied", 0)
    if spent and sent:
        lines.append(f"• цена одного отправленного ответа сегодня (со сводками): ${spent / sent:.4f}")
    price = state["price"]
    if price:
        pin, pout = float(price.get("prompt") or 0), float(price.get("completion") or 0)
        sample = await generator.knowledge.excerpt("6 и 17 совместимость пары")
        reply_in = (len(generator.reply_system) + len(sample) + 3000) / CHARS_PER_TOKEN
        post_in = (len(generator.system) + len(sample) + 2500) / CHARS_PER_TOKEN
        reply_cost = reply_in * pin + 400 * pout
        post_cost = post_in * pin + 900 * pout
        lines += ["", f"Оценка цены одного запроса без кэша (вход {pin * 1e6:.2f}$, выход {pout * 1e6:.2f}$ за млн токенов):",
                  f"• ответ: ≈{money(reply_cost)} — правила ответов и база знаний ≈{reply_in / 1000:.0f} тыс. токенов на входе",
                  f"• пост: ≈{money(post_cost)} — голос, методичка, эмоции, изобилие ≈{post_in / 1000:.0f} тыс. токенов",
                  f"• итого по сделанному сегодня ≈{money(reply_cost * by_status.get('replied', 0) + post_cost * n_posts)}"
                  " (без переписываний, сводок и пропусков нейросетью)"]
    ab = await reply_ab(db, generator, now)
    if ab:
        lines += ["", "A/B моделей ответов за 7 дней (продолжили разговор после нашего ответа):"] + ab
    from . import funnel
    lines += ["", "Что было дальше в боте:"] + ["• " + x for x in funnel.lines(await funnel.fetch(1))]
    lines += ["", "Картинки рисуются кодом — $0. Видео (fal.ai) не включено и с этого счёта не платится."]
    return "\n".join(lines)


async def reply_ab(db, generator, now: datetime) -> list[str]:
    """Качество ответов по моделям: доля людей, которые написали снова после нашего ответа в той же ветке."""
    from .autoreply import reply_model_for
    since = max((now - timedelta(days=7)).astimezone(timezone.utc).isoformat(),
                await db.kv_get("reply_ab_since") or "")  # раньше A/B не было — старые ветки не считаем
    rows = await db._rows("SELECT target_id, root_id, author, role, created_at FROM dialogue_messages "
                          "WHERE created_at >= ? ORDER BY created_at", (since,))
    first_reply: dict = {}
    talked: dict = {}
    authors: dict = {}
    for r in rows:
        thread = (r["target_id"], r["root_id"])
        if r["role"] == "assistant":
            first_reply.setdefault(thread, r["created_at"])
        else:
            authors.setdefault(thread, set()).add(r["author"])
            if thread in first_reply and r["created_at"] > first_reply[thread]:
                talked.setdefault(thread, set()).add(r["author"])
    ab_model, share = getattr(generator, "reply_ab_model", None), getattr(generator, "reply_ab_share", 0)
    stats: dict = {}
    for thread in [t for t, at in first_reply.items() if at >= since]:
        for author in authors.get(thread, ()):
            model = reply_model_for(author, generator.reply_model, ab_model, share).split("/")[-1]
            row = stats.setdefault(model, [0, 0])
            row[0] += 1
            row[1] += author in talked.get(thread, set())
    return [f"• {m}: {t} из {n} ({round(100 * t / n)}%)" for m, (n, t) in sorted(stats.items()) if n]
