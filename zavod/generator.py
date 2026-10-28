"""Генерация постов через OpenRouter (OpenAI-совместимый Chat Completions API).

https://openrouter.ai/docs/api-reference/chat-completion
"""

import logging
import re
from pathlib import Path

import httpx

from .codereply import numbers_note
from .knowledge import KnowledgeBase

API_URL = "https://openrouter.ai/api/v1/chat/completions"
KEY_URL = "https://openrouter.ai/api/v1/key"

log = logging.getLogger(__name__)


HOOK_CHECK = (
    "Ты строгий редактор Threads. Оцени пост по шкале 1–10: зацепит ли он человека в ленте настолько, что тот "
    "захочет написать комментарий. 10 — первая строка бьёт в нерв (интрига, узнавание с поворотом, дерзкая мысль, "
    "живая сцена, юмор), пост вызывает эмоцию, а последняя строка — крючок-обмен «напиши X — и получишь лично Y». "
    "1–5 — энциклопедия, лекция, перечень, сухой призыв без награды, всё уже сказано и спрашивать незачем. "
    "Ответ строго в две строки:\nОЦЕНКА: <число>\nПОЧЕМУ: <главная слабость одной фразой>"
)
# Текстовый юмористический поток (text_mode, 27.10.2026): вопрос в конце не обязателен — ценим панч и узнавание.
HOOK_CHECK_TEXT = (
    "Ты строгий редактор Threads. Оцени короткий юмористический текст по шкале 1–10: остановит ли он палец в ленте "
    "и захочется ли переслать или ответить. 10 — первая строка цепляет сразу, есть узнаваемая бытовая сцена и острый "
    "неожиданный панч, текст короткий (до ~280 знаков). Вопрос или призыв в конце не обязателен. 1–5 — назидание, "
    "лекция, перечень, нет шутки или панч предсказуем. "
    "Ответ строго в две строки:\nОЦЕНКА: <число>\nПОЧЕМУ: <главная слабость одной фразой>"
)
STRENGTHEN = (
    "Пост ниже не цепляет: {why}\nПерепиши его так, чтобы человек в ленте замер и захотел ответить. Первая строка — "
    "интрига, узнавание с поворотом, дерзкая мысль или живая сцена; эмоция и юмор; без лекций и перечней на всех; "
    "последняя строка — крючок-обмен «напиши X — и я лично сделаю для тебя Y» (игривый подарок, которого в посте нет). "
    "Смысл, числа и трактовки сохраняй, только из базы знаний Нумериты. Без ссылок и «сохрани», до 450 знаков. "
    "Верни только текст поста.\n\nПост:\n{text}"
)
REPLY_FALLBACK = "anthropic/claude-haiku-5.5"
REPLY_KB_CHARS = 1500  # 25.10.2026 (слово владельца): было 4000 — выдержка была основной частью цены ответа  # ответу хватает сути чисел из комментария; вся выдержка — основная часть цены ответа

SHARPEN = (
    "Ниже готовый пост из плана. Сам по себе он слабый: справка про число, какой полно везде, — без крючка, "
    "без юмора и без повода ответить. Перепиши его так, чтобы его хотелось прочитать до конца, переслать другу "
    "и прокомментировать.\n"
    "Планка: первая строка останавливает ленту (узнавание с неожиданным поворотом, непопулярное мнение, "
    "разрыв любопытства, точная бытовая сцена); одна острая или смешная деталь из жизни, по которой человек "
    "узнаёт себя или друга; трактовки — только из базы знаний Нумериты, смысл и числа исходника сохраняй; "
    "последняя строка — лёгкий вопрос или задание, на которое ответить можно за 3 секунды в комментариях "
    "(число, имя, «да/нет», отметить друга) — в виде обмена: «напиши X — и я лично сделаю для тебя Y», где Y — "
    "игривый личный подарок (суперсила, запрет на неделю, роль в фильме о твоей жизни, вердикт пары). "
    "Если в исходнике готовые ответы для всех чисел — оставь интригу, а ответ отдай лично в комментариях. "
    "Тон игривый, с юмором, вдохновляющий, не энциклопедия. Без ссылок и адресов, без «сохрани», без цен, до 450 знаков. "
    "Верни только текст поста.\n\nИсходник:\n{text}"
)


