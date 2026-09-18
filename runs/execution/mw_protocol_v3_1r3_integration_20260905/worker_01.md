# Execution Output: mw_protocol_v3_1r3_integration_20260905 - worker_01

## Boundary And Context Check

- Read `context/mw_protocol_v3_1r3_integration_20260905_execution_context.md`, `plans/codex_execution_mw_protocol_v3_1r3_integration_20260905.md`, Trellis 1R.3 `prd.md`/`design.md`/`implement.md`, amendment `plans/mw_protocol_v3_review_amendment_20260905.md` (1R.3 rows), product seams (`storage/sqlite.py`, `storage/selected.py`, `application/service.py`+`commands.py`+`queries.py`, `events/unit_of_work.py`+`models.py`, `api/router.py`+`composition.py`+`schemas.py`, `errors.py`, `ports/repositories.py`, `canonical/study_definition.py`), and existing helpers (`test_protocol_v3_1r2_mount.py`, `test_application_service.py`, `test_sqlite_product_storage.py` patterns). No PoC imports in new tests.
- Writes confined to authorized paths: `tests/protocol_v3/integration/` (3 new files) and `runs/mw_protocol_v3_1r3_20260905/` (new evidence). Zero edits to existing tests, fixtures, product sources, config, docs. No services started, no models/OCR/translation/Word, no live/monitoring, no network, no credentials. Synthetic identities only (`proj:1r3:*`, `sd:1r3:*`), tmp-dir databases. Test env exactly as mandated (venv python 3.12.13, SQLite 3.53.4, `env -i … PYTHONPATH=services/api:packages:.`).
- Concurrent working-tree change observed mid-session (details §5): adapted expectations, made no product edits.

## Work Performed

Created `tests/protocol_v3/integration/` (auto-collected via `testpaths=tests`):

- `integration_shared.py` — pytest-free shared builders (child processes import it): product factory/service with fixed clock, genesis/decision/command builders, JSON-safe canonical fingerprint (revision hash, canonical state, facts, decision lineage, stream head), raw table dumps, integrity/WAL/file-list probes, fixed `admitted_at` for deterministic dumps.
- `test_sqlite_end_to_end.py` (14 tests): commit durability across close + fresh-factory reopen; separate-process read with byte-identical canonical fingerprint; exact replay after restart writes nothing (`replayed=True`, 1 event, 1 outbox row); same-CAS-triple/different-payload → `P1_DECISION_CAS` without write; WAL-consistent backup/restore via `Connection.backup` while source open (integrity ok, full 10-table dump equality, fingerprint/event/outbox/allowlist equality, 2 admitted projects, restored copy writable rev3→rev4) with bare-main-file contrast proven stale (rev 2/2 events vs live rev 3/3 events); atomic rollback for CAS (`RevisionConflictError`), event-chain (`EventSequenceConflictError`), and outbox (`IdempotencyConflictError`) faults; stale apply → `P1_REVISION_STALE`; `_translate` mapping pins (incl. checkpoint-mismatch non-retryable, abort-without-cause → CAS); injected-COMMIT-failure → raw driver error (untyped, untrusted) → reconcile-by-logical-key → single-effect retry.
- `test_mounted_api_integration.py` (5 tests): mounted-composition mutation→GET agreement with direct adapter reads; all GETs (incl. 404s) produce zero business-table/file changes; stale apply → 409 typed envelope, 4 keys exactly, `can_retry=True`, no `.sqlite`/traceback/driver leaks; injected COMMIT failure → 500 unknown-outcome envelope (`can_retry=False`, "结果尚未确认…暂勿重复提交") → GET 404 reconcile → one identical retry → 1 event; real `app.main` in two processes (create, then read after restart) with hash equality and outsider 404.

## Artifacts And Evidence

- `tests/protocol_v3/integration/integration_shared.py`, `test_sqlite_end_to_end.py`, `test_mounted_api_integration.py` (new, owned).
- `runs/mw_protocol_v3_1r3_20260905/1r3_integration_focused.xml` + `.log`: **19 passed**.
- `runs/mw_protocol_v3_1r3_20260905/protocol_v3_regression.xml` + `.log`: **1424 passed** (1405 existing + 19 new), 0 failures, 1 pre-existing tar-extract DeprecationWarning.
- `runs/mw_protocol_v3_1r3_20260905/probe_diagnosis_20260905.py`: evidence probe behind the two first-run reds (kept, authorized dir).
- First-pass assessment: honest green. The two initial reds were test-side (my stale-read expectation; my WAL-lifecycle assumption), each diagnosed with product-code evidence and fixed in the tests; no product defect found, no expected values altered, nothing manufactured.

## Commands And Observations

- Focused: `env -i PATH=… HOME=… TMPDIR=… LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/integration -q --junitxml=runs/mw_protocol_v3_1r3_20260905/1r3_integration_focused.xml` → 19 passed.
- Regression: same env with `pytest tests/protocol_v3` → 1424 passed in ~31 s.
- Red 1 (HTTP unknown-commit): expected old generic envelope (`can_retry=True`, "请稍后重试") from my first `router.py` read; observed 500 + `can_retry=False` + "当前操作的结果尚未确认…暂勿重复提交". `git diff` shows `router.py` (plus 10 pre-existing 1R.2-session files) modified uncommitted in the working tree during my session (`_unexpected_envelope` rewritten to the reconcile-before-retry envelope). Current behavior satisfies the 1R.3 amendment (no blanket retry of unknown commits). Pinned current envelope exactly. No product edit by me.
- Red 2 (WAL premise): `wal size 0` — probe proved that with zero open connections SQLite checkpoints the WAL into the main file on last close (`-wal` empty/absent though data durable). Restructured: hold one open connection across the final service commit → frames stay in WAL (premise asserts `wal>0`, now deterministic) → backup + stale bare-copy contrast.
- `git status` confirms my footprint is only the two new owned paths; the `M` entries are the concurrent session's work.

## Blockers Or Missing Environment

- None. Venv already had Python 3.12 / SQLite 3.53.4 / fitz / xlrd; no installs performed.

## Rerun Requests Or Next Step

- Codex rerun: the two commands in §5 (focused, then `tests/protocol_v3`), followed by a fresh verifier; 1R.2 whole-repo collection debt stays open and separate per amendment (not claimed PASS here).
- Suggested Codex note: working-tree product/test modifications from the concurrent session (11 `M` files incl. `router.py`, `main.py`, api-contract tests) are uncommitted — confirm ownership/landing separately; my tests pin current working-tree behavior.
- No cleanup performed per instructions; probe and logs retained as evidence.
