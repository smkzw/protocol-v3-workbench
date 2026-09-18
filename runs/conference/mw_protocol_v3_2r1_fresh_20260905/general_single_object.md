# Conference Participant Output: mw_protocol_v3_2r1_fresh_20260905 - general_single_object

## Boundary Check

- Worked only inside the runner-provided workspace (`.`). No production paths read or modified; no source files edited (all probes are new files under `runs/mw_protocol_v3_2r1_fresh_20260905/` plus fresh `/tmp` SQLite dirs, as permitted).
- Read-only review plus synthetic temporary-SQLite repros. No product calls, no services/models/network, no visual/clinical/regulatory acceptance claimed. Did not read other participants' outputs.
- Used the pinned env spec (`env -i …`, `PYTHONPATH=tests/protocol_v3:services/api:packages:.`, `runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python`, `pytest -p no:cacheprovider`, SQLite 3.53.4). Baseline suites re-run by me: `test_graph_runtime.py` + `test_typed_facade.py` = **48 passed**; `test_graph_runtime_recovery.py` = **5 passed**.

## Independent Work Product

Whole-workflow pass over: `graph/{runtime,state,plan,ports}.py`, `runtime/reservations.py`, `storage/sqlite.py` (reserve/append/commit paths), `typed_facade.py`, all three test modules, three accepted cases (`ELIGIBILITY`, `OBJECTIVE_ESTIMAND_ENDPOINT`, `SAMPLE_SIZE`).

What is genuinely solid (so Codex need not relitigate): kill-before / kill-after / kill-mid-dispatch use real `os._exit` process death at the right boundaries (mid-dispatch kill lands inside the service, after the RUNNING commit, before the result-event commit — the reopened reservation is `RUNNING` with no result event); duplicate resume creates no second lineage; unknown-outcome never auto-redispatches; the committed-reservation discipline (RESERVED shell → RUNNING → terminal, per-operation commits, `flock` liveness probe, zero-transport-attempt orphan classification) correctly prevents double dispatch for compute nodes. The three-case facade matrix is real per-case execution, not a probe-only claim.

Defects below are ordered by impact. All were reproduced or structurally proven by me; file/line refs are exact.

### F1 — High: the "concurrent decision" test never overlaps (test-fidelity defect)

- **Location:** `tests/protocol_v3/test_graph_runtime_recovery.py:507` — `outcomes = [_spawn(payload) for payload in payloads]`, where `_spawn` is a blocking `subprocess.run` (`:271-276`).
- **Fact:** racer 0 must write evidence and exit before racer 1 is even spawned. The file-barrier rendezvous (`child_main` `"record_decision_race"`, `:180-208`) can never meet: racer 0 waits up to 5 s for a marker that cannot appear, then records uncontested; racer 1 starts later, observes the recorded decision, and takes the typed-conflict path. The assertion `sorted(...) == ["conflict","recorded"]` (`:509`) therefore passes **deterministically with zero overlapped instructions**.
- **Impact:** the suite proves sequential second-writer-conflicts only. It exercises none of: overlapped check-then-append, overlapped event-sequence allocation, or SQLite single-writer contention. Any claim that "concurrent decisions" were verified against real concurrency is unfounded.
- **Minimal repair:** spawn both racers with `Popen` (concurrent lifetimes), join both, then assert. My driver (`runs/mw_protocol_v3_2r1_fresh_20260905/true_race_driver.py`) does exactly this and is available as the replacement harness.

### F2 — High: `record_decision` has no compare-and-swap; truly overlapped conflicting decisions double-record, both return "recorded"

- **Location:** `services/api/app/protocol_workflow/graph/runtime.py:394-466`. The conflict check reads `view.recorded_decisions` from transaction T1 (`_load`, `:394`); the two decision events are built and appended in a later, separate transaction T2 (`_append_events`, `:429`), which re-reads the stream head fresh and allocates new sequences (`storage/sqlite.py:1062-1067,1227-1250`). No in-transaction recheck; no UNIQUE constraint on the decision key (event table keys are `(project_id, stream_id, sequence)` + `(project_id, stream_id, domain_event_id)`, `sqlite.py:328-329` — both freshly allocated per append, so overlapped appends never collide).
- **Proof (forced interleave, no source edits — thread wrappers park A between its T1 check and T2 append, then run B):** `runs/mw_protocol_v3_2r1_fresh_20260905/cas_proof.py` → `outcomes: {'B': 'recorded', 'A': 'recorded'}`, `n_decision_recorded: 2 ['dec-bbb','dec-aaa']`. Last-writer-wins silently; neither party sees any error. Exactly-one-wins is violated.
- **Calibrating evidence:** 13 true-overlap `Popen` rounds all serialized to exactly one winner with typed `GraphDecisionConflictError` for the loser. Reason: every `_load`/`_append_events` opens `BEGIN IMMEDIATE` even for reads, so the check-append gap is usually sub-millisecond and losers block-then-observe. The window is narrow in practice but structurally open; F1's test can never hit it because it never overlaps at all.
- **Impact:** under genuine operator concurrency (two reviewers confirming at once, retry storms), conflicting human decisions can both commit; the event log holds two `graph_decision_recorded` + two node-results for one decision node and the run proceeds from whichever appended last. Human-decision idempotency/CAS (a design requirement) is not enforced at the decision boundary.
- **Minimal repair (Codex decision Q2):** re-read `recorded_decisions` inside the T2 UoW transaction immediately before `append_events` and raise the existing typed `GraphDecisionConflictError`; or add `UNIQUE(project_id, stream_id, decision_key)` coverage for decision events and map the violation to that typed code. Add the Popen-based test from F1.

