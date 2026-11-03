"""Серии и лучшие часы (слово владельца 03.11.2026: «серии вместо случайной ленты; лучшие форматы в лучшие часы»).

Данные Threads за 30 дней: 19,4 тыс. зрителей, из них подписчиков 105 — охват есть, причины подписаться нет. Серия — узнаваемая «передача» в постоянный день и час: человек понимает, что завтра
или на следующей неделе будет продолжение. Лучшие часы по статистике аккаунта (МСК): среда и четверг 18–21, воскресенье 9–12.
- Ср 18–21: матрица «Угадай число» (держит охват 1,5–6,5 тыс.) — вес матрицы в этом окне ×5 (autopost.choose(now=…)).
- Чт 18–21: «Дата рождения и любовь» — формат-список text_marriage («Твоя дата рождения раскрывает твою энергию в…», 3,6 тыс. просмотров), а раз в неделю — «Пара недели».
- Вс 9–12: «Роль твоего числа» — text_roles («Твоя дата рождения = твоя роль главного героя», 1,6 тыс.).
Последней строкой серия называется («🗓 По четвергам — …»): это информация, не призыв. Одна серийная публикация на окно."""

from datetime import datetime

# weekday (0=пн) → (час начала, час конца, ключ рубрики, название RU, название EN, фраза RU, фраза EN)
WINDOWS = {
    3: (18, 21, "text_marriage", "Дата рождения и любовь", "Birth date and love",
        "🗓 По четвергам вечером — «Дата рождения и любовь»", "🗓 Thursday evenings — \"Birth date and love\""),
    6: (9, 12, "text_roles", "Роль твоего числа", "Your number's role",
        "🗓 По воскресеньям утром — «Роль твоего числа»", "🗓 Sunday mornings — \"Your number's role\""),
}
GRID_WINDOW = (2, 18, 21)  # среда 18–21: матрица «Угадай число»
PAIR_LABEL = ("🗓 Раз в неделю — «Пара недели»", "🗓 Once a week — \"Couple of the week\"")
GRID_BOOST = 5.0


def in_grid_window(now: datetime) -> bool:
    return now.weekday() == GRID_WINDOW[0] and GRID_WINDOW[1] <= now.hour < GRID_WINDOW[2]


def window_rubric(now: datetime):
    """Рубрика серии для текущего окна или None."""
    row = WINDOWS.get(now.weekday())
    if row and row[0] <= now.hour < row[1]:
        return row
    return None


async def due(db, now: datetime):
    """Запись окна, если серия ещё не выходила в это окно (один раз за окно), иначе None."""
    row = window_rubric(now)
    if not row or await db.kv_get(f"series:{now.date().isoformat()}:{row[2]}"):
        return None
    return row


async def mark(db, now: datetime, key: str) -> None:
    await db.kv_set(f"series:{now.date().isoformat()}:{key}", "1")


def label(key: str, en: bool) -> str | None:
    if key == "text_pair_week":
        return PAIR_LABEL[1 if en else 0]
    for row in WINDOWS.values():
        if row[2] == key:
            return row[6] if en else row[5]
    return None


LABELS_ENABLED = False  # слово владельца 03.11.2026: расписание по дням недели людям не показываем (ни в профиле, ни в постах) — «мелкая хрень, делать из этого целый день»; серии работают тихо, только по времени


def with_label(text: str, key: str, en: bool, limit: int = 500) -> str:
    """Дописать название серии последней строкой (если помещается и не выключено)."""
    if not LABELS_ENABLED:
        return text
    line = label(key, en)
    if not line or line in text:
        return text
    joined = f"{text.rstrip()}\n\n{line}"
    return joined if len(joined) <= limit else text
