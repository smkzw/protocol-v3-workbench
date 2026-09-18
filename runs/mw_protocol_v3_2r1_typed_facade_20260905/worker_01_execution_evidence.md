# Task2R.1 Typed Facade Execution Evidence — worker_01

Task: `mw_protocol_v3_2r1_typed_facade_20260905` (finite_code_task, high)
Worker: `zcode/GLM-5.3-Flash:max`, execution pass 2026-09-05 (off_peak chain)

## What was built

One coherent typed facade with a product runtime and a three-case recovery
matrix.  All artifacts are NEW files; no legacy, protected, storage,
contract, or accepted case file was touched.

### Product side (no pocs import anywhere; verified by a subprocess import probe)

- `services/api/app/protocol_workflow/graph/__init__.py` — public surface.
- `services/api/app/protocol_workflow/graph/plan.py` — product-owned
  `GraphPlan`/`GraphNodePlan` closed vocabulary; fail-closed validation
  (duplicate/unknown deps, cycles, ambiguous producers, uncovered inputs,
  root collisions, empty inputs); deterministic construction-order-independent
  material SHA-256.  `GraphPlanError(RuntimeError)` is used deliberately so
  pydantic v2 propagates it unwrapped.
- `services/api/app/protocol_workflow/graph/state.py` — run/node statuses,
  snapshot records, typed errors (`GraphPlanBindingError`,
  `GraphDecisionConflictError`, `GraphRunError`), closed event vocabulary
  (`graph_run_started`, `graph_node_result`, `graph_decision_pending`,
  `graph_decision_recorded`, `graph_checkpoint`,
  `graph_checkpoint_repaired`, `graph_run_completed`).
- `services/api/app/protocol_workflow/graph/ports.py` — product
  `OrchestratorPort` + `NodeService` typed service boundary.
- `services/api/app/protocol_workflow/graph/runtime.py` — `GraphRuntime`
  (one instance per project):
  - Event-sourced state on the product SQLite UoW
    (`build_unit_of_work_factory`); reconstruction replays events plus the
    committed reservation ledger; the checkpoint event is advisory and never
    certifies completion — divergence is detected and repaired by appending
    a corrected checkpoint (history retained, never rewritten).
  - Persist-first dispatch through `ReservationCoordinator` over
    `build_committed_reservation_repository_factory`: the service result is
    committed as a `graph_node_result` event BEFORE the coordinator records
    COMPLETED, so a crash between the two leaves truthful evidence on both
    sides; `advance` repairs a non-terminal reservation from the
    authoritative event/result data.
  - v1_1 contracts in the executed path: every dispatch builds a
    `NodeExecutionContract` and immediately calls `compact_dependencies()`;
    the compacted `mw_protocol_v3_contract_v1_1` contract is persisted on
    the result event and its dependency digest is re-verified through
    `matches_dependencies()` on every reconstruction.
  - Human decisions are product states: a DECISION node pauses the run into
    `awaiting_decision`; the runtime never self-approves;
    `record_decision` is idempotent/CAS per decision key; the reviewer
    identity travels as the event actor (actor_type=user) while the writer
    context (runtime owner + pid) is a separate payload field.
  - Unknown never auto-redispatched: a dead process's RUNNING shell or an
    UNKNOWN_OUTCOME reservation reconstructs as `blocked_unknown`; recovery
    requires explicit owner action — `resolve_blocked_with_failure` (crash
    window → FAILED) plus `retry_node` (append-only attempt N+1 under a
    stable decision identity), or `resolve_unknown_with_receipt`
    (UNKNOWN→COMPLETED with a verified receipt, no payload fabrication).
    Zero-transport-attempt orphan shells (dispatch never started) are
    retried through the coordinator's explicit path under a deterministic
    idempotent `orphan-recovery:<reservation_id>` decision identity.

### PoC side (thin adapter; imports product, never reverse)

- `pocs/protocol_v3/orchestrator/typed_facade.py` — `plan_from_case_graph`
  (1:1 read-only vocabulary conversion), `deterministic_services`
  (labeled synthetic placeholders; no invented clinical/statistical
  values), `graph_lock_node`.  The scheduler is NOT duplicated.
- `pocs/protocol_v3/orchestrator/tests/test_typed_facade.py` — drives all
  three accepted graphs (eligibility, objective-estimand-endpoint,
  sample-size) through the product runtime with typed output-schema checks,
  plus the per-case injection matrix with real own-process death.

### Tests (written red first; red evidence recorded before implementation)

