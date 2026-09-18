# Execution Output: mw_protocol_v3_1r2_mount_20260905 - worker_01

## Boundary And Context Check

- Read: execution context + Codex plan, `.trellis/tasks/09-05-protocol-v3-1r2/{prd,design,implement}.md`, `.trellis/spec/protocol-v3.md`, review amendment, 1R.1 storage gate. No home/SOUL files read; no project AGENTS.md needed (instructions self-contained).
- Worked only inside the runner CWD. 1R.1 frozen hashes verified intact at start (`sqlite.py 18770a1c…`, `selected.py 153fc687…`, both frozen tests match). Pre-existing dirty tracked files (AGENTS.md, hygiene scripts, baseline, frozen manifest) untouched — final `git diff` shows only my 3 tracked edits layered on top.
- No commits, no cleanup, no Trellis state changes, no task close. No live/model/OCR/translation/Word/service calls; tmp SQLite + fakes only, `/opt/homebrew/bin/python3.12` + `PYTHONPATH=services/api:packages:`. Main-owned venv under `runs/mw_protocol_v3_1r_integration_20260905/venv` never touched.
- Tools used: `read` (source/tests/plans), `grep` (callsites, pins), `bash` (pytest, hashes, env probes), `write` (1 new test file, 1 new module, 1 evidence note), `edit` (4 files). Every edit re-ground via tool echoes; three mangled-edit repairs verified by syntax probe + test run.

## Work Performed

Red-first, then minimal implementation of Task 1R.2 only:

1. **Red tests** — new `tests/protocol_v3/test_protocol_v3_1r2_mount.py` (29 tests). Red confirmed: `ModuleNotFoundError: app.protocol_workflow.api.composition`.
2. **`storage/sqlite.py`** — migration **v2** adds `protocol_workflow_project_allowlist(project_id PK, admitted_at)` + fingerprint; `SCHEMA_VERSION_LATEST` 1→2 (ownership preflight, `_reference_schema_fingerprint`, history validation all version-parameterized already). New `is_project_admitted(config, project_id)` (read-only: missing/empty/v1 file → `False`, never creates/migrates; foreign/malformed → loud `SqliteStorageConfigurationError`) and `admit_project(config, project_id)` (bootstraps via `_bootstrap`, idempotent `INSERT OR IGNORE`, first admission wins). No `CutoverStateRegistry`, no pocs/monitoring/legacy imports.
3. **`api/router.py`** (additive only) — public `protocol_workflow_not_found_envelope()` (reuses `_not_found_envelope`, zero new error shape) and optional `route_class` passthrough on `create_protocol_workflow_router` (default behavior unchanged).
4. **`api/composition.py`** (new, sole main wiring surface) — `protocol_workflow_config_from_env()` (pure; `WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED` truthy ∈ {1,true,yes,on}, default off; `…_DB` required iff on else fail-closed `ValueError`; `…_BUSY_TIMEOUT_MS` optional); `_LazyProductUnitOfWorkFactory` (defers `create_product_unit_of_work_factory` to first admitted request, thread-safe); `_ValidationEnvelopeRoute` (route-scoped Chinese 422 via the public validation handler; `HTTPException` passes through); admission `Depends` gate (read-only allowlist check → 404 not-found envelope before any UoW acquisition); `mount_protocol_workflow_router(app) -> bool` (off → `False`, app untouched).
5. **`app/main.py`** (narrow: 1 import + 1 call after `eligibility_router`) — `mount_protocol_v3_workflow_router(app)`; off by default = no routes/DB/worker.
6. **Superseded assertions updated** (1R.2 explicitly supersedes Task 1.9 no-mount rule): `test_main_py_…` → narrow-contract test (exactly one mount call; no router-factory/service/storage references); `test_sqlite_product_storage.py` v2 pins (`_PRODUCT_TABLES` + allowlist, bootstrap→v2, repeat-init→v2); the two synthetic-migration tests now build a true v1 base (`_MIGRATIONS[:1]`, `LATEST=1`) so their v1-history assertions hold verbatim.

## Artifacts And Evidence

- `runs/mw_protocol_v3_1r2_20260905/focused_1r2_mount.xml` — 28 passed, 1 skipped.
- `runs/mw_protocol_v3_1r2_20260905/full_protocol_v3.xml` — **1400 passed, 1 skipped, 101 subtests passed, 16.17s**.
- `runs/mw_protocol_v3_1r2_20260905/red_first.md` — red-run record.
- Proven: default-off no-op (no routes/files/threads, legacy 422 list-shape intact); enable-without-DB fail-closed naming the env var; empty/non-admitted → 404 Chinese envelope with DB file never created; admitted POST→GET→events round-trip on real WAL SQLite with identical `revision_sha256`; restart rebuild preserves allowlist/rows/hashes, outsider still 404; real v1 DB → v2 migration history `[(1,),(2,)]`, rows + event hashes equal, gate read leaves v1 at version 1; route-scoped 422 envelope coexists with legacy 422 on one app; AST scan finds no cutover/banned-surface references in the three product files.
- Hash drift (relevant, intended — needs verifier re-freeze): `sqlite.py 18770a1c…→61737a8c…`; `test_sqlite_product_storage.py 6710dd96…→a755d8ce…`. Unchanged: `selected.py 153fc687…`, `test_repository_backends.py 0b1dd33b…`.

## Commands And Observations

- Red: `pytest tests/protocol_v3/test_protocol_v3_1r2_mount.py -x` → `ModuleNotFoundError: composition` (expected).
- Green: above suites; `TestClient` + `app.openapi()` used for route presence (this FastAPI keeps includes as context wrappers, no `route_class` param on `include_router` — hence the factory-level `route_class` passthrough).
- Runtime: linked SQLite 3.53.4 (≥3.51.3 ✓), FastAPI 0.137.2, `xlrd` present, `fitz` absent in homebrew python.
- Main.py has no global `RequestValidationError` handler — route-scoped envelope was the correct choice; legacy 422 shape proven unchanged.

## Blockers Or Missing Environment

- **Real-main isolated entrypoint test skips** (not faked, not deleted): `test_real_main_isolated_entrypoint` → `SKIPPED: blocked on Main-owned legacy deps missing from /opt/homebrew/bin/python3.12: fitz(PyMuPDF); needs Main dependency-venv isolation closure`. `xlrd` is present; only `fitz` blocks. The test auto-activates once Main's venv closure lands. No packages installed, no global env changed.
- **Full-repository/main regression not run** — explicitly forbidden by the work item until Main's isolation closure; `tests/protocol_v3` full-dir regression is green as the bounded substitute.
- Deliberate behavior to note: enabling the flag without `WORKBENCH_PROTOCOL_V3_WORKFLOW_DB` raises `ValueError` at import (fail-closed); rollback is unsetting the flag. No HTTP admission endpoint exists by design (out-of-band `admit_project` only).

## Rerun Requests Or Next Step

- No rerun needed. Ready for Codex review + fresh verifier: freeze new hashes above, run the skipped real-main test after the dependency-venv closure, then proceed to 1R.3 (replay/backup). Task left open; no cleanup performed.
