You are continuing the SAME isolated Protocol v3 Task 1.5 acceptance session for the final bounded repair review. Do not restart the audit, inspect worker reports, or edit files. Reinspect only the current source/tests named below and decide whether every Round 2 remaining/new finding is now resolved. Preserve the original findings table, but do not search for unrelated later-phase work.

Read these files only:
- `AGENTS.md`
- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.5 and adjacent Phase 1 boundaries
- `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, section 18
- `packages/contracts/workbench_contracts/protocol_v3.py`, `DomainEvent` only
- `services/api/app/protocol_workflow/events/`
- `services/api/app/protocol_workflow/ports/repositories.py`
- `services/api/app/protocol_workflow/ports/unit_of_work.py`
- `services/api/app/protocol_workflow/storage/memory.py`
- `services/api/app/protocol_workflow/canonical/study_definition.py`
- `services/api/app/protocol_workflow/canonical/document.py`
- `tests/protocol_v3/test_event_replay.py`
- `tests/protocol_v3/test_event_outbox_atomicity.py`
- `tests/protocol_v3/test_repository_contract.py`

Write exactly one output file: `runs/conference/mw_protocol_v3_phase1_task15_acceptance_20260810/codex_luna_acceptance_round3.md`
The runner owns that path. Never write it through tools; return the report.

Hard boundaries are unchanged: read-only; no service/network/browser/package install; no directory-wide, source-baseline, security, adversarial or hygiene tests; no medical-monitoring reads. You may run only the three named focused test files or narrower tests using `PYTHONPATH=services/api:packages:.`, `-W error`, `-p no:cacheprovider`. Ephemeral stdin counterexamples are allowed and must leave no workspace artifact.

Round 2 repairs to challenge with the exact counterexamples:
1. Cross-composition migration identity: `DomainEvent.migrated_payload_sha256` is now part of the immutable event envelope hash. Every registered legacy upcaster must produce exactly that canonical migrated-payload hash. A legacy event without it fails closed. Re-run the pairwise-equal stateful upcaster against a fresh registry/engine; it must quarantine even though the new registry has no process-local observations.
2. Public outbox lifecycle: `OutboxDispatcher.acknowledge_one` first resolves the authoritative message through `OutboxRepository.get`, requires persisted status `DISPATCHED`, and then uses the persisted object. Passing a PENDING message must invoke neither handler nor inbox write and must leave the outbox PENDING.
3. Checkpoint replayability: `reconcile_checkpoint` now verifies the backing event through the closed upcaster registry before accepting it. A correctly hashed and registered `node.completed` event with unknown schema/upcaster, missing immutable migration evidence, or nondeterministic migration must not prove checkpoint completion.
4. Scope wording: the restart test now calls the shared in-memory repository state `shared repository state`, while module/test documentation explicitly says this is only port/composition-level restart evidence and does not prove OS-process durability.

Main-venue anchors already observed after the repair, which you must independently reproduce or challenge rather than trust:
- three focused files: `151 passed`
- Task 1.1-1.5 nine functional files: `372 passed`
- ruff check and ruff format check on the 13 changed functional files: pass
- memory compilation of the 13 files and `git diff --check`: pass

Scope decision remains: Task 1.5 creates storage-agnostic event/outbox/inbox modules and uses the Task 1.3 in-memory reference adapter. It does not create a SQLite/PostgreSQL durable adapter. Judge restart discovery at repository-port/composition level and reject any current claim of OS-process durability; do not require an out-of-scope durable adapter.

Return exactly:
# Independent Acceptance Round 3: Protocol v3 Task 1.5
## Verdict
`READY` or `NOT_READY`
## Findings Disposition
One row for the three substantive Round 2 defects and the P3 wording issue: RESOLVED/REMAINS/SCOPED, current evidence, exact remaining defect. Then state whether any original finding regressed.
## New Findings
P0-P4 with exact source/symbol and counterexample; write `none` for empty severities.
## Commands And Anchors
Exact executed commands/results and counterexample outputs.
## Boundary Check
## Next Step
State whether Codex may accept Task 1.5 now. No later-phase proposal.
