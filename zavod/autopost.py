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
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .cards import PALETTES, PLANETS, birth_days
from .knowledge import reduce_number
from . import greatpeople, personal, physics, text_mode

log = logging.getLogger(__name__)

DIGIT_WORDS = {1: "единица", 2: "двойка", 3: "тройка", 4: "четвёрка", 5: "пятёрка", 6: "шестёрка",
               7: "семёрка", 8: "восьмёрка", 9: "девятка"}
GENDERS = ["Женщина", "Парень", "Мужчина", "Девушка"]
# Кого зовём отметить (слово владельца 28.10.2026: друзей, подруг, детей, знакомых) — винительный падеж.
WHO_TO_TAG = ["подругу", "друга", "сестру", "брата", "маму", "дочку", "сына", "коллегу", "лучшую подругу",
              "того, кто всегда опаздывает", "того, с кем вы на одной волне", "соседку по офису", "кума или куму",
              "друга детства", "вторую половинку"]
# Палитра эмоций для постов-перекличек (prompts/emotions.md): эмоция и вопрос, на который отвечают за 3 секунды.
# Высокая активация (раздражение по мелочам, восхищение, смех, неловкость, тяга) — больше ответов и репостов
# (Бергер и Милкман, 2012); грусть и тоска — меньше. Злость — только на мелочи, никогда на людей и группы.
EMOTIONS = [
    ("раздражение", "Какая глупая мелочь в людях выводит вас из себя за секунду?"),
    ("раздражение", "Какая фраза бесит вас сильнее, чем должна?"),
    ("отвращение", "От какой привычки людей вас прямо передёргивает?"),
    ("неловкость", "Ваш самый неловкий момент, о котором вы до сих пор вспоминаете в 3 ночи?"),
    ("смех", "Что вы делаете, когда думаете, что вас никто не видит?"),
    ("восхищение", "Какое качество в людях восхищает вас с первой секунды?"),
    ("умиление", "От какой мелочи вы таете, как мороженое?"),
    ("ностальгия", "Какой запах сразу возвращает вас в детство?"),
    ("тяга", "Без чего ваше утро — не утро?"),
    ("облегчение", "Какое «нет» вы сказали — и стало легче дышать?"),
    ("гордость", "Чем вы тихо гордитесь, но никому не рассказываете?"),
    ("страх", "Чего вы боитесь, хотя все вокруг над этим смеются?"),
    ("удивление", "Что в людях до сих пор вас удивляет?"),
    ("интерес", "О чём вы можете говорить часами, только спросите?"),
    ("романтика", "Какой жест покоряет ваше сердце сразу?"),
    ("досада", "Какой совет вы слышите чаще всего — и он вас раздражает?"),
]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря"]


def when_phrase(day: date) -> str:
    """«начало ноября», «середина октября», «конец октября» — для своевременных постов."""
    part = "начало" if day.day <= 10 else "середина" if day.day <= 20 else "конец"
    return f"{part} {MONTHS_GEN[day.month - 1]}"
CTAS = ("link", "reply", "profile", "none")
from .lang import is_en as _is_en

BOT_LINK = "t.me/Numeritabot?start=ad_en_th_" if _is_en() else "t.me/Numeritabot?start=ad_th_"

# Безопасный ритм для Threads: никогда не чаще раза в час (лимит API — 250 постов в сутки,
# но частые посты нового аккаунта выглядят как спам), никогда не реже раза в 4 часа.
# 28.10.2026 (владелец: «не ходить по грани, красиво ехать»): качество важнее частоты — ≈6–8 постов в сутки.
MIN_GAP = timedelta(minutes=120)
MAX_GAP = timedelta(hours=14)  # 04.11.2026: реже и только лучшее — потолок паузы поднят
DAY_GAP = (720, 840)  # минут, 07:00–17:59; 30.10 владелец: «днём реже, вечером бомбить чаще»
NIGHT_GAP = (600, 720)  # минут, 00:00–06:59
# 30.10.2026, слово владельца: «вечер — люди читают Threads, врубим все газы». Вечерний прайм 18:00–22:59 — пост
# каждые 60–80 мин (≈5 за вечер, ≈10–11 в сутки при потолке 20); ответы — в прежних безопасных лимитах.
PRIME_HOURS = range(18, 23)
PRIME_GAP = (360, 420)  # 03.11: реже и сильнее (≈8–9 постов в сутки вместо 10–12): охват есть, не хватает причины подписаться; потолок 20 в сутки прежний
PRIME_MIN_GAP = timedelta(minutes=240)


