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
    "art": "Планка арт-объекта (оценка текста)",
    "elevate": "Подъём текста до арт-объекта",
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
    smart = await smart_ab(db, now)
    if smart:
        lines += ["", "A/B «умный ответ или ответ кодом» на комментарии с датой, 7 дней:"] + smart
    ab = await reply_ab(db, generator, now)
    if ab:
        lines += ["", "A/B моделей ответов за 7 дней (продолжили разговор после нашего ответа):"] + ab
    from . import funnel
    lines += ["", "Что было дальше в боте:"] + ["• " + x for x in funnel.lines(await funnel.fetch(1))]
    lines += ["", "Картинки рисуются кодом — $0. Видео (fal.ai) не включено и с этого счёта не платится."]
    return "\n".join(lines)


async def smart_ab(db, now: datetime, raw: bool = False):
    """Ветки по нику: сколько людей с датой получили ответ, сколько продолжили разговор; переходы в бота — по меткам
    …_pc / …_pi в «Что было дальше в боте». Цена: ответ кодом — $0."""
    from .autoreply import smart_arm
    from .codereply import find_birth, find_pair
    since = max((now - timedelta(days=7)).astimezone(timezone.utc).isoformat(), "2026-10-25")
    rows = await db._rows("SELECT target_id, root_id, author, role, body, created_at FROM dialogue_messages "
                          "WHERE created_at >= ? ORDER BY created_at", (since,))
    first_user: dict = {}
    first_reply: dict = {}
    talked: dict = {}
    for r in rows:
        thread = (r["target_id"], r["root_id"])
        if r["role"] == "assistant":
            first_reply.setdefault(thread, r["created_at"])
        elif thread not in first_user:
            first_user[thread] = (r["author"], r["body"])
        elif thread in first_reply and r["created_at"] > first_reply[thread] and r["author"] == first_user[thread][0]:
            talked[thread] = True
    stats = {"code": [0, 0], "ai": [0, 0]}
    for thread, (author, body) in first_user.items():
        if thread in first_reply and (find_birth(body or "") or find_pair(body or "")):
            row = stats[smart_arm(author)]
            row[0] += 1
            row[1] += thread in talked
    if raw:
        return stats
    names = {"code": "кодом ($0)", "ai": "нейросеть"}
    return [f"• {names[a]}: ответили {n}, продолжили разговор {t} ({round(100 * t / n)}%)"
            for a, (n, t) in stats.items() if n]


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


async def tune_code_share(db, now: datetime) -> str | None:
    """Раз в сутки: если ответ кодом держит разговор не хуже нейросети — больше людей получают ответ кодом ($0).
    Шаг 0,2; пределы 0,3–0,9 (10% — нейросеть для контроля). Решение — по доле продолживших разговор."""
    return None  # 28.10.2026 ответы кодом выключены владельцем — долю больше не поднимаем
    from . import autoreply
    stats = await smart_ab(db, now, raw=True)
    (nc, tc), (na, ta) = stats["code"], stats["ai"]
    share = float(await db.kv_get("code_share") or autoreply.CODE_SHARE)
    if nc < 30 or na < 30:
        return None
    rc, ra = tc / nc, ta / na
    new = min(0.9, share + 0.2) if rc >= 0.8 * ra else max(0.3, share - 0.2) if rc < 0.6 * ra else share
    if abs(new - share) < 1e-9:
        return None
    await db.kv_set("code_share", f"{new:.2f}")
    return (f"🤖 Ответы кодом: продолжили разговор {round(100 * rc)}% против {round(100 * ra)}% у нейросети — "
            f"теперь кодом отвечаю {round(100 * new)}% людей с датой или парой (было {round(100 * share)}%).")


