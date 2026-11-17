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


async def report(db, now: datetime, days: int = 7, raw: dict | None = None) -> str:
    from .optimizer import short_name
    posts = await db.engagement(now - timedelta(days=days))
    out = [f"📊 Что сработало за {days} дн.: постов {len(posts)}, просмотров {sum(int(p['views'] or 0) for p in posts)}, "
           f"лайков {sum(int(p['likes'] or 0) for p in posts)}, комментариев {sum(int(p['comments'] or 0) for p in posts)}"]
    out.append("\nТоп-5 постов (просмотры · лайки · комментарии — рубрика — первая строка):")
    for p in sorted(posts, key=_score, reverse=True)[:5]:
        out.append(f"{int(p['views'] or 0)} · {int(p['likes'] or 0)} · {int(p['comments'] or 0)} — {short_name(p['rubric'])} — {_first_line(p['text'])}")
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
    return "\n".join(out)
