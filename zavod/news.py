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
    # Наука и изобретения: открытия, прорывы, новые технологии.
    "N + 1": "https://nplus1.ru/rss",
    "Элементы": "https://elementy.ru/rss/news",
    "Hi-News": "https://hi-news.ru/feed",
}
SCIENCE_FEEDS = {"Naked Science", "N + 1", "Элементы", "Hi-News"}
REFRESH_SECONDS = 2 * 60 * 60
PER_SOURCE = 6  # чтобы одна лента не забивала остальные

GOOD = re.compile(
    r"благотвор|волонт|добр(ое|ые|ых|ым|ая|ой|оту|ота)|доброволь|спас(ли|ла|ел|ён|ены)|помог(ли|ла|ает)|"
    r"открыл[аи]?\s+(нов|школ|детск|сад|храм|церк|больниц|центр|парк|библиотек)|открыт(ие|а|ы)\s+(школ|детск|храм|церк)|"
    r"детск(ий|ого)\s+сад|храм|собор|монастыр|молитв|Бог|святын|паломни|"
    r"родил(ась|ся|ись)|малыш|новорожд|многодет|материнств|свадьб|"
    r"природ|заповедн|нацпарк|животн|приют|леопард|тигр|медвед|дельфин|птиц|редк(ий|их|ая)|высадил|деревь|"
    r"учён|учен(ые|ых)|исследовател|изобр[её]л|изобретени|разработал|создал[иа]?\s|прорыв|открыти|телескоп|"
    r"космос|галактик|планет|лекарств|вакцин|технолог|робот|"
    r"мир(но|ное|а)\s|примир|дружб|любов|счасть|улыбк|праздник|фестивал|рекорд|впервые|учёные|открыти[ея]",
    re.I,
)
# В научных лентах берём только настоящую науку и изобретения, без быта и «желтизны».
SCIENCE = re.compile(
    r"учён|учен(ые|ый|ых)|физик|биолог|геолог|астроном|химик|инженер|исследова|впервые|открыл|обнаружил|"
    r"создал|разработал|изобр[её]л|изобретени|прорыв|телескоп|космос|галактик|планет|звезд|робот|квант|"
    r"ген(ом|ы|ов)?\b|клетк|лекарств|вакцин|технолог|нейросет",
    re.I,
)
SCIENCE_BAD = re.compile(r"эякуляц|секс|психопат|псилоцибин|психодел|наркот|алкогол|маляри|паразит|токсичн", re.I)
# Всегда табу — даже в научных лентах.
HARD_BAD = re.compile(
    r"СВО|войн|военн|армии|армия|солдат|фронт|обстрел|дрон|беспилот|ракетн|взрыв|теракт|"
    r"погиб|гибел|смерт|скончал|умер|убий|убит|жертв|трагед|катастроф|"
    r"санкц|выбор|президент|Путин|Зеленск|Трамп|Байден|Украин|ВСУ|НАТО|Пентагон|Кремл|Госдум|депутат|министр|"
    r"политик|партия|митинг|протест|приговор|арест|преступ|наркот|иноагент|экстрем|террор|мобилиз|ядерн(ое|ый)\s+оруж",
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
    def __init__(self, feeds: dict[str, str] = FEEDS, check=None):
        self.feeds = feeds
        self.check = check or is_good
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
                    if taken < PER_SOURCE and self.check(title, science=source in SCIENCE_FEEDS):
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


def is_good(title: str, science: bool = False) -> bool:
    """Научные ленты — почти всё, кроме табу (там и так открытия); общие — только явно доброе."""
    if not title or len(title) < 25 or HARD_BAD.search(title):
        return False
    if science:
        return bool(SCIENCE.search(title)) and not SCIENCE_BAD.search(title)
    return bool(GOOD.search(title)) and not BAD.search(title)


# Хайп дня (слово владельца 28.10.2026: «провокационнее, остроумнее, на злобу дня; обыгрываем медийных личностей —
# поп-звёзд, юмористов, блогеров, тиктокеров, хайпожоров; военных, силовиков и войну не трогаем»).
HYPE_FEEDS = {
    "Лента.ру": "https://lenta.ru/rss/news/culture",
    "StarHit": "https://www.starhit.ru/rss/",
    "7 Дней": "https://7days.ru/rss/",
    "Google Новости": "https://news.google.com/rss/search?q=%D0%B1%D0%BB%D0%BE%D0%B3%D0%B5%D1%80+OR+"
                      "%D1%82%D0%B8%D0%BA%D1%82%D0%BE%D0%BA%D0%B5%D1%80+OR+%D0%BF%D0%B5%D0%B2%D0%B8%D1%86%D0%B0+OR+"
                      "%D1%80%D1%8D%D0%BF%D0%B5%D1%80+OR+%D1%8E%D0%BC%D0%BE%D1%80%D0%B8%D1%81%D1%82&hl=ru&gl=RU&ceid=RU:ru",
}
HYPE = re.compile(
    r"певиц|певец|рэпер|блогер|тикток|ютуб|стример|юморист|комик|стендап|Comedy|шоумен|ведущ|актёр|актер|актрис|"
    r"звезд|поп-|клип|трек|альбом|концерт|тур\b|шоу|сериал|премьер|фильм|наряд|образ|выход|заявил|признал|рассказал|"
    r"ответил|высмеял|пошутил|снял|хайп|вирусн|подписчик|миллион|рекорд|свадьб|роман",
    re.I,
)
# Сверх общего табу: силовики, суды и иски, деньги в долг, боль людей — развод, болезнь, дети, внешность и вес.
HYPE_BAD = re.compile(
    r"ФСБ|МВД|полиц|силов|Росгвард|прокур|следств|следовател|СК\b|уголовн|задерж|суд|иск\b|иски|адвокат|"
    r"изнасил|домогат|насили|развод|алимент|измен|болезн|болен|больниц|реанимац|операци|похорон|прощан|"
    r"больн|тяжел|врач|документалк|памят|убил|суицид|самоуб|травм|маньяк|дочь|дочк|сын\b|сына|сыном|внук|внуч|похуд|вес\b|фигур|пластик|внешност|ребён|ребен|дет(и|ей|ям)\b|беремен|роди(ть|ла)|"
    r"иноагент|уехал|эмигр|релокант|отмен|запрет|долг|банкрот|ДТП|авари|умер|смерт|скончал|похищ|"
    r"Украин|войн|СВО|военн|армия|армии|санкц|Путин|Трамп|Зеленск|политик|депутат|министр",
    re.I,
)


def is_hype(title: str, science: bool = False) -> bool:
    return bool(title and len(title) >= 25 and HYPE.search(title)
                and not HARD_BAD.search(title) and not HYPE_BAD.search(title))


class HypeNews(GoodNews):
    """Заголовки о медийных людях, над которыми можно остроумно и без унижения пошутить."""

    def __init__(self, feeds: dict[str, str] = HYPE_FEEDS):
        super().__init__(feeds, is_hype)
