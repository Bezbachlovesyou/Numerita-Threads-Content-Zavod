# Three bounded safety corrections, prepared

Owner requested completing unfinished improvements. This review branch fixes
three source-level conditional risks reported by the security monitor.

1. Brand video: durable atomic claim through existing claim_slot before paid
   generation. Multiple workers start one attempt. After cancellation or an
   uncertain failure, no automatic regeneration. This sacrifices automatic
   recovery to avoid repeated spending. Existing completed versions stay done;
   no version key is incremented, no old video is re-sent, no paid API was called.
   Recovery requires verifying provider billing and delivery before a separate
   operator action. Per-scene caching is not implemented or claimed.
2. Instagram: explicit configured destination remains supported. Automatic
   selection requires exactly one Instagram username/handle numerita.ai.
   Ambiguity/missing username stops publishing. Legacy first-account cache is
   ignored; only the newly verified cache is used. Real vendor fields/accounts
   are not accessible here, so production behavior must be verified before merge.
3. Redo replies: caller passes existing reply_budget_usd/timezone; same daily
   override and measured spending check run before each generation. Hourly and
   per-run limits remain. This is a preflight guard, not a provider hard billing
   cap; concurrent requests can still overshoot an estimate as in the old path.

Six tests on SQLite and a dedicated local PostgreSQL fixture cover concurrent
workers, cancellation/restart, legacy/ambiguous destination, exhausted budget
and rechecking between calls. All external generators, Telegram and Zernio
are stubs. Existing Instagram and redo tests are also run. No production DB,
users, keys, scheduled automation or dependency manifest was changed.

Manual tools/selftest.sh, check.sh and safe_push.sh validate this review branch.
The push gate rejects main/master. These are local validation scripts, not
scheduled automations. PostgreSQL fixture name numerita_factory_safety is local
on /tmp port5433; tests must never use a production DSN.

Status: prepared, not deployed. Factory Railway IDs/access are not confirmed
in the shared registry; do not merge to its auto-deploy branch blindly.
Rollback: revert code; no schema changes. Claim/cache records are not deleted
by rollback. Do not clear a paid claim merely to retry an uncertain request.
