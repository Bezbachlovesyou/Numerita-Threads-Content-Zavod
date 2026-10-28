"""ДНК и геном (слово владельца 28.10.2026: «изучи геном глубоко и внедри в базу знаний — устройство, расшифровка,
редактирование, на что влияет, мифы, тайны, курьёзы, прорывы»). Материал: knowledge/research/dna_genome.json,
обзор и границы — docs/dna-genome-research.md. К теме поста или комментария про ДНК/гены подмешиваются правило
честности и несколько самых подходящих проверенных фактов — коротко, чтобы не раздувать цену ответа."""

import json
import re
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "knowledge" / "research" / "dna_genome.json"
TRIGGER = re.compile(r"ДНК|DNA|геном|\bген(ы|ов|ам|ами|ах|е|а|ом)?\b|генетик|генетич|CRISPR|хромосом|наследствен|"
                     r"секвенир|эпигенет|мутаци|нуклеотид|двойн\w* спирал", re.I)
RULE = ("Числа рождения, нумерология и астрология не связаны с ДНК и ничего не говорят о генах и рисках; ДНК в наших "
        "текстах — только метафора («ДНК характера»). Мысли, слова, музыка (528 Гц) и аффирмации последовательность ДНК "
        "не меняют. Без медицинских советов: наследственные вопросы — к врачу-генетику. Легенды называть легендами.")
WORD = re.compile(r"[а-яёa-z0-9]{4,}", re.I)


@lru_cache(maxsize=1)
def data() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def _items() -> list[str]:
    d = data()
    out = [p["text"] for s in d["sections"] for p in s["points"]]
    out += [f"Миф: {m['myth']} Правда: {m['truth']}" for m in d["myths"]]
    out += [f"{f['text']} ({'проверено' if f.get('status') == 'проверено' else 'легенда'})" for f in d["fun_facts"]]
    return out


def excerpt(topic: str, limit: int = 4) -> dict | None:
    if not topic or not TRIGGER.search(topic):
        return None
    words = {w.lower()[:6] for w in WORD.findall(topic)}
    scored = sorted(_items(), key=lambda t: -len(words & {w.lower()[:6] for w in WORD.findall(t)}))
    return {"rule": RULE, "facts": scored[:limit]}
