Re-verifying the F1 fix and Task 1.5 invariants from the allowed sources only, then returning the round-2 report.Shell remains blocked in Ask mode; I'll statically re-verify the F1 repair and scan for double-counting or regression in the allowed sources.Checked the F1 repair path end-to-end. One residual doc mismatch remains on the repaired method; shell/pytest is still blocked in this Ask session.

# Conference Participant Output: mw_protocol_v3_phase1_task15_final_acceptance_20260810 - participant2_cursor_fallback

## Boundary Check

- Same isolated Cursor CLI participant-2 fallback session (round 2); no restart into other venues.
- Read-only; allowed files only. Did **not** inspect other participant/reviewer/run/log outputs.
- No edits, services, network, browser, package install, security/adversarial/hygiene suites, later tasks, or medical-monitoring reads.
- Ask-mode shell still rejects `pytest` / ephemeral probes; live green counts below are **not** independently observed here.

## Independent Work Product

Verdict: NOT_READY

| ID | Severity | Source / symbol | Finding | Reproducible counterexample | Smallest repair |
|---|---|---|---|---|---|
| F1 | CLOSED | `DispatchOutcomeKind.DEFERRED_NO_HANDLER`; `OutboxDispatcher.acknowledge_one`; `recover_dispatched` (`events/outbox.py`); `test_recovery_without_handler_remains_dispatched_not_failed` | Prior F1 is behaviorally fixed: no-handler on persisted `DISPATCHED` returns `DEFERRED_NO_HANDLER`, lands **once** in `still_dispatched`, never in `failed`, status stays `DISPATCHED`. Second sweep loop excludes IDs already in `still_dispatched` (no double-count). `dispatch_pending` claims then calls `acknowledge_one`, so it exposes the same non-terminal kind. | Encode/enqueue → `claim_pending` → `OutboxDispatcher(handler=None).recover_dispatched(..., handler=None)`: `failed==()`, `len(still_dispatched)==1`, stored `DISPATCHED`. Or `dispatch_pending` with `handler=None` after enqueue: outcome kind `DEFERRED_NO_HANDLER`, status `DISPATCHED`. | None (behavior). |
| D1 | P4 | `OutboxDispatcher.acknowledge_one` docstring step 2 (`events/outbox.py` ~611–612) | Docstring still says “return ``FAILED`` without mutating state” while the implementation returns `DEFERRED_NO_HANDLER`. Residual F1 surface inconsistency on the repaired public method. | Read docstring vs lines 655–661: kind is `DEFERRED_NO_HANDLER`, not `FAILED`. | Change step 2 text to `DEFERRED_NO_HANDLER` / leave `DISPATCHED` for a later cycle. |

Checkpoint / prior invariants (static re-check; no new defect):

- Complete-prefix double `replay_stream` before checkpoint success still present (`store.py` evidence_prefix → first/second replay + hash compare).
- Encoded counterexamples still present: unknown-schema predecessor; pairwise stateful upcaster; exact event/node/artifact/stream mismatch; PENDING ack precheck.
- Migrated-payload hash bind, closed registries, stream binding, UoW/crash paths covered by the three named suites unchanged in this re-read.

## Evidence And Assumptions

**F1 repair (code)**

```292:301:services/api/app/protocol_workflow/events/outbox.py
    * ``DEFERRED_NO_HANDLER`` — no handler is currently configured.  The
      message remains ``DISPATCHED`` for a later recovery sweep; this is not a
      permanent failure.
    ...
    DEFERRED_NO_HANDLER = "deferred_no_handler"
```

```532:555:services/api/app/protocol_workflow/events/outbox.py
                elif outcome.kind is DispatchOutcomeKind.DEFERRED_NO_HANDLER:
                    still_dispatched.append(outcome.message)
                ...
                        and current.outbox_message_id
                        not in {m.outbox_message_id for m in still_dispatched}
                    ):
                        still_dispatched.append(current)
```

```655:661:services/api/app/protocol_workflow/events/outbox.py
        if active_handler is None:
            return DispatchOutcome(
                kind=DispatchOutcomeKind.DEFERRED_NO_HANDLER,
                message=message,
                error_detail="no side-effect handler configured",
            )
```

**F1 exact test** — `TestCrossComponentCrashRecovery.test_recovery_without_handler_remains_dispatched_not_failed` asserts `failed == ()`, `len(still_dispatched) == 1`, stored `DISPATCHED`.

**`dispatch_pending`** — claims then `acknowledge_one`; with `handler=None` yields `DEFERRED_NO_HANDLER` without further transition (docstring of `dispatch_pending` already describes leave-`DISPATCHED`).

**D1** — same method’s docstring step 2 still names `FAILED`.

**Checkpoint non-regression** — `reconcile_checkpoint` still double-replays `evidence_prefix`; tests `test_checkpoint_rejects_unreplayable_predecessor`, `test_checkpoint_rejects_pairwise_stateful_upcaster`, `test_checkpoint_backed_by_event_succeeds` still present.

**Commands attempted (blocked)**

```text
PYTHONPATH=services/api:packages:. python3 -m pytest -W error -p no:cacheprovider \
  tests/protocol_v3/test_event_outbox_atomicity.py::TestCrossComponentCrashRecovery::test_recovery_without_handler_remains_dispatched_not_failed \
  tests/protocol_v3/test_event_replay.py \
  tests/protocol_v3/test_event_outbox_atomicity.py \
  tests/protocol_v3/test_repository_contract.py -q
```

Observed: shell `Rejected:` — cannot confirm main-venue anchors `1 passed` / `154 passed` / `375 passed` / Ruff / `git diff --check` in this session. Those are challenged, not trusted.

**Assumptions**

- Behavioral authority is enum + control flow + focused test, not the stale docstring sentence.
- In-memory adapter remains the Task 1.5 reference for these suites.

## Risks, Gaps, And Verification Needs

- Live pytest of the F1 node and three focused files must be re-run outside Ask mode before chair final acceptance.
- D1 is doc-only; runtime taxonomy matches the repaired contract. Under strict “no P0–P4” READY gate it still blocks.
- No dedicated `dispatch_pending(handler=None)` assertion exists; coverage is via shared `acknowledge_one` (acceptable if chair accepts path identity).

## Recommended Next Step

Fix D1’s one docstring sentence on `acknowledge_one` step 2, then re-run the exact F1 test and the three focused files with `PYTHONPATH=services/api:packages:. python3 -m pytest -W error -p no:cacheprovider ... -q`. If green and D1 gone, participant-2 can return `Verdict: READY` without further Task 1.5 scope.