async def report_days(db, generator, tz, days: int = 3) -> str:
    """Раскладка расходов завода за последние дни по статьям и дням (слово владельца 04.11.2026: «куда ушли деньги за 3 дня»). Только ключ завода — по нашему учёту;
    расходы других ключей того же счёта (основной бот, разработка) видны в самом OpenRouter: openrouter.ai → Activity (можно выгрузить CSV)."""
    now = datetime.now(tz)
    state = await openrouter_state(generator.api_key, generator.model)
    lines = [f"💸 Расходы завода за {days} дня"]
    credits, key = state["credits"], state["key"]
    if credits:
        left = float(credits.get("total_credits") or 0) - float(credits.get("total_usage") or 0)
        lines.append(f"Баланс счёта сейчас: {money(left)}")
    if key.get("usage_weekly") is not None:
        lines.append(f"Ключ завода: сегодня {money(float(key.get('usage_daily') or 0))}, за неделю {money(float(key['usage_weekly']))}")
    totals: dict[str, list] = {}
    per_day = []
    for i in range(days):
        day = (now - timedelta(days=i)).date()
        ledger = json.loads(await db.kv_get(f"cost:{day.isoformat()}") or "{}")
        total = sum(v[1] for v in ledger.values())
        per_day.append(f"{day:%d.%m}: {money(total)}" + ("" if ledger else " (учёта нет)"))
        for kind, (n, usd, *_rest) in ledger.items():
            base = kind.partition("·")[0]
            row = totals.setdefault(base, [0, 0.0])
            row[0] += n
            row[1] += usd
    lines.append("По дням: " + "; ".join(per_day))
    if totals:
        lines.append("")
        grand = sum(v[1] for v in totals.values()) or 1
        for base, (n, usd) in sorted(totals.items(), key=lambda kv: -kv[1][1])[:8]:
            lines.append(f"• {KINDS.get(base, base)}: {money(usd)} ({round(100 * usd / grand)}%, {n} запр.)")
        lines.append(f"Итого по учёту завода: {money(grand if totals else 0)}")
    lines.append(await post_cost_line(db, tz, days))
    lines.append("")
    lines.append("Расход других ключей этого счёта (основной бот, разработка) я отсюда не вижу: он в OpenRouter → Activity; ветку основного бота я уже попросил прислать свою раскладку.")
    return "\n".join(lines)[:3900]


async def openrouter_report(mgmt_key: str, days: int = 3) -> str:
    """Аналитика OpenRouter прямо в Telegram (слово владельца 04.11.2026): по ключам счёта и по моделям за последние дни, без захода в сайт.
    Нужен управляющий ключ (Management key, openrouter.ai/settings/management-keys) в переменной OPENROUTER_MANAGEMENT_KEY на Railway: обычный ключ эти данные не отдаёт."""
    if not mgmt_key:
        return ("Чтобы я показывал аналитику OpenRouter сам, нужен один шаг от вас:\n"
                "1) openrouter.ai → Settings → Management Keys → создать ключ (имя «analytics»);\n"
                "2) вставить его в Railway → сервис завода → Variables → OPENROUTER_MANAGEMENT_KEY (в чат ключ не присылайте).\n"
                "После этого команда /openrouter покажет расход по ключам и моделям за 3 дня.")
    headers = {"Authorization": f"Bearer {mgmt_key}"}
    lines = ["📊 OpenRouter: куда уходят деньги"]
    async with httpx.AsyncClient(timeout=30, headers=headers) as http:
        keys = []
        try:
            r = await http.get("https://openrouter.ai/api/v1/keys")
            keys = (r.json().get("data") or []) if r.is_success else []
            if not r.is_success:
                lines.append(f"Ключи: OpenRouter ответил {r.status_code} — проверьте, что это именно Management key.")
        except (httpx.HTTPError, ValueError):
            lines.append("Ключи: не удалось получить список.")
        if keys:
            lines.append("\nПо ключам (сегодня / 7 дней / месяц):")
            for k in sorted(keys, key=lambda k: -float(k.get("usage_monthly") or k.get("usage") or 0))[:8]:
                name = k.get("name") or k.get("label") or "без имени"
                lines.append(f"• {name}{' (выключен)' if k.get('disabled') else ''}: {money(float(k.get('usage_daily') or 0))} / "
                             f"{money(float(k.get('usage_weekly') or 0))} / {money(float(k.get('usage_monthly') or k.get('usage') or 0))}")
        by_model: dict[str, float] = {}
        by_day: dict[str, float] = {}
        got = False
        today = datetime.now(timezone.utc).date()
        for i in range(1, days + 1):
            day = (today - timedelta(days=i)).isoformat()
            try:
                r = await http.get("https://openrouter.ai/api/v1/activity", params={"date": day})
                rows = (r.json().get("data") or []) if r.is_success else []
            except (httpx.HTTPError, ValueError):
                rows = []
            for row in rows:
                got = True
                usd = float(row.get("usage") or 0)
                by_day[day] = by_day.get(day, 0.0) + usd
                model = str(row.get("model") or "?").split("/")[-1]
                by_model[model] = by_model.get(model, 0.0) + usd
        if got:
            lines.append("\nПо дням (UTC): " + "; ".join(f"{d[5:]}: {money(v)}" for d, v in sorted(by_day.items())))
            total = sum(by_model.values()) or 1
            lines.append("По моделям:")
            for m, v in sorted(by_model.items(), key=lambda kv: -kv[1])[:6]:
                lines.append(f"• {m}: {money(v)} ({round(100 * v / total)}%)")
        else:
            lines.append("\nПо дням и моделям OpenRouter данных не вернул (завершённых дней мало или ключ не управляющий).")
    return "\n".join(lines)[:3900]


