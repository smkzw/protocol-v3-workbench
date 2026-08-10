# Independent Acceptance: Protocol v3 Task 1.5
## Verdict
`NOT_READY`

## Findings

### P0

none

### P1

- **P1-1 — Replay determinism is not stable across replays.**
  `services/api/app/protocol_workflow/events/models.py:516-531`, `events/store.py:220-224`. A stateful upcaster returning `n // 2` produced two successful replays of the same event with `migration_run=0` and `migration_run=1`. This violates the fail-closed deterministic replay contract. Restrict migrations to immutable/version-pinned deterministic implementations and validate a stable migrated-payload identity. Retest repeated replay of the same persisted event.

- **P1-2 — Closed-world registries remain mutable after engine construction.**
  `events/models.py:416-448, 610-618`; `events/store.py:220-224`. Registering a new event type and upcaster after constructing the engine allowed successful replay: `post_construct_registry_mutation True`. Freeze registry snapshots or reject post-construction mutation. Retest mutation after engine construction must reject or quarantine.

- **P1-3 — Checkpoint reconciliation accepts mismatched or tampered evidence.**
  `events/store.py:443-489`. A valid `node.completed` event for another node, with a different artifact hash, returned success; an event with a tampered `event_sha256` also returned success. This violates section 18’s checkpoint fail-closed rule. Require exact event identity/node/artifact binding and envelope/chain verification before success. Retest wrong-node, wrong-artifact, tampered-event, and broken-chain claims.

- **P1-4 — Atomic mutation can bypass the required UoW context.**
  `events/unit_of_work.py:210-315`; `storage/memory.py:1033-1078`. Calling `apply_mutation` without `with uow:` raised `MutationAbortedError("outbox_enqueue")` but left the aggregate and event persisted: `bypass_persisted True 1`. Enforce an active transaction token before the first write. Retest direct invocation must fail before mutation, while in-scope rollback remains atomic.

- **P1-5 — Canonical mutation accepts an empty event list.**
  `events/unit_of_work.py:218-219, 293-297`; `storage/memory.py:442-451`. `apply_mutation(..., events=())` successfully persisted revision 1 with zero events: `empty_events_result 1 0`. This permits business state that cannot be reconstructed from events. Reject empty event sequences before CAS save. Retest state and event stream remain unchanged.

- **P1-6 — Authoritative Task 1.4 revision hashes are not enforced.**
  `events/store.py:539-546`; `canonical/study_definition.py:661-675`; `canonical/document.py:1094-1112`. A `StudyDefinitionV3` replay with `material_sha256()` as the supplied hash function succeeded and returned the material hash instead of `study_revision_hash()`. Use typed replay adapters with pinned `study_revision_hash`/`document_revision_hash`, rejecting mismatched callbacks. Retest wrong hash functions fail and correct hashes match exactly.

- **P1-7 — Inbox exactly-once wording is unconditional despite the crash window.**
  `events/inbox.py:1-33, 110-119, 251-271, 356-366`. A handler incremented a semantic-effect counter and then raised; the result stayed `RECEIVED`, and retry applied the effect again (`effect_count 2`). The current implementation requires caller idempotence but does not enforce it or transactionally combine the effect with `mark_consumed`. Either make exactly-once conditional on an explicit idempotency key/handler, or transact the business mutation and consume mark together. Retest a crash after effect-before-mark with a non-idempotent handler.

- **P1-8 — Stream identity is not bound during append or replay.**
  `events/store.py:272-283`; `storage/memory.py:442-501`. A chain containing `stream:a` followed by `stream:b` replayed successfully, and the repository stored both under `stream:a`: `mixed_stream_replay True 2`, `mixed_stream_append 2 ['stream:a', 'stream:b']`. Validate every event’s `stream_id` against the requested stream and replay scope. Retest mixed-stream append/replay must reject.

### P2

- **P2-1 — Event envelope hashes depend on the process local timezone.**
  `events/models.py:178-190`. The same event hashed differently under `TZ=UTC` and `TZ=Asia/Shanghai` (`timezone_hashes_equal False`). Normalize explicitly to UTC with fixed precision. Retest identical events under different local timezones produce identical hashes.

- **P2-2 — Repository mutators bypass their declared state machines.**
  `storage/memory.py:620-677, 772-792`. Direct calls transitioned `PENDING → COMPLETED` and `RECEIVED → CONSUMED` without dispatch, inbox proof, or semantic handler execution. Enforce legal current-state transitions in repository methods and reject stale/foreign acknowledgements. Retest illegal direct transitions fail closed.

### P3

