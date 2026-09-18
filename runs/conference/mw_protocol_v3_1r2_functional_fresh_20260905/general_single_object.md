I'll start from the assigned conference context and plan, then independently verify the Task1R.2 source against those requirements.Source of truth is the 1R.2 PRD/design plus the amendment, then I'll inspect the current mount, storage, and tests independently.Requirements are loaded. Next I’ll inspect the live mount, composition, storage, and the 1R.2 tests without using prior reviewer conclusions.Mount is in `main.py`; I’ll now check the import alias, SQLite allowlist/migration, and whether tests actually prove default-off and persistence.I’m going into the SQLite allowlist/migration path, `main.py` wiring, and the older contract tests that may still encode the superseded no-mount/v1 assertions.A likely real-main conflict is the existing client-contract middleware. I’ll check that path matching and whether old “must not mount” tests were actually upgraded.I’ll run the allowed isolated mount suite next, then inspect any remaining default-off or real-main gaps against the results.I have enough independent evidence: the enabled real-main path passed, but default-off on actual `app.main` is still unproven and the H6 skipif can hide a missing entrypoint. Drafting the conference report.# Conference Participant Output: mw_protocol_v3_1r2_functional_fresh_20260905 - general_single_object

## Boundary Check

- Role: `general_single_object` (独立代码设计审阅). Grok Build / grok-4.6. No chair authority, no final acceptance.
- Stayed inside the runner-bound workspace. Did not read `/Users/smkzw/.codex/AGENTS.md`, `/Users/smkzw/.hermes/SOUL.md`, worker reports, or other participant outputs. Did not use a project `AGENTS.md`.
- No source edits, no sibling report files, no production/live paths, no product-model/OCR/translation/Word calls, no service start, no dependency install, no full-repository pytest.
- Allowed verification only: isolated-venv focused mount suite, credential-free child env as specified.
- Report is returned in this response only; runner persists `runs/conference/mw_protocol_v3_1r2_functional_fresh_20260905/general_single_object.md`.

## Independent Work Product

**Verdict for Codex (1R.2 functional close): `NOT_READY`.**

The implemented wiring matches the approved 1R.2 shape on source inspection, and the focused suite is green including an actual-`app.main` **enabled** HTTP round-trip. That is not enough to close the task. The safety property that “default-off keeps the real main entry on the old chain” is not evidenced on `app.main`, and the only actual-main test is skippable on missing legacy deps, which would still yield pytest exit 0. PRD/H6 say dependency errors do not count as pass.

### What the code actually does (source, not executor claims)

1. **Actual main mount exists and is narrow.** `services/api/app/main.py:199-201` imports only `mount_protocol_workflow_router` (aliased `mount_protocol_v3_workflow_router`). `main.py:585-591` calls it once, with no config object, so it reads process env at import. No router factory, `ApplicationService`, or storage symbol is referenced from `main.py`.

2. **Default-off is a no-op of `include_router`, not a hidden route.** `composition.py:104-112` treats absent/non-truthy `WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED` as `enabled=False`. `create_mounted_protocol_workflow_router` returns `None` (`composition.py:229-230`). `mount_protocol_workflow_router` then returns `False` without `app.include_router` (`composition.py:271-277`). Truthy set is `{1,true,yes,on}` after strip/lower.

3. **Enable without DB path fails closed at mount, which on real main means import failure.** `ProtocolWorkflowMountConfig.adapter_config` (`composition.py:90-96`) raises `ValueError` naming `WORKBENCH_PROTOCOL_V3_WORKFLOW_DB`. That is invoked only after `enabled=True`. On `app.main`, this is module-import time, so a mis-set flag takes down legacy startup too. Fail-closed is intended; rollback is unset the flag.

4. **Admission is out-of-band SQLite, not `CutoverStateRegistry`.** Migration 2 (`sqlite.py:453-468`) adds `protocol_workflow_project_allowlist(project_id PK, admitted_at)` with an ownership fingerprint. `SCHEMA_VERSION_LATEST` is `_MIGRATIONS[-1][0]` → 2. `is_project_admitted` (`sqlite.py:2228-2294`) is read-only: missing/empty file → `False`; v1 (`version < 2`) → `False` without migrate; foreign/malformed → `SqliteStorageConfigurationError`. `admit_project` (`sqlite.py:2297-2336`) is the only enrollment path: `_bootstrap` then `INSERT OR IGNORE`. Composition has no HTTP admit route. Router-level `Depends` (`composition.py:201-214, 247-250`) 404s with the public Chinese not-found envelope before the lazy product factory runs.

