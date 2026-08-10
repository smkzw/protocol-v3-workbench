I'll run an isolated read-only Task 1.5 audit from the listed sources only, then falsify the checkpoint contract and return the participant report without writing the file.Next I'll read the events package, design §18, the three Task 1.5 tests, and the canonical modules.Reading the three Task 1.5 tests and the canonical hash helpers next.Running the three focused tests, then independent ephemeral falsification probes for the checkpoint contract.Retrying the focused tests and ephemeral falsification probes — the prior shell call was rejected.# Conference Participant Output: mw_protocol_v3_phase1_task15_final_acceptance_20260810 - participant2_cursor_fallback

## Boundary Check

- Role: Cursor CLI `cursor-grok-4.5-high` as declared participant-2 fallback after Grok Build no-progress breaker exhaustion; fresh isolated session.
- Read-only sources only (listed set): `AGENTS.md`, conference context, Hermes Task 1.5, design §18, `DomainEvent`, `events/`, repository/UoW ports, in-memory adapter, canonical `study_revision_hash` / `document_revision_hash`, and the three Task 1.5 tests.
- Did **not** inspect any Grok / Pi / Luna / worker / review / run / log outputs.
- No edits, network, browser, package installs, services, medical-monitoring, later tasks, or security/adversarial/hygiene suites.
- Ask-mode shell execution was rejected for both `pytest` and ephemeral stdin probes; verdict below is from static contract falsification against current sources. Live commands remain a verification gap for the chair.

## Independent Work Product

Verdict: NOT_READY

| ID | Severity | Source / symbol | Finding | Reproducible counterexample | Smallest repair |
|---|---|---|---|---|---|
| F1 | P3 | `OutboxDispatcher.acknowledge_one` + `recover_dispatched` (`events/outbox.py`); contradicts `OutboxRecoveryResult` / `recover_dispatched` docs | No-handler recovery is misclassified as permanent `failed` while the repository message remains `DISPATCHED`. That breaks honest at-least-once recovery taxonomy (design §18 / Task 1.5 crash resume). | Enqueue → `claim_pending` → `OutboxDispatcher(..., handler=None).recover_dispatched(project, messages=claimed, handler=None)`: `len(result.failed)==1`, `result.still_dispatched==()`, and `outbox.get(...).status is DISPATCHED`. | In `acknowledge_one`, when persisted status is `DISPATCHED` and `active_handler is None`, return a non-terminal outcome (new kind e.g. `DEFERRED_NO_HANDLER`, or reuse a path that feeds `still_dispatched`) **without** appending to `failed`; keep status `DISPATCHED`. Align `dispatch_pending` docs/outcomes the same way. |
| — | — | Checkpoint path under audit | Complete-prefix **double** `replay_stream` before checkpoint success is present and closes the prior Luna P2 class (unknown-schema predecessor; pairwise-stable stateful upcaster). | See Evidence CE1–CE3 (static). | None for the checkpoint fix itself. |
| — | — | Regression surfaces checked | Migrated-payload immutable hash binding; persisted `DISPATCHED` precheck before handler/inbox; closed registries + stream binding; UoW CAS+event+outbox atomicity; Task 1.4 authoritative revision-hash cross-check; honest inbox crash-window at-least-once are implemented and covered by the named tests (static). | See Evidence CE4–CE8. | None found beyond F1. |

Checkpoint contract (independently falsified against `EventReplayEngine.reconcile_checkpoint`):

1. Selects exact backing event by `(event_type, event_sha256[, stream_id])`, then binds `node_id` / optional `artifact_sha256`.
2. Replays `events[:backing_index+1]` **twice** under the same closed registries/reducer; quarantines if either pass quarantines or canonical revision hashes diverge.
3. Unknown-schema predecessor → first replay `UNKNOWN_SCHEMA_VERSION` → checkpoint `CHECKPOINT_EVENT_MISMATCH` (detail includes `unknown_schema_version`) **before** success.
4. Pairwise-equal stateful upcaster matching first migrated hash → second pass fails `NONDETERMINISTIC_UPCASTER` via immutable `migrated_payload_sha256` → `not replay-stable` quarantine **before** success.