def min_gap(now: datetime) -> timedelta:
    return PRIME_MIN_GAP if now.hour in PRIME_HOURS else MIN_GAP

# Тема Threads для рубрики: пост показывают тем, кто следит за темой. По умолчанию — нумерология.
TOPIC_TAGS = {"love": "Отношения", "pair": "Отношения", "ex": "Отношения", "wisdom": "Саморазвитие", "money": "Саморазвитие", "abundance": "Саморазвитие"}
DEFAULT_TOPIC_TAG = "Нумерология"


OWN_HANDLES = {"numerita.ai", "numeritabot", "numeritalovesyou"} | (
    {h.strip().lower().lstrip("@") for h in __import__("os").getenv("OWN_HANDLE", "").split(",") if h.strip()})
CREDIT_RE = re.compile(r"(?i)\b(по мотивам|идея|источник|автор|вдохновил[аио]?сь|спасибо)\b[^\n]*@[\w.]+[^\n]*")
MENTION_RE = re.compile(r"(?:\s*,|\s+и)?\s*(?<![\w/])@([A-Za-z0-9_.]*[A-Za-z0-9_])")


def strip_credits(text: str) -> str:
    """Убирает «по мотивам @…» и чужие @упоминания: наши посты и ответы — без рекламы других авторов."""
    text = CREDIT_RE.sub("", text)
    text = MENTION_RE.sub(lambda m: m.group(0) if m.group(1).lower() in OWN_HANDLES else "", text)
    lines = [re.sub(r"[ \t]{2,}", " ", line).rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# Слово владельца 03.11.2026 (аудитория Threads: Dating Threads 269, психология 178, Book Threads 221, AI Threads 161): пост уходит в ленты этих тем.
# Слово владельца 04.11.2026: «снизить траты завода в 5 раз, делать только то, что срабатывало, разнообразив его». По данным Threads за 30 дней просмотры и комментарии дают матрицы «Угадай число» (0,4–6,5 тыс.),
# списки по дням рождения про любовь/роли (1,6–3,6 тыс.), страхи, пары, «Пара недели», небо; остальное — единицы–десятки просмотров. Эти рубрики — ядро; остальные ×0,25 (не выключены: свежие форматы пробуются, но редко).
CORE = {"grid", "text_marriage", "text_roles", "text_flags", "text_rita", "text_angel", "text_vector", "text_misread", "text_sign", "text_sign_good", "text_sign_list", "text_matrix", "text_gotaway", "text_sign_clash", "text_asc", "text_story6", "text_asc", "text_sign_truth", "text_mercury", "text_planet", "text_goals_story", "text_fears", "text_reaction", "text_lessons", "text_heaven_pairs", "text_pair_week", "text_pair", "text_sky", "text_free", "text_celeb", "text_physics", "text_loves", "text_year", "text_seek", "text_from_comments"}
NON_CORE_FACTOR = 0.25
# Настоящие цифры из событий бота за 30 дней (ветка бота, 04.11.2026; тестовые аккаунты не исключены — поэтому только «больше 20»). Обновлять по новому отчёту бота.
GOALS_DATA = ("за 30 дней в боте больше 20 человек поставили себе цель и больше 20 записали свои маленькие победы (число приблизительное, без точной цифры). "
              "Отметок «цель выполнена» нет — НЕ пиши, что люди достигли целей; пиши про шаги и победы. Ни одной личной детали, имён, дат и сроков.")
GRID_SHARE = 0.22  # вес матрицы при допуске (раз в 3 поста максимум) даёт ≈15% ленты
# Данные Threads 03.11.2026: «сценки», «протоколы», «суд», ситкомы дают 4–60 просмотров и нули лайков — почти не выпускаем (×0,15), остальные форматы держат охват.
SUPPRESSED = {"text_court", "text_protocol", "text_chat", "text_office", "text_venus", "text_tag_family", "text_review", "text_choices"}
DATING_RUBRICS = {"text_gotaway", "text_flags", "text_loves", "text_marriage", "text_marry", "text_heaven_pairs", "text_pair", "text_pair_week", "text_tag_pair", "love", "pair", "ex"}  # только настоящие рубрики про любовь и пары: «Ищу тех, кто родился…» (text_seek) — продажа, не про отношения (03.11)
PSYCH_RUBRICS = {"text_qualities", "text_rita", "text_angel", "text_vector", "text_goals_story", "text_lessons", "text_fears", "text_reaction", "text_outgrow", "text_success", "text_levels", "text_gifts", "text_battery", "text_roles", "text_avoid", "text_great", "text_unknown"}


ASTRO_RUBRICS = {"text_sign", "text_sign_good", "text_sign_list", "text_sign_clash", "text_asc", "text_sign_truth", "text_mercury", "text_planet", "text_sky"}  # слово владельца 08.11.2026: «Знак × число» должен попадать в тему «Астрология», а не «Нумерология»


SIGN_RE = re.compile(r"(?i)\b(овен|овн[аоыуе]\w*|телец|тельц\w*|близнец\w*|скорпион\w*|стрелец|стрельц\w*|козерог\w*|водолей|водолея\w*|водолеев|весы|весов|aries|taurus|gemini|scorpio|sagittarius|capricorn|aquarius|pisces|virgo|libra)\b")
ASTRO_WORDS = re.compile(r"(?i)гороскоп|астролог|ретроград|знак\w* зодиака|зодиак|horoscope|astrolog|retrograde|zodiac")


def looks_astrological(text: str | None) -> bool:
    """Пост про знаки зодиака, даже если рубрика другая (слово владельца 08.11.2026: пост про знаки ушёл в «Нумерологию» — ошибка)."""
    if not text:
        return False
    return len({m.group(1).lower() for m in SIGN_RE.finditer(text)}) >= 2 or bool(ASTRO_WORDS.search(text))


def topic_tag_for(rubric: str | None, text: str | None = None) -> str:
    if rubric == "text_matrix":
        return "Tarot Threads"  # 22 аркана Таро: сообщество «Tarot Threads» (слово владельца 08.11.2026 нашёл его; отдельного синего про матрицу судьбы пока нет)
    if rubric in ASTRO_RUBRICS or looks_astrological(text):
        return "Astrology Threads"  # сообщество с 145 тыс. участников (скриншот владельца 08.11.2026); название одно для RU и EN
    if _is_en():  # английский аккаунт: ни одной кириллической буквы, в том числе в теме
        return "Dating Threads" if rubric in DATING_RUBRICS else "Psychology Threads" if rubric in PSYCH_RUBRICS else "Numerology Threads"
    if rubric in DATING_RUBRICS:
        return "Dating Threads"
    if rubric in PSYCH_RUBRICS:
        return "Psychology Threads"  # сообщество, найдено владельцем 08.11.2026
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


# Новые форматы по слову владельца — чаще, пока оптимизатор не наберёт по ним данных.
PLANETS_RU = ["Солнце", "Луна", "Венера", "Асцендент", "Марс"]
PLANETS_EN = ["Sun", "Moon", "Venus", "Ascendant", "Mars"]
# Цели постов (слово владельца 10.11.2026: реже, но чётче; чередуем форматы под комментарии, пересылки/репосты и сердечки).
GOAL_SHARES = {"text_gotaway", "text_loves", "text_heaven_pairs", "text_pair_week", "text_marriage", "text_sign_list", "text_flags", "text_celeb", "text_great", "text_tag_pair", "text_marry", "text_roles", "text_regret"}
GOAL_LIKES = {"text_angel", "text_qualities", "text_rita", "text_goals_story", "text_matrix", "text_lessons", "text_baza", "text_howto", "text_insight", "text_secrets", "text_success", "text_levels", "text_wealth"}
GOAL_MIX = {"comments": 2, "shares": 1, "likes": 1}  # на каждые 4 поста


def goal_of(key: str) -> str:
    return "shares" if key in GOAL_SHARES else "likes" if key in GOAL_LIKES else "comments"


def goal_deficit(recent: list[str]) -> str:
    """Цель, которой не хватает в последних 4 постах по целевой смеси (2 комментарии : 1 пересылки : 1 сердечки)."""
    seen = [goal_of(k) for k in recent[:4]]
    return max(GOAL_MIX, key=lambda g: GOAL_MIX[g] * (len(seen) + 1) / 4 - seen.count(g))


SIGNS_EN = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
SIGNS_RU = ["Овны", "Тельцы", "Близнецы", "Раки", "Львы", "Девы", "Весы", "Скорпионы", "Стрельцы", "Козероги", "Водолеи", "Рыбы"]
BOOST = {"text_baza": 2.5, "text_rollcall": 2.5, "text_one_digit": 2.0, "text_howto": 1.5, "text_myth": 2.0, "text_insight": 1.5, "text_who_told": 2.5, "text_heaven_pairs": 3.0, "text_what_next": 2.0, "text_tag_pair": 2.0, "text_hype": 3.0, "text_secrets": 3.0, "text_marry": 3.0, "text_celeb": 4.0, "text_aroma": 2.5, "text_roles": 2.5, "text_avoid": 2.5, "text_sunrise": 4.5, "text_seek": 4.0, "text_physics": 3.0, "text_year": 4.0, "text_fears": 3.0, "text_reaction": 3.0, "text_lessons": 3.0, "text_flags": 3.5, "text_rita": 3.0, "text_angel": 3.0, "text_vector": 3.0, "text_misread": 4.0, "text_sign": 4.0, "text_sign_good": 7.0, "text_sign_list": 5.0, "text_matrix": 3.0, "text_gotaway": 4.0, "text_sign_clash": 5.0, "text_story6": 3.0, "text_asc": 6.0, "text_sign_truth": 6.0, "text_mercury": 4.0, "text_planet": 4.0, "text_goals_story": 3.0, "text_free": 12.0, "text_pair": 4.0, "text_unknown": 3.0, "text_battery": 2.5, "text_outgrow": 2.5, "text_marriage": 4.0, "text_loves": 2.5, "text_gifts": 2.5, "text_eras": 2.5, "text_success": 2.5, "text_wealth": 2.5, "text_levels": 2.5, "grid": 8.0, "text_great": 2.0, "text_science": 2.0, "text_dna": 1.5, "text_sky": 1.5}  # не чаще раза в день — следит post_next


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

    def choose(self, recent: list[str], rng: random.Random, now: datetime | None = None) -> Rubric:
        """Следующая рубрика. recent — рубрики последних постов, свежие первыми."""
        by_key = {r.key: r for r in self.all_rubrics()}
        recent_ctas = [by_key[k].cta for k in recent[:5] if k in by_key]
        pool = [r for r in self.all_rubrics() if not recent or r.key != recent[0]]
        pool = [r for r in pool if r.key not in ("text_pair_week", "text_from_comments", "text_qualities")] or pool  # «Пара недели» выходит только по расписанию (pairweek.due), не по жребию
        if _is_en():  # английский аккаунт: без русских лент новостей/хайпа, картинок с русским текстом
            from .lang import EN_SKIP_RUBRICS
            pool = [r for r in pool if r.key not in EN_SKIP_RUBRICS] or pool
        if text_mode.enabled():
            pool = [r for r in pool if text_mode.allowed(r)] or [r for r in self.all_rubrics() if text_mode.allowed(r)]
            fresh_text = [r for r in pool if r.key.startswith('text_') or r.key == 'number_mirror'
                          or (r.key == 'grid' and text_mode.grid_enabled() and 'grid' not in recent[:2])]
            pool = fresh_text or pool
        if recent_ctas[:1] == ["link"] or recent_ctas.count("link") >= 2:
            pool = [r for r in pool if r.cta != "link"] or pool
        boost = {**BOOST, "grid": 4.0} if _is_en() else BOOST  # английский: «Угадай число» — главный двигатель
        if not any(k in personal.PERSONAL for k in recent[:3]) and rng.random() < personal.PERSONAL_SHARE:
            # третий механизм (год, время, пара — личное не узнать из общего поста): не реже, чем раз в 3–4 поста
            pool = [r for r in pool if r.key in personal.PERSONAL] or pool
        live = [r for r in pool if self.weights.get(r.key, 1.0) > 0]  # вес 0 — рубрику больше не делаем
        pool = live or pool
        weights = [max(0.2, self.weights.get(r.key, boost.get(r.key, 1.0))) for r in pool]
        weights = [w * (0.15 if r.key in SUPPRESSED else 1.0 if r.key in CORE else NON_CORE_FACTOR) for r, w in zip(pool, weights)]
        # Слово владельца 04.11.2026: матрицы «Угадай число» — самый сильный формат (до 6,5 тыс. просмотров, сотни комментариев), но выходили в ~6% постов. Гарантируем им долю GRID_SHARE
        # независимо от весов оптимизатора: вес матрицы = доля/(1−доля) от суммы остальных (пока матрицы не было в последних трёх постах).
        if "grid" not in recent[:2] and any(r.key == "grid" for r in pool):
            others = sum(w for r, w in zip(pool, weights) if r.key != "grid")
            weights = [(GRID_SHARE / (1 - GRID_SHARE)) * others if r.key == "grid" else w for r, w in zip(pool, weights)]
        if now is not None:  # среда 18–21 — окно матрицы «Угадай число» (series.py)
            from . import series
            if series.in_grid_window(now) and "grid" not in recent[:2]:
                weights = [w * (series.GRID_BOOST if r.key == "grid" else 1.0) for r, w in zip(pool, weights)]
        if recent:  # чередование целей: рубрикам недостающей цели вес ×2,5 (не отменяет оптимизатор и сетку)
            need = goal_deficit(recent)
            weights = [w * (2.5 if goal_of(r.key) == need else 1.0) for r, w in zip(pool, weights)]
        return self.effective(rng.choices(pool, weights=weights)[0])

    def render(self, rubric: Rubric, now: datetime, rng: random.Random) -> Slot:
        digit = rng.randint(1, 9)
        a, b = sorted(rng.sample(range(1, 10), 2))
        arcana = rng.randint(1, 22)
        today = now.date()
        emotion = rng.choice(EMOTIONS)
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
            emotion=emotion[1],
            digit_word=DIGIT_WORDS[digit],
            when=when_phrase(today),
            who=rng.choice(WHO_TO_TAG),
            physics=physics.fact_for(digit, rng) if "{physics}" in rubric.text else "",
            year_example=personal.year_example(rng) if "{year_example}" in rubric.text else "",
            sign=rng.choice(SIGNS_EN if _is_en() else SIGNS_RU) if "{sign}" in rubric.text else "",
            planet=rng.choice(PLANETS_EN if _is_en() else PLANETS_RU) if "{planet}" in rubric.text else "",
            goals_data=GOALS_DATA,
            great=greatpeople.block(greatpeople.pick(rng, _is_en()), _is_en()) if "{great}" in rubric.text else "",
        )
        if "{emotion}" in rubric.text:  # пометка для самоулучшения: какая эмоция лучше вовлекает
            topic += f"\n[эмоция: {emotion[0]}]"
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
        if now.hour in PRIME_HOURS:
            return timedelta(minutes=rng.uniform(*PRIME_GAP))
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