5. **Product service construction is lazy; registry load is not.** `_LazyProductUnitOfWorkFactory` (`composition.py:149-175`) defers `create_product_unit_of_work_factory` to first admitted UoW. Enabled mount **does** call `load_skill_registry` immediately (`composition.py:232-235`). That is file I/O, not DB/worker. `ApplicationService.__init__` only stores the factory; no worker thread.

6. **v1→v2 migration is a new table only.** `_bootstrap` (`sqlite.py:761-810`) preflights owned schema read-only, then applies pending migrations atomically with version-row insert. Migration 2 does not rewrite `event_stream` / `aggregate_revision`. A v1 file is not migrated by HTTP admission; only `admit_project` / factory bootstrap migrates.

7. **Validation is route-scoped.** `_ValidationEnvelopeRoute` (`composition.py:178-198`) catches only `RequestValidationError` and returns the Chinese 422 envelope. Legacy routes on the same app keep default FastAPI 422 lists. `main.py` does not register `protocol_workflow_validation_exception_handler` globally. Client-contract middleware (`runtime_readiness.py:156-163`) matches `/medical-writing` and `POST /api/projects`, not `protocol-workflow`.

### Highest-impact defect

**H6 actual-main default-off is not tested, and the only actual-main test can skip green.**

- **Evidence:** `tests/protocol_v3/test_protocol_v3_1r2_mount.py:712-719` uses `@pytest.mark.skipif(bool(_MISSING_LEGACY_DEPS))`. Missing `fitz`/`xlrd` → skip, suite still exits 0. The child script (`:655-708`) always sets `WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED=1`. There is no sibling subprocess that imports `app.main` with the flag absent and asserts: no `protocol-workflow` routes, default FastAPI 404 (not the Chinese envelope), no product DB file, no extra new-chain worker.
- Default-off *is* tested, but only on a blank `FastAPI()` (`TestDefaultOffMount`, `:277-310`), not the real composition root with its existing import graph, middleware, and startup/shutdown workers (`main.py:1375-1451`, `2470-2496`).
- PRD acceptance: “默认 off 与 legacy 路由/错误处理行为一致，新链不打开数据库或启动工作”; “H6实际入口/挂载…依赖错误不算通过.”
- **This run:** isolated venv has `fitz` and `xlrd`; the enabled real-main test **did run** and the suite was `30 passed, 0 skipped` in 3.28s. That proves the ON path on `app.main`. It does not prove the OFF path on `app.main`, and it does not make the skipif safe for a later green run without deps.

**Minimal repair (tests only, allowed 1R.2 paths):**

1. Delete the `skipif`. If `fitz`/`xlrd` are missing, `pytest.fail` with the isolated venv path. Dependency absence must be red, not skip.
2. Add `test_real_main_default_off_isolated_entrypoint`: same sanitized child env, **do not** set the enable flag, import `app.main`, assert no `protocol-workflow` in routes, `GET /api/projects/proj:1r2:admitted/protocol-workflow/study-definitions/sd:x` is FastAPI default 404 (`detail` is not the Chinese envelope dict), product DB path does not exist, and thread/worker delta is attributable only to pre-existing `DurableJobWorker` / startup recovery — not to sqlite product bootstrap.
3. Keep the existing enabled child test.

Until (1)+(2) are green in the same isolated venv, 1R.2 should not close.

### Other material findings

