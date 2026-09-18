# Task 1R.1 evidence handoff — worker_01 (zcode / GLM-5.3-Flash)

Task id: `mw_protocol_v3_1r1_sqlite_20260905` — Task1R.1 product SQLite adapter,
explicit factory route, dual-backend ports contract suite. Red-first, minimal
implementation, isolation zone only. This file is additive worker evidence;
Codex owns acceptance.

## Files changed / created (all within declared write paths)

| File | Change |
|---|---|
| `services/api/app/protocol_workflow/storage/sqlite.py` | NEW — product SQLite adapter (~1500 lines incl. docstrings) |
| `services/api/app/protocol_workflow/storage/selected.py` | MODIFIED — module-level import of the product builder + new `create_product_unit_of_work_factory` route + `__all__` entry + docstring truth updates. Behavior of existing functions unchanged; the `StorageNotReadyError` blocker message bytes are untouched (negative tests assert "sqlite.py"/"pocs"/"Codex follow-up" substrings). |
| `tests/protocol_v3/test_repository_backends.py` | NEW — backend-parametrized dual-backend contract suite (48 tests: 24 × memory/sqlite) |
| `tests/protocol_v3/test_sqlite_product_storage.py` | NEW — product-specific checks (24 tests) |
| `runs/mw_protocol_v3_1r1_20260905/*` | NEW — this evidence (red/green outputs, runtime identity) |

Scope check: `git status` shows no other modifications by this worker. The other
tracked modifications (`scripts/qc/...`, `tests/fixtures/...`,
`test_frozen_authority_manifest.py`, `test_repository_hygiene_mutator.py`) were
pre-existing Phase R changes present before dispatch. PoC, main.py, frontend,
monitoring, old tests/fixtures untouched. No package installed; no service
started; DBs created only under pytest tmp dirs.

## Public API for Codex composition (exact)

Config contract (validated fail-closed by the adapter):

```python
{
    "backend": "sqlite",        # required, exactly "sqlite" (selected.py also checks)
    "path": "<db file path>",   # required, non-empty str or PathLike
    "busy_timeout_ms": 5000,    # optional, positive int (bool rejected)
    "synchronous": "FULL",      # optional, only "FULL" accepted
}
```

Product route (explicitly enabled, the ONLY path supplying the real builder):

```python
from app.protocol_workflow.storage.selected import create_product_unit_of_work_factory
factory = create_product_unit_of_work_factory(config={"backend": "sqlite", "path": ...})
with factory() as uow: ...
```

Neutral factory unchanged: `create_unit_of_work_factory(config=..., adapter_builder=None)`
still raises `StorageNotReadyError` (message bytes preserved);
`adapter_builder=build_unit_of_work_factory` injection stays compatible.
Memory remains reachable only via `create_test_memory_unit_of_work_factory()`.

Adapter exports: `SqliteStorageError(RuntimeError)`,
`SqliteStorageConfigurationError`, `SqliteSchemaVersionError`,
`MIN_SQLITE_VERSION=(3,51,3)`, `assert_sqlite_version()`, `parse_sqlite_version`,
`SCHEMA_VERSION_LATEST=1`, `SqliteUnitOfWork` (plus `connection_pragmas()`
diagnostics), `build_unit_of_work_factory(config)`.

## Red-first evidence

- `red_evidence.txt` — both new test modules collected BEFORE implementation:
  `ModuleNotFoundError: No module named 'app.protocol_workflow.storage.sqlite'`
  and `ImportError: cannot import name 'create_product_unit_of_work_factory'`;
  exit 2, "2 errors during collection".
- Implementation written after the red run; no test was weakened to pass.

## Green evidence

- `green_focused.txt` — `tests/protocol_v3/test_repository_backends.py` +
  `tests/protocol_v3/test_sqlite_product_storage.py`: **104 passed**.
