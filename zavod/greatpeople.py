"""Нумерологический разбор великих людей (слово владельца 01.11.2026: лаконично, с числами души и миссии, на русском и английском аккаунтах).

Люди, даты рождения и по одному проверенному факту — из knowledge/formats/great_people.json (только общеизвестные даты, без политиков, военных,
участников скандалов, трагедий и болезней; даты по новому стилю). Числа считает КОД: число души — день рождения, сведённый к цифре; число миссии
(судьбы) — сумма всех цифр даты, сведённая к цифре, по правилам базы знаний. Модель ничего не считает и фактов сверх данных не добавляет;
это символический образ, а не доказательство и не диагноз (knowledge/honesty_policy.json)."""

import json
import random
from collections import deque
from datetime import date
from functools import lru_cache
from pathlib import Path

from .knowledge import reduce_number

PATH = Path(__file__).resolve().parent.parent / "knowledge" / "formats" / "great_people.json"
PLANETS_EN = {1: "Sun", 2: "Moon", 3: "Jupiter", 4: "Rahu", 5: "Mercury", 6: "Venus", 7: "Ketu", 8: "Saturn", 9: "Mars"}
PLANETS_RU = {1: "Солнце", 2: "Луна", 3: "Юпитер", 4: "Раху", 5: "Меркурий", 6: "Венера", 7: "Кету", 8: "Сатурн", 9: "Марс"}
RECENT: deque = deque(maxlen=14)  # недавние выбранные, чтобы не повторять подряд


@lru_cache(maxsize=1)
def people() -> list[dict]:
    return json.loads(PATH.read_text(encoding="utf-8"))


def numbers(born: str) -> dict:
    """Числа даты ГГГГ-ММ-ДД: душа (день → цифра), миссия (все цифры даты → цифра) и промежуточные суммы для показа расчёта."""
    d = date.fromisoformat(born)
    total = sum(int(c) for c in d.strftime("%d%m%Y"))
    return {"day": d.day, "soul": reduce_number(d.day), "sum": total, "mission": reduce_number(total), "date": d}


def pick(rng: random.Random, en: bool) -> dict:
    pool = [p for p in people() if not en or p["audience"] == "both"]
    fresh = [p for p in pool if p["ru"] not in RECENT] or pool
    person = rng.choice(fresh)
    RECENT.append(person["ru"])
    return person


def block(person: dict, en: bool) -> str:
    """Данные для задания: имя, дата, посчитанные кодом числа и один проверенный факт (модель их не меняет и не дополняет)."""
    n = numbers(person["born"])
    d = n["date"]
    if en:
        return (f"Person: {person['en']}, {person['field_en']}, born {d.day} {d.strftime('%B %Y')}. Computed by code (do not recalculate): soul number {n['soul']} "
                f"(birth day {n['day']}, planet {PLANETS_EN[n['soul']]}); mission number {n['mission']} (all digits of the date add to {n['sum']}, reduced to {n['mission']}, planet {PLANETS_EN[n['mission']]}). "
                f"Verified fact: {person['fact_en']} Use only this fact; do not add other life details or quotes.")
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    return (f"Человек: {person['ru']}, {person['field_ru']}, родился {d.day} {months[d.month - 1]} {d.year}. Посчитано кодом (не пересчитывай): число души {n['soul']} "
            f"(день рождения {n['day']}, планета {PLANETS_RU[n['soul']]}); число миссии {n['mission']} (сумма всех цифр даты {n['sum']} → {n['mission']}, планета {PLANETS_RU[n['mission']]}). "
            f"Проверенный факт: {person['fact_ru']} Используй только этот факт, не добавляй других подробностей жизни и цитат.")