### F3 — High: `resolve_unknown_with_receipt` certifies a content-less COMPLETED node; downstream never reaches usable content

- **Location:** `runtime.py:534-569` (adoption) interacting with `_node_status` (`:802-807`), `_gather_inputs` (`:998-1022`), `_finish_run_if_complete` (`:1180-1215`).
- **Repro:** `runs/mw_protocol_v3_2r1_fresh_20260905/receipt_zombie_repro.py` (timeout service → `blocked` → adopt fake sha):
  - `draft after receipt: completed`, `result events for draft: 0`
  - next `advance` **raises** `GraphRunError graph_result_payload_missing: input schema 'draft' of node 'review_node' has no committed result payload` — an exception, not a `blocked` snapshot, so `run_to_completion` also raises. The run is permanently wedged: the node reads COMPLETED, its hash is fabricated, no payload exists, and no API accepts a recovered payload (the API takes only `output_sha256`).
- **Second edge:** `_finish_run_if_complete` counts hash-only reservation-COMPLETED nodes as COMPLETED (`:1191-1198`); if the adopted node is the plan's final node, `EVENT_RUN_COMPLETED` certifies with an empty/missing `final_state` hash.
- **Impact:** the "usable recovery / one effective artifact lineage" acceptance is not met on the unknown-outcome path — the only path that184 names for ambiguous dispatches. The committed test (`test_graph_runtime.py:769-778`) stops at asserting the adopted node reads `completed` and never advances downstream, so the wedge is untested.
- **Minimal repair (Codex decision Q1):** either (a) make adoption payload-bearing — accept the verified output payload and commit a `graph_node_result` event (keeps lineage + downstream working), or (b) declare receipt-adoption lineage-closing only and route all dependency-feeding recovery through explicit retry; and map the missing-payload downstream case to a `blocked` snapshot with an explicit reason instead of an escaping exception. At minimum, exclude hash-only nodes from `_finish_run_if_complete` certification.

### F4 — Medium: concurrent `start_run` double-creates; differing roots silently overwrite the binding

- **Location:** `runtime.py:257-319`. Existence + binding check happens on the T1 `_load` (`:277-283`); the `EVENT_RUN_STARTED` is appended in T2 (`_append_events`), which allocates `sequence = head+1` from a fresh in-transaction head read (`sqlite.py:1227-1250`). Two concurrent starters both observe "no run", then append seq 1 and seq 2 — no collision, no error. Identical plans → duplicate start events (untidy, benign). Differing `root_inputs`/plan → the second start event silently rebinds `view.plan`/`root_payloads` on next `_load` (last-start-wins, `:676-678`), bypassing the `GraphPlanBindingError` fail-closed path that only guards the sequential case.
- **Status:** static proof (same mechanism as F2, confirmed by reading both sides); not dynamically reproduced. Untested path in the suite.
- **Minimal repair:** create-if-absent CAS inside the T2 transaction — recheck the stream head for a pre-existing start event before inserting; on mismatch raise the existing typed binding error. One targeted concurrent-start test.

### F5 — Low: concurrent compute-node advance fails closed correctly but leaks repository error types

- **Mechanism (correct):** overlapped `_execute_node` on the same node serializes on `BEGIN IMMEDIATE` + `UNIQUE(project_id, logical_call_id, idempotency_key)` (`sqlite.py:381`); the loser converges to the winner's row via `reserve()` → `_outcome_for_existing` → `UnknownOutcomeConflictError`, or hits the `flock` liveness probe (`has_live_dispatch`, `:2085-2092`) while the winner dispatches. No double physical dispatch — verified by reading `reserve_or_reuse` (`reservations.py:303-373`) and `_dispatch_and_persist` (`:500-658`).
- **Defect (minor):** `advance()`/`retry_node()` do not translate `UnknownOutcomeConflictError`/`IdempotencyConflictError` into `GraphRunError` codes, so callers catching only graph-typed errors miss the must-retry-later signal and see storage-layer exceptions instead.
- **Minimal repair:** catch-and-translate at the `GraphRuntime` boundary to a typed code (e.g. `graph_reservation_contended_retryable`), preserving fail-closed convergence. One overlapped-advance test asserting error type + eventual convergence. (Codex decision Q3.)

### F6 — Gap (not a runtime defect): no proof of reviewer/writer independence

