# Conference Participant Output: mw_protocol_v3_1r4_durable_fresh_20260905 - general_single_object

## Boundary Check

- Same-session continuation round 2; no new session opened. Read-only recheck: inspected the updated orphan-disposal block (`runtime/reservations.py:337-361`), the import (`:42-44`), and the new test (`test_durable_reservation_dispatch.py:401-439`). No source or test modifications made; original boundaries persist.
- No services launched, no model calls, no production paths read. Verification used exactly the prescribed environment string.
- This report supersedes the round-1 disposition for R1; R2–R4 dispositions below record Codex decisions, not new findings.

## Independent Work Product

**Updated verdict: R1 is fixed correctly and minimally. The catch-and-converge patch matches the proposed remedy exactly, the new regression test deterministically reproduces the reported failure mode, and all affected suites are green and stable. No further source change is warranted from this role.**

Fix assessment (against actual code, not description):

1. **Scope of the catch is exactly right.** The `try/except RepositoryStateTransitionError` wraps only the orphan-dispose `transition(…FAILED)` (`reservations.py:337-349`). Probe, re-read, and all other transitions are untouched, so no unrelated failure is masked and no retry loop is introduced.
2. **Convergence logic is semantically complete.** The handler re-reads by row ID and delegates to `_outcome_for_existing`, which yields precisely the decision table this role specified: fresh-terminal (FAILED/COMPLETED) → return the outcome (dual-survivor case converges to FAILED; owner-completed-mid-probe case converges to the owner's COMPLETED under normal reuse semantics, with zero new dispatches); fresh-nonterminal (RESERVED/RUNNING/UNKNOWN) → `UnknownOutcomeConflictError`, fail closed, converge on a later call. The missing-row branch (`fresh is None` → `UnknownOutcomeConflictError … from None`) is defensive dead code — no `DELETE` path exists in either repository — but it is fail-closed, carries an actionable message, and correctly suppresses the repository-internal chain. Keeping it is the boring-safe choice.
3. **No layering or import hazard.** `RepositoryStateTransitionError` comes from the already-imported `ports.repositories` module; no new dependency edge, no cycle risk, no DDL/API/state-machine change.
4. **Test quality is good.** `test_concurrent_orphan_recovery_converges_without_repository_error` forces the interleaving with a `threading.Barrier(2)` injected via a per-handle `has_live_dispatch` shim (instance-attribute shadow, no cross-test leakage; both handles closed by their own context managers), asserts `errors == []`, `outcomes == [FAILED, FAILED]`, and `dispatch_count == 0` on both threads, and is robust to scheduling skew (a thread that arrives late simply reuses the already-FAILED row through the non-racy path and still asserts FAILED). Bounded waits throughout (`Barrier.wait(timeout=10)`, `join(15)`); a broken barrier fails loudly rather than hanging.

Verification evidence: `test_durable_reservation_dispatch.py` → **7 passed** (6 prior + 1 new); adjacent suites (`test_sqlite_reservation_lifecycle`, `test_execution_reservations`, `test_reservation_result_projection`, `test_result_storage_consolidation`, `test_superseded_result_migration`) → **65 passed**; new race test additionally run 4× total → **passed every time**. Combined **72 green, 0 failures**.

Codex dispositions R2–R4 (recorded, accepted — none weakens durability, scientific fidelity, or unknown reconciliation):
- **R2:** physical dispatch must use the committed factory; raw UoW is business-transaction/legacy-test composition only, and 2R.1 wiring must enforce this. Consistent with the round-1 finding (UoW handles lack `has_live_dispatch`, so cross-process disposal through them was never safe); enforcement at the wiring layer is the correct place, not a coordinator runtime guard.
- **R3:** no lock-file cleanup/GC authorized; inode growth retained as a known local cost. Correct tradeoff — the "never unlink" rule is load-bearing for the flock protocol, and on a local single-user macOS target the growth (one small file per reservation) is negligible.
- **R4:** `find_unresolved` remains the recovery query for both RUNNING and UNKNOWN; no rename of `recover_unknown`. Agreed — the port contract already documents RUNNING→COMPLETED session adoption, and the crash-after-accept test pins the behavior.

## Evidence And Assumptions

Evidence (observed this round):
- `reservations.py:42-44` — `RepositoryStateTransitionError` added to the existing `ports.repositories` import.
- `reservations.py:337-361` — orphan-dispose `try/except` → `get` by row ID → `None`→Unknown / else `_outcome_for_existing`; success path unchanged.
- `test_durable_reservation_dispatch.py:401-439` — new race test source as summarized above.
- Test runs (prescribed env): 7 passed (durable file); 65 passed (five adjacent suites); 4/4 passes of the new test in isolation. (One incidental note: `--count` is not a supported pytest flag in this repo config — the first invocation printed ini/rootdir lines and still ran once; all loop runs passed normally. No test-runner change needed.)
- Prior round's report of the initial failure (`RepositoryStateTransitionError failed->failed`) is Codex-provided context, not directly observed; the barrier-forced interleaving in the committed test reproduces exactly that transition collision by construction.

Assumptions/inferences (marked):
- `[INFERENCE]` No `DELETE` exists on `execution_reservation` (based on round-1 full-read of `sqlite.py` reservation sections); hence the `fresh is None` branch is unreachable in practice, retained purely as fail-closed defense. No new search was run to re-prove this; a one-line grep by Codex at synthesis time would confirm it at negligible cost.
- `[INFERENCE]` Flakiness assessment rests on 4 isolation runs plus structural reasoning (both scheduling orders converge to `[FAILED, FAILED]`); not a statistical guarantee, but the test is order-insensitive by design.

## Risks, Gaps, And Verification Needs

- **Self-challenge on round 1, answered:** (a) Round 1 proposed "terminal → return outcome; else raise Unknown" — the implementation delegates the whole table to `_outcome_for_existing`, which is exactly that table; no contradiction. (b) Round 1 did not explicitly bless the owner-completed-mid-probe sub-case converging to COMPLETED rather than raising Unknown — on recheck this is correct reuse semantics (same logical call + key, terminal row) and matches the "converge to durable evidence, never redispatch" comment. (c) Round 1 called the `transition` layer's lack of an optimistic-concurrency guard a fact; the chosen fix level (coordinator converge, repository stays dumb fail-closed) is the better layering — repository raises, coordinator interprets. No SQL change needed. (d) One omission in round 1 worth correcting: the losing racer in `reserve()` also mints a lock file for its discarded fresh id (file litter per duplicate claim, not just per dispatch). This strengthens rather than weakens the R3 disposition — GC stays out, cost stays documented.
- **Remaining gaps (all non-blocking, owned elsewhere):** R2 enforcement lives in future 2R.1 wiring — until then, nothing in code stops a caller from dispatching through a UoW handle; that composition remains single-process/test-only by convention only. R3 growth has no accounting (no log line counting `.dispatch-locks/` entries); acceptable locally, worth one sentence in operator notes. R4's `find_unknown_outcome` vs `find_unresolved` distinction relies on operator discipline; the test suite pins it.
- **Verification needs:** none outstanding for this role. The requested regression test exists, fails pre-fix per Codex report, passes post-fix repeatedly, and adjacent suites show no shared-change breakage.

## Recommended Next Step

- **Disposition:** close R1 as remediated and verified (72 green, race test stable 4/4); record R2–R4 per Codex decisions above with no further action in this venue.
- **Concrete asks for Codex synthesis (all bounded, none blocking):** (1) one-line grep confirming no `DELETE` on `execution_reservation`, justifying the `fresh is None` branch as permanent defense; (2) carry the "committed factory mandatory for dispatch; UoW is business-transaction only" rule explicitly into the 2R.1 wiring task acceptance criteria so the conventional constraint becomes enforced; (3) one operator-note sentence covering lock-file growth and the `find_unresolved`-for-recovery rule.
- **No follow-up pass requested by this role**; available same-session if Codex directs otherwise. Codex remains final authority.
