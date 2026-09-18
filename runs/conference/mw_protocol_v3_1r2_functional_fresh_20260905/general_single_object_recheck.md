I'll re-read the current mount tests and API docs, then re-run the isolated suite to check whether F1 and F2 actually landed.F2 docs look updated. Next I’ll inspect the DurableJobWorker sweeper and re-run the isolated mount suite to see whether the new OFF comparison actually holds.The isolated suite is 31 passed with the new default-off child. I’ll attribute the sweeper thread to the existing `DurableJobWorker` and report F1/F2 against the current tests and docs.

# Conference Participant Output: mw_protocol_v3_1r2_functional_fresh_20260905 - general_single_object_recheck

## Boundary Check

- Same bounded role: `general_single_object`, read-only source review, no edits, no sibling files, no live/service/model, no task close, no full-repository pytest.
- Read this follow-up’s initial set plus the cited implementation points: `tests/protocol_v3/test_protocol_v3_1r2_mount.py`, `services/api/app/protocol_workflow/api/__init__.py`, `api/router.py` (module + `create_protocol_workflow_router` docstring), `main.py:585-591` and `:2494-2496`, `medical_writing_durable_jobs.py` `DurableJobWorker.__init__` / `_start_sweeper`.
- Allowed verification only: the original isolated mount command.
- Original `general_single_object.md` was not rewritten. This text is the new runner artifact.

## Independent Work Product

**F1 and F2, as originally cited, are resolved.** This is a recheck of those two defects, not a 1R.2 gate PASS, not full-repository status, and not task acceptance.

### F1 (actual-main OFF + fail-closed deps) — resolved

**Deps no longer skip.** `skipif` is gone. `test_real_main_isolated_entrypoint` (`test_protocol_v3_1r2_mount.py:738-744`) `assert not _MISSING_LEGACY_DEPS` and fails with the isolated venv hint. Missing `fitz`/`xlrd` is red, not skip.

**OFF child exists; ON child remains.** The same test is parametrized `enabled in [False, True]` (`:738`, ids `default-off` / `enabled`). ON still admits, imports `app.main`, and round-trips create/get/events (`:691-734`, `:795-802`).

**OFF comparison vs no-op mount does test “no added v3 routes / product DB / v3 threads,” with the right control for legacy impurity.**

Child with flag absent (`:665-689`, parent pops `ENV_ENABLED` at `:766-767`):

- Import-time thread snapshot, then `import app.main`.
- Asserts no `protocol-workflow` in `route.path`.
- `GET /api/projects/proj:1r2:admitted/protocol-workflow/study-definitions/sd:x` must be FastAPI default `{"detail": "Not Found"}` (not the Chinese admission envelope).
- Product DB path `WORKBENCH_PROTOCOL_V3_WORKFLOW_DB` must not exist (checked after that GET).
- Prints `{disabled, started_threads}`.

Second fresh child (`:786-793`) sets `BASELINE_WITHOUT_V3_MOUNT=1`, which replaces `composition.mount_protocol_workflow_router` with `lambda app: False` **before** `import app.main` (`:669-671`). Parent requires `payload == baseline_payload`.

That equality is a differential check against a patched no-op, not a claim that `app.main` import is thread-free.

**Why a zero-thread assertion would be wrong:** `main.py:2496` always constructs `DurableJobWorker(mw_durable_store)` after the v3 mount line (`:591`). `DurableJobWorker.__init__` (`medical_writing_durable_jobs.py:1053-1054`) starts `_start_sweeper` by default. `_start_sweeper` (`:1260-1265`) starts a daemon named `durable-mw-sweeper`. That is pre-existing medical-writing recovery, not the 1R.2 chain. Do not change that worker for 1R.2. The no-op baseline also imports `app.main`, so both children start the sweeper; extra v3 threads would make `started_threads` differ.

**Does this actually cover the three “no added” claims?**

| Claim | How it is checked | Strength |
|---|---|---|
| No added v3 routes | Independent `route.path` scan **and** HTTP GET must stay default 404 JSON | HTTP is the real gate: a mounted empty-allowlist chain would return the Chinese `detail` dict. `route.path` alone can miss include wrappers (the in-process helper uses OpenAPI for that). HTTP covers the user path. |
| No product database | `Path(WORKBENCH_PROTOCOL_V3_WORKFLOW_DB).exists()` is false after import + GET; both children assert this | Targets the v3 sqlite path, not `WORKBENCH_RUNTIME_DIR` legacy files. Correct split. |
| No added v3 threads | Import-time `(name, target __qualname__)` delta equal to no-op-mount child | Attributes `durable-mw-sweeper` to legacy. Does **not** snapshot threads after `TestClient`/startup. |

