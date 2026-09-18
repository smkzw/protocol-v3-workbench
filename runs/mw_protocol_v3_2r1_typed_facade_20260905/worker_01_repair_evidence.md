# Task2R.1 Typed Facade Repair Evidence — worker_01_followup

Same-session bounded repair after Codex NOT-accepted review
(`reviews/mw_protocol_v3_2r1_codex_findings_20260905.md`) and fresh-reviewer
repro (`runs/conference/mw_protocol_v3_2r1_fresh_20260905/general_single_object.md`).
Red-first: the four Codex probes were re-run against the unmodified first pass
and all four failed (`codex_four_probes_prerepair_rerun.xml`), then repaired,
then all four pass (`codex_four_probes_postrepair.xml`).

## Environment (per Codex correction)

`env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=…
TMPDIR=… LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
PYTHONPATH=tests/protocol_v3:services/api:packages:.
WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false WORKBENCH_RUNTIME_DIR=<fresh tmp>`
with `runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python`,
`pytest -q -p no:cacheprovider --tb=short`, fresh WORKBENCH_RUNTIME_DIR
(/tmp/mw2r1-repair) for every run.

## Per-finding disposition

### Finding 1 (+fresh F2): decision check/append not atomic — FIXED (in-UoW guard)

- `runtime.py`: new `_append_events_tx(run_id, specs, guard)` — the guard runs
  INSIDE the same UoW transaction as the append, after a fresh authoritative
  `read_events`, before any row is written; `_decision_guard` raises the typed
  `GraphDecisionConflictError` on any conflicting existing decision and
  returns False (idempotent reuse, no second event) for the identical
  identity.  `record_decision` now appends through this path.  No new schema,
  no new platform — existing UoW/SQLite single-writer discipline.