- `green_full_suite.txt` — full `tests/protocol_v3`:
  `1344 passed, 2 warnings, 101 subtests passed in 18.85s` (R.3 baseline
  1240+101 + 104 new = 1344 ✓). Command:
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:. /opt/homebrew/bin/python3.12 -m pytest tests/protocol_v3 -q -p no:cacheprovider --tb=short`
- `runtime_identity.txt` — `/opt/homebrew/bin/python3.12` links SQLite 3.53.4
  (≥ 3.51.3 gate ✓). Version gate additionally fail-closed-tested by
  monkeypatching 3.51.2 (asserts no file/dir created before the gate).

## Design decisions Codex should know

1. **Schema v1 + ordered atomic migrations.** `schema_version` table; fresh DBs
   bootstrap in ONE transaction (interrupted first init can never leave a
   version-table-only brick); upgrades apply pending migrations each in their
   own `BEGIN IMMEDIATE` with an in-transaction version re-check. Future
   schema (version > 1) → `SqliteSchemaVersionError`, contents untouched
   (tested). Foreign DB without `schema_version` → `SqliteStorageConfigurationError`,
   never adopted (tested). Non-database file → same, byte-identical (tested).
2. **Project-scoped identity PKs.** Deliberate schema deviation from the PoC:
   `execution_reservation` PK is `(project_id, execution_reservation_id)`
   (outbox/inbox likewise) because the PORT treats those ids as project-scoped
   (`get(project_id, id)`), while the PoC used global PKs — the PoC would
   IntegrityError on the same reservation id in two projects where memory
   (the ports reference implementation) allows it. Shared suite covers
   same-logical-ids-across-projects for aggregates, streams, outbox, inbox,
   reservations.
3. **Reservation attempt-collision detection pre-INSERT.** Memory raises
   `IdempotencyConflictError` when a second reservation reuses
   `(project, logical_call, attempt)` with a different idempotency key; the PoC
   relied on the UNIQUE constraint and leaked `sqlite3.IntegrityError`. The
   product adapter checks identity/attempt collisions explicitly and raises the
   port error (covered on both backends).
4. **Validate-then-insert event batches.** Mirrors memory semantics: a batch
   with a bad event writes ZERO rows, so an exception caught inside a larger
   transaction never leaks a partial batch (dedicated test on both backends).
   The PoC inserted per-event and would leave rows 1..k-1 inside the caller's
   transaction.
5. **Read-model mutators match application callers:** `replace_chapter_coverage`
   / `replace_decision_graph` (full replacement, stale rows cleared, tested) +
   `upsert_workflow_run_status` — same names as memory so projector code is
   backend-agnostic. PoC only had `upsert_*` which would NOT clear stale rows.
6. **Enum round-trips** (`SideEffectKind`, `CanonicalState`, `WorkflowRunStatus`,
   statuses) are stored as `.value` and parsed back to enum on read, matching
   memory equality semantics (PoC stored `str(enum)` and leaked a raw string).
7. **selected.py wiring constraint.** The existing structural test
   (`test_no_database_private_leakage_from_selected_surface`) forbids
   function-scope imports anywhere except `create_test_memory_unit_of_work_factory`
   and forbids SQL/driver/journal tokens in the source. The product builder is
   therefore imported once at module level (clean, no trickery);
   `storage.sqlite` import is side-effect-free (subprocess test: empty-cwd
   import creates no file/dir/worker).
8. **Post-close reads.** The product UoW raises `UnitOfWorkClosedError` on ALL
   handle operations after close (memory still allows reads after close). Both
   behaviors are port-legal (port leaves post-commit readability
   adapter-specific); the shared suite only observes through open UoWs.
9. **No benchmark machinery.** No checkpoint/quarantine tables, no crash child,
   no `RetryableStorageError` retry driver, no auto-retry anywhere (schema test
   asserts those PoC tables are absent).
10. **Not covered here (out of 1R.1 scope):** multi-writer concurrency, crash
    recovery, backup/restore — PoC evidence + Task 1R.3 own those; artifact
    store (`uow.artifact_store is None` for SQLite); router mounting (1R.2).

## Verification needs remaining for Codex

- Independent fresh verification (worker does not close the task).
- Composition decision: whether 1R.2 should call
  `create_product_unit_of_work_factory` from the composition root or keep
  passing `build_unit_of_work_factory` through the injection hook.
- Whole-repo pytest intentionally NOT run (per context: legacy main imports).