| ID | Type | Finding | Repair |
|---|---|---|---|
| F2 | Doc contradiction | `router.py:662-663` still says the router is not product-mounted and `main.py` stays untouched. `api/__init__.py:7-9` repeats that Task 1.9 claim and still tells hosts to register the validation handler **globally**. 1R.2’s whole point is the opposite: actual mount + route-scoped 422 so legacy 422 stays list-shaped. A later worker following those docs could unmount or register a global handler and break old APIs. | Update those two docstrings in allowed files to: factory remains locally testable; product mount is only `composition.mount_protocol_workflow_router`; do not register the validation handler on `app.main`. |
| F3 | Evidence gap | Restart durability (`test_restart_preserves_allowlist_rows_and_hashes`, `:409-436`) rebuilds a new `FastAPI()` in-process over the same file. That shows SQLite persistence, not process restart of `app.main`. | Cheap extra: enabled child writes, process exits, second child imports `app.main` against the same DB and reads the same `revision_sha256`. Not a substitute for F1. |
| F4 | Evidence gap | v1→v2 hash preservation (`:444-524`) goes through `ApplicationService` + `build_unit_of_work_factory`, then `admit_project`. It never sends HTTP at the v1 file. Source implies HTTP cannot migrate (admission returns False on v1). | Optional: HTTP GET against a v1 file must 404 and leave `schema_version` at 1; then `admit_project` + HTTP GET preserves hashes. |
| F5 | Residual behavior | `is_project_admitted` raises `SqliteStorageConfigurationError` / `SqliteSchemaVersionError` for foreign/future files. `_admission_gate` does not catch them (`composition.py:207-212`). Those requests 500 via FastAPI default, not the Chinese unexpected envelope. Design comment calls this loud misconfiguration. | Do **not** add a security suite. Optional 1R.2-sized map: catch `SqliteStorageError` in the gate and raise `HTTPException(500, detail=unexpected envelope)` so HTTP never includes the path string. Or leave as-is and record it as 1R.3 error-mapping, not a missing 1R.2 feature. |
| F6 | Coupling | `main.py` now **always** imports `composition` → router → `selected` → `sqlite`, even when the flag is off. Default-off is lazy for DB/worker, not for the import graph. A future import error in that stack takes down the whole workbench. Amendment already says old `main` import was never pure. | Accept as residual. Do not add a second lazy-import layer unless Codex wants import-failure isolation as a 1R.2 requirement. |

### Challenge to a plausible “30 passed → PASS” close

A green focused file is not H6. The enabled real-main child is necessary and, in this venv, sufficient for the **ON** HTTP path. Closing on that over-claims:

- default-off on the real entry (the user-visible compatibility guarantee);
- “依赖错误不算通过” (skipif violates it);
- full `protocol_v3` / repository regression (explicitly out of this conference’s command list; still a PRD box).

I am not inventing extra 1R.3 backup/replay or 1R.5 security work. Those are correctly out of scope.

### Draft / output plan (for Codex, not executed)

1. Keep current product code unless F5 is in scope; the mount/allowlist/migration design is the approved one.
2. Repair the mount suite: fail-closed real-main deps; add default-off real-main child (F1).
3. Fix stale Task 1.9 sentences in `router.py` and `api/__init__.py` (F2).
4. Main owner (not this role) runs adjacent `test_protocol_v3_api_contract.py`, `test_sqlite_product_storage.py`, `test_repository_backends.py` in the same venv. This review did not.
5. Fresh verifier re-reads source + new real-main OFF evidence. Worker does not close the Trellis task.

## Evidence And Assumptions

### Evidence (observed)

- PRD/design/implement: `.trellis/tasks/09-05-protocol-v3-1r2/{prd,design,implement}.md`. Amendment supersession: `plans/mw_protocol_v3_review_amendment_20260905.md` (1R.2 row; stage-assertion upgrade; 1R.5 excluded). Spec reminder: `.trellis/spec/protocol-v3.md`.
- Mount wiring: `main.py:199-201, 585-591`. Composition: `composition.py` (full file). Router factory `route_class` hook: `router.py:652-703`. Allowlist/migration: `sqlite.py:281-472, 559-810, 2204-2336`. Product factory route: `selected.py:304-326`. `ApplicationService` init has no worker: `application/service.py:233-251`. Client-contract path filter: `runtime_readiness.py:156-163`.
- Tests read: `tests/protocol_v3/test_protocol_v3_1r2_mount.py` (full); `test_protocol_v3_api_contract.py` (header + `test_main_py_references_only_the_1r2_composition_entrypoint` at `:1071-1082`); `test_sqlite_product_storage.py` (`_PRODUCT_TABLES` includes allowlist, `SCHEMA_VERSION_LATEST == 2` at `:343-355` and forward-migration class `:1155-1241`); `test_repository_backends.py` (imports product sqlite factory; no leftover “schema must stay v1” assertion found).
- Stale Task 1.9 docs: `router.py:662-663`, `api/__init__.py:7-9`.
- Isolated venv: `runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python` → Homebrew Python 3.12; `sqlite3.sqlite_version = 3.53.4`; `fitz` True; `xlrd` True.
- Command (exact, env `-i`, no cache): `pytest tests/protocol_v3/test_protocol_v3_1r2_mount.py -q -p no:cacheprovider` → **`30 passed in 3.28s`**, exit 0. Parametrization count includes `test_real_main_isolated_entrypoint`; 0 skipped ⇒ that test ran.

### Assumptions

