# Conference Participant Output: mw_protocol_v3_1r4_durable_fresh_20260905 - general_single_object

## Boundary Check

- Worked inside the runner workspace only. Read the four source-of-truth files (`storage/sqlite.py`, `runtime/reservations.py`, `ports/repositories.py`, `contracts/protocol_v3.py`) plus the named test files. Did not read production paths, other runner reports, or private execution reasoning.
- No source edits made (frozen-source pass). No services launched, no model calls. Created no probe files; relied on the committed focused suites plus code audit.
- Verification runs used exactly the prescribed environment string. `test_execution_reservations_adversarial.py` named in the context does not exist in `tests/protocol_v3/` (glob confirms); treated as absent optional file per scope, not as license to broaden.

## Independent Work Product

**Verdict: the committed repair is correct on its primary claims, with one genuine race defect remaining (orphan-dispose path leaks an unmapped exception under concurrency) plus three minor limitations. No rework of the durability architecture is warranted.**

What I verified against actual source (not narrative):

1. **Persist-first durability holds.** `ReservationCoordinator._dispatch_and_persist` commits the RESERVED shell via `SqliteCommittedOperationReservationRepository.reserve()` (own `BEGIN IMMEDIATE…COMMIT`, `synchronous=FULL`) before preflight/dispatch, moves to RUNNING with `transport_attempts=1` before `transport.dispatch`, and only then dispatches. Confirmed by `test_sqlite_claim_is_durable_before_physical_dispatch` (independent-connection observation of `("running", 1)` mid-dispatch) and by the two `os._exit` crash-child tests: crash-before-RUNNING leaves a durable `("reserved", 0)` orphan shell; crash-after-accept leaves a durable `("running", 1)` claim that restart refuses to redispatch.
2. **Cross-process live ownership holds for the committed handle.** Each committed handle takes a non-blocking `fcntl.flock` on a per-`(project_id, reservation_id)` file *before* committing the shell and holds it until a terminal state persists; `has_live_dispatch` probes the same file, and process death releases it automatically. `test_separate_process_caller_preserves_live_reserved_owner` (spawn context) proves a survivor in another process fail-closes with `UnknownOutcomeConflictError` and zero dispatches while the owner is live. In-process coverage comes from `_INFLIGHT_CLAIMS` claimed before `reserve()` and released in `finally`. The two mechanisms compose correctly: in-process registry covers the pre-commit window (shell not yet visible to others), the file lock covers everything after commit.
3. **Unknown-outcome non-redispatch holds.** `reserve()` raises `UnknownOutcomeConflictError` on UNKNOWN rows; `reserve_or_reuse` and `retry_explicit` both converge to it; the original idempotency key stays bound to attempt 1 after explicit retry (`test_unknown_outcome_explicit_retry_is_durable_and_append_only`, replay-identity idempotence included). Duplicate-claim races with distinct reservation ids serialize on `BEGIN IMMEDIATE` + the `UNIQUE (project_id, logical_call_id, idempotency_key)` / `UNIQUE (…, attempt)` constraints; the loser returns the winner's row without dispatching (reserve precedes dispatch — the retry loop's "no physical dispatch occurred" comment checks out).
4. **Explicit retry history is append-only and durable.** `retry_explicit` binds attempts to `idempotency_key::retry-decision:<id>`, allocates `max(attempt)+1`, retries on attempt-number collision, and never mutates attempt 1. Survives handle restart.
5. **Business-UoW atomicity is preserved.** `SqliteUnitOfWork` still commits/rolls back at the `with` boundary; `SqliteCommittedOperationReservationRepository` is a separate handle with its own connection and per-operation transactions. `close()` semantics are idempotent and release file locks. No autocommit of caller data introduced.

Test evidence: `test_durable_reservation_dispatch.py` + `test_sqlite_reservation_lifecycle.py` → **8 passed**; `test_execution_reservations.py` + `test_reservation_result_projection.py` → **44 passed**. Zero failures.

## Evidence And Assumptions

Evidence (observed):
- `sqlite.py:2068-2172` — committed handle: flock-before-commit in `reserve()`, lock release only when `result.terminal_state is not None` in `transition()`, per-op `BEGIN IMMEDIATE/COMMIT`, dedicated connection, idempotent `close()`.
- `sqlite.py:380-382` — DDL carries `PRIMARY KEY (project_id, execution_reservation_id)`, `UNIQUE (project_id, logical_call_id, idempotency_key)`, `UNIQUE (project_id, logical_call_id, attempt)`; adoption preflight fingerprints constraints, not just names (`:768-787`).
- `reservations.py:313-350` — orphan path: `find` → `_inflight_owner`/`has_live_dispatch` probe → `transition(…FAILED, attempts=0)`, with **no** `try/except RepositoryStateTransitionError` and no re-read.
- `reservations.py:543-646` — `_claim_inflight` before `reserve()`, `_release_inflight` in `finally`; reserve precedes preflight precedes dispatch.
- `reservations.py:672-694` — `_outcome_for_existing` fail-closes RESERVED/RUNNING/UNKNOWN with `UnknownOutcomeConflictError`.
- `sqlite.py:260-278` — `_conn_for`: manual transaction control, `synchronous=FULL`, `busy_timeout`, WAL set once at bootstrap (documented rationale).
- Tests listed above, all green under the prescribed env.

