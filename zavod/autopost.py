"""Автопостинг без жёсткого расписания.

Бот сам решает, когда выпустить следующий пост и о чём он будет:
- интервал между постами живой: днём примерно 70–100 минут, ночью реже, со случайным разбросом;
  самоулучшение (optimizer.py) сокращает интервал в часы, когда люди лучше реагируют, и растягивает в слабые,
  но не чаще раза в час — чтобы Threads не принял аккаунт за спам;
- рубрику выбирает по весам: сильные чаще, слабые реже, новые (эксперименты) — с запасом, чтобы успеть проверить;
- ссылка на бота — не в двух постах подряд и не больше чем в 2 из последних 5;
- готовые тексты (prompts/threads_script.md) выходят в первую очередь, через пост.
"""

import logging
import random
import re
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from pathlib import Path

from .cards import PALETTES, PLANETS, birth_days
from .knowledge import reduce_number

log = logging.getLogger(__name__)

DIGIT_WORDS = {1: "единица", 2: "двойка", 3: "тройка", 4: "четвёрка", 5: "пятёрка", 6: "шестёрка",
               7: "семёрка", 8: "восьмёрка", 9: "девятка"}
GENDERS = ["Женщина", "Парень", "Мужчина", "Девушка"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
CTAS = ("link", "reply", "profile", "none")
BOT_LINK = "t.me/Numeritabot?start=ad_th_"

# Безопасный ритм для Threads: никогда не чаще раза в час (лимит API — 250 постов в сутки,
# но частые посты нового аккаунта выглядят как спам), никогда не реже раза в 4 часа.
MIN_GAP = timedelta(minutes=60)
MAX_GAP = timedelta(hours=4)
DAY_GAP = (70, 100)  # минут, 07:00–23:59
NIGHT_GAP = (110, 160)  # минут, 00:00–06:59

# Тема Threads для рубрики: пост показывают тем, кто следит за темой. По умолчанию — нумерология.
TOPIC_TAGS = {"love": "Отношения", "pair": "Отношения", "ex": "Отношения", "wisdom": "Саморазвитие", "money": "Саморазвитие"}
DEFAULT_TOPIC_TAG = "Нумерология"


def topic_tag_for(rubric: str | None) -> str:
    return TOPIC_TAGS.get(rubric or "", DEFAULT_TOPIC_TAG)


def part_of_day(at: time) -> str:
    if at.hour < 5:
        return "глубокая ночь"
    if at.hour < 11:
        return "утро"
    if at.hour < 17:
        return "день"
    if at.hour < 22:
        return "вечер"
    return "поздний вечер"


def soul_group(digit: int) -> str:
    """Дни рождения с этим числом души: 8 → «8, 17, 26»."""
    return ", ".join(str(d) for d in range(1, 32) if reduce_number(d) == digit)


def hour_bucket(hour: int) -> str:
    """Трёхчасовые окна для статистики по времени суток: «0», «3», …, «21»."""
    return str(hour // 3 * 3)


@dataclass(frozen=True)
class Rubric:
    cta: str  # link — ссылка на бота первым комментарием; reply — зовём ответить; profile — «ссылка в профиле»; none
    key: str  # попадает в метку ссылки ad_th_<key>…
    text: str


@dataclass(frozen=True)
class Slot:
    key: str  # защита от дублей
    when: datetime
    rubric: Rubric
    topic: str
    tag: str  # метка ссылки после ad_th_
    card_number: str | None = None  # крупно на картинке
    card_label: str | None = None  # подпись под числом
    card_cta_text: str | None = None  # свой текст кнопки на картинке
    card_dates: str | None = None  # дни рождения с числом на картинке


def load_rubrics(path: Path) -> list[Rubric]:
    """Строки вида «- link soul: текст рубрики»."""
    rubrics = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^- (\w+) (\w+): (.+)$", line.strip())
        if match and match.group(1) in CTAS:
            rubrics.append(Rubric(*match.groups()))
        elif line.startswith("- "):
            log.warning("Рубрика пропущена, ожидается «- <%s> <ключ>: текст»: %s", "|".join(CTAS), line)
    return rubrics


class ContentPlan:
    def __init__(self, rubrics: list[Rubric], enabled: bool = True):
        self.rubrics = rubrics
        self.enabled = enabled and bool(rubrics)
        # Всё ниже заполняет самоулучшение (optimizer.py) из базы.
        self.overrides: dict[str, str] = {}  # переписанные тексты рубрик
        self.weights: dict[str, float] = {}  # насколько часто брать рубрику (1.0 — обычно)
        self.hour_weights: dict[str, float] = {}  # >1 — в эти часы постим чаще
        self.custom: list[Rubric] = []  # новые рубрики, которые бот придумал сам
        self.card_weights: dict[str, float] = {}  # «palette:0», «style:question» → вес
        self.bank: list[BankPost] = []  # готовые посты «не подарок — джекпот» (prompts/jackpot.md)

    def choose_card(self, rng: random.Random) -> tuple[int, str]:
        """Палитра и стиль фразы для картинки: удачные чаще, но остальные тоже пробуем."""
        palettes = list(range(len(PALETTES)))
        palette = rng.choices(palettes, [max(0.3, self.card_weights.get(f"palette:{p}", 1.0)) for p in palettes])[0]
        styles = ["intrigue", "question"]
        style = rng.choices(styles, [max(0.3, self.card_weights.get(f"style:{s}", 1.0)) for s in styles])[0]
        return palette, style

    def all_rubrics(self) -> list[Rubric]:
        return self.rubrics + self.custom

    def effective(self, rubric: Rubric) -> Rubric:
        text = self.overrides.get(rubric.key)
        return replace(rubric, text=text) if text else rubric

    def choose(self, recent: list[str], rng: random.Random) -> Rubric:
        """Следующая рубрика. recent — рубрики последних постов, свежие первыми."""
        by_key = {r.key: r for r in self.all_rubrics()}
        recent_ctas = [by_key[k].cta for k in recent[:5] if k in by_key]
        pool = [r for r in self.all_rubrics() if not recent or r.key != recent[0]]
        if recent_ctas[:1] == ["link"] or recent_ctas.count("link") >= 2:
            pool = [r for r in pool if r.cta != "link"] or pool
        weights = [max(0.2, self.weights.get(r.key, 1.0)) for r in pool]
        return self.effective(rng.choices(pool, weights=weights)[0])

    def render(self, rubric: Rubric, now: datetime, rng: random.Random) -> Slot:
        digit = rng.randint(1, 9)
        a, b = sorted(rng.sample(range(1, 10), 2))
        arcana = rng.randint(1, 22)
        today = now.date()
        topic = rubric.text.format(
            part_of_day=part_of_day(now.time()),
            weekday=WEEKDAYS[today.weekday()],
            day_number=reduce_number(today.day),
            tomorrow_number=reduce_number((today + timedelta(days=1)).day),
            digit=digit,
            group=soul_group(digit),
            n=rng.randint(1, 31),
            a=a,
            b=b,
            arcana=arcana,
            gender=rng.choice(GENDERS),
            digit_word=DIGIT_WORDS[digit],
        )
        number, label, cta_text, dates = None, None, None, None
        if "{a}" in rubric.text and "{b}" in rubric.text:
            number, label, cta_text = f"{a} · {b}", "Совместимость", "Напиши два числа в ответах"
        elif "{arcana}" in rubric.text:
            number, label = str(arcana), "Аркан"
        elif "{digit}" in rubric.text or "{group}" in rubric.text:
            number, label = str(digit), PLANETS[digit]
            dates = birth_days(digit)
            # Человек должен сразу понять, его ли это число: даём модели дни рождения явно.
            topic += f"\nДни рождения с числом души {digit}: {soul_group(digit)} — обязательно назови их, лучше в первой строке."
        elif "{day_number}" in rubric.text or "{tomorrow_number}" in rubric.text:
            number, label = str(reduce_number(today.day)), "Число дня"
        return Slot(
            key=f"auto {now:%Y-%m-%d %H:%M}",
            when=now,
            rubric=rubric,
            topic=topic,
            tag=f"{rubric.key}{digit}_{now:%d%m}",
            card_number=number,
            card_label=label,
            card_cta_text=cta_text,
            card_dates=dates,
        )

    def next_gap(self, now: datetime, rng: random.Random) -> timedelta:
        low, high = NIGHT_GAP if now.hour < 7 else DAY_GAP
        minutes = rng.uniform(low, high) / self.hour_weights.get(hour_bucket(now.hour), 1.0)
        return min(MAX_GAP, max(MIN_GAP, timedelta(minutes=minutes)))


@dataclass(frozen=True)
class ScriptedPost:
    key: str
    text: str


@dataclass(frozen=True)
class BankPost:
    number: str
    label: str | None
    text: str


def load_bank(path: Path) -> list[BankPost]:
    """Готовые посты: заголовок «## <число> [подпись]», под ним текст поста."""
    if not path.exists():
        return []
    bank = []
    for block in re.split(r"^## ", path.read_text(encoding="utf-8"), flags=re.M)[1:]:
        head, _, text = block.partition("\n")
        number, _, label = head.strip().partition(" ")
        if text.strip():
            bank.append(BankPost(number, label.strip() or None, text.strip()))
    return bank


def load_script(path: Path) -> list[ScriptedPost]:
    """Готовые посты: заголовок «## …», под ним текст строками с «>». Остальное — заметки."""
    if not path.exists():
        return []
    posts, title, lines = [], None, []

    def flush():
        text = "\n".join(lines).strip()
        if title and text:
            posts.append(ScriptedPost(f"script {title}", text))

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            flush()
            title, lines = line[3:].strip(), []
        elif title is not None and line.startswith(">"):
            lines.append(line[1:].removeprefix(" "))
    flush()
    return posts
