"""Автопостинг по контент-плану: в заданное время бот сам пишет пост и публикует его.

Рубрики берутся по кругу из prompts/content_plan.md, номер рубрики и числа в ней
вычисляются из даты и времени, поэтому после перезапуска план не сбивается.
"""

import logging
from datetime import date, datetime, time, timedelta
from itertools import combinations_with_replacement
from pathlib import Path

from .knowledge import reduce_number

log = logging.getLogger(__name__)

# Если бот был выключен в момент слота, догоняем не дольше этого окна, а потом пропускаем.
CATCH_UP = timedelta(minutes=20)
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
PAIRS = list(combinations_with_replacement(range(1, 10), 2))


def parse_times(raw: str) -> list[time]:
    """«9:00, 12:30,18:00» → отсортированный список времён."""
    result = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            hours, _, minutes = part.partition(":")
            result.append(time(int(hours), int(minutes or 0)))
    return sorted(set(result))


def load_rubrics(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line[2:].strip() for line in lines if line.startswith("- ") and line[2:].strip()]


class ContentPlan:
    def __init__(self, times: list[time], channel_times: list[time], rubrics: list[str]):
        self.times = times
        self.channel_times = set(channel_times)
        self.rubrics = rubrics

    @property
    def enabled(self) -> bool:
        return bool(self.times and self.rubrics)

    def topic(self, day: date, slot: int) -> str:
        index = day.toordinal() * len(self.times) + slot
        position = index % len(self.rubrics)
        rubric = self.rubrics[position]
        # Растёт каждый раз, когда рубрика повторяется; сдвиг на номер рубрики,
        # чтобы соседние посты не были про одно и то же число.
        turn = index // len(self.rubrics) + position
        a, b = PAIRS[turn % len(PAIRS)]
        return rubric.format(
            date=day.strftime("%d.%m.%Y"),
            weekday=WEEKDAYS[day.weekday()],
            day_number=reduce_number(day.day),
            n=turn % 31 + 1,
            digit=turn % 9 + 1,
            a=a,
            b=b,
            arcana=turn % 22 + 1,
        )

    def due(self, now: datetime) -> list[tuple[str, str, bool]]:
        """Слоты, время которых наступило не позже CATCH_UP назад: (ключ, тема, постить ли в канал)."""
        result = []
        for slot, at in enumerate(self.times):
            when = datetime.combine(now.date(), at, now.tzinfo)
            if when <= now < when + CATCH_UP:
                key = f"{now.date().isoformat()} {at:%H:%M}"
                result.append((key, self.topic(now.date(), slot), at in self.channel_times))
        return result

    def upcoming(self, now: datetime, count: int) -> list[tuple[datetime, str]]:
        result = []
        day = now.date()
        while len(result) < count:
            for slot, at in enumerate(self.times):
                when = datetime.combine(day, at, now.tzinfo)
                if when > now:
                    result.append((when, self.topic(day, slot)))
            day += timedelta(days=1)
        return result[:count]