Assumptions/inferences (marked):
- `[INFERENCE]` macOS `flock` semantics assumed per code comment and `test_separate_process_caller_preserves_live_reserved_owner` passing on this host; did not independently test lock behavior under `SIGKILL` beyond the `os._exit` children (equivalent for fd release).
- `[INFERENCE]` The missing `test_execution_reservations_adversarial.py` was renamed or folded into `test_durable_reservation_dispatch.py`; did not search history (immutable-history edits out of scope).

## Risks, Gaps, And Verification Needs

**R1 (highest impact, genuine defect): orphan-dispose race leaks `RepositoryStateTransitionError`.**
The orphan path (`reservations.py:336-349`) is read-probe-then-write across two transactions. Two interleavings break the fail-closed contract:
- (a) Two survivors both observe an orphan RESERVED shell and both probe `False`; the first transitions to FAILED, the second's `transition(…FAILED)` raises `RepositoryStateTransitionError` (FAILED→FAILED is not in the allowed map, `sqlite.py:1880-1893`) instead of converging.
- (b) The live owner completes between the survivor's probe and its dispose transition (RESERVED→COMPLETED by owner); the survivor's dispose then raises `RepositoryStateTransitionError` instead of converging to the owner's result.
Callers are specified to expect `UnknownOutcomeConflictError` or a terminal outcome; `RepositoryStateTransitionError` is an unmapped repository-layer leak. Probability is low (narrow window) but the shape is exactly the concurrent-recovery path this repair exists to harden, and the fix is small.
*Proposed remedy (boring, semantics-preserving):* in the orphan-dispose path only, catch `RepositoryStateTransitionError`, re-read the row by id, and converge: terminal row → `return _outcome_for_existing(project_id, fresh)`; still-RESERVED → raise `UnknownOutcomeConflictError`; RUNNING/UNKNOWN → raise `UnknownOutcomeConflictError`. No DDL, no new states, no API change. Suggested regression test: two threads/handles racing `reserve_or_reuse` over one orphan RESERVED shell; assert both callers end in `{FAILED outcome, UnknownOutcomeConflictError}` and never `RepositoryStateTransitionError`, with `dispatch_count == 0`.

**R2 (residual risk, not a defect): raw-UoW dispatch has no cross-process liveness.**
`has_live_dispatch` is probed via `getattr(repository, "has_live_dispatch", None)`; the UoW repository has no such attribute, so a coordinator wired to a UoW handle (allowed by the structural `_RepositoryLike`) disposes RESERVED shells with only the in-process registry as evidence — unsafe across processes. The docstrings correctly direct the dispatch runtime to the committed factory, but nothing enforces it.
*Proposed remedy:* either a one-line guard (coordinator warns/fails when a dispatch that observed a RESERVED shell runs on a repository without `has_live_dispatch`), or a short doc assertion in the factory's contract that multi-process dispatch MUST use committed handles and the UoW route is single-process/test-only. No behavior change to the committed path.

**R3 (minor, operational): unbounded `.dispatch-locks/` file accumulation.**
Every dispatch (including losing racers, which mint a fresh id, open+lock, then close on reuse) creates a never-unlinked lock file; `has_live_dispatch` probes also create files as a side effect. Correct for safety (the "never unlink" comment is right — inode replacement would admit two owners), but the directory grows monotonically with reservation count.
*Proposed remedy:* document the growth and optionally add an out-of-band GC that unlinks only files whose lock is acquirable **and** whose reservation row is terminal — never as part of the dispatch hot path.

**R4 (minor, already covered by tests but worth naming): RUNNING-crash recovery rides `recover_unknown`.**
A crash-after-accept row stays RUNNING; reconciliation calls `recover_unknown` (RUNNING→COMPLETED, session-adopting), which works but overloads the "unknown" name, and `find_unknown_outcome` does not list RUNNING rows (only `find_unresolved` does). Operators must know to look at `find_unresolved`. This matches the port contract ("live RUNNING→COMPLETED may adopt the provider session") — no change proposed beyond keeping the `find_unresolved` guidance visible.

Verification still needed (for Codex, not this pass): R1's racing-survivor regression test does not exist yet; everything else asserted here is covered by the 52 green tests above.

## Recommended Next Step

- **Codex decision:** accept R1 as a bounded follow-up (catch-and-converge in the orphan-dispose path + racing-survivor regression test, touching only `runtime/reservations.py` and `test_durable_reservation_dispatch.py`), and confirm R2–R4 may be handled as documentation-only notes with no source change in this round.
- **Bounded questions for Codex:**
  1. Is `RepositoryStateTransitionError`→converge (R1 remedy) the approved exception mapping, or should the survivor surface `UnknownOutcomeConflictError` unconditionally without re-reading (simpler, but loses the converge-to-completed case in interleaving (b))?
  2. Is the raw-UoW dispatch route (R2) officially single-process/test-only, so that a doc-level constraint suffices and no runtime guard is required?
  3. May a future task own lock-file GC (R3), explicitly out of scope for this repair, so this pass closes with no cleanup mechanism?
- **Safe provisional path if Codex does not answer:** ship the durability repair as-is (evidence supports its primary claims on this local macOS target); file R1 as the single must-fix follow-up before any concurrent-recovery load, and treat R2–R4 as known limitations, not blockers.
