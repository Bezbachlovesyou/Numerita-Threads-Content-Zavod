"""Игра «Угадай число»: от внимания к личному (слово владельца 31.10.2026: «рубрика даёт отклик в 10 раз активнее — как конвертировать
его в бота? сделать такие игры в Нумерите: люди высматривают, подмечают, потом слушают, что это значит»).

Разбор по шести операциям. Анализ: игра цепляет, потому что есть задание с проверяемым ответом, чувство «я нашёл», азарт и сравнение с другими, а отвечать
легко (написать число). Но ответ не личный и ничего не говорит о человеке, поэтому в боте ему нечего делать. Сравнение: сильные игры («что ты увидел первым»)
дают человеку зеркало. Абстракция: игра ценна, когда рождает ЛИЧНЫЙ выбор («моё число»), который можно прочитать и который открывает следующий вопрос.
Обобщение: каждая игра = действие человека → честное прочтение его выбора → следующий личный ввод (день рождения, год, время, пара). Синтез: «игра-зеркало» — ответ
под матрицей проверяет КОД (нашёл k из N спрятанных, пасхалка), прочтение строится по расчёту кода (цифры и сумма → планета), затем мост к дню рождения.
Конкретизация: check() / note() / record() ниже; итоги выпуска копятся для постов «что замечали чаще всего»; игры для бота — docs/game-design.md.

Честность: это игра-образ, а не тест личности и не диагноз; повтор цифры не усиливает планету по науке — только по языку символов."""

import json
import re

from .cards import PLANETS, SEQUENCES
from .knowledge import reduce_number

TOKEN = re.compile(r"(?<!\d)(\d{3,4})(?!\d)")
KEEP_IDS = 400


def tokens(comment: str) -> list[str]:
    """Числа из 3–4 цифр в комментарии без повторов, в порядке появления («111 и 777», «нашла 1234!»)."""
    seen, out = set(), []
    for t in TOKEN.findall(comment or ""):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def check(comment: str, hidden: list[str], egg: str | None = None) -> dict:
    """Что нашёл человек: найденные из спрятанных, пасхалка, числа вне матрицы, сколько ещё осталось (без названий)."""
    toks = tokens(comment)
    found = [t for t in toks if t in hidden]
    return {"tokens": toks, "found": found, "egg": bool(egg and egg in toks), "outside": [t for t in toks if t not in hidden and t != egg],
            "total": len(hidden), "left": len(hidden) - len(set(found)), "first": toks[0] if toks else None}


def reading(seq: str) -> str:
    """Расчёт кода для числа: цифры, сумма, планета суммы — основа прочтения (модель сама не считает)."""
    total = sum(int(c) for c in seq)
    soul = reduce_number(total)
    if len(set(seq)) == 1:
        d = int(seq[0])
        head = f"{seq}: цифра {d} ({PLANETS.get(d, '?')}) повторена {len(seq)} раза"
    else:
        head = f"{seq}: цифры " + ", ".join(f"{c} ({PLANETS.get(int(c), '?')})" for c in seq)
    return f"{head}; сумма {total} → {soul} ({PLANETS.get(soul, '?')})"


def note(chk: dict, egg: str | None = None) -> str:
    """Добавка к заданию ответа под матрицей: игра-зеркало (прочтение выбора человека) и мост к личному."""
    if not chk["tokens"]:
        lead = ("Человек ничего не назвал из спрятанных чисел (но играет): подбодри, подскажи, куда смотреть (по краям и в углах), "
                "не называя ни одного спрятанного числа.")
        body = ""
    else:
        found = ", ".join(chk["found"]) or "ничего из спрятанного"
        lead = (f"КОД ПРОВЕРИЛ ОТВЕТ: найдено {len(set(chk['found']))} из {chk['total']} спрятанных ({found})"
                + ("; пасхалку без подсветки он нашёл — похвали и раскрой её смысл" if chk["egg"] else "")
                + (f"; ещё осталось {chk['left']} (какие — не называй)" if chk["left"] else "; нашёл все спрятанные") + ".")
        picks = chk["found"] or chk["outside"][:2]
        body = " Расчёты кода для его чисел: " + " | ".join(reading(t) for t in picks[:3]) + "."
        if chk["outside"] and chk["found"]:
            body += f" Числа вне этой матрицы ({', '.join(chk['outside'][:3])}) назови красивыми, но в этом выпуске их нет."
        elif chk["outside"]:
            body += " Таких чисел в этой матрице нет — но они красивые: мягко скажи и подсказывай, не называя ответы."
    return (
        "\n\nИГРА «УГАДАЙ ЧИСЛО» — порядок ответа. " + lead + body + " 1) Сначала азарт и юмор: рада его находке. 2) Затем прочти его выбор как ИГРУ-ЗЕРКАЛО "
        "по расчётам кода (цифры и планеты, сумма): что его взгляд поймал первым, как образ из языка чисел; честно: это игра-образ, а не тест и не диагноз. "
        "Не выдумывай значений сверх базы знаний и расчётов. 3) Затем одной фразой мост к личному: число притяжения — это игра, а число души считается по "
        "дню рождения; напиши день рождения числом — скажу, совпал ли твой взгляд с твоим числом. Приглашение в бота — только если его просит задание, без давления.")


async def grid_of(db, post_id: int | None) -> dict | None:
    """Данные матрицы поста (спрятанное, пасхалка) или None, если пост — не матрица."""
    if not post_id:
        return None
    post = await db.get(post_id)
    if not post or post.rubric != "grid" or not post.card:
        return None
    try:
        grid = (json.loads(post.card) or {}).get("grid")
    except ValueError:
        return None
    return grid if grid and grid.get("hidden") else None


async def record(db, post_id: int, comment_id: str, chk: dict) -> None:
    """Копим ответы выпуска: сколько человек нашли какое число, какое называли первым (для постов-итогов). Повтор того же комментария не считается."""
    key = f"game:{post_id}"
    data = json.loads(await db.kv_get(key) or "{}") or {"n": 0, "found": {}, "first": {}, "egg": 0, "seen": []}
    if comment_id in data["seen"]:
        return
    data["seen"] = (data["seen"] + [comment_id])[-KEEP_IDS:]
    data["n"] += 1
    for t in set(chk["found"]):
        data["found"][t] = data["found"].get(t, 0) + 1
    if chk["first"]:
        data["first"][chk["first"]] = data["first"].get(chk["first"], 0) + 1
    data["egg"] += int(chk["egg"])
    await db.kv_set(key, json.dumps(data, ensure_ascii=False))


async def results(db, post_id: int) -> dict | None:
    data = json.loads(await db.kv_get(f"game:{post_id}") or "{}")
    return data or None


def results_line(data: dict | None, top: int = 4) -> str:
    """Итоги выпуска одной строкой: сколько играло, что находили чаще всего, пасхалка (для постов «что замечали чаще всего»)."""
    if not data or not data.get("n"):
        return "ответов пока нет"
    top_found = sorted(data["found"].items(), key=lambda kv: -kv[1])[:top]
    first = sorted(data["first"].items(), key=lambda kv: -kv[1])[:3]
    parts = [f"играло {data['n']}"]
    if top_found:
        parts.append("чаще всего находили " + ", ".join(f"{k} ({v})" for k, v in top_found))
    if first:
        parts.append("первым называли " + ", ".join(f"{k} ({v})" for k, v in first))
    if data.get("egg"):
        parts.append(f"пасхалку нашли {data['egg']}")
    return "; ".join(parts)


def known_sequence(token: str) -> bool:
    return token in SEQUENCES
