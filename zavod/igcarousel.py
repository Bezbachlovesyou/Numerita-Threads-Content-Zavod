"""Карусели Instagram из текстовых картинок (слово владельца 31.10.2026: «захватывали внимание, давали комментарии и подписчиков, интригу, улыбку; чтобы люди
узнавали себя и своих близких; и подводили ко входу в бота»). Русская и английская версии отдельные (языки не мешаем).

Механика: обложка с обещанием узнавания → по три группы дней рождения на слайд (девять групп, у каждой своя узнаваемая бытовая сцена с юмором; в третьем лице, чтобы
узнавать и себя, и «своего человека») → финальный слайд: вопрос, повод написать день рождения числом (ответ в комментариях, не «отметь/перешли») и мост «год, время и пара
считаются лично — ссылка в шапке профиля». Образы чисел из теней и даров базы знаний; это шутка и символика, не диагноз и не приговор. Внизу — значок Telegram и @Numeritabot.
Без платных генераций: PIL, $0. Один набор — один сюжет, палитра на весь набор."""

import io
import math
import random

from PIL import Image, ImageDraw, ImageFilter

from .cards import FOOTER, H, PALETTES, W, _font, _footer, _gradient

GROUPS = ["1 · 10 · 19 · 28", "2 · 11 · 20 · 29", "3 · 12 · 21 · 30", "4 · 13 · 22 · 31", "5 · 14 · 23", "6 · 15 · 24", "7 · 16 · 25",
          "8 · 17 · 26", "9 · 18 · 27"]

