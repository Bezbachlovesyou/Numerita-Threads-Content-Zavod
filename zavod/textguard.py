"""Контролёр текста и ответа (урок ментора Влада 29.10.2026: «все наказания аккаунтов были за содержимое, а не за
темп: одинаковые тексты и мусор в ответах»).

- Антидубль: сравнение по тройкам слов, порог 35% совпадения; первая строка (заголовок) — больше 80% общих слов;
  вопрос в конце сверяется отдельно — он приедается быстрее всего.
- Мусор: неподставленные переменные, плейсхолдеры, markdown — такой текст не уходит никогда.
"""

import re

WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
SHINGLE_LIMIT = 0.35
TITLE_LIMIT = 0.8
QUESTION_LIMIT = 0.8
GARBAGE = re.compile(
    r"\$\{|\{[a-z_]+\}|\{\{|\}\}|\*\*|__|^#{1,6}\s|\[(?:адрес|ссылка|link|имя|name)[^\]]*\]|\bundefined\b|\bNone\b|"
    r"\bnull\b|<[a-z/][^>]*>|\{LINK\}|```", re.IGNORECASE | re.MULTILINE)


# Призывы ради реакций (Meta: vote/react/share/tag/comment bait) и розыгрыши — Threads не рекомендует такие посты
# людям, которые на нас не подписаны, а повторы снимают рекомендации со всего аккаунта (29.10.2026).
BAIT = re.compile(
    r"лайк(?:ни|ай)?,?\s+если|ставь(?:те)?\s+(?:лайк|сердечк|❤)|за\s+лайк|репост|сделай(?:те)?\s+репост|поделись|"
    r"перешли|отметь(?:те)?\b|тегни|сохрани(?:те)?\b|голосуй|проголосуй|напиши(?:те)?\s+[«\"]?(?:да|\+|1)[»\"]?\s|"
    r"розыгрыш|разыгрыва|конкурс|победител|giveaway|подпишись|подписывайся", re.IGNORECASE)


def bait(text: str) -> str | None:
    m = BAIT.search(text or "")
    return m.group(0) if m else None


def words(text: str) -> list[str]:
    return [w.lower().replace("ё", "е") for w in WORD.findall(text or "")]


def shingles(text: str, n: int = 3) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)} if len(w) >= n else ({tuple(w)} if w else set())


def similarity(a: str, b: str) -> float:
    """Доля общих троек слов от меньшего текста: 1.0 — один текст целиком внутри другого."""
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def word_overlap(a: str, b: str) -> float:
    wa, wb = set(words(a)), set(words(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def first_line(text: str) -> str:
    return next((line for line in (text or "").splitlines() if line.strip()), "")


def last_question(text: str) -> str:
    found = re.findall(r"[^.!?…\n]*\?", text or "")
    return found[-1].strip() if found else ""


def garbage(text: str) -> str | None:
    m = GARBAGE.search(text or "")
    return m.group(0) if m else None


def post_problem(text: str, recent: list[str]) -> str | None:
    """Почему пост нельзя выпускать как есть, или None."""
    if junk := garbage(text):
        return f"служебный мусор «{junk}»"
    if hook := bait(text):
        return f"призыв ради реакций «{hook}» — Threads не рекомендует такие посты; дай причину ответить без призыва"
    title, question = first_line(text), last_question(text)
    for old in recent:
        if similarity(text, old) >= SHINGLE_LIMIT:
            return "слишком похож на прошлый пост: «" + first_line(old)[:60] + "»"
        if len(words(title)) >= 4 and word_overlap(title, first_line(old)) > TITLE_LIMIT:
            return "первая строка повторяет прошлую: «" + first_line(old)[:60] + "»"
    for old in recent[:30]:
        q = last_question(old)
        if question and q and len(words(question)) >= 3 and word_overlap(question, q) > QUESTION_LIMIT:
            return "вопрос в конце уже был: «" + q[:60] + "»"
    return None


def reply_problem(text: str, recent: list[str]) -> str | None:
    """Почему ответ нельзя отправлять как есть, или None."""
    if junk := garbage(text):
        return f"служебный мусор «{junk}»"
    for old in recent:
        if len(words(text)) >= 8 and similarity(text, old) >= SHINGLE_LIMIT:
            return "повторяет недавний ответ"
    return None
