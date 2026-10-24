"""Добрые новости для своевременных постов: доброта, любовь, дети и мамы, природа, вера, благотворительность,
открытия школ и храмов, примирение. Берём открытые RSS-ленты изданий (только заголовки — как повод для поста),
политику, СВО, войны, трагедии и криминал отсекаем жёстким фильтром, а нейросеть ещё раз проверяет тон.
"""

import logging
import random
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

FEEDS = {
    "РИА Новости": "https://ria.ru/export/rss2/archive/index.xml",
    "ТАСС": "https://tass.ru/rss/v2.xml",
    "Российская газета": "https://rg.ru/xml/index.xml",
    "Правмир": "https://www.pravmir.ru/feed/",
    "Фома": "https://foma.ru/feed",
    "Naked Science": "https://naked-science.ru/feed",
}
REFRESH_SECONDS = 2 * 60 * 60
PER_SOURCE = 6  # чтобы одна лента не забивала остальные

GOOD = re.compile(
    r"благотвор|волонт|добр(ое|ые|ых|ым|ая|ой|оту|ота)|доброволь|спас(ли|ла|ел|ён|ены)|помог(ли|ла|ает)|"
    r"открыл[аи]?\s+(нов|школ|детск|сад|храм|церк|больниц|центр|парк|библиотек)|открыт(ие|а|ы)\s+(школ|детск|храм|церк)|"
    r"детск(ий|ого)\s+сад|храм|собор|монастыр|молитв|Бог|святын|паломни|"
    r"родил(ась|ся|ись)|малыш|новорожд|многодет|материнств|свадьб|"
    r"природ|заповедн|нацпарк|животн|приют|леопард|тигр|медвед|дельфин|птиц|редк(ий|их|ая)|высадил|деревь|"
    r"мир(но|ное|а)\s|примир|дружб|любов|счасть|улыбк|праздник|фестивал|рекорд|впервые|учёные|открыти[ея]",
    re.I,
)
BAD = re.compile(
    r"СВО|войн|военн|воен|армии|армия|солдат|фронт|удар|атак|обстрел|дрон|беспилот|ракет|взрыв|теракт|"
    r"погиб|гибел|смерт|скончал|умер|убий|убит|ранен|жертв|трагед|катастроф|авари|ДТП|пожар|наводнен|"
    r"санкц|выбор|президент|Путин|Зеленск|Трамп|Байден|Украин|ВСУ|НАТО|Пентагон|Кремл|Госдум|депутат|министр|"
    r"политик|партия|митинг|протест|суд\b|суда|судит|приговор|арест|задерж|преступ|мошен|наркот|"
    r"иноагент|экстрем|террор|мобилиз|границ|оккуп|ядерн|эвакуац|инфляц|кризис|штраф|запрет|"
    r"грипп|вирус|зараз|эпидеми|боёв|боев|бои\b|ополчен|партизан|секта|нападен|травл|бо[её]ц|бойц|спецназ|зависимост|потерял|унижа|казино|гонени|скандал|прогул|демонтир|"
    r"Армени|Грузи|Косов|Израил|Иран|Китай|США|инвалид|болезн|рак\b|онколог|диагноз|насили|избил|пропал|"
    r"архиере|епархи|сменил|отставк|уволен|долг|кредит|налог|цены|подорож",
    re.I,
)


@dataclass(frozen=True)
class Headline:
    title: str
    source: str


class GoodNews:
    def __init__(self, feeds: dict[str, str] = FEEDS):
        self.feeds = feeds
        self.items: list[Headline] = []
        self.loaded_at = 0.0

    async def headlines(self) -> list[Headline]:
        """Свежие добрые заголовки (кэш на 2 часа). Пусто — если ленты недоступны или доброго нет."""
        if time.monotonic() - self.loaded_at < REFRESH_SECONDS and self.loaded_at:
            return self.items
        found: list[Headline] = []
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "Mozilla/5.0 NumeritaBot"}) as http:
            for source, url in self.feeds.items():
                try:
                    response = await http.get(url)
                    response.raise_for_status()
                    root = ET.fromstring(response.content)
                except (httpx.HTTPError, ET.ParseError) as e:
                    log.info("Лента %s недоступна: %s", source, e)
                    continue
                taken = 0
                for item in root.iter("item"):
                    title = re.sub(r"\s+", " ", (item.findtext("title") or "")).strip()
                    if taken < PER_SOURCE and is_good(title):
                        found.append(Headline(title, source))
                        taken += 1
        seen, unique = set(), []
        for h in found:
            if h.title.lower() not in seen:
                seen.add(h.title.lower())
                unique.append(h)
        self.items, self.loaded_at = unique, time.monotonic()
        log.info("Добрых новостей: %s", len(unique))
        return unique

    async def candidates(self, used: set[str], rng: random.Random, limit: int = 10) -> list[Headline]:
        """Несколько свежих добрых заголовков из разных лент — нейросеть выберет самый светлый."""
        fresh = [h for h in await self.headlines() if h.title not in used]
        rng.shuffle(fresh)
        return fresh[:limit]


def is_good(title: str) -> bool:
    return bool(title) and len(title) >= 25 and bool(GOOD.search(title)) and not BAD.search(title)
