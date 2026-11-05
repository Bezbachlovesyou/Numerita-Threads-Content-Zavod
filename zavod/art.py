"""Планка «арт-объект» (слово владельца 31.10.2026: «каждый текст — арт-объект; усреднённого текста быть не должно; живой,
одухотворённый, с интригой, хуком, острейшим юмором, интересным научным фактом или историей про нумерологию; он должен взрывать;
и постарайся внедрить рифму»; «жёлтая пресса никому не интересна»).

Судья (дешёвая модель) оценивает текст по пяти измерениям: хук, интрига, юмор, содержание (факт или история), живость; отдельно
отмечает, есть ли рифма, и не звучит ли текст как усреднённый шаблон. Не дотянул — один-два раза поднимаем текст (elevate) именно по
слабому месту, а не пересказываем заново. Всё равно ниже планки — пост не выходит (слот возьмёт другой формат); после нескольких
отказов подряд выпускаем лучший вариант и пишем владельцу, чтобы планка не остановила ленту.
Рифма — желанная, не обязательная: не вымученная, смысл важнее рифмы. Жёлтая пресса (ложные сенсации, кликбейт без содержания) — провал."""

import logging
import re
from datetime import date

log = logging.getLogger(__name__)

DIMENSIONS = ("ХУК", "ИНТРИГА", "ЮМОР", "СОДЕРЖАНИЕ", "ЖИВОСТЬ")
ART_MIN = 8.5  # среднее по пяти измерениям
FLOOR = 6  # ни одно измерение не ниже
MAX_ELEVATE = 2
FALLBACK_AFTER = 4  # столько отказов подряд — выпускаем лучший вариант, чтобы лента не встала
MAX_TEXT = 470  # лимит Threads 500; запас под ссылки с меткой

JUDGE = (
    "Ты беспощадный литературный редактор Threads. Оцени текст как художественное высказывание: он должен остановить палец в ленте "
    "и запомниться. Текст может быть на русском или английском: критерии те же, рифму оценивай на языке текста. "
    "Оценки 1–10, строгие, 8 — это уже сильно, 10 — редкость:\n"
    "ХУК — первая строка бьёт в нерв (узнавание с поворотом, дерзкая мысль, живая сцена).\n"
    "ИНТРИГА — хочется дочитать, есть недосказанность или поворот.\n"
    "ЮМОР — острый, неожиданный, над ситуацией; панч не предсказуем.\n"
    "СОДЕРЖАНИЕ — есть интересный проверяемый научный факт или настоящая история про числа, а не вода и общие слова.\n"
    "ЖИВОСТЬ — живой, одухотворённый голос с образом и музыкой фраз, без канцелярита, назидания и штампов.\n"
    "Отдельно: РИФМА — ДА, если есть естественная рифма (панч, двустишие), иначе НЕТ. ШАБЛОН — ДА, если текст звучит как "
    "усреднённый шаблон (формула «скетч про число», общая мудрость, пересказ справки) или как жёлтая пресса (ложная сенсация, "
    "кликбейт без содержания), иначе НЕТ.\n"
    "Ответ строго по строкам, без пояснений:\nХУК: <число>\nИНТРИГА: <число>\nЮМОР: <число>\nСОДЕРЖАНИЕ: <число>\n"
    "ЖИВОСТЬ: <число>\nРИФМА: <ДА/НЕТ>\nШАБЛОН: <ДА/НЕТ>\nСЛАБОЕ: <самое слабое место одной фразой и как его усилить>"
)

ELEVATE = (
    "Подними этот текст до арт-объекта. Слабое место по оценке редактора: {weak}\n"
    "Сделай его живым, одухотворённым, с интригой и острым хуком в первой строке, с острейшим неожиданным юмором над ситуацией, "
    "с интересным научным фактом или настоящей историей про числа (только из базы знаний и из исходного текста, новых фактов, "
    "цифр, имён и цитат не выдумывай); пусть он «взрывает». Если рифма ложится естественно (панч, двустишие, концовка), "
    "используй её, но не вымучивай: смысл важнее рифмы. Без жёлтой прессы, кликбейта, назидания, штампов и общих слов. "
    "Сохрани язык текста (английский — только литературный английский, ни одной русской буквы), числа, дни рождения и честные "
    "оговорки (нумерология — символический язык, а не наука и не предсказание). Не длиннее {limit} знаков. "
    "Без ссылок, хештегов и «сохрани/перешли». Верни только текст.\n\nТекст:\n{text}"
)

STATS = {"day": None, "judged": 0, "passed_first": 0, "elevated": 0, "rejected": 0, "forced": 0, "rhyme": 0, "sum": 0.0}
_state = {"rejects": 0}