- Forced-interleave repro (fresh reviewer's `cas_proof.py`, run read-only):
  pre-repair `outcomes: {'B': 'recorded', 'A': 'recorded'}, n=2`; post-repair
  `outcomes: {'B': 'GraphDecisionConflictError:graph_decision_conflict',
  'A': 'recorded'}, n_decision_recorded: 1`.
- Ported deterministic stale-precheck test (new hook at the new seam,
  assertions unchanged — documented in the test docstring):
  `test_graph_runtime.py::TestDecisionAndStartAtomicity::
  test_conflicting_decisions_cannot_both_pass_stale_precheck` parks writer A
  between its stale pre-check and its append transaction; writer B commits a
  conflicting decision; A's in-transaction guard fails closed.  Asserts
  exactly one decision event, outcomes sorted [conflict, recorded], loser
  error exactly `GraphDecisionConflictError`.

### Finding 2 (+fresh F1): sequential race harnesses — REPLACED with overlapping Popen

- `test_graph_runtime_recovery.py`: `_spawn_overlapping` creates ALL children
  via `Popen` before joining any; child `record_decision_race` mode requires
  the marker rendezvous and exits 75 on rendezvous failure (parent hard-fails
  on returncode — no timeout-then-proceed); ONLY `GraphDecisionConflictError`
  maps to outcome "conflict"; any unexpected error type would surface as an
  unexpected outcome/returncode and fail the test.
- `test_typed_facade.py`: same rework for all three cases
  (`_spawn_children_overlapping`, rendezvous-required exit 75, typed-error
  assertion) in `TestInjectionMatrixWithProcessDeath::
  test_concurrent_decision_at_declared_lock_has_one_winner`.
- New `test_identical_concurrent_decisions_reuse_exactly_once`: two overlapping
  racers with a truly identical decision identity both report recorded and
  exactly one `graph_decision_recorded` + one lock node result survive.
- Fresh reviewer's `true_race_driver.py` (read-only run): conflict mode →
  `n_decision_recorded: 1`, outcomes [conflict, recorded], loser error
  `GraphDecisionConflictError`; duplicate mode (same identity, different
  value content per racer) → still exactly one recorded event and one typed
  conflict — correct CAS semantics for differing content under one key.

### Finding 3 (+fresh F3): receipt recovery restores USABLE content — FIXED (payload-bearing adoption)

- `resolve_unknown_with_receipt` now takes `output` (payload) +
  `output_sha256` (declared hash); verifies equality (`graph_receipt_hash_
  mismatch` typed refusal otherwise), persists the same typed
  `graph_node_result` (schema, rebuilt v1_1 contract, input provenance,
  `recovered_receipt: True`), converges the existing UNKNOWN reservation to
  COMPLETED via `coordinator.recover_unknown` with zero dispatch and zero new
  attempts.
- Hash-only receipt is refused as insufficient evidence: node stays
  `blocked_unknown` with explicit snapshot stop_reason
  `unknown_outcome_requires_payload_bearing_receipt` — never certified, never
  an untyped exception; unknown work is never auto-retried.
- Hash-only reservation-COMPLETED states are reclassified `blocked_unknown`
  in `_node_status` and can never certify run completion
  (`_finish_run_if_complete` refuses without durable result payloads).
- Compatibility: the old hash-only call form raises TypeError (required
  `output` kwarg) — the fresh reviewer's original `receipt_zombie_repro.py`
  therefore stops at that line by design; its scenario is ported and extended
  in the allowed suite: `test_unknown_outcome_never_auto_redispatches`
  (mismatch refusal + adoption + downstream consumption proven via the review
  dispatch's material input hash equal to `canonical_input_hash` over the
  recovered payload) and `TestTerminalReceiptRecovery::
  test_terminal_node_receipt_recovery_completes_the_run` (terminal node
  adoption → run completes with the adopted hash in `final_state`; identical
  second receipt idempotent; different receipt typed `graph_node_completed`).

### Finding 4: decision output hash — FIXED

`record_decision` now hashes the exact persisted output object
(`{"decision_id","actor_id","value","reason"}`) into the node result's
`output_sha256`; the bare value hash is retained separately as
`value_sha256` on the decision event for dedup.  Regression:
`test_decision_content_hash_matches_actual_downstream_payload` (ported probe)
plus a value-hash assertion.

### Finding 5 (+fresh): lost completion event — FIXED (advance converges; loop bounded)

- `advance` now calls `_finish_run_if_complete` after the node scan, so a run
  whose results are all durable but whose completion event was lost converges
  to completed with zero dispatches.
- `run_to_completion` is bounded (256 steps) and fails closed with typed
  `graph_no_progress` when no new events appear between advances.
- Real-death coverage: `TestCrashWindowConvergence::
  test_reopen_after_kill_before_completion_event_finishes_without_dispatch` —
  child dies (exit 71) inside its own completion step exactly when all four
  results are durable and the completion event is not; parent reopens,
  `advance` completes with zero executions, single COMPLETED attempt per node.
- Ported probe: `test_reopen_final_result_without_completion_event_finishes_
  without_dispatch` (kept the probe's instance-level `_finish_run_if_complete`
  crash hook; the reopened runtime completes without dispatch).

### Finding (+fresh F5 / prompt item 6): contended reservation errors typed — FIXED

`advance`/`retry_node` translate `UnknownOutcomeConflictError` → typed
`graph_reservation_contended_retryable` (wait/retry-later; never permission to
dispatch) and `IdempotencyConflictError` → typed `graph_input_binding_conflict`
(hard conflict).  Coverage: `TestOverlappedAdvanceContention::
test_same_node_advance_dispatches_once_and_converges` — two overlapping
children advance the same pending node behind a required rendezvous; at most
one physical draft dispatch; any loser error is exactly the typed retriable
code; the run then completes with a single draft attempt and one result event.

### Finding (+fresh F6 / prompt item 7): QC independence evidence — ADDED (offline orchestration evidence)

- `node_result` events now carry `service_invocation` provenance:
  `service_id`, `invocation_id`, owner, `declared_input_schemas`, and the
  writer context (`runtime_owner` + pid) — typed provenance binding each
  injected invocation to its declared inputs, separate from writer-private
  context and from the human confirmation.
- `test_graph_runtime.py::TestQCInvocationIndependence` demonstrates with an
  injected QC service (fresh context per invocation, no shared closure): it
  receives exactly the declared input schemas; the request carries no runtime
  private surface (asserted via `NodeServiceRequest.__slots__`); the QC
  execution identity differs from the writer identity; the human decision
  actor is separate from both.  The test class docstring explicitly labels
  this OFFLINE ORCHESTRATION EVIDENCE — not actual-model fresh context and
  not clinical acceptance; real-model QC activation stays deferred.
- No new agent framework; the QC node remains a plain `NodeService` over the
  existing typed boundary.  No exact minimal need to report beyond this.

### Fresh F4 (concurrent start) — FIXED

`start_run` now compares root input identities in the fast path (typed
`graph_root_inputs_conflict` on changed facts) and appends through
`_append_events_tx` with `_start_guard`: inside the transaction, an existing
start with identical plan identity AND identical root hashes is idempotent
reuse (False); anything else raises the typed binding error — concurrent
starts can never double-create a run or silently rebind roots.
`test_same_run_cannot_silently_accept_changed_root_facts` (ported probe)
covers the sequential changed-roots case.

## Verification results (corrected environment)

| Run | Result | Evidence (runs/mw_protocol_v3_2r1_typed_facade_20260905/) |
|---|---|---|
| Codex 4 probes, pre-repair | 4 failed | `codex_four_probes_prerepair_rerun.xml` |
| Codex 4 probes, post-repair | 4 passed | `codex_four_probes_postrepair.xml` |
| Focused: product 29 + recovery 10 + facade 26 | 65 passed | `focused_suites_postrepair.xml` |
| Full tests/protocol_v3 + pocs/protocol_v3/orchestrator/tests | **1661 passed** (42.9s) | `full_suites_postrepair.xml` |
| Reviewer cas_proof.py (forced TOCTOU) | 1 winner + typed conflict | stdout captured in report |
| Reviewer true_race_driver.py (conflict/duplicate) | 1 recorded event each; typed conflict | stdout captured in report |
| Reviewer receipt_zombie_repro.py | stops at old signature by design (hash-only refused); ported to allowed suite | disposition above |
| Seven accepted Task 2.1 files | unchanged (hash diff clean) | `seven_file_hashes_expected.txt` |

1649 (prior corrected baseline, excluding the four probes) + 12 net new/updated
focused tests = 1661, consistent; with node on PATH the previously
environment-failing frontend wrapper tests also pass, so no red remains.

## Boundary

- Edits limited to: `services/api/app/protocol_workflow/graph/runtime.py`,
  `tests/protocol_v3/test_graph_runtime.py`,
  `tests/protocol_v3/test_graph_runtime_recovery.py`,
  `pocs/protocol_v3/orchestrator/tests/test_typed_facade.py` — all within the
  originally allowed nine-file set.  No storage/contracts/runtime-reservations/
  main/legacy/frontend edits; the three tracked-file modifications visible in
  git status (contracts, reservations, test_contracts) pre-existed this
  session's dispatch and were not touched.
- No services/models/network/install/live writes; children kill only
  themselves; fresh temporary SQLite per test; no historical evidence
  rewritten (reviewer scripts and original probe XML preserved read-only).

## Remaining limitations

1. True-overlap decision contention on local SQLite usually serializes below
   the interleave window; correctness is therefore guaranteed by the
   in-transaction guard (proven by the forced-interleave tests), not by race
   frequency.
2. Receipt adoption requires the caller to hold the recovered payload; a
   payload-recovery pipeline (obtaining the payload from the provider) is
   future work — the runtime refuses unusable hash-only evidence instead.
3. QC independence evidence is orchestration-layer only (labeled as such);
   actual-model QC remains deferred by plan.
