"""Сводка «что сработало» за N дней (слово владельца 17.11.2026: «табличка о самых больших достижениях и какие форматы их
спровоцировали»): топ постов, рубрики по просмотрам/комментариям/приходу в бота, расходы. $0 — только база и учёт бота."""
import json
from datetime import datetime, timedelta

from . import attribution


def _score(p: dict) -> float:
    return int(p["comments"] or 0) + 0.2 * int(p["likes"] or 0) + int(p["views"] or 0) / 200


def _first_line(text: str) -> str:
    line = next((s.strip() for s in (text or "").splitlines() if s.strip()), "")
    return line[:60] + ("…" if len(line) > 60 else "")


def _avg(rows: list[dict], key: str) -> float:
    return sum(int(r[key] or 0) for r in rows) / len(rows) if rows else 0.0


def conclusions(posts: list[dict]) -> list[str]:
    """Выводы кодом ($0), слово владельца 20.11.2026: «когда я отключаюсь, без меня выходит шняга — проверь цифрами».
    Посты владельца (через пульт, topic ops:…) против автоматических; сколько постов вообще «зашло»; лучшая и худшая рубрика."""
    if not posts:
        return ["\nВыводы: постов за период нет."]
    hits = [p for p in posts if int(p["comments"] or 0) >= 5 or int(p["likes"] or 0) >= 10]
    dead = [p for p in posts if int(p["comments"] or 0) == 0 and int(p["likes"] or 0) <= 2]
    own = [p for p in posts if str(p.get("topic") or "").startswith("ops:")]
    auto = [p for p in posts if p not in own]
    out = ["\nВыводы:",
           f"• зашло (5+ комментариев или 10+ лайков): {len(hits)} из {len(posts)}; пустых (0 комментариев, до 2 лайков): {len(dead)}."]
    if own and auto:
        oc, ol, ac, al = _avg(own, "comments"), _avg(own, "likes"), _avg(auto, "comments"), _avg(auto, "likes")
        verdict = "посты с участием владельца сильнее" if oc + ol / 5 > 1.2 * (ac + al / 5) else \
                  "автоматические не хуже" if ac + al / 5 >= oc + ol / 5 else "разница небольшая"
        out.append(f"• посты владельца (пульт) — {len(own)}: в среднем {oc:.1f} комм. и {ol:.1f} лайка; "
                   f"автоматические — {len(auto)}: {ac:.1f} и {al:.1f} → {verdict}.")
    by: dict[str, list[dict]] = {}
    for p in posts:
        by.setdefault(p["rubric"], []).append(p)
    ranked = sorted(((r, _avg(v, "comments") + _avg(v, "likes") / 5, len(v)) for r, v in by.items() if len(v) >= 2),
                    key=lambda x: x[1], reverse=True)
    if len(ranked) >= 2:
        from .optimizer import short_name
        out.append(f"• лучшая рубрика (от 2 постов): {short_name(ranked[0][0])}; слабее всех: {short_name(ranked[-1][0])}.")
    return out


async def report(db, now: datetime, days: int = 7, raw: dict | None = None) -> str:
    from .optimizer import short_name
    posts = await db.engagement(now - timedelta(days=days))
    out = [f"📊 Что сработало за {days} дн.: постов {len(posts)}, просмотров {sum(int(p['views'] or 0) for p in posts)}, "
           f"лайков {sum(int(p['likes'] or 0) for p in posts)}, комментариев {sum(int(p['comments'] or 0) for p in posts)}"]
    def row(p):
        return f"{int(p['views'] or 0)} · {int(p['likes'] or 0)} · {int(p['comments'] or 0)} — {short_name(p['rubric'])} — {_first_line(p['text'])}"
    out.append("\nТоп-5 по комментариям (просмотры · лайки · комментарии — рубрика — первая строка):")
    out += [row(p) for p in sorted(posts, key=lambda p: (int(p["comments"] or 0), int(p["likes"] or 0)), reverse=True)[:5]]
    out.append("\nТоп-5 по лайкам:")
    out += [row(p) for p in sorted(posts, key=lambda p: (int(p["likes"] or 0), int(p["comments"] or 0)), reverse=True)[:5]]
    out += conclusions(posts)
    table = await attribution.rubric_table(db, now, days, raw)
    out.append("\nРубрики (постов · просм./пост · комм./пост · пришли в бота · оплатили):")
    for t in sorted(table, key=lambda t: (-t["paid"], -t["came"], -(t["views"] or 0) / max(t["posts"], 1)))[:10]:
        vpp = round((t["views"] or 0) / max(t["posts"], 1))
        out.append(f"{short_name(t['rubric'])}: {t['posts']} · {vpp} · {t['comments_per_post']:.1f} · {t['came']} · {t['paid']}")
    spent = 0.0
    for i in range(days):
        ledger = json.loads(await db.kv_get(f"cost:{(now - timedelta(days=i)).date().isoformat()}") or "{}")
        spent += sum(v[1] for v in ledger.values())
    came = sum(t["came"] for t in table)
    out.append(f"\nРасход завода: ${spent:.2f}" + (f", на одного пришедшего ${spent / came:.2f}" if came else ", пришедших по меткам нет"))
    from . import pdfpost
    out.append(pdfpost.describe(await pdfpost.best_slots(db, now)))
    return "\n".join(out)