def clean_key(raw: str) -> str:
    """Убирает то, что часто попадает в ключ при копировании: пробелы, кавычки, «Bearer »."""
    key = raw.strip().strip("'\"").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def mask_key(key: str) -> str:
    return f"{key[:12]}…{key[-4:]} ({len(key)} симв.)" if len(key) > 16 else f"({len(key)} симв.)"


def complete_sentences(text: str) -> str:
    """Обрезает оборванный текст до последнего законченного предложения (или пусто, если такого нет)."""
    match = list(re.finditer(r"[.!?…)»✨🌙💫🔥🤍]\s", text + " "))
    return text[: match[-1].start() + 1].strip() if match else ""


class GenerationError(Exception):
    pass


class Generator:
    def __init__(self, api_key: str, model: str, voice_path: Path, knowledge: KnowledgeBase):
        self.api_key = clean_key(api_key)
        self.model = model
        self.system = voice_path.read_text(encoding="utf-8")
        playbook = voice_path.with_name("playbook.md")  # хуки, сторителлинг, что заходит в Threads
        if playbook.exists():
            self.system += "\n\n" + playbook.read_text(encoding="utf-8")
        emotions = voice_path.with_name("emotions.md")  # палитра эмоций: как вовлекать осознанно и бережно
        if emotions.exists():
            self.system += "\n\n" + emotions.read_text(encoding="utf-8")
        reply_path = voice_path.with_name("reply_voice.md")
        self.reply_system = reply_path.read_text(encoding="utf-8") if reply_path.exists() else self.system
        abundance = voice_path.with_name("abundance.md")  # деньги и изобилие: вдохновляем, не обесцениваем
        if abundance.exists():
            text = abundance.read_text(encoding="utf-8")
            self.system += "\n\n" + text
            self.reply_system += "\n\n" + text
        from . import text_mode
        if text_mode.enabled():
            self.system += '\n\n' + text_mode.STYLE
        self.knowledge = knowledge
        self.reply_model = model  # модель ответов на комментарии (задаётся при запуске)
        self.cost_sink = None  # async (kind, usd, prompt_tokens, completion_tokens, cached_tokens) — учёт расходов

    async def _with_knowledge(self, prompt: str, about: str, limit: int | None = None) -> str:
        excerpt = (await self.knowledge.excerpt(about))[:limit]
        if not excerpt:
            return prompt
        return (
            "База знаний Numerita (выдержка). Трактовки чисел, расчёт и правила голоса бери отсюда. Если вопрос шире "
            "выдержки (знаки и планеты в астрологии, психология, книги, наука) — отвечай по сути по общепринятым знаниям, "
            "конкретно и сравнительно, честно отделяя символические трактовки от фактов; не отвечай «в базе нет»:\n"
            f"{excerpt}\n\n{prompt}"
        )

    async def improve(self, system: str, prompt: str, max_tokens: int | None = None, kind: str = "other",
                      model: str | None = None) -> str:
        """Свободный запрос к модели (самоулучшение контент-плана)."""
        return await self._complete(system, prompt, max_tokens=max_tokens, kind=kind, model=model)

    async def write_reply(self, post: str, comment: str, author: str, mode: str = "plain",
                          model: str | None = None) -> str:
        """Ответ на комментарий под постом. «SKIP» — отвечать не нужно.

        mode: plain — польза и разговор без приглашения; старые profile/question/offer также plain;
        link — человек сам попросил, где посчитать: бот добавит ссылку после ответа.
        """
        endings = {
            "plain": "Про бота и профиль не пиши.",
            "profile": "В конце с улыбкой намекни, что в боте Нумериты человек узнает гораздо больше: полный разбор "
                       "по имени и дате (а если назвал две даты — полную совместимость пары) — «ссылка в шапке профиля».",
            "question": "Ответь по сути. Если на вопрос точнее ответить по дате рождения — последней фразой скажи, "
                        "что по дате Нумерита ответит лично в боте, «ссылка в шапке профиля». Иначе про бота не пиши.",
            "offer": "Последней фразой мягко, без давления и без цен скажи, что в Telegram у Нумериты за 10 секунд — "
                     "карта по имени и дате, а там и полный разбор (если назвал две даты — совместимость пары). "
                     "Ссылку бот добавит сам строкой ниже.",
            "link": "Человек сам спросил, где узнать больше: ответь по сути и последней фразой скажи, что посчитать "
                    "своё число души и судьбы можно у Нумериты в Telegram — ссылку бот добавит сам строкой ниже.",
        }
        mode = "link" if mode == "link" else "plain"
        prompt = (
            numbers_note(comment)  # числа уже посчитаны кодом (слово владельца 25.10.2026)
            + f"Наш пост:\n{post}\n\nКомментарий от @{author}:\n{comment}\n\n"
            + "Сам не пиши никаких ссылок, адресов и @упоминаний. " + endings[mode]
        )
        prompt = await self._with_knowledge(prompt, comment, REPLY_KB_CHARS)
        model = model or self.reply_model
        try:
            return await self._complete(self.reply_system, prompt, max_tokens=400, kind="reply", model=model)
        except GenerationError:
            if model == REPLY_FALLBACK:
                raise
            # Дешёвая модель не справилась (пусто, сбой провайдера) — один раз пишет запасная.
            log.warning("Модель ответов %s не ответила — пишет %s", model, REPLY_FALLBACK)
            return await self._complete(self.reply_system, prompt, max_tokens=400, kind="reply", model=REPLY_FALLBACK)

    def _system_content(self, system: str, model: str):
        """Длинные правила одинаковы у всех запросов — у моделей Anthropic кэшируем их: повторное чтение
        стоит десятую часть цены (кэш живёт 5 минут, а ответы идут каждые 2–5 минут)."""
        if not model.startswith("anthropic/"):
            return system
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    async def _record_cost(self, kind: str, usage: dict) -> None:
        if self.cost_sink is None or not usage:
            return
        try:
            cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            await self.cost_sink(kind, float(usage.get("cost") or 0), int(usage.get("prompt_tokens") or 0),
                                 int(usage.get("completion_tokens") or 0), int(cached))
        except Exception:
            log.exception("Не удалось записать расход")

    async def check_key(self) -> None:
        """Проверяет ключ при запуске и пишет результат в логи Railway."""
        if not self.api_key.startswith("sk-or-"):
            log.error("OPENROUTER_API_KEY не похож на ключ OpenRouter (должен начинаться с sk-or-v1-): %s",
                      mask_key(self.api_key))
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                response = await http.get(KEY_URL, headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as e:
            log.warning("Не удалось проверить ключ OpenRouter: %s", e)
            return
        if response.is_success:
            log.info("Ключ OpenRouter принят: %s", mask_key(self.api_key))
        else:
            log.error("OpenRouter НЕ принял ключ %s: %s %s",
                      mask_key(self.api_key), response.status_code, response.text[:200])

    async def write_post(self, topic: str, previous: str | None = None) -> str:
        from . import text_mode
        grid = text_mode.enabled() and text_mode.grid_enabled() and text_mode.GRID_MARKER in topic
        if grid:
            topic += '\n\n' + text_mode.GRID_STYLE
        elif text_mode.enabled():
            topic += '\n\n' + text_mode.STYLE
        prompt = await self._with_knowledge(f"Тема поста: {topic}", topic)
        if previous:
            prompt += (
                "\n\nВот предыдущий вариант, он не подошёл. "
                f"Напиши заметно другой пост на ту же тему:\n\n{previous}"
            )
        system = self.system.replace(text_mode.STYLE,'') if grid else self.system
        return await self._complete(system, prompt, kind="post")

    async def hook_score(self, text: str) -> tuple[int, str]:
        """Дешёвая проверка крючка (модель ответов): оценка 1–10 и главная слабость."""
        from . import text_mode
        check = HOOK_CHECK_TEXT if text_mode.enabled() else HOOK_CHECK
        raw = await self._complete(check, text, max_tokens=120, kind="hookcheck", model=self.reply_model)
        score = re.search(r"ОЦЕНКА:\s*(\d+)", raw)
        why = re.search(r"ПОЧЕМУ:\s*(.+)", raw)
        return (int(score.group(1)) if score else 10), (why.group(1).strip() if why else "")

    async def strengthen(self, text: str, why: str) -> str:
        from . import text_mode
        task = STRENGTHEN.format(text=text, why=why or "нет крючка")
        if text_mode.enabled():  # крючок-обмен в конце не навязываем юмористическому тексту
            task = task.replace("последняя строка — крючок-обмен «напиши X — и я лично сделаю для тебя Y» (игривый "
                                "подарок, которого в посте нет). ", "сильный неожиданный панч в конце. ")
        prompt = await self._with_knowledge(task, text)
        if text_mode.enabled(): prompt += '\n\n' + text_mode.STYLE
        return await self._complete(self.system, prompt, kind="strengthen")

    async def sharpen(self, text: str) -> str:
        """Огранка готового поста из плана: голый кусок справки превращаем в пост, в который хочется вовлечься."""
        prompt = await self._with_knowledge(SHARPEN.format(text=text), text)
        from . import text_mode
        if text_mode.enabled(): prompt += '\n\n' + text_mode.STYLE
        return await self._complete(self.system, prompt, kind="sharpen")

    async def _complete(self, system: str, prompt: str, max_tokens: int | None = None, _retry: bool = False,
                        kind: str = "other", model: str | None = None) -> str:
        from .honesty import apply
        system = apply(system)
        model = model or self.model
        try:
            async with httpx.AsyncClient(timeout=180) as http:
                response = await http.post(
                    API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "X-Title": "Numerita Threads Content Zavod",
                    },
                    json={
                        "model": model,
                        **({"max_tokens": max_tokens} if max_tokens is not None else {}),
                        "usage": {"include": True},
                        # Короткие ответы без «размышлений»: рассуждения — это оплачиваемые токены выхода.
                        **({"reasoning": {"enabled": False}} if kind in ("reply", "summary", "hookcheck")
                           and not model.startswith("anthropic/") else {}),  # цена каждого запроса — для отчёта о расходах
                        "messages": [
                            {"role": "system", "content": self._system_content(system, model)},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
        except httpx.HTTPError as e:
            raise GenerationError("Не удалось связаться с OpenRouter.") from e

        try:
            payload = response.json()
        except ValueError:
            raise GenerationError(f"OpenRouter вернул ошибку {response.status_code}.")
        if response.is_error or "error" in payload:
            message = payload.get("error", {}).get("message", response.text)
            if response.status_code == 429:
                message = "превышен лимит запросов, попробуйте через минуту"
            elif response.status_code == 401:
                message = (f"ключ не принят ({message}). Проверьте OPENROUTER_API_KEY на Railway: "
                           f"сейчас бот видит {mask_key(self.api_key)}")
            elif response.status_code == 402:
                message = "закончились деньги на балансе OpenRouter"
            raise GenerationError(f"Ошибка OpenRouter: {message}")

        await self._record_cost(f"{kind}·{model.split('/')[-1]}" if kind in ("reply", "summary") else kind,
                                payload.get("usage") or {})
        choice = payload["choices"][0]
        text = (choice["message"].get("content") or "").strip()
        if choice.get("finish_reason") == "length" and max_tokens and not _retry:
            # Модель упёрлась в предел длины (часть уходит на «размышления») — обрывок не публикуем:
            # повторяем с запасом, а если снова оборвалось — режем по последнему законченному предложению.
            log.warning("Ответ оборвался на пределе %s токенов — повторяю с запасом", max_tokens)
            return await self._complete(system, prompt, max_tokens=max_tokens * 4, _retry=True, kind=kind, model=model)
        if choice.get("finish_reason") == "length":
            text = complete_sentences(text)
        if not text:
            raise GenerationError("Модель вернула пустой ответ.")
        return text


