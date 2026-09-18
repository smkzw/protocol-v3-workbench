All work is complete and verified. Here is the worker report:

---

# Execution Output: mw_protocol_v3_1r4_durable_dispatch_20260905 - worker_01

## Boundary And Context Check

- Read exactly the initial read set (execution context + Codex plan), then per its source-of-truth instruction: `.trellis/tasks/09-05-protocol-v3-1r4/{checkpoint.md, prd.md, design.md, implement.md}`, the four owned files, and the callers needed to avoid breaking contracts: `tests/protocol_v3/test_execution_reservations.py`, `storage/memory.py`, `storage/selected.py`, `ports/unit_of_work.py`, `ports/repositories.py` (signature surface), `runtime/__init__.py`. Did not read prior reviewer reasoning beyond the checkpoint's factual record.
- Writes confined to the four owned files plus `runs/mw_protocol_v3_1r4_durable_dispatch_20260905/` evidence. No production writes, no product model/OCR/translation calls, no installs, no cleanup, no task closure, no conference. Ports/typed contracts untouched. `test_execution_reservations.py` untouched (39/39 still pass unchanged).
- Red defect reproduced first, exactly as the checkpoint documented: `test_sqlite_claim_is_durable_before_physical_dispatch` failed with `assert [None] == [('running', 1)]` — the raw-UoW coordinator composes the whole reservation inside the caller's transaction, so nothing is durable at physical dispatch.

## Work Performed

**1. `storage/sqlite.py` — committed-operation dispatch surface (additive).**
- `SqliteCommittedOperationReservationRepository`: a reservation-repository handle owning one dedicated connection; each mutator (`reserve`, `transition`) runs as its own `BEGIN IMMEDIATE … COMMIT` (fail → rollback; `synchronous=FULL` fsync per commit), reads are autocommit snapshots. Reuses `_SqliteReservationRepository` row semantics via an always-active guard, so the coordinator sees the identical port surface.
- `build_committed_reservation_repository_factory(config)`: same fail-closed validation/bootstrap path as `build_unit_of_work_factory` (engine gate, read-only adoption preflight, ordered migrations).
- The raw UoW reservation repository and the superseded-result repair are untouched: business-transaction semantics preserved, no autocommitting of arbitrary caller events.

**2. `runtime/reservations.py` — live-ownership protection (no API removals).**
- Process-wide in-flight-claim registry keyed `(project_id, reservation_id)`: `_dispatch_and_persist` registers before the RESERVED shell is written and releases in `finally`, so a committed shell can never be observed without its live owner registered.
- `reserve_or_reuse` RESERVED branch: if the shell is actively owned by an in-process dispatch → raise `UnknownOutcomeConflictError` (no takeover, no redispatch); otherwise (dead process / foreign writer / seeded recovery fixture) → legacy zero-attempt `FAILED`/`dispatch_not_started_recovery` disposal. This keeps the old in-memory orphan fixture (`test_restart_disposes_reserved_shell_without_dispatch`) passing unchanged while closing the live-owner takeover hole. Unknown-outcome reconciliation, append-only attempts, and explicit-retry semantics are unchanged.

**3. `tests/protocol_v3/test_sqlite_reservation_lifecycle.py`** — Test 2's construction switched to the real committed-operation entrypoint; its independent-connection assertion is byte-identical (`assert observed == [("running", 1)]`). Test 1 untouched.

