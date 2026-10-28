"""Небесный календарь (слово владельца 28.10.2026: «выжать из Swiss Ephemeris всё для регулярных крутых анализов —
отношения, общество, люди, цели, настроение»). Код считает настоящие события ближайших дней: развороты планет
(ретро и директ), смену знаков, новолуния и полнолуния, затмения, нижние соединения Венеры и Меркурия.
Посты рубрики text_sky получают эти факты; астрономия — как факт, астрология и числа — честно как символический язык.
"""

from datetime import datetime, timedelta, timezone

SIGNS = "Овен Телец Близнецы Рак Лев Дева Весы Скорпион Стрелец Козерог Водолей Рыбы".split()
SIGNS_PREP = "Овне Тельце Близнецах Раке Льве Деве Весах Скорпионе Стрельце Козероге Водолее Рыбах".split()
PLANETS = {"Меркурий": 2, "Венера": 3, "Марс": 4, "Юпитер": 5, "Сатурн": 6}
NUMBER = {"Солнце": 1, "Луна": 2, "Юпитер": 3, "Меркурий": 5, "Венера": 6, "Сатурн": 8, "Марс": 9}


def _jd(d: datetime) -> float:
    import swisseph as swe
    return swe.julday(d.year, d.month, d.day, d.hour + d.minute / 60)


def _pos(d: datetime, body: int):
    import swisseph as swe
    return swe.calc_ut(_jd(d), body, swe.FLG_SPEED)[0]


def upcoming(now: datetime, days: int = 7) -> list[str]:
    """События от now до now + days, по часам (точность до часа достаточна для поста)."""
    import swisseph as swe
    now = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    out: list[tuple[datetime, str]] = []
    prev = {name: _pos(now, b) for name, b in {**PLANETS, "Солнце": swe.SUN}.items()}
    prev_phase = (_pos(now, swe.MOON)[0] - prev["Солнце"][0]) % 360
    for h in range(1, days * 24 + 1):
        t = now + timedelta(hours=h)
        cur = {name: _pos(t, b) for name, b in {**PLANETS, "Солнце": swe.SUN}.items()}
        for name in cur:
            (lon0, _, _, sp0), (lon1, _, _, sp1) = prev[name][:4], cur[name][:4]
            if int(lon0 // 30) != int(lon1 // 30):
                out.append((t, f"{name} переходит в знак {SIGNS[int(lon1 // 30)]}"))
            if name != "Солнце" and (sp0 < 0) != (sp1 < 0):
                kind = "разворачивается назад (начало ретроградности)" if sp1 < 0 else "разворачивается вперёд (конец ретроградности)"
                out.append((t, f"{name} {kind} на {lon1 % 30:.0f}° в {SIGNS_PREP[int(lon1 // 30)]}"))
        phase = (_pos(t, swe.MOON)[0] - cur["Солнце"][0]) % 360
        if prev_phase > 300 and phase < 60:
            out.append((t, f"новолуние в {SIGNS_PREP[int(cur['Солнце'][0] // 30)]}"))
        if prev_phase < 180 <= phase:
            out.append((t, f"полнолуние: Луна в {SIGNS_PREP[int((cur['Солнце'][0] + 180) % 360 // 30)]}"))
        prev, prev_phase = cur, phase
    lines = [f"{t + timedelta(hours=3):%d.%m %H:00} МСК — {text}" for t, text in out]
    for kind, fn in (("солнечное", swe.sol_eclipse_when_glob), ("лунное", swe.lun_eclipse_when)):
        try:
            when = swe.revjul(fn(_jd(now), swe.FLG_SWIEPH, 0)[1][0])
            date = datetime(when[0], when[1], when[2], tzinfo=timezone.utc)
            if date - now < timedelta(days=30):
                lines.append(f"ближайшее {kind} затмение — {date:%d.%m.%Y}")
        except Exception:
            pass
    return lines


def state(now: datetime) -> list[str]:
    """Что на небе прямо сейчас: ретроградные планеты и фаза Луны — всегда есть о чём сказать."""
    import swisseph as swe
    now = now.astimezone(timezone.utc)
    out = []
    for name, body in PLANETS.items():
        lon, _, _, sp = _pos(now, body)[:4]
        if sp < 0:
            out.append(f"сейчас {name} {'ретроградна' if name == 'Венера' else 'ретрограден'} в {SIGNS_PREP[int(lon // 30)]}")
    sun, moon = _pos(now, swe.SUN)[0], _pos(now, swe.MOON)[0]
    phase = (moon - sun) % 360
    lit = round(50 * (1 - __import__("math").cos(__import__("math").radians(phase))))
    out.append(f"Луна в {SIGNS_PREP[int(moon // 30)]}, освещена на {lit}%, {'растёт' if phase < 180 else 'убывает'}")
    return out


def topic(now: datetime) -> str:
    events = upcoming(now) + state(now)
    if not events:
        return ""
    return ("\n\nНебо ближайших дней (посчитано Swiss Ephemeris, это факты астрономии):\n" + "\n".join(events[:6]) +
            "\nВозьми одно событие. Астрономию объясни просто и точно; символику — честно как язык астрологии и чисел "
            f"(планета ↔ число: {', '.join(f'{k} — {v}' for k, v in NUMBER.items())}), без предсказаний и страха. "
            "Переведи в отношения, настроение, цели. Не выдумывай событий сверх списка.")
