# Execution Output: mw_protocol_v3_full_review_20260912 - worker_01

## Boundary And Context Check

- **Fallback declaration:** primary `zcode/GLM-5.3-Flash` role was unavailable before a resumable session existed. I am the declared `pi` fallback (`opencode-go` / `muse-spark-1.3-contributor`). Same bounded role, source list, output path, quality gates; no conferences started.
- **Capability limitation:** fallback model differs from the pinned Z-Code app-server model/thought level named in the prompt; I used my own available tools (read/grep/bash) as the assignment requires. I did not claim verdicts I could not evidence; every finding below cites file:line actually read.
- **Boundaries honored:** work inside `.` only; product sources/tests READ-ONLY (no edits made); no services started, no model/OCR/translation calls, no credentials touched (home-dir credential DB never opened), no recursive agents, no internet; excluded `registries/chapters.py` and `registries/dependency_graph.py` (not opened). Report returned in-response only; runner persists it to `runs/execution/mw_protocol_v3_full_review_20260912/worker_01.md`.
- **Source-of-truth read:** checkpoint (`09-12-protocol-v3-review-replan/checkpoint.md`), handoff `HANDOFF_PROTOCOL_V3_3R4_20260912.md`, pause record `MW_PROTOCOL_V3_3R4_NO_LOSS_PAUSE_20260912_2322.md`, amendment `plans/mw_protocol_v3_review_amendment_20260905.md`, execution plan/context. Prior-owner assertions treated as evidence to challenge: I re-verified composition, atomicity, and recovery claims against code rather than accepting them. Two inherited claims I **confirm**: default-off mount is a genuine no-op (`composition.py:243-244` returns `None` before any I/O) and reservation dispatch is persist-first **only** on the committed-op path (`sqlite.py:2042-2066`); raw-UoW wiring keeps business-transaction atomicity by design (`reservations.py:526-534` documents this).
- **Coverage gaps (material, for Codex):** `api/schemas.py`, `storage/memory.py`, `runtime/adapters/*` (live GLM transport surface — the known wire-shape blocker area — not re-verified here), `agent5/run_manifest.py` + `exception_cards.py`, `canonical/decisions.py|document.py|study_definition.py` internals (surface only), `events/store.py|models.py` internals (surface only), `packages/contracts/.../protocol_v3.py`, full router route table. Findings are confined to code actually read.

## Work Performed

Traced actual main composition (`main.py:591` → `mount_protocol_workflow_router` → `create_mounted_protocol_workflow_router` → lazy UoW factory + admission gate + validation-envelope route) and read the full backend chain: canonical/hashing surface, storage (sqlite selected/committed/UoW/allowlist), events (coordinator/outbox-dispatcher/inbox-consumer), runtime (reservation coordinator, idempotency, harness surface, profiles, omp credential resolver), graph runtime (transport/execute/repair/append/guards), application service (create/apply/queries/_translate), reconstruction, registries loader, artifacts store, ports surface, error catalog. Ran 70 isolated tests green as verification (see §5). Findings distinguish implemented bugs (reachable today) from future-feature absences.

## Artifacts And Evidence

No new files written (read-only role; pytest ran without evidence writes). Findings with file:line, trigger, test gap, smallest repair:

**F1 — apply-to-missing aggregate returns 409 retryable with misleading copy (implemented bug, medium).**
- Evidence: `services/api/app/protocol_workflow/application/service.py:940-957` groups `AggregateNotFoundError` into `P1_DECISION_CAS retryable=True` → `api/router.py:164-170` maps to **409**. That code's public copy (`errors.py:290`) says "您查看的推荐已被更新…请查看最新推荐后重新确认" — wrong guidance when the object does not exist. Inconsistent with the admission gate, which reports absent objects as **404** not-found (`api/composition.py:222-226`, `api/router.py:128-133`).
- Trigger: `apply_decision` with unknown `study_definition_id`, or cross-project id (`get_current` returns `None` → `AggregateNotFoundError`, `service.py:416-420`).
- Test gap: `tests/protocol_v3/test_application_service.py:648-668` (`test_project_mismatch_fails_closed`) pins only `.code`, never `retryable`/HTTP status; no missing-aggregate test exists.
- Repair (needs Codex approval — test pins current code): dedicated not-found arm (404 + existing not-found envelope) for `AggregateNotFoundError`; update the one pinning test. `IdempotencyConflictError` in the same arm is fine as-is (client retries with a new key).

