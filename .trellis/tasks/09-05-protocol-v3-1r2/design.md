# 1R.2 design

Reuse existing router factory and ApplicationService via narrow actual-main
composition. Preserve service injection tests and fresh coordinator semantics.
Explicit default-off config plus durable per-project allowlist, never an
in-memory cutover registry. Only admitted requests acquire product service.

Prefer allowlist in product SQLite via versioned migration, keeping schema
ownership verification intact. No manual unknown table insertion. Construct
configuration/router without DB opening or worker startup on import/mount.
Route-scope validation handling and delegate legacy errors to existing handler.
No automatic project enrollment or public activation API in this phase.

Real-main tests require tmp runtime plus sanitizing inherited AI settings,
role settings and eligibility artifact paths. Never use LIVE launch scripts.
Rollback through default-off and isolated snapshots, not unrelated git resets.