def parse(raw: str) -> dict | None:
    """{'scores': {...}, 'total': float, 'rhyme': bool, 'template': bool, 'weak': str} или None, если ответ не разобран."""
    scores = {}
    for name in DIMENSIONS:
        m = re.search(rf"{name}\s*:\s*(\d+(?:[.,]\d+)?)", raw or "", re.I)
        if not m:
            return None
        scores[name] = min(10.0, float(m.group(1).replace(",", ".")))
    rhyme = re.search(r"РИФМА\s*:\s*(ДА|НЕТ)", raw, re.I)
    template = re.search(r"ШАБЛОН\s*:\s*(ДА|НЕТ)", raw, re.I)
    weak = re.search(r"СЛАБОЕ\s*:\s*(.+)", raw)
    return {"scores": scores, "total": sum(scores.values()) / len(scores),
            "rhyme": bool(rhyme and rhyme.group(1).upper() == "ДА"),
            "template": bool(template and template.group(1).upper() == "ДА"),
            "weak": weak.group(1).strip() if weak else "слабый хук и мало содержания"}


def passed(report: dict) -> bool:
    return (report["total"] >= ART_MIN and min(report["scores"].values()) >= FLOOR and not report["template"])


def _stat(**add) -> None:
    today = date.today().isoformat()
    if STATS["day"] != today:
        STATS.update(day=today, judged=0, passed_first=0, elevated=0, rejected=0, forced=0, rhyme=0, sum=0.0)
    for key, value in add.items():
        STATS[key] += value


def stats_line() -> str:
    n = STATS["judged"]
    if not n:
        return "планка арт-объекта: с запуска оценок ещё не было"
    return (f"планка арт-объекта (с запуска): оценено {n}, с первого раза {STATS['passed_first']}, поднято {STATS['elevated']}, "
            f"не пропущено {STATS['rejected']}, выпущено по запасному правилу {STATS['forced']}, средняя оценка "
            f"{STATS['sum'] / n:.1f}, с рифмой {STATS['rhyme']}")


async def judge(generator, text: str) -> dict | None:
    """Оценка редактора; None — оценка недоступна (сбой модели или ответ не разобран), тогда пост не блокируем."""
    try:
        raw = await generator.improve(JUDGE, text, max_tokens=220, kind="art", model=generator.reply_model)
    except Exception as e:
        log.warning("Судья арт-объекта недоступен, пост выходит без оценки: %s", e)
        return None
    report = parse(raw if isinstance(raw, str) else "")
    if report is None:
        log.warning("Оценка арт-объекта не разобрана: %r", (raw or "")[:120])
    return report


async def elevate(generator, text: str, report: dict) -> str:
    prompt = ELEVATE.format(weak=report["weak"], limit=MAX_TEXT, text=text)
    from . import text_mode
    if text_mode.enabled():
        prompt += "\n\n" + text_mode.STYLE
    return (await generator.improve(generator.system, prompt, max_tokens=700, kind="elevate")).strip()


async def art_gate(generator, body: str, english: bool = False) -> str | None:
    """Текст (без ссылок) → текст на уровне планки, либо None: планка не взята, пост не выпускаем."""
    from . import lang
    report = await judge(generator, body)
    if report is None:
        return body
    _stat(judged=1, sum=report["total"], rhyme=int(report["rhyme"]))
    if passed(report):
        _stat(passed_first=1)
        _state["rejects"] = 0
        return body
    best, best_total = body, report["total"]
    for _ in range(MAX_ELEVATE):
        try:
            better = await elevate(generator, body, report)
        except Exception as e:
            log.warning("Поднять текст до арт-объекта не удалось: %s", e)
            break
        if not better or len(better) > MAX_TEXT or (english and lang.has_cyrillic(better)):
            break
        _stat(elevated=1)
        again = await judge(generator, better)
        if again is None:
            return better
        if again["total"] >= best_total:
            best, best_total = better, again["total"]
        if passed(again):
            _state["rejects"] = 0
            return better
        body, report = better, again
    _state["rejects"] += 1
    if _state["rejects"] >= FALLBACK_AFTER:  # планка не должна останавливать ленту совсем
        _state["rejects"] = 0
        _stat(forced=1)
        log.warning("Планка арт-объекта не взята %s раз подряд — выпускаю лучший вариант (%.1f)", FALLBACK_AFTER, best_total)
        return best
    _stat(rejected=1)
    log.info("Текст не дотянул до арт-объекта (%.1f): %s — не выпускаю", best_total, report["weak"])
    return None
