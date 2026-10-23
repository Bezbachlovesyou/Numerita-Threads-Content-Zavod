"""Автопостинг по контент-плану: в заданное время бот сам пишет пост и публикует его.

Рубрики берутся по кругу из prompts/content_plan.md, номер рубрики и числа в ней
вычисляются из даты и времени, поэтому после перезапуска план не сбивается.
Готовые тексты с точным временем (prompts/threads_script.md) публикуются как есть,
а сгенерированный пост в это время пропускается.
"""

import logging
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from itertools import combinations_with_replacement
from pathlib import Path
from zoneinfo import ZoneInfo

from .knowledge import reduce_number

log = logging.getLogger(__name__)

# Если бот был выключен в момент слота, догоняем не дольше этого окна, а потом пропускаем.
CATCH_UP = timedelta(minutes=20)
# Каждый день сдвигаем слоты на 0–12 минут, чтобы посты не выходили минута в минуту, как у робота.
JITTER_MINUTES = 13
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
PAIRS = list(combinations_with_replacement(range(1, 10), 2))
CTAS = ("link", "reply", "profile", "none")
BOT_LINK = "t.me/Numeritabot?start=ad_th_"


def parse_times(raw: str) -> list[time]:
    """«9:00, 12:30,18:00» → отсортированный список времён."""
    result = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            hours, _, minutes = part.partition(":")
            result.append(time(int(hours), int(minutes or 0)))
    return sorted(set(result))


def soul_group(digit: int) -> str:
    """Дни рождения с этим числом души: 8 → «8, 17, 26»."""
    return ", ".join(str(d) for d in range(1, 32) if reduce_number(d) == digit)


@dataclass(frozen=True)
class Rubric:
    cta: str  # link — ссылка на бота с меткой; reply — зовём ответить; profile — «ссылка в профиле»; none
    key: str  # попадает в метку ссылки ad_th_<key>…
    text: str


@dataclass(frozen=True)
class Slot:
    key: str  # «2026-10-24 09:10» — по нему защищаемся от дублей
    when: datetime  # с учётом дневного сдвига
    rubric: Rubric
    topic: str
    tag: str  # метка ссылки после ad_th_
    to_channel: bool


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
    def __init__(self, times: list[time], channel_times: list[time], rubrics: list[Rubric]):
        self.times = times
        self.channel_times = set(channel_times)
        self.rubrics = rubrics
        # Самоулучшение (optimizer.py): переписанные тексты рубрик и временные замены слабых рубрик.
        self.overrides: dict[str, str] = {}
        self.swaps: dict[str, str] = {}

    def effective(self, rubric: Rubric) -> Rubric:
        swapped = self.swaps.get(rubric.key)
        if swapped:
            rubric = next((r for r in self.rubrics if r.key == swapped and r.cta == rubric.cta), rubric)
        text = self.overrides.get(rubric.key)
        return replace(rubric, text=text) if text else rubric

    @property
    def enabled(self) -> bool:
        return bool(self.times and self.rubrics)

    def _slot(self, day: date, slot: int, tz: ZoneInfo) -> Slot:
        at = self.times[slot]
        index = day.toordinal() * len(self.times) + slot
        position = index % len(self.rubrics)
        rubric = self.effective(self.rubrics[position])
        # Растёт каждый раз, когда рубрика повторяется; сдвиг на номер рубрики,
        # чтобы соседние посты не были про одно и то же число.
        turn = index // len(self.rubrics) + position
        digit = turn % 9 + 1
        a, b = PAIRS[turn % len(PAIRS)]
        topic = rubric.text.format(
            weekday=WEEKDAYS[day.weekday()],
            day_number=reduce_number(day.day),
            tomorrow_number=reduce_number((day + timedelta(days=1)).day),
            digit=digit,
            group=soul_group(digit),
            n=turn % 31 + 1,
            a=a,
            b=b,
            arcana=turn % 22 + 1,
        )
        jitter = timedelta(minutes=(day.toordinal() * 7 + slot * 5) % JITTER_MINUTES)
        return Slot(
            key=f"{day.isoformat()} {at:%H:%M}",
            when=datetime.combine(day, at, tz) + jitter,
            rubric=rubric,
            topic=topic,
            tag=f"{rubric.key}{digit}_{day:%d%m}",
            to_channel=at in self.channel_times,
        )

    def due(self, now: datetime) -> list[Slot]:
        """Слоты, время которых наступило не позже CATCH_UP назад (вчерашние — тоже, для слотов после полуночи)."""
        result = []
        for day in (now.date() - timedelta(days=1), now.date()):
            for slot in range(len(self.times)):
                item = self._slot(day, slot, now.tzinfo)
                if item.when <= now < item.when + CATCH_UP:
                    result.append(item)
        return result

    def upcoming(self, now: datetime, count: int) -> list[Slot]:
        result = []
        day = now.date()
        while len(result) < count:
            result += [s for s in (self._slot(day, i, now.tzinfo) for i in range(len(self.times))) if s.when > now]
            day += timedelta(days=1)
        return result[:count]


@dataclass(frozen=True)
class ScriptedPost:
    key: str
    when: datetime
    text: str


def load_script(path: Path, tz: ZoneInfo) -> list[ScriptedPost]:
    """Готовые посты: заголовок «## ГГГГ-ММ-ДД ЧЧ:ММ», под ним текст строками с «>». Остальное — заметки."""
    if not path.exists():
        return []
    posts, when, lines = [], None, []

    def flush():
        text = "\n".join(lines).strip()
        if when and text:
            posts.append(ScriptedPost(f"script {when:%Y-%m-%d %H:%M}", when, text))

    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^## (\d{4}-\d{2}-\d{2} \d{1,2}:\d{2})", line)
        if match:
            flush()
            when, lines = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=tz), []
        elif when is not None and line.startswith(">"):
            lines.append(line[1:].removeprefix(" "))
    flush()
    return posts