**F2 — internal wiring defect surfaced as user-retryable 409 (implemented wart, low-medium).**
- Evidence: `service.py:899-909` maps `MissingRepositoryError`/`_MissingRepositoryError` → `P1_DECISION_CAS retryable=True` (409 "recommendation updated"). A `None` repository handle is a composition bug, not a user conflict.
- Trigger: only via mis-composition today (composition always wires handles), so reachability is latent.
- Test gap: `TestMissingRepositoryHandle` covers the coordinator raise, not the service `_translate` arm.
- Repair: map to a non-retryable 500 code. No existing catalog code fits exactly (`P1_CHECKPOINT_EVENT_MISMATCH` would lie about cause) — likely needs a new catalog entry; Codex decision.

**F3 — causeless `MutationAbortedError` defaults to retryable CAS (latent, low).**
- Evidence: `service.py:862-870`; pinned by `tests/protocol_v3/integration/test_sqlite_end_to_end.py:662-668`. Only causeless construction is the `events`-empty programming guard (`events/unit_of_work.py:271-276`), unreachable via public API (`build_and_apply` always supplies one event).
- Repair: map causeless abort to non-retryable; one-line + test update. Optional.

**F4 — RESERVED detected but never repaired in graph recovery scan (inconsistency, low).**
- Evidence: `_load_reservation_states` flags `RESERVED` rows with committed result events as repairs (`graph/runtime.py:937-944`), but `_apply_reservation_repairs` only transitions `RUNNING`/`UNKNOWN_OUTCOME` (`graph/runtime.py:1692-1695`) then clears the list (`1705`).
- Trigger: unreachable via product wiring (committed-op repo always commits `RUNNING` before the transport's result-event commit, `reservations.py:588-607` vs `graph/runtime.py:192-206`). Reachable only via raw-UoW misuse or hand-seeded rows — then the row is re-detected every load and never converges.
- Test gap: no test seeds RESERVED+result.
- Repair: either include `RESERVED` in the repair guard or drop it from the scan with a comment. One-line.

**F5 — read queries take the single-writer lock (contention, low; NOT a data-purity bug).**
- Evidence: all four `get_*` open `with self._factory()` (`service.py:532,560,614,640`) → `SqliteUnitOfWork.__enter__` issues `BEGIN IMMEDIATE` (`storage/sqlite.py:2582-2588`). No business write occurs (correctly pinned by `TestQueries`), but each read holds the DB-level RESERVED lock for its duration, serializing concurrent writers (API reads × graph `advance`).
- Test gap: no lock-level/pragmas test on the read path.
- Repair (simplification): read-only/deferred UoW path for queries. Defer unless contention is observed.

**F6 — mount-time registry load can crash app import when enabled (robustness, low).**
- Evidence: `create_mounted_protocol_workflow_router` calls `load_skill_registry` (`api/composition.py:246-249`) synchronously from `mount_protocol_v3_workflow_router(app)` at `main.py:591` with no try. Enabled + missing/corrupt registry → `ValueError` at import → whole app down (disabled path is correctly zero-I/O).
- Test gap: `test_protocol_v3_1r2_mount.py` covers disabled/no-op/admitted/corrupt-DB-503, not corrupt-registry-at-mount.
- Repair: defer registry load lazily (same pattern as `_LazyProductUnitOfWorkFactory`) or wrap with an explicit fail-closed startup error. Note: loud failure is arguably correct for misconfiguration — the fix is about *when* (import vs first use), not silence.

**F7 — dead defensive code (simplifications, negligible risk).**
- (a) `recover_dispatched` second loop (`events/outbox.py:540-555`) can never append: every processed id is excluded by status-or-id checks. Delete or cover; deletion is safe.
- (b) `_status_for` special-cases two codes (`api/router.py:165-169`) that are `retryable=True` by catalog construction (`errors.py:290-291` + constructor match enforcement) — the trailing `409 if error.retryable else 500` already covers them.
- (c) Cosmetic: `_validate_migration_history` message says `1..{SCHEMA_VERSION_LATEST}` while checking `1..latest` (`storage/sqlite.py:689-694`).

**Absence of future features (NOT bugs — do not file as defects):** `SqliteUnitOfWork.artifact_store` returns `None` (`sqlite.py:2514-2516`) and `LocalArtifactStore` is unwired into product composition — verified zero callers touch `uow.artifact_store` in service/events/graph paths, and `LocalArtifactStore` itself is correct (atomic temp+replace writes, content verification on read: `artifacts/local_store.py:138-169,247-251`). Conditional-applicability executor still deferred (3R.4 second work item, owned elsewhere). Cross-process reservation safety is local-only by design (in-memory registry + `flock` dir `sqlite.py:2075-2093`; lock files never GC'd — already a standing memory note, accumulates one small file per reservation; fine for local deployment, flag before any shared hosting).

**Positives confirmed (do not regress):** CAS+event+outbox atomicity in one UoW (`events/unit_of_work.py:288-328`); `acknowledge_one` re-reads persisted state before acting (`outbox.py:624-636`); inbox-first short-circuit (`640-654`); crash matrix documented and matched by code; migration preflight (exact history + table/column/constraint fingerprints, future-version never rewritten: `sqlite.py:661-790`); genesis-pinned reconstruction (`application/reconstruction.py:9-35`); admission gate strictly read-only, never bootstraps (`sqlite.py:2674-2740`); 500 envelope is reconcile-before-retry (`router.py:136-141`); duplicate graph results blocked by reservation serialization + in-tx guards (`graph/runtime.py:1497-1553,1592-1627`).

## Commands And Observations

- `pytest tests/protocol_v3/test_application_service.py` (isolated env per context template: `env -i`, pinned venv, `PYTHONPATH=tests/protocol_v3:services/api:packages:.`, `-p no:cacheprovider`): **28 passed, 1.01s**.
- `pytest tests/protocol_v3/test_protocol_v3_api_contract.py tests/protocol_v3/test_graph_runtime_recovery.py` (same env): **42 passed, 16.15s**.
- `grep` surveys used for: risk markers (only `NotImplemented` hit is a legitimate `__eq__` protocol return; `pragma: no cover` hits are documented defensive branches), `artifact_store`/`backup` wiring, retryable/not-found test pins.
- Observation: suite is fast and green on the touched paths; F1/F2/F4/F6 have no failing test today because the gaps are missing-case coverage, not regressions — repairs will require Codex-approved test updates where pins exist (F1 test at `test_application_service.py:660-668`; F3 test at `test_sqlite_end_to_end.py:662-668`).

## Blockers Or Missing Environment

None blocking. Pinned venv `runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python` works. Unread areas listed in §2 are resume points, not blockers. One flag: `resolve_omp_zhipu_key` reads `~/.omp/agent/agent.db` at runtime (home dir, outside workspace) — I read only its source, never the DB; any future live probing of that path needs explicit Codex authorization.

## Rerun Requests Or Next Step

- Recommended Codex decisions: (1) accept F1 repair direction (404+not-found envelope for `AggregateNotFoundError`) and authorize the one test update; (2) choose F2's target code (new catalog entry vs reuse); (3) confirm F4–F7 as cleanup-grade (worker-safe follow-ups) vs wont-fix.
- Suggested next worker (bounded, read-only + minimal edit): implement F1/F3/F4/F7-a/F7-b with the approved test updates, re-run the three suites above plus `test_sqlite_end_to_end.py` and `test_protocol_v3_1r2_mount.py`.
- No rerun of this review needed; resume point for deeper pass: `runtime/adapters/*`, `api/schemas.py`, agent5 `run_manifest.py`/`exception_cards.py`, semantic-document mutation path existence (router route table vs `canonical/document.py`).
