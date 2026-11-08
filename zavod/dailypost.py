"""Пост дня для ручной публикации в Facebook и Instagram (слово владельца 08.11.2026): раз в день владельцу приходит лучший по реакциям
пост недели — готовый текст для копирования, подпись с хэштегами (≤5) и промпт для Grok (картинка/ролик 9:16 по канону Нумериты).
Всё считает код ($0): лучший = лайки + 3×комментарии по последнему замеру; один и тот же пост дважды не присылаем; ссылок и @упоминаний в тексте нет."""
import json
import re
from datetime import timedelta

from . import instagram, lang

MIN_AGE = timedelta(hours=12)
LINK_RE = re.compile(r"(https?://\S+|t\.me/\S+|@\w+)", re.I)
SKIP_RUBRICS = {"grid"}  # матрицы живут видео в Threads; для ручного поста берём текст

CANON = ("Нумерита: светлый цифровой ангел-хранитель, лицо и причёска как в референсе (прикрепи assets/numerita_angel.jpg); "
         "вокруг головы отдельный светящийся нимб из переливающихся золотых цифр (вращается только нимб, лицо неподвижно); "
         "фон: звёздная вселенная, мерцающие звёзды, дальние кометы, мягкая туманность, золотой цифровой дождь как в «Матрице» "
         "(только цифры, без букв и иероглифов, 20 планов глубины); взгляд в кадр; вертикаль 9:16, без сплющивания; "
         "без надписей сверху, снизу только @Numeritabot")


def screen_text(text: str) -> str:
    """Надпись на экране: первая строка поста (хук), не длиннее 90 знаков, по границе слова."""
    first = LINK_RE.sub("", text).strip().split("\n")[0].strip()
    return first if len(first) <= 90 else first[:90].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"


def grok_prompt(text: str) -> str:
    return (f"Вертикальный ролик 9:16, 8 секунд. {CANON}. Нумерита смотрит в камеру и мягко произносит главную мысль; "
            f"плавный наезд камеры, свет переливается по цифрам. На экране аккуратная плашка с текстом: «{screen_text(text)}». "
            "Музыка спокойная, космическая. Без насилия, без страшных образов.")


def clean(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", LINK_RE.sub("", text)).strip()


async def pick(db, now):
    best, best_score = None, -1
    sent = set(json.loads(await db.kv_get("dailypost:sent") or "[]"))
    for post in await db.recent_published(now - timedelta(days=7)):
        if post.id in sent or post.rubric in SKIP_RUBRICS or not post.published_at or now - post.published_at < MIN_AGE:
            continue
        sample = json.loads(await db.kv_get(f"performance:{post.id}:latest") or "{}")
        if sample.get("likes") is None:
            continue
        score = (sample.get("likes") or 0) + 3 * (sample.get("comments") or 0)
        if score > best_score:
            best, best_score = (post, sample), score
    return best


async def messages(db, now) -> list[str]:
    if lang.is_en():
        return []
    got = await pick(db, now)
    if not got:
        return []
    post, sample = got
    sent = json.loads(await db.kv_get("dailypost:sent") or "[]")[-60:] + [post.id]
    await db.kv_set("dailypost:sent", json.dumps(sent))
    text = clean(post.text)
    caption = instagram.limit_hashtags(f"{text}\n\nСсылка — в шапке профиля ✨\n\n{instagram.TAGS_BY_LANG['ru']}")[:2200]
    head = (f"📲 Пост дня для Facebook и Instagram: лучший за неделю ({sample.get('likes') or 0} лайков, "
            f"{sample.get('comments') or 0} комментариев).\nНиже две части: 1) подпись, скопируй как есть; 2) промпт для Grok (картинка или ролик 9:16).")
    return [head, caption, "🎬 Промпт для Grok:\n" + grok_prompt(text)]
