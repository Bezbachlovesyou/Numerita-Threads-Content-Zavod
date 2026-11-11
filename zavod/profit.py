"""Контролёр прибыли — отдельный от контента «агент» (слово владельца 31.10.2026: «все эксперименты, видео, новые площадки,
партнёрства и рекламные кампании не убыточны ни при каких случаях, и это контролирует отдельный агент»).

Без нейросети (арифметика не должна зависеть от настроения модели) и со своими квитанциями. Три раза в день (те же часы,
что у обхода по Голдратту) считает за 7 суток: расходы (нейросеть + записанные траты на эксперименты) против выручки
(оплаты в ⭐ и доллары из статистики основного бота). Выручку, которой нет в данных, не считает нулём: «неизвестно».

Честная граница: сами расходы на посты и ответы — это вложение в рост, и без оплат они дают минус; гарантировать «ни при каких
случаях без убытка» для опыта с неизвестным исходом нельзя. Контролёр делает достижимое: ни одна НОВАЯ платная затрата не
стартует без ворот allow() — либо на неё есть «да» владельца на сумму (authorize), либо она укладывается в долю выручки;
потолок убытка задаёт владелец (loss_budget, по умолчанию 0); при уходе в минус — вопрос владельцу с ‼️ и варианты.
Любая новая платная функция обязана вызывать allow() перед заказом."""

import json
import logging
from datetime import datetime, timedelta

from . import chain

log = logging.getLogger(__name__)

RUN_HOURS = (11, 15, 19)  # как у обхода по Голдратту
STAR_USD = 0.013  # оценка: Telegram выплачивает разработчику около 1,3 цента за ⭐; уточняется по факту выплат
EXPERIMENT_SHARE = 0.3  # какую долю недельной выручки можно пускать на новые опыты
ALARM_EVERY = timedelta(days=7)
# Слово владельца 11.11.2026: «два отчёта с разницей в минуту и разными цифрами; не слать так часто — смотреть на минусы
# по нескольку раз в день негативно влияет на психику». Цифры были верные, но у каждого экземпляра свои (RU и EN
# считают свои расходы). Теперь владельцу пишет только русский экземпляр, раз в неделю (понедельник, вечерний проход),
# бережным тоном; английский считает молча. Подробности — по команде в пульте, когда владелец сам захочет.
REPORT_WEEKDAY = 0  # понедельник


def _day(now: datetime) -> str:
    return now.date().isoformat()


async def record(db, label: str, usd: float, now: datetime) -> None:
    """Записать трату на эксперимент (видео, площадка, партнёрство, реклама) в журнал контролёра."""
    key = f"profit:spend:{_day(now)}"
    data = json.loads(await db.kv_get(key) or "{}")
    data[label] = round(data.get(label, 0.0) + usd, 4)
    await db.kv_set(key, json.dumps(data, ensure_ascii=False))


async def authorize(db, label: str, usd: float) -> None:
    """«Да» владельца на сумму для эксперимента label (накапливается, тратится через allow)."""
    key = f"profit:auth:{label}"
    await db.kv_set(key, f"{float(await db.kv_get(key) or 0) + usd:.4f}")


async def _auth_left(db, label: str) -> float:
    return float(await db.kv_get(f"profit:auth:{label}") or 0)


async def loss_budget(db) -> float:
    return float(await db.kv_get("profit:loss_budget") or 0)


async def costs(db, now: datetime, days: int = 7) -> dict:
    """Расходы за days суток: нейросеть (cost:<дата>) и записанные эксперименты (profit:spend:<дата>)."""
    llm, exp = 0.0, 0.0
    for i in range(days):
        day = _day(now - timedelta(days=i))
        for row in json.loads(await db.kv_get(f"cost:{day}") or "{}").values():
            llm += float(row[1])
        exp += sum(json.loads(await db.kv_get(f"profit:spend:{day}") or "{}").values())
    return {"llm": llm, "experiments": exp, "total": llm + exp}


def revenue(c: dict) -> dict:
    """Выручка из статистики основного бота: ⭐ (оценка по STAR_USD) и доллары; рубли и прочее не пересчитываем."""
    bot = c.get("bot")
    if not bot:
        return {"known": False, "usd": 0.0, "note": "нет данных из бота"}
    usd = bot["stars"] * STAR_USD + bot.get("usd", 0.0)
    note = []
    if bot.get("rub"):
        note.append(f"плюс {bot['rub']:.0f} ₽, в доллары не пересчитано")
    if not bot["stars"] and not bot.get("usd") and not bot.get("rub") and bot["paid"]:
        note.append(f"оплат {bot['paid']}, но суммы бот не отдаёт: выручка неполная")
    return {"known": True, "usd": usd, "note": "; ".join(note)}


async def state(db, now: datetime, c: dict | None = None, days: int = 7) -> dict:
    c = c or await chain.collect(db, now, days)
    cost, rev = await costs(db, now, days), revenue(c)
    net = rev["usd"] - cost["total"] if rev["known"] else None
    budget = await loss_budget(db)
    if net is None:
        status = "unknown"
    elif net >= 0:
        status = "plus"
    else:
        status = "minus_in_budget" if -net <= budget else "minus"
    # Сколько можно пустить на новые опыты без отдельного «да»: доля выручки минус уже потраченное на опыты.
    allowance = max(0.0, rev["usd"] * EXPERIMENT_SHARE - cost["experiments"]) if status == "plus" else 0.0
    return {"cost": cost, "revenue": rev, "net": net, "status": status, "allowance": allowance, "loss_budget": budget, "chain": c}


