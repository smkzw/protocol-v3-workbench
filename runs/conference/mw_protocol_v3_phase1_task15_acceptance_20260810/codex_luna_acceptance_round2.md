# Independent Acceptance Round 2: Protocol v3 Task 1.5
## Verdict
`NOT_READY`

## Original Findings Disposition

| Finding | Disposition | Current evidence | Exact remaining defect |
|---|---|---|---|
| P1-1 | RESOLVED | `EventReplayEngine.__init__` freezes both registries (`events/store.py:235-238`); registry-freeze regression passes (`test_event_replay.py:1667-1683`). | none |
| P1-2 | REMAINS | Same-engine pairwise drift now quarantines (`events/models.py:551-577`; `test_event_replay.py:1449-1487`). | The migrated-payload pin is registry-local, not persisted. A fresh registry/engine replayed the same event successfully to `migration_run=2` after the first engine materialized `migration_run=0`. |
| P1-3 | RESOLVED | UTC normalization uses fixed microsecond precision (`events/models.py:189-199`); timezone-equivalence test passes (`test_event_replay.py:319-340`). | none |
| P1-4 | RESOLVED | Replay rejects mixed streams; repository append rejects event/target stream mismatch (`events/store.py:290-304`; `storage/memory.py:443-471`). | none |
| P1-5 | RESOLVED | `CheckpointClaim` requires exact event hash; reconciliation verifies chain, envelope, stream, node, event type, artifact binding and presence (`events/store.py:155-175, 485-580`). | The separate unknown-schema checkpoint gap is listed below as P2. |
| P1-6 | RESOLVED | Typed states use `study_revision_hash`/`document_revision_hash`; material-hash callbacks quarantine (`events/store.py:628-645`; replay tests around `1220-1303`). | none |
| P1-7 | RESOLVED | Mutation checks active UoW and non-empty events before CAS (`events/unit_of_work.py:271-276, 579-589`; `ports/unit_of_work.py:188-196`). | none |
| P1-8 | REMAINS | Repository mutators reject illegal terminal and inbox transitions; repository tests pass. | Public `OutboxDispatcher.acknowledge_one` invokes the handler and records the inbox result before `mark_completed` rejects a supplied `PENDING` message, leaving the outbox pending with a persisted inbox result. |
| P2-1 | SCOPED | Inbox docs explicitly state at-least-once handler execution and conditional exactly-once effect (`events/inbox.py:14-19, 254-275`); crash regression observes two handler calls (`test_event_outbox_atomicity.py:1146-1175`). | none under the stated logical-key/shared-transaction precondition. |
| P2-2 | RESOLVED | Conflict test uses a get-then-record race and reaches `IDEMPOTENCY_CONFLICT` (`test_event_outbox_atomicity.py:1028-1079`). | none |
| P3-1 | SCOPED | Restart composition uses a fresh UoW, drops the message object, and discovers through `list_dispatched` (`test_event_outbox_atomicity.py:879-937`; repository port `600-625`). | No OS-process durability is claimed or tested, consistent with the frozen Task 1.5 scope. |
| P3-2 | REMAINS | Test header and memory adapter correctly disclaim cross-process durability (`test_event_outbox_atomicity.py:15-24`; `storage/memory.py:1067-1074`). | `test_event_outbox_atomicity.py:922-923` still calls the shared in-memory state “durable repository state,” which is an inaccurate acceptance claim. |

## New Findings

- P0: none.

- P1: `UpcasterRegistry.migrate` (`events/models.py:568-576`). Counterexample: same event, same stateful upcaster, first engine succeeds with `migration_run=0`; a fresh registry/engine succeeds with `migration_run=2`. The pin must be persisted with immutable event evidence or otherwise shared across replay compositions. Decisive retest: fresh-registry replay must quarantine or prove the same migrated-payload hash.

- P1: `OutboxDispatcher.acknowledge_one` (`events/outbox.py:598-693`). Counterexample output: `RepositoryStateTransitionError`, `handler_calls 1`, `outbox_status pending`, `inbox_result` present. This permits an external effect and inbox write before rejecting an illegal lifecycle state. Smallest repair: validate the current persisted message is `DISPATCHED` before invoking the handler or writing the inbox. Decisive retest: passing `PENDING` must invoke neither handler nor inbox write.

- P2: `EventReplayEngine.reconcile_checkpoint` (`events/store.py:452-580`). A validly hashed `node.completed` event with unknown schema/upcaster produced `checkpoint_reconcile True 1`, while `replay_stream` quarantined it as `unknown_schema_version`. The method documents that callers replay separately, so severity depends on that caller discipline; nevertheless, checkpoint evidence can be accepted for an event that cannot replay. Smallest repair: validate schema/upcaster availability during reconciliation or require a successful replay result before checkpoint completion.

- P3: none beyond original P3-2.

- P4: none.

## Commands And Anchors

Executed focused test command:

```text
PYTHONPATH=services/api:packages:. python3 -m pytest -W error -p no:cacheprovider tests/protocol_v3/test_event_replay.py tests/protocol_v3/test_event_outbox_atomicity.py tests/protocol_v3/test_repository_contract.py -q
```

Observed:

```text
149 passed in 0.45s
```

Executed stdin-only probes:

```text
PYTHONPATH=services/api:packages:. python3 -
```

Observed upcaster probe:

```text
same_engine_first True {'old_revision': 1, 'migration_run': 0}
same_engine_second True nondeterministic_upcaster
fresh_engine True {'old_revision': 1, 'migration_run': 2}
shared_call_count 6
late_register RegistryFrozenError
```

Observed checkpoint probe:

```text
checkpoint_reconcile True 1
event_replay True unknown_schema_version
```

Observed public dispatcher probe:

```text
acknowledge_exception RepositoryStateTransitionError
handler_calls 1
outbox_status pending
inbox_result rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr
```

Static source reads confirmed the cited symbols and line anchors. The first upcaster probe wrapper had a harness-only `ReplayOutcome.is_success` attribute error; the corrected stdin probe above was rerun successfully.

## Boundary Check

No files were edited or written through tools. No report path was written. Only the three permitted focused test files were executed. No services, packages, network, browser, production/runtime data, security/adversarial/hygiene tests, source-baseline tests, logs/reports, or medical-monitoring files were accessed. Ephemeral probes used standard input and left no workspace artifacts.

## Next Step

Codex may not accept Task 1.5 now. The fresh-replay nondeterminism pin, late public outbox lifecycle rejection, and inaccurate durability wording remain unresolved.
