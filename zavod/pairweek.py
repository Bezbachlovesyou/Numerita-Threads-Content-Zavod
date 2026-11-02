"""«Пара недели» (рубрика text_pair_week; слово владельца 02.11.2026 через ветку основного бота; поправки владельца: без процентов совместимости — «совместимость в процентах не измерить»,
без политиков, без пар с трагедиями и болезнями). Раз в неделю: одна известная пара — числа души и судьбы каждого (считает код), знак Солнца и стихия (считает код), один проверенный факт из
knowledge/formats/pairs_week.json и мостик «проверь свою пару» со ссылкой `ad_th_pair` (первым комментарием, как все ссылки в постах — не чаще раза в двое суток).
Модель ничего не считает, факты не меняет; это образ, а не приговор и не измерение."""

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .greatpeople import PLANETS_EN, PLANETS_RU, numbers

PATH = Path(__file__).resolve().parent.parent / "knowledge" / "formats" / "pairs_week.json"
EVERY = timedelta(days=6, hours=12)
HOURS = range(12, 21)  # окно публикации (МСК), когда живая аудитория
SIGNS = [  # (месяц, день начала, знак ru, знак en, стихия ru, стихия en)
    (1, 20, "Водолей", "Aquarius", "воздух", "air"), (2, 19, "Рыбы", "Pisces", "вода", "water"), (3, 21, "Овен", "Aries", "огонь", "fire"),
    (4, 20, "Телец", "Taurus", "земля", "earth"), (5, 21, "Близнецы", "Gemini", "воздух", "air"), (6, 21, "Рак", "Cancer", "вода", "water"),
    (7, 23, "Лев", "Leo", "огонь", "fire"), (8, 23, "Дева", "Virgo", "земля", "earth"), (9, 23, "Весы", "Libra", "воздух", "air"),
    (10, 23, "Скорпион", "Scorpio", "вода", "water"), (11, 22, "Стрелец", "Sagittarius", "огонь", "fire"), (12, 22, "Козерог", "Capricorn", "земля", "earth")]


@lru_cache(maxsize=1)
def pairs() -> list[dict]:
    return json.loads(PATH.read_text(encoding="utf-8"))


def sun_sign(d: date) -> tuple:
    """Знак Солнца по дате (границы по сезонам): возвращает запись SIGNS."""
    current = SIGNS[-1]  # до 19 января — Козерог
    for row in SIGNS:
        if (d.month, d.day) >= (row[0], row[1]):
            current = row
    return current if (d.month, d.day) >= (1, 20) or d.month > 1 else SIGNS[-1]


def person_line(person: dict, en: bool) -> str:
    n = numbers(person["born"])
    s = sun_sign(n["date"])
    name = person["en"] if en else person["ru"]
    if en:
        return f"{name}: soul {n['soul']} ({PLANETS_EN[n['soul']]}), destiny {n['mission']} ({PLANETS_EN[n['mission']]}), Sun in {s[3]} ({s[5]})"
    return f"{name}: душа {n['soul']} ({PLANETS_RU[n['soul']]}), судьба {n['mission']} ({PLANETS_RU[n['mission']]}), Солнце — {s[2]} ({s[4]})"


def block(pair: dict, en: bool) -> str:
    """Данные для задания: посчитаны кодом, модель их не меняет."""
    a, b = pair["a"], pair["b"]
    sa, sb = sun_sign(date.fromisoformat(a["born"])), sun_sign(date.fromisoformat(b["born"]))
    same = sa[5] == sb[5] if en else sa[4] == sb[4]
    if en:
        element = f"same element ({sa[5]})" if same else f"elements {sa[5]} and {sb[5]}"
        return (f"Couple of the week. Computed by code (do not recalculate): {person_line(a, True)}; {person_line(b, True)}; {element}. "
                f"Verified fact (use only this): {pair['fact_en']} No percentages, no verdict: compatibility cannot be measured in percent — it is an image of two numbers and two skies.")
    element = f"одна стихия ({sa[4]})" if same else f"стихии {sa[4]} и {sb[4]}"
    return (f"Пара недели. Посчитано кодом (не пересчитывай): {person_line(a, False)}; {person_line(b, False)}; {element}. "
            f"Проверенный факт (используй только его): {pair['fact_ru']} Никаких процентов и приговоров: совместимость в процентах не измерить — это образ двух чисел и двух небес.")


async def due(db, now: datetime) -> bool:
    """Пора ли выпускать пару недели: прошло 6,5 суток, дневное окно по МСК."""
    if now.hour not in HOURS:
        return False
    last = await db.kv_get("pairweek:last")
    return not last or now - datetime.fromisoformat(last) >= EVERY


async def take(db, now: datetime, en: bool) -> dict:
    """Следующая пара по кругу (EN — только мировые имена); запоминает выбор."""
    idx = int(await db.kv_get("pairweek:idx") or 0)
    pool = [p for p in pairs() if not en or p["audience"] == "both"]
    pair = pool[idx % len(pool)]
    await db.kv_set("pairweek:idx", str(idx + 1))
    await db.kv_set("pairweek:last", now.isoformat())
    return pair