- The runtime does separate identities on the wire (runtime events as `SYSTEM/graph-runtime`; decisions as `USER/<actor_id>` with `writer_context.runtime_owner/pid`, `runtime.py:443-447`). But every decision test records a single human decision and asserts completion; nothing asserts the reviewer identity differs from any writer/agent identity, or that QC semantics are independent. Per the conference brief, a fresh human decision event is not by itself proof of independent QC — the suite currently treats it as such. Recommend one test asserting distinct reviewer identity on the decision event and rejection/absence semantics, or explicitly scoping QC-independence out of 2R.1 with a named follow-up.

## Evidence And Assumptions

**Observed (tool-grounded):**
- Baseline green on the pinned env: 48 passed (`test_graph_runtime.py` + facade tests, 27 s), 5 passed (recovery, 10 s), SQLite 3.53.4.
- F1: sequential `_spawn` list-comprehension (`recovery:507` over blocking `subprocess.run :271-276`); barrier protocol (`:180-208`) structurally unable to rendezvous. No run needed — deterministic by construction.
- F2: forced-interleave output `both recorded / n_decision_recorded: 2` (`cas_proof.py`, `/tmp/mw2r1-cas7`); plus 13 true-overlap Popen rounds all serializing 1-winner/1-typed-conflict (narrow window, `BEGIN IMMEDIATE` reads).
- F3: zombie repro transcript quoted above (`receipt_zombie_repro.py`, `/tmp/mw2r1-zombie`): `completed` + `0 result events` + `GraphRunError graph_result_payload_missing` escaping `advance`.
- F5-correctness-half: `UNIQUE(logical_call_id, idempotency_key)` + `BEGIN IMMEDIATE` + `flock` probe read at `sqlite.py:328-382, 2085-2133`, `reservations.py:303-373`.
- Three cases parametrized (`test_typed_facade.py:53-57`); facade mid-dispatch kill is genuine (`os._exit` inside service after RUNNING commit, `:370-376`); product-import isolation test passes.

**Inferred (marked):**
- F4 dynamic behavior is inferred from the identical T1-check/T2-allocate structure as F2 (proven pattern), not yet executed — flagged as needing one confirmation run.
- F2's production hit-rate is low (sub-ms window under local SQLite) — inferred from 13 serialized overlap rounds; severity comes from silent last-writer-wins on human decisions, not frequency.
- Cross-process `flock` reasoning assumes local filesystem (WAL DB on local disk); NFS/remote-FS behavior not probed — out of scope, noted for the record.

## Risks, Gaps, And Verification Needs

1. **F2/F4 share one root cause** (check in T1, mutate in T2, no in-transaction revalidation). Any repair must cover both `record_decision` and `start_run`, or the second will be cited back. Verification: Popen-overlap decision test asserting exactly one `graph_decision_recorded`; concurrent-start test asserting typed binding failure (not silent rebind).
2. **F3 blocks the "usable recovery" acceptance** on the unknown path. Verification: unknown → adopt → `advance` must yield either working downstream content (payload-bearing adoption) or a `blocked` snapshot with explicit reason — never an escaping exception and never a certified run with empty hashes.
3. **Convergence-signal typing (F5):** verification is a two-process overlapped `advance` asserting (a) single physical execution, (b) loser gets a typed retryable code, (c) later `advance` converges.
4. **QC-independence (F6)** needs an explicit scope decision; otherwise a reviewer will re-raise it at closure.
5. **No regression risk from this review:** zero source edits made; evidence scripts live under `runs/mw_protocol_v3_2r1_fresh_20260905/` (`true_race_driver.py`, `receipt_zombie_repro.py`, `cas_proof.py`) and are reusable as the repair-validation harness.

## Recommended Next Step

Bounded repair round, then same-reviewer revalidation (no closure yet): (1) in-transaction decision/start CAS + truly-concurrent tests (F1/F2/F4); (2) payload-bearing receipt adoption or retry-only routing + hash-only exclusion from run certification (F3); (3) error-type translation for contended advance (F5); (4) explicit QC-independence scope note (F6). Reverify with the three evidence drivers plus the 53-test focused set.

**Bounded questions for Codex:**
- **Q1:** Is `resolve_unknown_with_receipt` intended to feed downstream nodes (then it must accept and commit the verified payload), or is it lineage-closing only (then unknown-feeding-downstream must go through explicit retry, and hash-only nodes must not certify)? The fix shape depends on this.
- **Q2:** Is a `UNIQUE` constraint on the decision key (or equivalent in-transaction recheck inside the existing UoW, no new platform) an acceptable repair under schema-ownership rules, applied to both `record_decision` and `start_run`?
- **Q3:** Should overlapped-advance contention surface as a typed retryable `GraphRunError` code, or is the raw repository `UnknownOutcomeConflictError` the accepted caller contract? If the latter, the port doc (`ports.py`) should say so.
- **Provisional path if unanswered:** treat F2/F3 as blocking for closure (failing human-decision CAS and non-usable recovery contradict explicit 2R.1 acceptance), F4/F5 as must-fix-before-closure, F6 as scope-note; do not close on the current suite alone.