SETS = {
    "quarrel": {
        "palette": 2,
        "ru": {
            "cover": "КАК ТЫ ССОРИШЬСЯ, ПО ДНЮ РОЖДЕНИЯ",
            "sub": "Листай. Узнаешь себя и своего человека",
            "note": "Образы чисел, шутка и символика, не диагноз",
            "lines": [
                "Не извиняется первым. Но через час принесёт чай и сделает вид, что это просто чай.",
                "Обижается молча. Ждёт, что вы догадаетесь. Вы не догадались. Теперь обижается и на это.",
                "Прочтёт лекцию о том, как правильно ссориться. С примерами. Вы уже не в ссоре, вы на семинаре.",
                "Скажет «всё нормально» и уйдёт строить новую жизнь. Версия 2.0. Без вас.",
                "Расскажет всё, быстро. Через полчаса спросит: «а из-за чего мы вообще?»",
                "Хлопнет дверью, но красиво. И вернётся за зарядкой, которая «случайно» осталась.",
                "Уйдёт в тишину. Вы ищете смысл. Он ищет смысл жизни. Встретитесь на кухне в три ночи.",
                "Выдаст протокол ссоры. С пунктами. Подпишите, пожалуйста.",
                "Вспыхнет за секунду, остынет за две, час будет жалеть и приготовит вам ужин.",
            ],
            "bridge": "Узнал(а) себя? Или того, с кем ссоришься?",
            "ask": "Напиши день рождения числом — скажу, как ты ссоришься и чего хочешь на самом деле",
            "private": "Год, время рождения и пару считаем лично: ссылка в шапке профиля",
            "caption": "Как ты ссоришься — по дню рождения 😅\n\nЛистай и узнавай себя. И своего человека.\n\nНапиши свой день рождения числом в комментариях — скажу, как ты ссоришься "
                       "и чего хочешь на самом деле. Год, время и пару считаем лично: ссылка в шапке профиля.\n\n"
                       "#нумерология #деньрождения #числосудьбы #астрология #нумерита #отношения #юмор",
        },
        "en": {
            "cover": "HOW YOU ARGUE, BY BIRTH DAY",
            "sub": "Swipe. Spot yourself, and your person",
            "note": "Images of numbers, humor and symbolism, not a diagnosis",
            "lines": [
                "Won't apologize first. Will bring you tea an hour later and call it \"just tea\".",
                "Goes quiet, hurt. Expects you to guess. You didn't. Now they're hurt about that too.",
                "Gives a lecture on how to argue properly. With examples. You're not in a fight anymore, you're in a seminar.",
                "Says \"it's fine\" and leaves to build a new life. Version 2.0. Without you.",
                "Says everything, fast. Half an hour later: \"wait, what were we fighting about?\"",
                "Slams the door, beautifully. Comes back for the charger they \"accidentally\" left.",
                "Disappears into silence. You search for meaning. So do they. See you in the kitchen at 3 a.m.",
                "Hands you the minutes of the argument. Numbered. Please sign.",
                "Flares in a second, cools in two, feels guilty for an hour and cooks you dinner.",
            ],
            "bridge": "Found yourself? Or the person you argue with?",
            "ask": "Tell me your birth day as a number: I'll tell you how you argue and what you really want",
            "private": "Year, birth time and partner are best done in private: link in bio",
            "caption": "How you argue, by birth day 😅\n\nSwipe and spot yourself. And your person.\n\nTell me your birth day as a number in the comments and I'll tell you how you argue and "
                       "what you really want. Year, birth time and partner are best done in private: link in bio.\n\n"
                       "#numerology #birthday #lifepathnumber #astrology #zodiac #relationships #humor",
        },
    },
    "ok": {
        "palette": 0,
        "ru": {
            "cover": "ЧТО НА САМОМ ДЕЛЕ ЗНАЧИТ ТВОЁ «ОК»",
            "sub": "По дню рождения. Листай и переводи",
            "note": "Образы чисел, шутка и символика, не диагноз",
            "lines": [
                "«Ок». (Я сам всё сделаю. Лучше.)",
                "«Ок». (Спросите, что случилось. Нет, не сейчас. Да, сейчас.)",
                "«Ок!» (Дальше три абзаца пояснений.)",
                "«Ок». (Уже придумано три запасных плана.)",
                "«Ок))» (Через минуту: «а давай по-другому!»)",
                "«Ок, дорогой». (Запомнено. Навсегда.)",
                "«Ок». (Я где-то далеко. К вечеру вернусь.)",
                "«Ок». (Внесено в график. Срок: вчера.)",
                "«ОК!!» (Уже бегу. Уже почти. Уже.)",
            ],
            "bridge": "Какое «ок» твоё?",
            "ask": "Напиши день рождения числом — переведу и другие твои сообщения",
            "private": "Год, время рождения и пару считаем лично: ссылка в шапке профиля",
            "caption": "Что на самом деле значит твоё «ок» 😏\n\nЛистай и переводи. Узнал(а) себя или своего человека?\n\nНапиши день рождения числом — переведу и другие твои сообщения. "
                       "Год, время и пару считаем лично: ссылка в шапке профиля.\n\n#нумерология #деньрождения #числосудьбы #астрология #нумерита #юмор #мемы",
        },
        "en": {
            "cover": "WHAT YOUR \"OK\" REALLY MEANS",
            "sub": "By birth day. Swipe and translate",
            "note": "Images of numbers, humor and symbolism, not a diagnosis",
            "lines": [
                "\"OK.\" (I'll do it myself. Better.)",
                "\"OK.\" (Ask what's wrong. No, not now. Yes, now.)",
                "\"OK!\" (Followed by three paragraphs of explanation.)",
                "\"OK.\" (Three backup plans already drafted.)",
                "\"OK)))\" (In a minute: \"actually, let's do it differently!\")",
                "\"OK, sweetheart.\" (Noted. Forever.)",
                "\"OK.\" (I'm somewhere far away. Back by evening.)",
                "\"OK.\" (Scheduled. Deadline: yesterday.)",
                "\"OK!!\" (On my way. Almost there. Already running.)",
            ],
            "bridge": "Which \"OK\" is yours?",
            "ask": "Tell me your birth day as a number: I'll translate your other messages too",
            "private": "Year, birth time and partner are best done in private: link in bio",
            "caption": "What your \"OK\" really means 😏\n\nSwipe and translate. Did you spot yourself, or your person?\n\nTell me your birth day as a number and I'll translate your other "
                       "messages too. Year, birth time and partner are best done in private: link in bio.\n\n#numerology #birthday #lifepathnumber #astrology #zodiac #humor #memes",
        },
    },
    "love": {
        "palette": 4,
        "ru": {
            "cover": "КАК ТЫ ПОКАЗЫВАЕШЬ ЛЮБОВЬ, ПО ДНЮ РОЖДЕНИЯ",
            "sub": "Листай. Узнаешь свой язык любви",
            "note": "Образы чисел, шутка и символика, не диагноз",
            "lines": [
                "Любит по-королевски: решит за двоих, что вы едете в Италию. И купит билеты.",
                "Любит тихо: помнит, какой чай вы пьёте, когда плохо. Приносит, не спрашивая.",
                "Любит словами: советует, объясняет, присылает статьи. «Я о тебе думала» = ссылка на лекцию.",
                "Любит необычно: сюрприз в понедельник, платье на вешалке в ванной. Его не забывают.",
                "Любит голосовыми: четыре минуты двадцать секунд. Про всё сразу. С песней.",
                "Любит красотой: свечи, плед, цветы, вечер. Раньше, чем вы заметили, что устали.",
                "Любит присутствием: молча сидит рядом. Это максимум. И это очень много.",
                "Любит поступками: починит кран, оплатит счёт, никогда не опоздает. Слов не надо.",
                "Любит щедро: отдаст последнее, потом ждёт «спасибо» глазами. (Скажите вслух!)",
            ],
            "bridge": "Узнал(а) свой язык любви? Или того, кого любишь?",
            "ask": "Напиши день рождения числом — скажу, как ты любишь и что тебе нужно в ответ",
            "private": "Год, время рождения и пару считаем лично: ссылка в шапке профиля",
            "caption": "Как ты показываешь любовь — по дню рождения 🤍\n\nЛистай. Узнаешь свой язык любви. И язык своего человека.\n\nНапиши день рождения числом в комментариях — скажу, как ты "
                       "любишь и что тебе нужно в ответ. Год, время и пару считаем лично: ссылка в шапке профиля.\n\n"
                       "#нумерология #деньрождения #любовь #астрология #нумерита #отношения #числосудьбы",
        },
        "en": {
            "cover": "HOW YOU SHOW LOVE, BY BIRTH DAY",
            "sub": "Swipe. Find your love language",
            "note": "Images of numbers, humor and symbolism, not a diagnosis",
            "lines": [
                "Loves like royalty: decides for both of you that you're going to Italy. And buys the tickets.",
                "Loves quietly: remembers the tea you drink when things are bad. Brings it without asking.",
                "Loves in words: advice, explanations, articles. \"I was thinking of you\" = a link to a lecture.",
                "Loves unusually: a Monday surprise, a dress hanging in the bathroom. Unforgettable.",
                "Loves in voice notes: four minutes twenty seconds. About everything. With a song.",
                "Loves with beauty: candles, a blanket, flowers, an evening, before you notice you're tired.",
                "Loves by presence: sits beside you in silence. It's the maximum. And it's a lot.",
                "Loves by deeds: fixes the tap, pays the bill, is never late. No words needed.",
                "Loves generously: gives their last, then waits for a \"thank you\" with their eyes. (Say it out loud!)",
            ],
            "bridge": "Did you find your love language? Or the one you love?",
            "ask": "Tell me your birth day as a number: I'll tell you how you love and what you need back",
            "private": "Year, birth time and partner are best done in private: link in bio",
            "caption": "How you show love, by birth day 🤍\n\nSwipe. Find your love language. And your person's.\n\nTell me your birth day as a number in the comments and I'll tell you how you "
                       "love and what you need back. Year, birth time and partner are best done in private: link in bio.\n\n"
                       "#numerology #birthday #love #astrology #zodiac #relationships #lifepathnumber",
        },
    },
}


