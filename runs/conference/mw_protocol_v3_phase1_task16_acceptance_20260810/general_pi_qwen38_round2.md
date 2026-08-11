All 31 independent probes pass; 112/112 focused tests confirmed on my own run. One last adversarial sweep on the repair edges before finalizing: concurrent dispose race (both interleavings fail closed with zero dispatch — verified by reasoning over `memory.py:955-1009` transition table), StableId validity of the new error code (passes `model_validate` inside `transition`, confirmed by the probe row persisting), and RESERVED-with-attempts>0 impossibility (repo enforces RESERVED→RUNNING is the only attempts increment, so RESERVED⇒transport_attempts==0 and RUNNING⇒≥1). No new P0–P4.

# Conference Participant Output: mw_protocol_v3_phase1_task16_acceptance_20260810 - general_pi_qwen38 (Round 2)

## Boundary Check

- Read-only compliance: re-read only the declared Task 1.6 source packet (`protocol_v3.py`, `runtime/{idempotency,reservations,__init__}.py`, `ports/repositories.py`, `storage/memory.py`, the two named test files). No worker/manager/review/metrics/run/raw-log/other-participant files opened. No source file modified.
- Execution compliance: ran exactly the two allowed focused files plus one deterministic probe script written to `/tmp` (outside workspace, read-only intent, no workspace writes). No security/hygiene/source-baseline/directory-wide/service/live-provider runs.
- Report path: `runs/conference/mw_protocol_v3_phase1_task16_acceptance_20260810/general_pi_qwen38_round2.md` is runner-managed; returned below, not written by tools.
- Independence: findings derived solely from current filesystem state and my own test/probe runs; Codex's 112/112 claim re-verified, not accepted on trust.

## Independent Work Product

### Verification verdict per former finding (all re-executed against repaired code)

**F1 — RESTRICTED fallback accepted implicit target. VERIFIED FIXED.**
- Evidence: `idempotency.py:300-305` now raises `FallbackSafetyViolation` when `sensitivity_tier is RESTRICTED` and either `target_provider` or `target_region` is `None`; allowlist membership still enforced afterwards (`:307-312`). Pin: `test_execution_reservations.py:1260-1271` (`test_restricted_fallback_requires_explicit_target`).
- My probes: no-target / provider-only / region-only all raise; both-targets-in-allowlist returns the canonical payload verbatim; region outside allowlist raises. 5/5 PASS.

**F2 — dangling RESERVED shell on restart. VERIFIED FIXED.**
- Evidence: `reservations.py:254-271` disposes an existing `RESERVED` row in place to `FAILED` with `dispatch_not_started_recovery` (defined `:124`), `transport_attempts=0`, before any transport call; decision-tree docstring updated (`:223-228`). Safety premise holds: `_dispatch_and_persist` transitions RESERVED→RUNNING with `transport_attempts=1` (`:486-496`) before `transport.dispatch` (`:501`), and the repository rejects any RESERVED exit with an attempt count other than `existing` (FAILED) or `existing+1` (RUNNING) (`memory.py:990-1002`), so RESERVED⇒dispatch never started.
- Pins: `test_execution_reservations.py:610-652` (dispose, zero dispatch, `find_unresolved` empty), `:561-608` (terminal-persist-failure RUNNING row: restart raises, zero dispatch).
- My probes: dispose returns FAILED + correct error code + `transport_attempts==0` + zero dispatch + zero preflight; second call reuses the FAILED row with zero dispatch and same row id; input-hash mismatch raises `IdempotencyConflictError` and leaves the shell undisposed; `retry_explicit` after disposal appends attempt 2, lineage reads `[FAILED@1, COMPLETED@2]`. 13/13 PASS.
- Note: the design clause "restart…不能…伪造 failed" is not violated — there is no dispatch ambiguity at transport_attempts==0, and the row is transitioned through the repository state machine with full pydantic revalidation, not overwritten; lineage is preserved, not erased.

**F3 — RUNNING receipt-session adoption vs UNKNOWN recovery lock. VERIFIED FIXED/PINNED.**
- Evidence: `memory.py:1015-1029` documents and enforces the split: RUNNING→COMPLETED may adopt a provider-issued session; UNKNOWN_OUTCOME recovery must present the persisted session identity or raises `RepositoryStateTransitionError`. Coordinator comment `reservations.py:537-540`.
- Pins: `test_repository_contract.py:1028-1051` (adoption allowed), `:995-1026` (cross-session recovery rejected).
- My probes: live completion adopts `sess:provider-live`; timeout→UNKNOWN persists placeholder session; recovery with wrong session raises and row stays discoverable in `find_unresolved`; recovery with the persisted session completes. 5/5 PASS.

