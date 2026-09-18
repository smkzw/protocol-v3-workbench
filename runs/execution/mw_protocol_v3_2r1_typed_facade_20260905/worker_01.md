# Execution Output: mw_protocol_v3_2r1_typed_facade_20260905 - worker_01

## Boundary And Context Check

- Worked only inside the runner-bound workspace. Read the initial read set (execution context, Codex plan), then the declared sources of truth: Trellis `09-05-protocol-v3-2r1` prd/design/implement, `plans/mw_protocol_v3_review_amendment_20260905.md` (2R.1 boundary row + 1R.4 committed-dispatch/v1_1 sections), `runs/MW_PROTOCOL_V3_TASK21_NO_LOSS_PAUSE_20260812_0708.md` (seven hashes + graph material hashes), the seven accepted PoC files, and the product surfaces `packages/contracts/workbench_contracts/protocol_v3.py`, `services/api/app/protocol_workflow/{ports,runtime,storage,events,canonical}` plus read-only test examples (`test_sqlite_reservation_lifecycle.py`, `test_durable_reservation_dispatch.py`, `test_execution_reservations.py`).
- Wrote only the authorized NEW files: `services/api/app/protocol_workflow/graph/` (5 modules), `tests/protocol_v3/test_graph_runtime.py`, `tests/protocol_v3/test_graph_runtime_recovery.py`, `pocs/protocol_v3/orchestrator/typed_facade.py`, `pocs/protocol_v3/orchestrator/tests/test_typed_facade.py`, evidence under `runs/mw_protocol_v3_2r1_typed_facade_20260905/`. `git status` verified: zero tracked-file modifications by this worker; all other dirty/untracked paths pre-existed the dispatch.
- The seven accepted Task 2.1 files were hashed before and after work: all seven match the pause record exactly (file order preserved); the three pinned graph material hashes still reproduce via the accepted 75-test suite. No package installation, no service/model/provider/network/live-DB operation, no Trellis closure, no cleanup/archive, no peer review, no conference. Tests killed only their own synthetic child processes.

## Work Performed

Task2R.1 implemented as one coherent typed facade, red-first (failing tests recorded before implementation: 22 failed + 5 failed + facade collection error, saved in `failing_tests_red_evidence.txt`).

**Product runtime** (`app.protocol_workflow.graph`, no pocs import — proven by a subprocess module-delta probe):
- `plan.py` — product-owned closed `GraphPlan`/`GraphNodePlan` vocabulary: fail-closed validation (duplicate/unknown deps, cycles, ambiguous output producers, uncovered inputs, root collisions, empty inputs), deterministic construction-order-independent material SHA-256. `GraphPlanError(RuntimeError)` deliberately so pydantic v2 propagates it unwrapped (verified by probe).
- `state.py` — run/node statuses, snapshots, typed errors (`GraphPlanBindingError`, `GraphDecisionConflictError`), closed event vocabulary (`graph_run_started/node_result/decision_pending/decision_recorded/checkpoint/checkpoint_repaired/run_completed`).
- `ports.py` — product `OrchestratorPort` + `NodeService` typed service boundary.
- `runtime.py` — `GraphRuntime` (project-scoped): event-sourced state over the real SQLite UoW (`build_unit_of_work_factory`); reconstruction from authoritative events + committed reservation ledger; advisory checkpoint with detect-and-repair of divergence (history never rewritten); persist-first dispatch through `ReservationCoordinator` over `build_committed_reservation_repository_factory` (result event commits BEFORE the COMPLETED transition; result-vs-reservation splits repaired from event/result data); **v1_1 contracts in the executed path** — every dispatch builds a `NodeExecutionContract` and immediately calls `compact_dependencies()`, persists the compacted contract on the result event, and re-verifies its digest via `matches_dependencies()` on every reconstruction; human decision pauses are product states (`awaiting_decision`, never self-approved, idempotent/CAS per decision key, reviewer identity as event actor vs writer context as separate payload field); unknown/RUNNING crash windows reconstruct as `blocked_unknown` and are **never auto-redispatched** — explicit owner resolution + append-only retry (stable decision identity, `allowed_attempts` bound), or verified receipt adoption; zero-transport-attempt orphan shells retried via a deterministic idempotent `orphan-recovery:<reservation_id>` identity.

