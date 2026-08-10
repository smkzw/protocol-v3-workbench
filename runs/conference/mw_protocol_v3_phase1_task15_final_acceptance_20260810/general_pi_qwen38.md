All evidence gathered. Let me compile the final report.

---

# Conference Participant Output: mw_protocol_v3_phase1_task15_final_acceptance_20260810 - general_pi_qwen38

## Boundary Check

**Role:** `general_pi_qwen38` / `pi` / `cms-smk` / `cms-model` (effective daytime route replacing `qwen3.8-max`).
**Scope:** Read-only contradiction acceptance of Task 1.5 (domain event, transactional outbox/inbox, checkpoint double-replay fix). No implementation edits, no production paths, no prior reviewer/worker output consulted.
**Read set used:** AGENTS.md, conference context, Codex main-venue plan, frozen Task 1.5 plan (`.hermes/plans/2026-08-09_020923-...`), design section 18, `packages/contracts/workbench_contracts/protocol_v3.py` DomainEvent, `services/api/app/protocol_workflow/events/{models,store,outbox,inbox,unit_of_work}.py`, `services/api/app/protocol_workflow/storage/memory.py` (via test imports), and the three named tests.
**Tests executed:** `test_event_replay.py`, `test_event_outbox_atomicity.py`, `test_repository_contract.py` — all with `PYTHONPATH=services/api:packages:. -W error -p no:cacheprovider`.
**Boundary compliance:** Confirmed. No production paths read or modified; no implementation edits; only the three named tests or narrower subsets were run with the required flags; all probes were ephemeral stdin (no artifacts left).

## Independent Work Product

**Verdict: READY**

| # | Invariant / Counterexample | Source Location | Challenge Method | Result | Severity |
|---|---|---|---|---|---|
| 1 | **Counterexample A: unknown-schema predecessor before valid backing event** | `store.py:574-617` + `test_event_replay.py:1197-1239` | Ephemeral probe + test `test_checkpoint_rejects_unreplayable_predecessor` | First prefix replay quarantines with `CHECKPOINT_EVENT_MISMATCH` / `"cannot be replayed: unknown_schema_version"`. The double-replay at lines 580-592 catches the unreplayable predecessor before acceptance. | — (PASS) |
| 2 | **Counterexample B: pairwise-stateful upcaster whose first migrated hash matches** | `store.py:593-617` + `test_event_replay.py:1241-1287` | Ephemeral probe: upcaster returns `migration_run = calls//2`; `migrate()` calls it twice per invocation; persisted hash matches run 0. | First replay succeeds (calls 0-1 → run 0). Second replay calls 2-3 → run 1 → hash mismatch vs persisted → `NondeterministicUpcasterError` → quarantine with `"not replay-stable"`. 4 total upcaster invocations observed. | — (PASS) |
| 3 | **PENDING outbox message invokes neither handler nor inbox write** | `outbox.py:612-627` | Ephemeral probe: enqueue PENDING, call `acknowledge_one` | Raises `RepositoryStateTransitionError` before any handler call (handler.calls=0) or inbox write (inbox.get_result=None). | — (PASS) |
| 4 | **Exact event/artifact/node/stream mismatch quarantine** | `store.py:525-572` | Ephemeral probe: artifact_sha256 mismatch in backing event payload | Quarantined with `CHECKPOINT_EVENT_MISMATCH` / `"does not bind the checkpoint artifact"`. Stream mismatch quarantined with `STREAM_ID_MISMATCH`. | — (PASS) |
| 5 | **Event envelope migration identity** | `models.py:134-236` | Code audit: `compute_event_sha256` excludes only `event_sha256`+`schema_version`; binds identity, chain, schema/upcaster, payload hash, emission time. `verify_event_integrity` recomputes and compares. | No self-referential hash; chain position bound; tampered events rejected. | — (PASS) |
| 6 | **Closed event-type allow-list (no permissive default)** | `models.py:655-716` | Code audit + `test_event_replay.py:1704+` | `assert_registered` raises `UnknownEventTypeError`; unknown types quarantine with `UNKNOWN_EVENT_TYPE`. No default-open path. | — (PASS) |
| 7 | **Outbox lifecycle state machine** | `outbox.py:200-271` | Code audit: `PENDING→{DISPATCHED,FAILED}`, `DISPATCHED→{COMPLETED,FAILED}`, terminal `{COMPLETED,FAILED}`. | No backward edges; `IllegalOutboxTransitionError` on violations. Re-dispatch of DISPATCHED is not a transition (stays DISPATCHED) — correct. | — (PASS) |
| 8 | **Inbox consumer exactly-once semantic effect** | `inbox.py:254-375` | Code audit + `test_event_outbox_atomicity.py:1125+` | CONSUMED/SUPERSEDED skipped; RECEIVED→CONSUMED only; handler idempotency required; crash-window re-apply documented honestly. | — (PASS) |
| 9 | **Canonical revision hash cross-validation** | `store.py:677-696` | Code audit + `test_event_replay.py:1403-1425` | `isinstance` cross-check catches reducer returning wrong convention (`material_sha256` vs `study_revision_hash`) → `REVISION_HASH_MISMATCH` quarantine. | — (PASS) |
| 10 | **UoW atomicity (CAS→event→outbox)** | `unit_of_work.py:288-328` | Code audit + `test_event_outbox_atomicity.py:412+` | Each step wrapped in `MutationAbortedError`; failure propagates out of `with uow:` triggering rollback. No partial writes. | — (PASS) |
| 11 | **At-least-once dispatch with exactly-once semantic effect** | `outbox.py:581-711` | Code audit + `test_event_outbox_atomicity.py:666+` | Inbox-first short-circuit (skip re-dispatch if result exists); idempotency conflict → `FAILED`; ack only after inbox write durable. | — (PASS) |
| 12 | **Full test suite** | `test_event_replay.py`, `test_event_outbox_atomicity.py`, `test_repository_contract.py` | `pytest -W error -p no:cacheprovider` | **153 passed in 0.44s**, including 11 `TestCheckpointReconciliation` tests. | — (PASS) |