def _stars(img: Image.Image, rng: random.Random, accent: tuple, cy: int) -> Image.Image:
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W // 2 - 360, cy - 360, W // 2 + 360, cy + 360), fill=accent + (60,))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(130)))
    stars = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stars)
    for _ in range(170):
        x, y, r = rng.randrange(W), rng.randrange(H), rng.choice((1, 1, 1, 2, 2, 3))
        sd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rng.randrange(60, 220)))
    return Image.alpha_composite(img, stars)


def _fit(draw, text: str, name: str, weight: str, sizes: tuple, width: int, max_lines: int, max_h: int | None = None, lh: float = 1.22):
    """Самый крупный шрифт из sizes, при котором текст помещается и по строкам (перенос по словам), и по высоте max_h."""
    from .cards import _wrap
    for size in sizes:
        font = _font(name, size, weight)
        lines = _wrap(draw, text, font, width)
        if len(lines) <= max_lines and (max_h is None or len(lines) * int(size * lh) <= max_h):
            return font, lines, size
    return font, lines[:max_lines], size


def _dots(draw, index: int, total: int, accent: tuple) -> None:
    """Точки-индикатор слайдов вверху (графика, не надпись)."""
    gap, r = 26, 6
    x0 = W / 2 - (total - 1) * gap / 2
    for i in range(total):
        draw.ellipse((x0 + i * gap - r, 64 - r, x0 + i * gap + r, 64 + r), fill=accent + (255 if i == index else 90,))