**PoC adapter** (`typed_facade.py`, one-directional pocs→product): read-only 1:1 vocabulary conversion of the three accepted graphs, deterministic labeled synthetic services (no invented clinical/statistical values), lock-node locator. Scheduler not duplicated.

**Recovery matrix with real process death** (synthetic subprocesses, `os._exit` at declared boundaries, real SQLite reopen in the parent): kill-before (exit 67 — no partial state, clean re-run, one lineage), kill-after (exit 68 — durable result reused, no re-execution, single attempt), kill-inside-dispatch (exit 69 after the durable RUNNING claim — blocked, explicit resolve + retry → attempts [1 FAILED, 2 COMPLETED]), duplicate resume across processes (no new events/results/dispatches), and a genuine two-process concurrent-decision race (exactly one recorded; loser fails closed with the typed conflict). All exercised for the product probe plan and per-case at the accepted graphs' declared injection targets.

## Artifacts And Evidence

- Code: `services/api/app/protocol_workflow/graph/{__init__,plan,state,ports,runtime}.py`; `pocs/protocol_v3/orchestrator/typed_facade.py`
- Tests: `tests/protocol_v3/test_graph_runtime.py` (22), `tests/protocol_v3/test_graph_runtime_recovery.py` (5), `pocs/protocol_v3/orchestrator/tests/test_typed_facade.py` (26)
- Evidence directory `runs/mw_protocol_v3_2r1_typed_facade_20260905/`: `failing_tests_red_evidence.txt`, `seven_file_hashes_after.txt`, `seven_file_hashes_expected.txt`, `test_graph_runtime.xml`, `test_graph_runtime_recovery.xml`, `test_typed_facade.xml`, `test_case_contracts_75.xml`, `test_v3_regression_2r1.xml`, `worker_01_execution_evidence.md` (full write-up)

## Commands And Observations

Isolated env per context (`env -i PATH=/usr/bin:/bin HOME=… TMPDIR=… LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:.`), python `runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python` (3.12.13), `pytest -q -p no:cacheprovider --tb=short` with unique XML names:

| Suite | Result |
|---|---|
| New suites, final combined run | **128 passed** (22 + 5 + 26 + accepted-75) in 34.1s |
| Full `tests/protocol_v3` regression | **1543 passed, 1 skipped, 4 failed** in 40.7s |
| 4 failures triaged | `test_frontend_check_wrapper.py` — pre-existing/environmental: `run_frontend_checks.py` raises `node executable is not available on PATH` under the sanitized runner PATH before any assertion; identical failures reproduce without this task's scope; unrelated to graph/facade surfaces |
| Seven accepted files + graph hashes | all hashes match the Task2.1 pause record exactly |

Notable design observation recorded in-code: pydantic v2 propagates non-ValueError validator exceptions unchanged, which is why `GraphPlanError` subclasses `RuntimeError` — callers catch the typed error directly instead of unwrapping `ValidationError`.

## Blockers Or Missing Environment

None blocking. Honest limitations recorded for Codex (details in `worker_01_execution_evidence.md`):
1. The runtime is deliberately not wired into router/composition — later-phase work.
2. The result-event-vs-reservation split repair path is implemented but has no dedicated test producing that exact (narrower) crash window; same authoritative-event discipline as the exercised over-claiming-checkpoint test.
3. `resolve_unknown_with_receipt` completes a node without a payload by design; downstream then fails closed (`graph_result_payload_missing`) until real payload recovery exists.

## Rerun Requests Or Next Step

No rerun requested. Resume point for Codex: independent audit of the five new graph modules against the Trellis PRD/design and the amendment's 2R.1 row, then the fresh verifier pass; acceptance evidence paths are listed above. Codex remains the final authority for acceptance and closure; this worker claims no acceptance.