## Evidence And Assumptions

**Authority**

- Task 1.5: events are business authority; checkpoint is execution position only; unknown schema/upcaster quarantines; outbox/inbox exactly-once semantic effect with at-least-once delivery.
- Design §18: same; canonical mutation + outbox same transaction; checkpoint without event/artifact fail-closed.

**Checkpoint double-replay (store.py)**

```574:617:services/api/app/protocol_workflow/events/store.py
        evidence_prefix = tuple(events[: backing_index + 1])
        first_replay = self.replay_stream(
            evidence_prefix,
            expected_stream_id=evidence_stream_id,
        )
        ...
        second_replay = self.replay_stream(
            evidence_prefix,
            expected_stream_id=evidence_stream_id,
        )
        ...
        if (
            first_replay.success.canonical_revision_sha256
            != second_replay.success.canonical_revision_sha256
        ):
            return self._checkpoint_mismatch(...)
```

**CE1 (unknown-schema predecessor)** — encoded in `TestCheckpointReconciliation.test_checkpoint_rejects_unreplayable_predecessor`; matches store path above.

**CE2 (pairwise stateful upcaster)** — encoded in `test_checkpoint_rejects_pairwise_stateful_upcaster`; second migrate fails `migrated_payload_sha256` bind in `UpcasterRegistry.migrate`.

**CE3 (happy path)** — `test_checkpoint_backed_by_event_succeeds`; success only after double replay.

**CE4 (PENDING precheck)** — `acknowledge_one` loads persisted row and requires `DISPATCHED` before handler/inbox; `test_public_ack_rejects_pending_before_handler_or_inbox_write`.

**CE5 (F1)** — `acknowledge_one` returns `DispatchOutcomeKind.FAILED` when `active_handler is None` without mutating status; `recover_dispatched` appends that outcome to `failed`, while docs say leave `DISPATCHED` / `still_dispatched`.

**CE6 (migrated hash)** — legacy migrate requires `migrated_payload_sha256`; missing/mismatch → `NONDETERMINISTIC_UPCASTER`; covered by nondeterministic / pairwise tests.

**CE7 (registries / stream / revision hash)** — engine freezes registries; `STREAM_ID_MISMATCH`; `_revision_hash` cross-checks `study_revision_hash` / `document_revision_hash`.

**CE8 (UoW + crash honesty)** — `EventSourcedUnitOfWork.apply_mutation` ordering + inactive/empty-event guards; inbox-before-ack recovery; `test_crash_after_effect_before_marker_requires_idempotent_handler` documents at-least-once handler window.

**Commands attempted (blocked in Ask mode)**

```text
PYTHONPATH=services/api:packages:. python3 -m pytest -W error -p no:cacheprovider \
  tests/protocol_v3/test_event_replay.py \
  tests/protocol_v3/test_event_outbox_atomicity.py \
  tests/protocol_v3/test_repository_contract.py -q
```

Observed: shell tool `Rejected:` (empty body) — no pytest stdout collected.

Ephemeral stdin falsification probe: same rejection; no artifacts created.

**Assumptions**

- In-memory adapter is the Task 1.5 reference for port semantics (not production durability).
- Named tests are authoritative executable counterexamples; static alignment is strong but not a substitute for the blocked run.

## Risks, Gaps, And Verification Needs

- Chair/runner must re-run the three named pytest files outside Ask mode; treat this report’s READY gate as blocked on F1 plus missing live green evidence.
- F1 does not reopen the checkpoint double-replay P2; it is a separate recovery-result honesty defect inside Task 1.5 outbox recovery.
- No claim about SQLite/PostgreSQL adapters, Task 1.6+, or production processes.

## Recommended Next Step

Patch F1 so `DISPATCHED` + no handler is reported as deferred/`still_dispatched` (status unchanged), add a focused assertion in `test_event_outbox_atomicity.py`, re-run the three named tests with `PYTHONPATH=services/api:packages:. python3 -m pytest -W error -p no:cacheprovider ... -q`, then re-open participant-2 only if the checkpoint counterexamples and F1 regression both pass.
