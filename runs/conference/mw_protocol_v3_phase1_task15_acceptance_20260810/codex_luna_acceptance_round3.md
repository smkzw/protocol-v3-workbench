# Independent Acceptance Round 3: Protocol v3 Task 1.5
## Verdict
`NOT_READY`

## Findings Disposition

| Round 2 item | Disposition | Current evidence | Exact remaining defect |
|---|---|---|---|
| Cross-composition migration identity | RESOLVED | `DomainEvent.migrated_payload_sha256` is included in the envelope hash (`protocol_v3.py:1004-1020`; `events/models.py:171-186`). Fresh-registry replay now quarantines on hash mismatch. | none |
| Public outbox lifecycle | RESOLVED | `acknowledge_one` resolves persisted state and requires `DISPATCHED` before handler/inbox access (`events/outbox.py:612-627`). Probe confirmed zero handler calls, no inbox result, and `PENDING` remains. | none |
| Checkpoint replayability | REMAINS | Unknown schema and missing migration evidence now quarantine. However, a pairwise-equal stateful upcaster with a matching first migrated hash lets `reconcile_checkpoint` succeed; a later replay quarantines. A stream with an unknown-schema prefix also reconciles successfully because only the backing event is migrated. | Checkpoint reconciliation does not prove full-stream replayability or detect pairwise stateful drift before accepting completion evidence. |
| P3 scope wording | RESOLVED | Restart test now says “shared repository state” (`test_event_outbox_atomicity.py:961-962`); surrounding documentation explicitly disclaims cross-process durability (`:179-187`, `storage/memory.py:1067-1074`). | none |

No original finding regressed. The previously repaired migration envelope, public outbox guard, repository contracts, canonical hashes, inbox semantics, and stream binding remain covered by the focused suite.

## New Findings

- P0: none.

- P1: none.

- P2: `EventReplayEngine.reconcile_checkpoint` (`events/store.py:485-585`).

  Counterexamples:

  ```text
  pairwise_checkpoint_success True
  later_replay True nondeterministic_upcaster
  pairwise_calls 4
  ```

  The checkpoint path invokes the pairwise-equal migration once and accepts the matching immutable hash. A later replay produces a different migration result and quarantines.

  ```text
  checkpoint_with_unknown_prefix True
  full_replay True unknown_schema_version
  ```

  An unknown-schema predecessor is chain- and envelope-valid, but checkpoint reconciliation migrates only the backing event and still returns success.

  Smallest repair: validate every event in the checkpoint evidence prefix through the closed event/upcaster/replay contract, and require a stability check that rejects pairwise stateful migrations before checkpoint success. Decisive retest: both counterexamples must return checkpoint quarantine.

- P3: none.

- P4: none.

## Commands And Anchors

Focused functional command:

```text
PYTHONPATH=services/api:packages:. python3 -m pytest -W error -p no:cacheprovider tests/protocol_v3/test_event_replay.py tests/protocol_v3/test_event_outbox_atomicity.py tests/protocol_v3/test_repository_contract.py -q
```

Observed:

```text
151 passed in 0.42s
```

Fresh-registry migration probe:

```text
first True {'old_revision': 1, 'migration_run': 0}
fresh True nondeterministic_upcaster
missing_evidence True nondeterministic_upcaster
event_hash_binds_migration True
```

PENDING outbox probe:

```text
exception RepositoryStateTransitionError
handler_calls 0
inbox_present False
outbox_status pending
```

Checkpoint probes:

```text
pairwise_checkpoint_success True
later_replay True nondeterministic_upcaster
pairwise_calls 4
missing_evidence_checkpoint True checkpoint_event_mismatch
unknown_schema_checkpoint True checkpoint_event_mismatch
checkpoint_with_unknown_prefix True
full_replay True unknown_schema_version
```

The nine-file `372 passed`, Ruff, format, compilation, and `git diff --check` anchors were not executed because this isolated venue permits only the three named focused test files or narrower tests.

## Boundary Check

No files were edited or written through tools. The runner-owned report path was not touched. No services, packages, network, browser, worker reports, runtime data, prohibited tests, or medical-monitoring files were accessed. All counterexamples used standard input and left no workspace artifacts.

## Next Step

Codex may not accept Task 1.5 yet. Checkpoint reconciliation remains insufficiently fail-closed for pairwise stateful migrations and unreplayable predecessor events.
