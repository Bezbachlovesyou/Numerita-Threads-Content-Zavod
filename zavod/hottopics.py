"""«Три числа» — острые темы короткой формой (слово владельца 20.11.2026: у друга в Threads работает «Три знака, к которым сейчас
разворачивается финансовый поток: … твой знак тут? кидай дату рождения, скажу, откуда придут деньги»; «нечто подобное с цифрами:
деньги, отношения, замуж, работа… вот такого типа постить»).

Наша форма — та же простая и цепкая, но честная (knowledge/honesty_policy.json): «по нумерологии» (традиция), без «сейчас
к вам придут деньги» и без обещаний; в ответе — дар по числу человека: через что к нему по традиции приходят деньги, что ищет
его число в браке и т. п. Здоровье — только как силы и энергия, без болезней (табу); страсть — без пошлости.
Текст собирается кодом ($0, без нейросети): заголовок темы, три группы дней рождения, вопрос-обмен. Чередуется с глубокой
серией (deepseries.py): одна публикация в сутки, через день. Деньги — чаще всего (каждая третья тема)."""
from __future__ import annotations

RUBRIC = "text_three"
ENABLED = True
KV_IDX = "three:idx"
CURRENT: dict = {}

GROUPS = {1: "1, 10, 19, 28", 2: "2, 11, 20, 29", 3: "3, 12, 21, 30", 4: "4, 13, 22, 31", 5: "5, 14, 23",
          6: "6, 15, 24", 7: "7, 16, 25", 8: "8, 17, 26", 9: "9, 18, 27"}

KEYCAPS = {n: f"{n}\ufe0f\u20e3" for n in range(1, 10)}

# (ключ, заголовок RU, заголовок EN, три группы по традиции, ответ-обмен RU, EN, тема Threads RU, EN)
MONEY_ASK = ("Твоя дата тут? Напиши день рождения — скажу, откуда к тебе по числу приходят деньги 💰",
             "Is your date here? Drop your birth day — I'll tell you where money comes to you by your number 💰")