**F4 — cross-coordinator duplicate retry. VERIFIED FIXED/PINNED.**
- Evidence: repository ownership is the cross-instance arbiter; coordinator docstring `reservations.py:186-189` states duplicate decisions observing an in-flight winning row fail closed and converge later. `reserve()` returns the existing in-flight row, `_outcome_for_existing` raises `UnknownOutcomeConflictError` for RESERVED/RUNNING/UNKNOWN (`:590-602`).
- Pin: `test_execution_reservations.py:1074-1142` (one dispatch, loser fail-closed, replay converges to winner row).
- My probes: two coordinators, same decision id, barrier-synchronized → exactly 1 dispatch, 1 winner, 1 `UnknownOutcomeConflictError`; replay returns winner row with no further dispatch. 4/4 PASS.

**F5 — original UNKNOWN attempt after later explicit retry. VERIFIED FIXED/PINNED.**
- Evidence: retry rows are keyed `{original_key}::retry-decision:{decision_id}` (`:572-582`), so the original idempotency key stays bound to attempt 1; `_by_logical_call` never rekeys.
- Pin: `test_execution_reservations.py:1144-1177` (`test_resolved_retry_does_not_rebind_original_unknown_key`).
- My probes: after retry attempt 2 completes, `reserve_or_reuse` on the original key still raises `UnknownOutcomeConflictError` with zero dispatch; original row remains `UNKNOWN_OUTCOME` attempt 1 and is still discoverable via `find_unresolved`. 4/4 PASS.

### Focused test suite (my own run, not Codex's claim)

`PYTHONPATH=$PWD:$PWD/services/api python3 -m pytest tests/protocol_v3/test_execution_reservations.py tests/protocol_v3/test_repository_contract.py -q -p no:cacheprovider` → **112 passed in 1.02s**. Matches main-venue observation.

### Residual informational observations (P5, non-blocking; no counterexample produced)

- P5-a: in the concurrent dispose race on one dangling RESERVED shell, the loser surfaces either `UnknownOutcomeConflictError` (observed FAILED) or `RepositoryStateTransitionError` (lost the transition race). Both fail closed with zero dispatch; the error taxonomy is just not uniform.
- P5-b: `recover_unknown` raises `KeyError` on a malformed receipt missing `output_sha256` rather than a typed error. Fail-closed and state-safe (no transition occurs), but a typed code would improve the audit story.
- P5-c: `_retry_lock` is coordinator-local by design; cross-process serialization rests entirely on the repository claim. Documented; adequate for the in-memory reference adapter under Task 1.6 scope.

## Evidence And Assumptions

Evidence (directly observed this round):
- Repaired sources: `reservations.py` lines 124, 223-228, 254-271, 537-541; `idempotency.py` lines 226-229, 300-305; `memory.py` lines 1015-1029.
- Test pins: `test_execution_reservations.py:610-652, 1074-1142, 1144-1177, 1260-1271`; `test_repository_contract.py:995-1026, 1028-1051`.
- Own runs: 112/112 focused tests; 31/31 custom probes (script at `/tmp/r2_task16_probes.py`, executed with workspace read-only).
- Round-1 evidence carried: success-criteria mapping (persist-first, RUNNING ownership, reuse, recovery, retry lineage, fallback shaping) all previously confirmed and unaffected by repairs except F2's decision-tree branch.

Assumptions:
- Design §17.2/§18 and frozen Task 1.6 micro-steps remain the acceptance authority; "不得伪造 failed" permits a zero-transport-attempt FAILED disposition because RUNNING is proven to precede every physical dispatch.
- `dispatch_not_started_recovery` is an acceptable stable error id (it passes the `StableId` regex inside `model_validate`; no separate error-code registry file was in the declared packet).

## Risks, Gaps, And Verification Needs

- No open P0–P4 found this round; all five former counterexamples fail to reproduce against repaired code.
- P5-a/P5-b/P5-c above are informational; none violates a Task 1.6 success criterion or design clause, and each is fail-closed.
- Unverified by design (out of scope): real-transport behavior, later tasks' registry/LangGraph integration, storage adapters beyond the in-memory reference, and all security/hygiene dimensions.
- Verification still Codex-owned: full named Task 1.1–1.6 regression, static checks, frozen-plan SHA-256, medical-monitoring boundary.

## Recommended Next Step

**READY.** No P0–P4 remains in the Task 1.6 packet as read on the current filesystem. F1–F5 are each fixed in source, pinned by focused tests, and independently reproduced as fixed by my own probes. Codex may proceed with its owned final regression/static/hash-boundary checklist and commit the Task 1.6 slice. Optional (non-blocking) follow-ups for a later task: unify the concurrent-dispose error type (P5-a) and give `recover_unknown` a typed malformed-receipt error (P5-b). Codex remains final authority.