async def allow(db, label: str, usd: float, now: datetime) -> tuple[bool, str]:
    """Ворота для новой платной затраты. Решает код: есть «да» владельца на сумму или доля выручки в плюсе."""
    left = await _auth_left(db, label)
    if usd <= left + 1e-9:
        await db.kv_set(f"profit:auth:{label}", f"{left - usd:.4f}")
        await record(db, label, usd, now)
        return True, f"по «да» владельца (осталось ${left - usd:.2f})"
    st = await state(db, now)
    if st["status"] == "plus" and usd <= st["allowance"] + 1e-9:
        await record(db, label, usd, now)
        return True, f"влезает в {int(EXPERIMENT_SHARE * 100)}% недельной выручки (осталось ${st['allowance'] - usd:.2f})"
    why = {"unknown": "выручка неизвестна", "minus": "неделя в минусе", "minus_in_budget": "неделя в минусе",
           "plus": f"доступно только ${st['allowance']:.2f}"}[st["status"]]
    return False, f"отказ: {why}, на ${usd:.2f} нет «да» владельца"


def weekly_line(st: dict) -> str:
    """Одна бережная строка владельцу раз в неделю: вложено в рост и что пришло, без «в минусе сверх потолка»."""
    cost, rev = st["cost"], st["revenue"]
    got = f"оплат пока ${rev['usd']:.2f}" if rev["known"] else "оплаты пока не видны в данных"
    return (f"🌱 Неделя завода (русский Threads): вложено в рост ${cost['total']:.2f}, {got}. "
            "Новые платные опыты — только по вашему «да» на сумму.")


def lines(st: dict) -> list[str]:
    cost, rev = st["cost"], st["revenue"]
    if not rev["known"]:
        return [f"💰 Контролёр прибыли: за 7 дней расходы ${cost['total']:.2f} (нейросеть ${cost['llm']:.2f}, опыты "
                f"${cost['experiments']:.2f}); выручка неизвестна — {rev['note']}. Новые платные опыты закрыты, пока нет «да» на сумму."]
    verdict = {"plus": "в плюсе", "minus_in_budget": "в минусе, но в пределах вашего потолка",
               "minus": "в минусе сверх потолка", "unknown": "неизвестно"}[st["status"]]
    out = [f"💰 Контролёр прибыли: за 7 дней расходы ${cost['total']:.2f} (нейросеть ${cost['llm']:.2f}, опыты ${cost['experiments']:.2f}), "
           f"выручка ${rev['usd']:.2f}, итог ${st['net']:+.2f} — {verdict}."]
    if rev["note"]:
        out.append("  Выручка: " + rev["note"] + ".")
    out.append(f"  На новые опыты без отдельного «да» доступно ${st['allowance']:.2f}.")
    return out


async def alarm(db, st: dict, now: datetime) -> str | None:
    """‼️ владельцу, когда неделя в минусе сверх потолка: при смене состояния и не чаще раза в 3 дня."""
    if st["status"] != "minus":
        await db.kv_set("profit:alarm_status", st["status"])
        return None
    last = await db.kv_get("profit:alarm_at")
    changed = await db.kv_get("profit:alarm_status") != "minus"
    if not changed and last and now - datetime.fromisoformat(last) < ALARM_EVERY:
        return None
    await db.kv_set("profit:alarm_status", "minus")
    await db.kv_set("profit:alarm_at", now.isoformat())
    cost, rev = st["cost"], st["revenue"]
    return (f"‼️ Контролёр прибыли: за 7 дней расходы ${cost['total']:.2f} при выручке ${rev['usd']:.2f} "
            f"(минус ${-st['net']:.2f}, ваш потолок убытка ${st['loss_budget']:.2f}). Новые платные опыты закрыты. "
            f"Варианты: 1) оставить, это вложение в рост; 2) урезать расходы на ответы (REPLY_BUDGET_USD); "
            f"3) дать «да» на конкретную сумму эксперимента.")


async def run_due(db, now: datetime, tz) -> list[str]:
    """Три раза в день, со своими квитанциями (profit_run:<дата>:<час>). Возвращает сообщения владельцу (только ‼️ и вечерняя строка)."""
    now = now.astimezone(tz)
    notices = []
    for hour in RUN_HOURS:
        if not hour <= now.hour < hour + 2:
            continue
        key = f"profit_run:{_day(now)}:{hour}"
        tries = int(await db.kv_get(key + ":tries") or 0)
        if await db.kv_get(key) == "success" or tries >= 3:
            continue
        await db.kv_set(key + ":tries", str(tries + 1))
        try:
            c = await chain.collect(db, now)
            await chain.snapshot(db, now, c)
            st = await state(db, now, c)
            await db.kv_set("profit:last", json.dumps({"at": now.isoformat(), "status": st["status"], "net": st["net"]}))
            from . import lang
            weekly = not lang.is_en() and now.weekday() == REPORT_WEEKDAY and hour == RUN_HOURS[-1]
            if weekly:  # раз в неделю, только русский экземпляр, одна бережная строка (11.11.2026)
                await db.kv_set("profit:alarm_status", st["status"])
                await db.kv_set("profit:alarm_at", now.isoformat())
                notices.append(weekly_line(st))
            await db.kv_set(key, "success")
        except Exception:
            log.exception("Контролёр прибыли: проход %s не удался", key)
            await db.kv_set(key, "failed")
    return notices