TOPICS = [
    ("money", "Три числа рождения с самой сильной денежной жилкой по нумерологии:",
     "Three birth numbers with the strongest money streak in numerology:", (8, 4, 1), *MONEY_ASK, "Нумерология", "Numerology Threads"),
    ("marry", "Три числа рождения, которые по нумерологии созданы для брака:",
     "Three birth numbers that numerology says are made for marriage:", (6, 2, 4),
     "Твоя дата тут? Напиши день рождения — скажу, что твоё число ищет в браке 💍",
     "Is your date here? Drop your birth day — I'll tell you what your number looks for in marriage 💍", "Dating Threads", "Dating Threads"),
    ("work", "Три числа рождения, которым по нумерологии тесно в найме:",
     "Three birth numbers that numerology says feel cramped in a 9-to-5:", (1, 5, 8),
     "Твоя дата тут? Напиши день рождения — скажу, где твоё число раскрывается в работе 🚀",
     "Is your date here? Drop your birth day — I'll tell you where your number shines at work 🚀", "Psychology Threads", "Psychology Threads"),
    ("money_people", "Три числа рождения, к которым деньги по нумерологии приходят через людей:",
     "Three birth numbers that, in numerology, earn through people:", (2, 3, 6), *MONEY_ASK, "Нумерология", "Numerology Threads"),
    ("love", "Три числа рождения, которые любят сильнее всех — и молчат об этом:",
     "Three birth numbers that love the hardest — and never say it:", (7, 4, 8),
     "Твоя дата тут? Напиши день рождения — скажу, как любит твоё число ❤️",
     "Is your date here? Drop your birth day — I'll tell you how your number loves ❤️", "Dating Threads", "Dating Threads"),
    ("passion", "Три числа рождения с самым горячим темпераментом по нумерологии:",
     "Three birth numbers with the hottest temper in numerology:", (5, 9, 1),
     "Твоя дата тут? Напиши день рождения — скажу, что зажигает твоё число 🔥",
     "Is your date here? Drop your birth day — I'll tell you what lights your number up 🔥", "Dating Threads", "Dating Threads"),
    ("money_save", "Три числа рождения, которые по нумерологии умеют копить:",
     "Three birth numbers that numerology says know how to save:", (4, 8, 7), *MONEY_ASK, "Нумерология", "Numerology Threads"),
    ("energy", "Три числа рождения, которые по нумерологии отдают больше всех сил другим:",
     "Three birth numbers that numerology says give the most energy to others:", (6, 2, 9),
     "Твоя дата тут? Напиши день рождения — скажу, что возвращает силы твоему числу 🌿",
     "Is your date here? Drop your birth day — I'll tell you what recharges your number 🌿", "Psychology Threads", "Psychology Threads"),
    ("ex", "Три числа рождения, к которым по нумерологии чаще всего возвращаются бывшие:",
     "Three birth numbers that exes keep coming back to, in numerology:", (6, 2, 8),
     "Твоя дата тут? Напиши день рождения — скажу, почему к твоему числу возвращаются 😏",
     "Is your date here? Drop your birth day — I'll tell you why people come back to your number 😏", "Dating Threads", "Dating Threads"),
    ("money_big", "Три числа рождения, которые по нумерологии строят деньги через своё дело:",
     "Three birth numbers that, in numerology, build money through their own business:", (1, 8, 5), *MONEY_ASK, "Нумерология", "Numerology Threads"),
    ("luck", "Три числа рождения, которым по нумерологии чаще везёт:",
     "Three birth numbers that numerology calls the luckiest:", (3, 5, 9),
     "Твоя дата тут? Напиши день рождения — скажу, через что приходит твоя удача 🍀",
     "Is your date here? Drop your birth day — I'll tell you how luck finds your number 🍀", "Нумерология", "Numerology Threads"),
    ("family", "Три числа рождения, из которых по нумерологии выходят самые тёплые родители:",
     "Three birth numbers that numerology says make the warmest parents:", (6, 2, 4),
     "Твоя дата тут? Напиши день рождения — скажу, какой дар твоё число даёт семье 🏡",
     "Is your date here? Drop your birth day — I'll tell you the gift your number brings to family 🏡", "Нумерология", "Numerology Threads"),
    ("money_talent", "Три числа рождения, к которым по нумерологии деньги приходят через талант:",
     "Three birth numbers that, in numerology, earn through talent:", (3, 7, 9), *MONEY_ASK, "Нумерология", "Numerology Threads"),
    ("lead", "Три числа рождения, которые по нумерологии рождены руководить:",
     "Three birth numbers that numerology says are born to lead:", (1, 8, 4),
     "Твоя дата тут? Напиши день рождения — скажу, какой ты руководитель по числу 👑",
     "Is your date here? Drop your birth day — I'll tell you what kind of leader your number is 👑", "Psychology Threads", "Psychology Threads"),
    ("intuition", "Три числа рождения с самой сильной интуицией по нумерологии:",
     "Three birth numbers with the strongest intuition in numerology:", (7, 2, 9),
     "Твоя дата тут? Напиши день рождения — скажу, как говорит интуиция твоего числа 🔮",
     "Is your date here? Drop your birth day — I'll tell you how your number's intuition speaks 🔮", "Нумерология", "Numerology Threads"),
]


def compose(topic: tuple, en: bool) -> str:
    key, head_ru, head_en, groups, ask_ru, ask_en, *_ = topic
    lines = "\n".join(f"{KEYCAPS[g]} {GROUPS[g]}" for g in groups)  # число и дни рождения, которые к нему относятся
    return f"{head_en if en else head_ru}\n\n{lines}\n\n{ask_en if en else ask_ru}"


async def take(db) -> tuple:
    n = int(await db.kv_get(KV_IDX) or 0)
    await db.kv_set(KV_IDX, str(n + 1))
    topic = TOPICS[n % len(TOPICS)]
    CURRENT.clear()
    CURRENT["topic"] = topic
    return topic


def turn(recent: list[str]) -> bool:
    """Через день с глубокой серией: «Три числа», если прошлый пост был не «Три числа»."""
    return ENABLED and (not recent or recent[0] != RUBRIC)


def topic(en: bool) -> str | None:
    t = CURRENT.get("topic")
    return (t[7] if en else t[6]) if t else None