async def post_cost_line(db, tz, days: int = 7) -> str:
    """Средневзвешенная цена одного поста (слово владельца 05.11.2026): все расходы завода по учёту за дни, где учёт есть, делим на все созданные за эти дни посты
    (и вышедшие, и снятые, и не вышедшие) и на оставшиеся живыми. Это все-включено: ответы, проверки, обходы, самоулучшение."""
    now = datetime.now(tz)
    total, ledger_days = 0.0, []
    for i in range(days):
        day = (now - timedelta(days=i)).date()
        raw = await db.kv_get(f"cost:{day.isoformat()}")
        if raw:
            total += sum(v[1] for v in json.loads(raw).values())
            ledger_days.append(day)
    if not ledger_days:
        return "Цена поста: учёта расходов ещё нет."
    first = min(ledger_days)
    since = datetime.combine(first, datetime.min.time(), tz).astimezone(timezone.utc).isoformat()
    rows = await db._rows("SELECT status, COUNT(*) AS n FROM posts WHERE created_at >= ? GROUP BY status", (since,))
    made = sum(int(r["n"]) for r in rows)
    alive = sum(int(r["n"]) for r in rows if r["status"] == "published")
    if not made:
        return f"Цена поста: расходы {money(total)} за {len(ledger_days)} дн., постов за это время нет."
    line = f"Цена поста (всё включено, {len(ledger_days)} дн. учёта): {money(total)} ÷ {made} созданных = {money(total / made)}"
    if alive and alive != made:
        line += f"; на один оставшийся живым ({alive}) = {money(total / alive)}"
    return line


# Жёсткий дневной потолок расходов завода (слово владельца 05.11.2026: «2,55 за день — непозволительно много; меньше доллара»). Считается на каждый экземпляр (RU и EN): вместе ≈ $0,8 + ответы.
SOFT_USD = 0.30   # дальше необязательные проверки (цельность, оценка, обходы, сводки) не запускаются: пост выходит как есть или не выходит по правилам кода
HARD_USD = 0.40   # дальше новые посты не пишутся до завтра


async def today_total(db, tz) -> float:
    raw = await db.kv_get(day_key(datetime.now(tz)))
    return sum(v[1] for v in json.loads(raw).values()) if raw else 0.0


def make_guard(db, tz):
    async def guard() -> float:
        return await today_total(db, tz)
    return guard
