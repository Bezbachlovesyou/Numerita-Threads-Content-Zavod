"""Страж фактов о небе (слово владельца 10.11.2026: «все утверждения про позиции на небе нужно обязательно сверять через реальный расчёт, иначе это фейк»).
Пост (и команда пульта) с утверждением о новолунии, полнолунии, ретрограде или затмении проверяется расчётом Swiss Ephemeris на момент выхода:
не подтверждено — не выходит, владельцу строка с причиной. Рубрика text_sky получает проверенные факты из skyevents и страж не нужен.
Нет библиотеки (песочница) — проверку пропускаем, в бою она стоит (requirements.txt)."""
import re
from datetime import datetime, timedelta, timezone

PLANETS = {"меркур": 2, "венер": 3, "марс": 4, "юпитер": 5, "сатурн": 6,
           "mercury": 2, "venus": 3, "mars": 4, "jupiter": 5, "saturn": 6}
NEW = re.compile(r"новолуни|new moon", re.I)
FULL = re.compile(r"полнолуни|full moon", re.I)
RETRO = re.compile(r"ретроград|retrograde", re.I)
ECLIPSE = re.compile(r"затмени|eclipse", re.I)
WINDOW_DAYS = 2.2  # «вчера/сегодня/завтра» вокруг точной фазы


def claims(text: str) -> list[str]:
    out = []
    for key, rx in (("new", NEW), ("full", FULL), ("eclipse", ECLIPSE)):
        if rx.search(text):
            out.append(key)
    if RETRO.search(text):
        found = [p for p in PLANETS if re.search(p, text, re.I)]
        out += [f"retro:{p}" for p in found] or ["retro:?"]
    return out


def verify(text: str, now: datetime | None = None) -> list[str]:
    """Список проблем (пусто — всё подтверждено или нечего проверять)."""
    wanted = claims(text)
    if not wanted:
        return []
    try:
        import swisseph as swe
    except ImportError:
        return []
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute / 60)
    sun, moon = swe.calc_ut(jd, swe.SUN)[0], swe.calc_ut(jd, swe.MOON)[0]
    elong = (moon[0] - sun[0]) % 360
    per_day = 12.19  # градусов в сутки: Луна уходит от Солнца
    problems = []
    for claim in wanted:
        if claim == "new" and not (elong <= per_day * WINDOW_DAYS or elong >= 360 - per_day * WINDOW_DAYS):
            problems.append(f"новолуния рядом нет (Луна от Солнца на {elong:.0f}°)")
        elif claim == "full" and abs(elong - 180) > per_day * WINDOW_DAYS:
            problems.append(f"полнолуния рядом нет (Луна от Солнца на {elong:.0f}°)")
        elif claim == "eclipse":
            problems.append("затмение: не подтверждено расчётом, уберите или возьмите дату из рубрики «небо»")
        elif claim.startswith("retro:"):
            name = claim.split(":", 1)[1]
            if name == "?":
                problems.append("ретроград: не названа планета")
            elif swe.calc_ut(jd, PLANETS[name], swe.FLG_SPEED)[0][3] >= 0:
                problems.append(f"{name} сейчас не ретроградна")
    return problems