def _arrow(draw, accent: tuple) -> None:
    """Стрелка «листай» у правого края."""
    cx, cy = W - 42, H // 2
    draw.line((cx - 18, cy, cx + 14, cy), fill=accent + (230,), width=7)
    draw.polygon([(cx + 24, cy), (cx + 6, cy - 16), (cx + 6, cy + 16)], fill=accent + (230,))


def _base(palette: int, seed: str, cy: int):
    rng = random.Random(seed)
    top, bottom, accent = PALETTES[palette % len(PALETTES)]
    img = _gradient(top, bottom).convert("RGBA")
    img = _stars(img, rng, accent, cy)
    return img, ImageDraw.Draw(img), top, accent, rng


def _jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


def render_cover(set_key: str, lang: str) -> bytes:
    data = SETS[set_key]
    t = data[lang]
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    font, lines, size = _fit(probe, t["cover"], "PlayfairDisplay.ttf", "Bold", (84, 76, 68, 60, 54, 48), W - 150, 4, lh=1.18)
    sub_font, sub_lines, _ = _fit(probe, t["sub"], "Montserrat.ttf", "Medium", (36, 32, 28), W - 200, 2)
    lh = int(size * 1.18)
    text_h = len(lines) * lh + 20 + len(sub_lines) * 46
    text_top = H - 190 - text_h  # текст стоит над подписью бота
    ring = min(285, max(170, text_top - 110 - 90))
    cy = max(ring + 105, min(470, text_top - ring - 60))
    img, d, top, accent, rng = _base(data["palette"], f"{set_key}-{lang}-cover", cy)
    cx = W // 2
    d.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=accent + (150,), width=3)
    d.ellipse((cx - ring - 42, cy - ring - 42, cx + ring + 42, cy + ring + 42), outline=accent + (45,), width=2)
    a = rng.uniform(0, 6.28)
    px, py = cx + ring * math.cos(a), cy + ring * math.sin(a)
    d.ellipse((px - 15, py - 15, px + 15, py + 15), fill=accent + (255,))
    pts, big = [], ring * 150 / 285
    for k in range(16):  # звезда в центре
        r = big if k % 2 == 0 else big * 0.3
        ang = math.pi / 8 * k - math.pi / 2
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    d.polygon(pts, fill=accent + (255,))
    y = text_top
    for line in lines:
        d.text((cx, y), line, font=font, fill=(255, 255, 255, 255), anchor="ma")
        y += lh
    y += 20
    for line in sub_lines:
        d.text((cx, y), line, font=sub_font, fill=accent + (240,), anchor="ma")
        y += 46
    _dots(d, 0, 5, accent)
    _arrow(d, accent)
    _footer(d, cx)
    return _jpeg(img)