Python binding of the baseline patch is valid: `main.py` does `from ...composition import mount_protocol_workflow_router as mount_protocol_v3_workflow_router` at import, so a pre-import attribute swap is what `app.main` binds.

### F2 (stale Task 1.9 mount / global handler docs) — resolved at the cited sites

- `create_protocol_workflow_router` (`router.py:662-663`): now “factory remains locally testable. Product mounting is owned only by `composition.mount_protocol_workflow_router` (Task 1R.2).”
- `api/__init__.py:7-9` and `:22-24`: product mounting is the 1R.2 composition switch; do not register the validation handler globally on `app.main`.

**Residual docs, not a reopened F2 blocker:** `router.py` **module** docstring still says the shared `main.py` is not edited and the router is not product-mounted (`:10-13`), and still tells hosting apps they SHOULD register the validation handler (`:36-39`). That contradicts the updated function docstring and `__init__.py`. Hygiene only; it does not un-mount or register a global handler.

### Checks run this recheck

```
env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:.
WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false
runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
tests/protocol_v3/test_protocol_v3_1r2_mount.py -q -p no:cacheprovider
```

**Result: `31 passed in 8.41s`, exit 0, 0 skipped.** Count is previous 30 plus the new default-off parametrization (ON still present). Longer wall time matches two extra `app.main` subprocesses on the OFF branch.

### Not inferred as PASS

Codex: do not infer PASS from this request; full repository collection has separate gaps; F5 / process replay-backup stay 1R.3. This recheck only closes the two cited defects.

## Evidence And Assumptions

### Evidence

- Test body: fail-closed deps `:742-744`; OFF child `:665-689`; baseline patch `:669-671`, `:786-793`; payload equality `:793`; ON path `:691-734`, `:795-802`.
- `DurableJobWorker` sweeper: `main.py:2496`; constructor `:1053-1054`; thread name `durable-mw-sweeper` at `:1260-1265`. Mount call is earlier at `main.py:591`.
- F2 function/`__init__` text as quoted above. Leftover module docstring `router.py:10-13, 36-39`.
- Pytest: 31 passed, 8.41s, isolated venv, no skip.

### Assumptions

- Codex dispositions stand: F5 HTTP mapping and process replay/backup are 1R.3; no security program; do not alter the durable-mw sweeper.
- `from composition import mount_...` in `app.main` sees the patched attribute in the baseline child.

### Inference

- Equal `started_threads` in this run means the default-off mount added no extra named import-time thread beyond the no-op control. Not a proof that startup/`TestClient` never starts other legacy threads (both children run GET; those threads are outside the compared snapshot).

### Uncertainty

- `route.path` vs OpenAPI include wrappers is theoretically weak; the default 404 JSON is the compensating observation.
- Adjacent `test_protocol_v3_api_contract.py` / `test_sqlite_product_storage.py` / `test_repository_backends.py` and full-repo collection still not executed here.

## Risks, Gaps, And Verification Needs

**Residuals (not F1/F2 reopeners)**

- `router.py` module header still carries Task 1.9 “main untouched / not product-mounted” and a global-handler SHOULD. Optional docstring-only cleanup.
- Test module header (`test_protocol_v3_1r2_mount.py:29-31`) still says the real-main entrypoint is skipped when deps are missing. False; it now fails. Optional comment fix.
- In-process “restart” is still a new `FastAPI()` over the same file, not process replay of `app.main` (1R.3 per Codex).
- Admission `SqliteStorageError` still unmapped to the Chinese 500 envelope (F5 → 1R.3).
- Full-repository / historical import gaps: out of this focused suite; report separately.

**Verification still not this role**

- Adjacent three pytest files; full repository; live env var audit; Trellis close.

## Recommended Next Step

Treat **F1 and F2 as resolved** for this functional recheck. Optional non-blocking docstring/comment cleanup (`router.py` module header; test file skip wording). Do **not** change `DurableJobWorker` / `durable-mw-sweeper`. Do **not** add security tests. Do **not** close 1R.2 from this conference object.

**Scoped recommendation:** 1R.2 **functional review of the previously blocking F1/F2 items: RESOLVED.** Overall 1R.2 **task/gate status: not accepted here** — full-repository evidence and final Codex acceptance remain separate.

**Decision points left with Codex (not this role)**

- Whether leftover `router.py` module docstring is worth a one-line cleanup in allowed paths.
- Adjacent suite + full-repo ownership stays with main owner.

**Bounded questions:** none required to keep F1/F2 closed. F5/replay remain 1R.3 as already disposed.