## Evidence And Assumptions

**Test execution (required flags):**
```
PYTHONPATH=services/api:packages:. python3 -m pytest \
  tests/protocol_v3/test_event_replay.py \
  tests/protocol_v3/test_event_outbox_atomicity.py \
  tests/protocol_v3/test_repository_contract.py \
  -q -W error -p no:cacheprovider
→ 153 passed in 0.44s
```

**Checkpoint reconciliation tests (isolation):**
```
pytest tests/protocol_v3/test_event_replay.py::TestCheckpointReconciliation -v -W error -p no:cacheprovider
→ 11 passed in 0.36s
```
Both decisive counterexamples explicitly named:
- `test_checkpoint_rejects_unreplayable_predecessor` — PASS
- `test_checkpoint_rejects_pairwise_stateful_upcaster` — PASS

**Ephemeral probe — pairwise-stateful upcaster (counterexample B):**
```
quarantined: True
reason: checkpoint_event_mismatch
detail: ...not replay-stable: nondeterministic_upcaster: ...produced migrated payload sha256=1f7f..., expected=9767...
calls total: 4
has not replay-stable: True
```
Observation: `migrate()` invokes the upcaster 2× per call (within-pair guard at `models.py:561-565`). First `replay_stream` uses calls 0-1 (both run 0, matches persisted hash). Second `replay_stream` uses calls 2-3 (both run 1, hash mismatch). This is the exact mechanism by which the double-replay defeats a pairwise-stable stateful upcaster.

**Ephemeral probe — PENDING outbox precheck:**
```
initial status: OutboxStatus.PENDING
correctly raised RepositoryStateTransitionError
handler calls: 0 (expected 0)
inbox result: None (expected None)
```

**Ephemeral probe — exact artifact mismatch:**
```
artifact mismatch quarantined: True
reason: checkpoint_event_mismatch
detail contains bind: True
```

**Ephemeral probe — nondeterministic upcaster at plain replay level:**
```
nondet replay quarantined: True
reason: nondeterministic_upcaster
```

**Ephemeral probe — stream-id binding mismatch:**
```
stream mismatch quarantined: True
reason: stream_id_mismatch
```

**Assumptions:**
- The three named tests are the complete Task 1.5 acceptance suite per the conference context (line 39).
- `services/api/app/protocol_workflow/storage/memory.py` is the in-memory reference adapter named in the source-of-truth list (context line 25); its contracts are validated by `test_repository_contract.py`.
- The `Python 3.9.6` / `pydantic 2.13` environment in the isolated workspace is the locked toolchain (no package installation was performed).

## Risks, Gaps, And Verification Needs

**No P0-P4 defect found in Task 1.5.** The following are observations, not blockers:

1. **[OBSERVATION — conservative, not a defect]** `reconcile_checkpoint` validates the *entire* event stream chain integrity (lines 497-523), not just the prefix through the backing event. If a stream has a valid prefix but a corrupted tail event *after* the backing event, checkpoint reconciliation fails. This is correct fail-closed behavior — a corrupted tail indicates stream integrity compromise — but it means checkpoint acceptance is sensitive to events that are logically unrelated to the checkpoint being reconciled. This is the safer choice; no change recommended.

2. **[OBSERVATION — design discipline, not Task 1.5 scope]** The `migrate()` within-pair determinism check (calls 1-2 per invocation) is structurally necessary for the double-replay fix to work: without it, a pairwise-stable upcaster whose first pair matches the persisted hash would pass a *single* `replay_stream` call, and only the *second* isolated `replay_stream` call would expose it. The double-replay at lines 580-617 is the authoritative guard. The within-pair check in `migrate()` alone is insufficient (it only catches intra-pair divergence, not cross-invocation statefulness). Both layers are correctly present.

3. **[OBSERVATION — out of Task 1.5 scope]** The `_observed_output_hashes` dict in `UpcasterRegistry` (line 431) is instance-local memory. Across a process restart or fresh engine construction, it resets. This is mitigated by the immutable `migrated_payload_sha256` evidence carried in each event envelope (lines 574-585), which is the authoritative cross-restart guard. The double-replay provides the within-session guard. No gap for Task 1.5.

4. **[GAP — verification limitation]** I did not exercise a PostgreSQL-backed adapter; only the in-memory reference adapter was tested. The design (section 5.2) defers storage PoC to Task 1.8, so this is correctly out of Task 1.5 scope. Codex should confirm the Task 1.8 storage PoC exercises the same invariant surface.

## Recommended Next Step

**READY — no blocking question for Codex.** Task 1.5's complete-prefix double-replay checkpoint repair correctly quarantines both decisive counterexamples (unknown-schema predecessor; pairwise-stateful upcaster). The event/outbox/inbox/UoW authority contracts show no regression across all 153 tests and 6 independent ephemeral probes. The implementation matches design section 18's split-brain reconciliation and exactly-once semantic-effect discipline.

The only forward-looking note: when Task 1.8 locks the storage adapter, confirm the PostgreSQL-backed outbox/inbox/event-stream implementations satisfy the same lifecycle, idempotency, and chain-integrity contracts that the in-memory reference adapter passes here. That is Task 1.8 scope, not a Task 1.5 deficiency.