- User-approved supersession of “main must not mount” and “schema fixed v1” is in force; leftover 1.9 wording is drift, not a reason to unmount.
- 1R.5 security engineering/tests stay `USER_EXCLUDED`. I am not treating their absence as fail or pass.
- 1R.3 backup/replay and 1R.4 simplification are future tasks, not 1R.2 holes.
- `WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED` is unset in live launch scripts (repo grep of this checkout showed only composition + this test file). Not verified against live hosts.
- FastAPI dependency injection of `project_id` into the outer-router admission `Depends` works because the enabled HTTP tests passed; I did not separately unit-test FastAPI internals.

### Inference (not observed)

- Default-off on `app.main` is *likely* a no-op, because the function returns before `include_router`. That is reasoning from source, not a real-main observation.
- Outsider POST 404 probably writes no outsider rows, because the gate raises `HTTPException` before the endpoint. The test does not query SQLite for that.
- Adjacent sqlite/api-contract/repository-backend suites were updated in source to v2 / single composition symbol and *probably* still pass. Not executed here.

### Recommendation vs uncertainty

- **Recommendation:** Codex should not close 1R.2 on this suite alone. Require F1 (fail-closed real-main + default-off child) and F2 docstring repair. Do not start 1R.5. Do not treat this conference output as acceptance.
- **Uncertainty:** Whether Codex treats blank-`FastAPI()` default-off plus source inspection as enough H6 for OFF. I argue it is not, because H6 is about the actual entry and the skipif can hide the ON evidence on the next machine.

## Risks, Gaps, And Verification Needs

**Risks**

- Accidental enable in a developer/live shell mounts the new chain at `app.main` import. Empty allowlist still 404s, but enabled-without-DB-path crashes the whole process, legacy included.
- Skipif lets a future “30 passed / 1 skipped” or “29 passed, 1 skipped” be misread as H6 done.
- Stale “main stays untouched” docs can drive a revert of the approved mount.
- Always-on import of the new stack: default-off no longer means “main can start if protocol_workflow is broken.”

**Gaps this pass did not close**

- Actual-main default-off (F1).
- Process-level restart of `app.main` (F3).
- HTTP vs v1 file non-migration (F4).
- `test_protocol_v3_api_contract.py`, `test_sqlite_product_storage.py`, `test_repository_backends.py` not run (conference forbade full repo; adjacent files were source-read only).
- Full repository regression (PRD box; main owner’s job).
- Live env / launch-script audit for the new env vars.

**Verification still needed (Codex / main owner)**

1. F1 tests in the same isolated venv command.
2. Adjacent three files in that venv (not this role’s allowed command).
3. Confirm no launch path exports `WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED` (outside this review’s production-path ban).
4. Fresh verifier: source + new OFF child output. Do not let the worker close Trellis.

**Not recommended**

- New security/adversarial tests, identity platform, or relabeling 1R.5 as “basic correctness.”
- Starting uvicorn/live, calling product models, or using `start_stable_backend.zsh`.

## Recommended Next Step

Codex should treat 1R.2 product wiring as **functionally plausible and ON-path evidenced**, and **not accepted**. Same-session follow-up to an execution worker (not this reviewer, unless an edit round is authorized): implement F1+F2 only; re-run the same isolated mount command; show 0 skipped and a default-off `app.main` child. Then a fresh verifier, not the implementer, closes.

**Objections**

1. “30 passed” is not H6 default-off on the real entry.
2. `skipif` on `fitz`/`xlrd` contradicts “依赖错误不算通过.”
3. Task 1.9 “main untouched” text is still in product modules after an approved mount.

**Proposed solutions:** F1 test repair; F2 docstring repair; leave F5 to Codex (1R.2 map vs 1R.3).

**Decision points for Codex**

1. Is actual-main **default-off** a close gate, or is blank-app default-off plus source inspection enough?
2. Must real-main missing deps fail the suite (my recommendation) or remain skip?
3. Are `router.py` / `api/__init__.py` docstring updates in 1R.2 allowed paths this round?
4. Who runs adjacent sqlite/api-contract/repository-backend suites — main owner in parallel, or a follow-up execution packet?

**Bounded questions**

- Q1: Confirm F1 (fail-closed deps + default-off `app.main` child) is required before 1R.2 close. If no, state what H6 artifact replaces it.
- Q2: Confirm F5 (admission `SqliteStorageError` → 500 vs Chinese 500 envelope) is 1R.3, not a 1R.2 blocker.
- Q3: Confirm adjacent pytest files are main-owner scope so this conference does not over-claim them.

Safe provisional path until those answers: do not close 1R.2; do not unmount; do not add security work; do not start live.
