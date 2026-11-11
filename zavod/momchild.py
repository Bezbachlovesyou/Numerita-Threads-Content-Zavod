"""«Мама и ребёнок по числам» — ветка-таблица (рубрика text_mom_child; слово владельца 11.11.2026: чужой формат «дети по месяцу
рождения мамы» собрал 107 тыс. просмотров и 252 комментария — «проработаем, изучим, внедрим с нашей интригой, кульминацией, хуком»).

Что берём у формата: таблица, где каждый находит себя и своего ребёнка (узнавание → комментарий «я 6, сын 4»), ветка 1/3–3/3
(дочитывание), смягчающая кульминация в конце. Что делаем по-своему и честно: вместо выдуманных «кармических месяцев» — числа души
(день рождения, сведённый к цифре) и то, как эти числа ладят по базе Нумериты (kb.json → pairs, поле tone). Ни один ребёнок не
«несовместим»: трудная пара чисел названа «ребёнок-учитель» — рядом с ним взрослый растёт сам. Это язык символов, не диагноз.
Всё кодом, $0: модель арифметику и таблицу не трогает.
"""

DAYS = {1: "1, 10, 19, 28", 2: "2, 11, 20, 29", 3: "3, 12, 21, 30", 4: "4, 13, 22, 31", 5: "5, 14, 23", 6: "6, 15, 24",
        7: "7, 16, 25", 8: "8, 17, 26", 9: "9, 18, 27"}
# Снимок kb.json → pairs[tone] на 11.11.2026 (good — ладят легко, hard — точка роста); сверяется тестом и tones(kb).
GOOD = {1: [2, 3], 2: [1, 3, 9], 3: [1, 2, 3, 8, 9], 4: [5, 8], 5: [4, 6, 7], 6: [5, 9], 7: [5], 8: [3, 4, 9], 9: [2, 3, 6, 8]}
HARD = {1: [4], 2: [4, 7], 3: [7], 4: [1, 2, 4, 6, 9], 5: [], 6: [4, 7], 7: [2, 3, 6], 8: [], 9: [4]}
LIMIT = 500  # знаков в одном посте Threads

WORDS = {
    "ru": {
        "mom": {"who": "Мама", "hook": "Почему с одним ребёнком легко, а с другим — как с инопланетянином? 🤱",
                "grow": "рядом с кем мама растёт сама", "ask": "Напишите своё число и число ребёнка"},
        "dad": {"who": "Папа", "hook": "Почему с одним ребёнком папе легко, а с другим — как с инопланетянином? 👨‍👧",
                "grow": "рядом с кем папа растёт сам", "ask": "Напишите своё число и число ребёнка"},
        "rule": "Сложите цифры дня рождения до одной: 24 → 2+4 = 6. Так считают и взрослого, и ребёнка.",
        "tease": "У двух из девяти ребёнка-учителя нет совсем. У одного их пять. Найдите себя 👇",
        "days": "дни", "easy": "С полуслова: дети", "teacher": "Ребёнок-учитель:", "none": "Ребёнка-учителя нет: ключ находится к любому",
        "next": "Дальше 👇",
        "final": "⚠️ Ребёнок-учитель — не трудный ребёнок. Это тот, {grow}. Остальные числа вас дополняют.\n"
                 "Это язык чисел, образ, а не диагноз.\n\n{ask} — скажу, чему вы учите друг друга.",
    },
    "en": {
        "mom": {"who": "Mom", "hook": "Why is one child easy, and the other feels like an alien? 🤱",
                "grow": "who makes a mom grow", "ask": "Share your number and your child's"},
        "dad": {"who": "Dad", "hook": "Why is one child easy for dad, and the other feels like an alien? 👨‍👧",
                "grow": "who makes a dad grow", "ask": "Share your number and your child's"},
        "rule": "Add the birthday digits down to one: 24 → 2+4 = 6. Same for parent and child.",
        "tease": "Two of the nine have no teacher child at all. One has five. Find yourself 👇",
        "days": "born on", "easy": "Clicks instantly: kids", "teacher": "Teacher child:", "none": "No teacher child: you find a key to any",
        "next": "More 👇",
        "final": "⚠️ A teacher child is not a difficult child. It's the one {grow}. The rest complement you.\n"
                 "A language of numbers, not a diagnosis.\n\n{ask} — I'll tell you what you teach each other.",
    },
}


def tones(kb: dict) -> tuple[dict, dict]:
    """(GOOD, HARD) из живой базы: kb["pairs"]["a-b"]["tone"]."""
    good, hard = {m: [] for m in range(1, 10)}, {m: [] for m in range(1, 10)}
    for m in range(1, 10):
        for c in range(1, 10):
            a, b = sorted((m, c))
            tone = kb["pairs"][f"{a}-{b}"]["tone"]
            if tone == "good":
                good[m].append(c)
            elif tone == "hard":
                hard[m].append(c)
    return good, hard


def _block(n: int, w: dict, who: str, good: dict, hard: dict) -> str:
    nums = lambda xs: ", ".join(map(str, xs))
    teacher = f"• {w['teacher']} {nums(hard[n])}" if hard[n] else f"• {w['none']}"
    return f"✨ {who} {n} ({w['days']} {DAYS[n]})\n• {w['easy']} {nums(good[n])}\n{teacher}"


def thread(lang: str = "ru", who: str = "mom", kb: dict | None = None) -> list[str]:
    """Три поста ветки: 1/3 хук, правило и интрига + числа 1–3; 2/3 — числа 4–6; 3/3 — числа 7–9 и кульминация."""
    w = WORDS[lang]
    p = w[who]
    good, hard = tones(kb) if kb else (GOOD, HARD)
    blocks = [_block(n, w, p["who"], good, hard) for n in range(1, 10)]
    items = [
        "\n\n".join([p["hook"], w["rule"] + "\n" + w["tease"], *blocks[:3]]),
        "\n\n".join([*blocks[3:6], w["next"]]),
        "\n\n".join([*blocks[6:], w["final"].format(grow=p["grow"], ask=p["ask"])]),
    ]
    for i, item in enumerate(items):
        if len(item) > LIMIT:
            raise ValueError(f"пост {i + 1} ветки длиннее {LIMIT} знаков: {len(item)}")
    return items
