"""Физика и число (слово владельца 31.10.2026: «физика подтверждена экспериментом, людям это нравится; пусть Нумерита
будет и про науку»). К рубрике text_physics подмешивается один проверенный факт о планете числа души из
knowledge/formats/physics_facts.json — с источником и границей. Модель факты не придумывает: числа, годы и опыты берутся только отсюда.
Метафора остаётся метафорой: физика не доказывает нумерологию (knowledge/honesty_policy.json)."""

import json
import random
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "knowledge" / "formats" / "physics_facts.json"


@lru_cache(maxsize=1)
def data() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def fact_for(digit: int, rng: random.Random) -> str:
    """Строка «Проверенный факт: … (источник: …) Граница: …» для числа души digit (1–9) или пустая строка."""
    items = data().get(str(digit)) or []
    if not items:
        return ""
    f = rng.choice(items)
    return f"Проверенный факт: {f['fact']} (источник: {f['source']}). Граница: {f['limit']}"
