# Execution Output: mw_protocol_v3_1r4_storage_impl_20260905 - worker_01

## Boundary And Context Check

- Work dir only; no production paths touched; no product calls, installs, live writes, cleanup, or task closure.
- Read assigned set: `context/mw_protocol_v3_1r4_storage_impl_20260905_execution_context.md`, `plans/codex_execution_mw_protocol_v3_1r4_storage_impl_20260905.md`, `context/mw_protocol_v3_1r4_result_storage_20260905_context.md`, plus authorized sources: `.trellis/tasks/09-05-protocol-v3-1r4/{prd,design,implement}.md`, `plans/mw_protocol_v3_review_amendment_20260905.md` (1R.4 rows), `storage/sqlite.py`, `storage/memory.py`, `ports/repositories.py`, `events/{inbox,outbox,store,unit_of_work}.py`, `tests/protocol_v3/{test_sqlite_product_storage,test_repository_backends,test_event_outbox_atomicity}.py`. Extra reads were required to pin the exact migration representation, port freeze, and legacy-test fingerprint expectations; each is named here.
- Writes strictly to the two authorized paths: `services/api/app/protocol_workflow/storage/sqlite.py` (edit) and `tests/protocol_v3/test_result_storage_consolidation.py` (new). No existing test modified. Report returned in-response only; runner persists it.

## Work Performed

- Wrote failing tests first: new file with 17 tests → red run showed 10 failed (all consolidation assertions), 7 passed (standalone/port/failure paths already correct). Evidence the red was real: e.g. `assert _inbox_count(...) == 0` failed with `1 == 0` (legacy dual-write present).
- Implemented Task 1R.4 in `storage/sqlite.py` only:
  - Migration 3 (append-only, additive): `ALTER TABLE outbox_message ADD COLUMN result_sha256 / result_received_at / result_consumed_at` (all nullable; old rows get NULL). Fingerprint entry carries the full 15-column `outbox_message` shape. `SCHEMA_VERSION_LATEST` is now 3.
  - Minimal representation: paired-result state = three nullable columns. `result_sha256 NULL` = no receipt; set + `result_consumed_at NULL` = RECEIVED; both set = CONSUMED. Dispatch `status` (`COMPLETED`) is untouched by receipt/consumption — no synthesized premature completion flag.
  - Single authority: `_SqliteInboxRepository` routes by key. Outbox row exists (and v3 columns present) → writes update only outbox columns, never insert into `inbox_result`. No outbox row → legacy `inbox_result` path verbatim (standalone never invents dispatch). Missing-columns probe keeps pre-migration/monkeypatched schemas on the legacy path.
  - History: `get_result` prefers consolidated outbox state once present, else returns the historical row unchanged; historical rows are never UPDATEd/DELETEd. First post-migration write adopts history verbatim (same id/sha/timestamps, including CONSUMED). Hash conflicts name history (`IdempotencyConflictError` against outbox or historical sha).
  - Port surface unchanged: `OutboxMessage`/`InboxResult` shapes, all outbox methods, and standalone inbox id transitions are byte-identical.
- Green run: 18/18 new tests (added a v3 UNIQUE-loss preflight test after triage). Related suites (`test_repository_backends`, `test_event_outbox_atomicity`) fully green.

## Artifacts And Evidence

- `services/api/app/protocol_workflow/storage/sqlite.py`: +migration 3, +rewritten `_SqliteInboxRepository` with authority docstring.
- `tests/protocol_v3/test_result_storage_consolidation.py`: 18 tests across migration, single-authority, received/consumed distinction, standalone compat, historical preservation, end-to-end no-duplicate-effects, v3 preflight.
- Red receipt: `10 failed, 7 passed` on first run. Green receipt: `18 passed` for the new file; `123 passed` with backends+atomicity.
- Full `tests/protocol_v3`: `4 failed, 1449 passed`. All 4 failures triaged as stale legacy expectations (existing tests unmodified per boundary):
  1. `test_sqlite_product_storage.py::TestSchemaVersionAndMigrations::test_bootstrap_creates_product_schema_with_version_two` — literal `== 2` vs new 3.
  2. Same file `test_repeated_initialization_is_safe` — same literal (`assert 3 == 2`).
  3. `test_protocol_v3_1r2_mount.py::...::test_v1_database_migrates_preserving_rows_and_hashes` — history `[(1,),(2,),(3,)] == [(1,),(2,)]`; rows/hashes asserts before it passed.
  4. `test_sqlite_product_storage.py::TestConstraintIntegrityPreflight::test_unique_constraint_loss_on_outbox_is_rejected` — fixture hardcodes 12-col outbox DDL; construction fails (`has 12 columns but 15 values were supplied`) before any preflight assert. Negative-intent still valid; my new `TestV3ConstraintPreflight` proves UNIQUE-loss on the widened table is still rejected with the file untouched.
- Tree note: `git status` shows both my files as untracked (`??`) and many pre-existing `M` entries (AGENTS.md, main.py, etc.) I did not touch.

## Commands And Observations

- Red: `.../venv/bin/python -m pytest tests/protocol_v3/test_result_storage_consolidation.py -q -p no:cacheprovider` (exact context env: `env -i PATH=... HOME=/Users/smkzw TMPDIR=.../T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false`) → 10 failed, 7 passed, 0.46 s. Venv SQLite 3.53.4 ≥ gate 3.51.3.
- Green (same env): new file 18 passed; +backends+atomicity 123 passed; full `tests/protocol_v3` 4 failed / 1449 passed in ~29 s.
- Self-inflicted churn during test edits (dropped `import pytest`, misplaced hash snapshot, two broken intermediate edits) was repaired in-file; final file verified green. No source edits were reverted.

## Blockers Or Missing Environment

- No blocking environment gap; venv/toolchain worked as specified.
- Needs Codex disposition (not worker-actionable): the 4 legacy failures above. Proposed minimal updates for Codex-owned follow-up: bump `== 2` literals to `== 3` (2 tests), extend expected history to `[(1,),(2,),(3,)]` (1R.2 mount test), extend the UNIQUE-loss fixture DDL with the 3 nullable result columns. Also `TestSchemaVersionAndMigrations` name `..._version_two` is stale.

## Rerun Requests Or Next Step

- Rerun new tests: same exact env with `pytest tests/protocol_v3/test_result_storage_consolidation.py -q -p no:cacheprovider`. Expected: 18 passed.
- Rerun suite: `pytest tests/protocol_v3 -q -p no:cacheprovider`. Expected: 1449 passed + the same 4 disposition-pending failures; any additional failure is a real regression.
- Remaining verification (Codex-owned): independent verifier replay of actual migration/recovery per implement.md step 4; Codex acceptance and task closure. Worker does not accept own task.