def render_groups(set_key: str, lang: str, part: int) -> bytes:
    """Слайд part (0–2): три группы дней рождения с их сценами; один размер шрифта на весь слайд."""
    data = SETS[set_key]
    t = data[lang]
    img, d, top, accent, rng = _base(data["palette"], f"{set_key}-{lang}-g{part}", 240 + part * 330)
    cx = W // 2
    top_y, block = 130, 340
    sizes = (60, 56, 52, 48, 44, 40, 36)
    uniform = min(_fit(d, t["lines"][part * 3 + k], "PlayfairDisplay.ttf", "SemiBold", sizes, W - 210, 4, max_h=226)[2] for k in range(3))
    tfont = _font("PlayfairDisplay.ttf", uniform, "SemiBold")
    lh = int(uniform * 1.22)
    for k in range(3):
        idx = part * 3 + k
        y = top_y + k * block
        label = GROUPS[idx]
        font = _font("Montserrat.ttf", 40, "Bold")
        tw = d.textlength(label, font=font)
        d.rounded_rectangle((cx - tw / 2 - 34, y, cx + tw / 2 + 34, y + 70), radius=35, fill=accent + (255,))
        d.text((cx, y + 35), label, font=font, fill=top + (255,), anchor="mm")
        from .cards import _wrap
        lines = _wrap(d, t["lines"][idx], tfont, W - 210)
        ty = y + 96 + max(0, (block - 96 - 30 - lh * len(lines)) // 2)
        for line in lines:
            d.text((cx, ty), line, font=tfont, fill=(255, 255, 255, 255), anchor="ma")
            ty += lh
    _dots(d, 1 + part, 5, accent)
    _arrow(d, accent)
    _footer(d, cx)
    return _jpeg(img)


def render_bridge(set_key: str, lang: str) -> bytes:
    data = SETS[set_key]
    t = data[lang]
    img, d, top, accent, rng = _base(data["palette"], f"{set_key}-{lang}-bridge", 520)
    cx = W // 2
    pts = []
    for i in range(16):
        r = 110 if i % 2 == 0 else 34
        ang = math.pi / 8 * i - math.pi / 2
        pts.append((cx + r * math.cos(ang), 250 + r * math.sin(ang)))
    d.polygon(pts, fill=accent + (255,))
    font, lines, size = _fit(d, t["bridge"], "PlayfairDisplay.ttf", "Bold", (76, 68, 60, 54), W - 150, 3)
    y, lh = 420, int(size * 1.2)
    for line in lines:
        d.text((cx, y), line, font=font, fill=(255, 255, 255, 255), anchor="ma")
        y += lh
    y += 40
    pfont, plines, psize = _fit(d, t["ask"], "Montserrat.ttf", "SemiBold", (40, 36, 32), W - 220, 4)
    plh = int(psize * 1.35)
    box_h = len(plines) * plh + 56
    d.rounded_rectangle((90, y, W - 90, y + box_h), radius=44, fill=accent + (255,))
    ty = y + 28
    for line in plines:
        d.text((cx, ty), line, font=pfont, fill=top + (255,), anchor="ma")
        ty += plh
    y += box_h + 44
    nfont, nlines, nsize = _fit(d, t["private"], "Montserrat.ttf", "Medium", (30, 28, 26), W - 200, 3)
    for line in nlines:
        d.text((cx, y), line, font=nfont, fill=(255, 255, 255, 215), anchor="ma")
        y += int(nsize * 1.4)
    y += 14
    fn, fl, fs = _fit(d, t["note"], "Montserrat.ttf", "Medium", (24, 22), W - 200, 2)
    for line in fl:
        d.text((cx, y), line, font=fn, fill=(255, 255, 255, 130), anchor="ma")
        y += int(fs * 1.4)
    _dots(d, 4, 5, accent)
    _footer(d, cx)
    return _jpeg(img)


def render_set(set_key: str, lang: str) -> list[bytes]:
    """Пять слайдов: обложка, три слайда по три группы, финал с мостом к боту (в Instagram до десяти)."""
    return [render_cover(set_key, lang)] + [render_groups(set_key, lang, p) for p in range(3)] + [render_bridge(set_key, lang)]


def caption(set_key: str, lang: str) -> str:
    return SETS[set_key][lang]["caption"]