- `tests/protocol_v3/test_graph_runtime.py` (22) — product contracts,
  pocs-free fixtures: plan validation, execution/decision pause/CAS,
  reviewer/writer separation, persisted v1_1 contracts with executable
  freshness verification, reconstruction equality after reopen,
  one-lineage-per-logical-key, old-graph rejection, over-claiming checkpoint
  repair, run completion never certified by checkpoint alone, completed
  reuse, unknown fail-closed + receipt adoption, explicit append-only retry,
  blocked RUNNING crash window (crafted via the committed repository).
- `tests/protocol_v3/test_graph_runtime_recovery.py` (5) — real synthetic
  subprocesses (`os._exit` of their own process only) against real SQLite:
  kill-before (exit 67, no partial state, clean re-run), kill-after
  (exit 68, durable result reused, no re-execution, single attempt),
  kill-inside-dispatch (exit 69 after the RUNNING claim → blocked, explicit
  resolve + retry → attempts [1 FAILED, 2 COMPLETED]), duplicate resume
  across processes (no new events/results/dispatches), and a genuine
  two-process concurrent decision race (exactly one recorded, loser fails
  closed with the typed conflict).

## Commands and results (isolated env, venv python 3.12.13, PYTHONDONTWRITEBYTECODE=1)

Command form:
`env -i PATH=/usr/bin:/bin HOME=... TMPDIR=... LANG=en_US.UTF-8
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
PYTHONPATH=services/api:packages:.
runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest -q -p
no:cacheprovider --tb=short <targets> --junitxml=<evidence>`

| Suite | Result | Evidence |
|---|---|---|
| Red (before implementation) | 22 failed + 5 failed + facade collection error | `failing_tests_red_evidence.txt` |
| tests/protocol_v3/test_graph_runtime.py | 22 passed | `test_graph_runtime.xml` |
| tests/protocol_v3/test_graph_runtime_recovery.py | 5 passed | `test_graph_runtime_recovery.xml` |
| pocs .../tests/test_typed_facade.py | 26 passed | `test_typed_facade.xml` |
| pocs .../tests/test_case_contracts.py (accepted Task2.1) | 75 passed | `test_case_contracts_75.xml` |
| Full tests/protocol_v3 regression | 1543 passed, 1 skipped, 4 failed | `test_v3_regression_2r1.xml` |

The 4 failures are `test_frontend_check_wrapper.py` — pre-existing and
environmental: `run_frontend_checks.py` raises `node executable is not
available on PATH` under the sanitized `env -i PATH=/usr/bin:/bin` runner
environment before any assertion runs.  Re-verified with a Homebrew PATH
added: the same 4 fail identically with all of this worker's changes absent
in relevant part (they never reach inventory-count logic; root cause is the
node binary resolution), and they do not touch any surface of this task.
Recorded here as pre-existing, not introduced by 2R.1.

## Seven accepted Task 2.1 files: unchanged

`seven_file_hashes_after.txt` matches the Task2.1 no-loss pause record
(`runs/MW_PROTOCOL_V3_TASK21_NO_LOSS_PAUSE_20260812_0708.md`) exactly, file
for file; the three pinned graph material hashes still reproduce (the
accepted 75-test suite includes the pinned-hash and cross-process hash
tests).

## Boundary compliance

- Writes limited to: the five new `graph/` modules, the two new
  `tests/protocol_v3` files, the two new pocs files, and evidence under
  `runs/mw_protocol_v3_2r1_typed_facade_20260905/`.
- `git status` verified: no tracked file modified by this worker; all other
  dirty/untracked paths pre-existed the dispatch.
- No package installation, no service/model/provider/network/live-database
  operation, no Trellis closure, no cleanup/archive, no peer review,
  no conference.
- Tests killed only their own synthetic child processes; never searched for
  or signaled any other process.

## Known limitations / remaining verification for Codex

1. The graph runtime is not yet wired into any product entrypoint (router/
   composition) — per plan this phase explicitly stops at the typed runtime;
   later wiring is out of scope for 2R.1.
2. The result-event-vs-reservation split repair path (`_apply_reservation_
   repairs`) is implemented but has no dedicated test that produces the
   exact split (it requires killing a process strictly between the result
   commit and the COMPLETED transition, a narrower window than the exercised
   mid-dispatch kill); its semantics are the same authoritative-event
   discipline proven by the over-claiming-checkpoint test.
3. `resolve_unknown_with_receipt` intentionally completes a node without a
   result payload; downstream nodes then fail closed with
   `graph_result_payload_missing` until real payload recovery exists.  This
   is a deliberate fail-closed posture, not a finished payload-recovery
   feature.
4. The 4 pre-existing frontend wrapper failures and the wider repo hygiene
   state are outside this task's scope (see the P1R legacy disposition).