**4. `tests/protocol_v3/test_durable_reservation_dispatch.py` (new, 5 tests, all green):**
- Child crash before RUNNING (`os._exit(70)` in preflight): durable `("reserved", 0)` row survives process death; survivor disposes the orphan shell without dispatching; explicit retry appends attempt 2; attempt 1 stays queryable (append-only).
- Child crash after provider acceptance (`os._exit(71)` after writing the acceptance marker): durable `("running", 1)` claim; restart fail-closes with zero redispatch; same-session `recover_unknown` completes the crashed attempt; subsequent reuse with zero dispatches.
- Concurrent caller vs live RESERVED owner and vs live RUNNING owner (threads, blocked transports): fail-closed `UnknownOutcomeConflictError`, durable row provably unchanged (no FAILED takeover), convergence to the owner's result after release, one physical dispatch total.
- Explicit retry over real SQLite across restarts: attempt 1 stays `UNKNOWN_OUTCOME` under its original idempotency key, duplicate `retry_decision_id` is idempotent (no new attempt/dispatch), original key never becomes retryable.

## Artifacts And Evidence

- `services/api/app/protocol_workflow/storage/sqlite.py` — committed-operation handle + factory (file is untracked in git: it carries the uncommitted 1R.4 storage work; my changes are additive).
- `services/api/app/protocol_workflow/runtime/reservations.py` — registry + no-takeover guard. Note: the working-tree diff also shows Codex's pre-existing `ReservationOutcome` projection edit (already present before this pass); my edits layer on top of it.
- `tests/protocol_v3/test_sqlite_reservation_lifecycle.py`, `tests/protocol_v3/test_durable_reservation_dispatch.py`.
- Evidence in `runs/mw_protocol_v3_1r4_durable_dispatch_20260905/`: `1r4_durable_dispatch_focused_green.xml` (70 passed), `1r4_durable_dispatch_full_suite_green.xml` (1474 passed), `1r4_negative_control_old_composition_red.txt`.
- Negative control (decisive): the pre-repair raw-UoW composition under the identical child crash leaves **zero** visible rows — the reservation is silently lost; the repaired composition leaves a durable `reserved/0` row. The new crash tests are therefore genuine regression tests, not vacuous green.

## Commands And Observations

- Exact test env from the context (`env -i … runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest`).
- Before fix: lifecycle `1 failed, 1 passed` (`[None] != [('running', 1)]`). After fix: lifecycle + new file `7 passed`, stable across 5 consecutive runs (concurrency/polling robust).
- First-use set (lifecycle, durable dispatch, execution_reservations, result_storage_consolidation, superseded_result_migration, result_projection): **70 passed**.
- Full `tests/protocol_v3`: **1474 passed, 1 warning (historical tar warning), 33s** — including `test_compact_dependency_contract.py` at 11/11. The checkpoint listed that file as 5 expected WIP failures, but it now passes; I did not touch it, so Codex's disjoint contract slice has evidently landed since. No known WIP failures remain in protocol_v3.
- `py_compile` clean on all four owned files (pyflakes not in venv — skipped).

## Blockers Or Missing Environment

None blocking. Stated limitations (inference/decision, flagged for Codex):
1. **Cross-process live-owner liveness is not attempted.** The registry is deliberately process-local: SQLite is single-writer and the deployment model is one dispatching process. A RESERVED shell from a *live foreign process* would be disposed as an orphan by a second process (its `transport_attempts=0` proves dispatch never started, so there is no double-dispatch risk; the live owner's subsequent RUNNING transition fails loudly with `RepositoryStateTransitionError` rather than silently). True cross-process liveness needs a lease/heartbeat table — a platform concern outside this bounded repair; requires Codex authorization if wanted.
2. The committed-op handle is one-connection-per-handle, not per-handle thread-safe (documented; mirrors the one-UoW-per-unit-of-work model).
3. The application service (`application/service.py`) is **not** wired to the new factory — outside my file ownership.

## Rerun Requests Or Next Step

No rerun needed. Questions/decisions for Codex:
1. Should the application-service dispatch path be switched to `build_committed_reservation_repository_factory` (needs explicit extra file authorization), and should it be re-exported beyond `storage.sqlite`?
2. Confirm the process-local liveness scope (limitation 1) is acceptable for 1R.4 acceptance, or schedule the lease-table design separately.

Fresh independent verification remains with Codex per the packet; this worker claims no final acceptance.