- **P3-1 — Focused tests contain material coverage gaps and one tautological conflict test.**
  `tests/protocol_v3/test_event_outbox_atomicity.py:975-1020` pre-populates the inbox, causing the dispatcher to short-circuit at `outbox.py:612-626`; it does not exercise the conflict branch at `outbox.py:652-680`. The tests also lack registry-mutation, checkpoint-integrity, empty-event, UoW-bypass, and semantic-effect crash-window cases. Add focused regression tests and rerun the three named files.

- **P3-2 — Fresh-process durability is not demonstrated by the in-memory restart test.**
  `tests/protocol_v3/test_event_outbox_atomicity.py:826-906`; `storage/memory.py:1036-1041`. The test uses a fresh UoW over the same in-memory repository object, not a fresh process over durable storage. The recovery API is present, but durable cross-process behavior remains unverified. Retest repository discovery across an actual process/storage boundary.

### P4

none

## Contract Matrix

| Contract | Status | Evidence | Uncertainty |
|---|---|---|---|
| 1. Events/artifacts are business truth; checkpoints are execution location | FAIL | Replay exists, but empty-event mutation persists canonical state; checkpoint reconciliation is type-only. | Immutable-artifact durable adapter was not exercised. |
| 2. Envelope, payload, chain, schema, and upcaster integrity fail closed | FAIL | Replay verifies hashes, sequence, predecessor, known types, schemas, and upcasters; stream identity and timezone-stable hashing are missing. | Durable repository validation was not tested. |
| 3. Nondeterministic upcasters and mutable registries fail closed | FAIL | Same event replayed successfully into two states; post-construction registry mutation was accepted. | None for the reproduced cases. |
| 4. StudyDefinition/SemanticDocument replay returns authoritative revision hash | FAIL | Correct `study_revision_hash` test passes, but a material hash callback also succeeds. | SemanticDocument direct counterexample was not separately executed. |
| 5. Checkpoint/event/artifact split-brain fails closed | FAIL | Missing-event and missing-artifact happy tests pass; tampered and wrong-node checkpoint probes succeeded. | None for the reproduced cases. |
| 6. CAS + event + outbox are atomic under documented UoW usage | PARTIAL | In-scope `with uow:` rollback tests pass; direct coordinator use leaves partial writes. | Custom/durable UoW behavior was not tested. |
| 7. Fresh process discovers DISPATCHED messages and avoids duplicate remote calls with inbox result | PARTIAL | Repository discovery and inbox-first recovery tests pass over shared in-memory state. | No real durable cross-process test. |
| 8. Inbox idempotency semantics are honest across effect/mark crash window | FAIL | Handler effect ran twice after simulated crash before `mark_consumed`; docs claim unconditional exactly-once. | None for the reproduced crash window. |
| 9. Public composition, conflict fail-closed, no duplicate retry/restart records | PARTIAL | Normal enqueue/record conflicts and retry paths pass; direct state transitions bypass safeguards. | Concurrent durable races were not tested. |
| 10. Tests exercise real contracts | FAIL | `137 passed`, but critical counterexamples and the dispatcher conflict branch are untested. | Additional regression tests are required. |

## Commands And Anchors

Executed required anchor:

```bash
PYTHONPATH=services/api:packages:. python3 -m pytest -W error -p no:cacheprovider tests/protocol_v3/test_event_replay.py tests/protocol_v3/test_event_outbox_atomicity.py tests/protocol_v3/test_repository_contract.py -q
```

Observed: exit 1 before collection because the environment could not create temporary files. The retry with `-s` also failed during `tests/__init__.py` temporary-directory setup.

Executed stdin-only workaround, still using the three named files, `-W error`, and `-p no:cacheprovider`:

```text
137 passed in 0.45s
```

The workaround only bypassed the unrelated `tests` package initializer and created no workspace artifact.

Targeted stdin probes reproduced:

```text
pairwise ... migration_run=0 ... migration_run=1 ... calls 4
post_construct_registry_mutation True
mixed_stream_replay True 2
mixed_stream_append 2 ['stream:a', 'stream:b']
checkpoint_wrong_node_artifact True
checkpoint_tampered_event True
study_hash != study_revision_hash
bypass_result raised outbox_enqueue
bypass_persisted True 1
empty_events_result 1 0
effect_count 2
pending_to_completed PENDING COMPLETED
received_to_consumed_direct CONSUMED
timezone_hashes_equal False
```

The focused test pass is executed evidence; the absence of a durable fresh-process implementation is an acceptance limitation inferred from the current in-memory source and tests.

## Boundary Check

No source, test, or report file was edited. The runner-owned report path was not written. No services were started, packages installed, network/browser access used, security/adversarial/hygiene/source-baseline tests run, or directory-wide suite executed. No medical-monitoring files or conference/worker/manager reports were accessed. All counterexamples were ephemeral stdin input to `python3 -` and left no workspace artifact.

## Next Step

Codex may not accept Task 1.5. The current focused tests are green, but the reproduced P1 contract failures require repair and decisive retesting before acceptance.
