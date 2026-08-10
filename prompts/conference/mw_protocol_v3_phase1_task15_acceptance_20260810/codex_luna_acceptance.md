You are the isolated independent verifier for Protocol v3 Phase 1 Task 1.5. Use a fresh context. You may use read-only shell/file tools and run only the focused functional tests listed below. Do not edit any file.

Work only inside the current workspace root supplied by the runner.

Read these files only:
1. `AGENTS.md`
2. `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.5 and its adjacent Phase 1 contracts
3. `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, section 18
4. Current source under `services/api/app/protocol_workflow/events/`
5. `services/api/app/protocol_workflow/ports/repositories.py`
6. `services/api/app/protocol_workflow/storage/memory.py`
7. Task 1.4 canonical hashing/reducers needed to verify replay identity
8. `tests/protocol_v3/test_event_replay.py`, `tests/protocol_v3/test_event_outbox_atomicity.py`, `tests/protocol_v3/test_repository_contract.py`

Write exactly one output file: `runs/conference/mw_protocol_v3_phase1_task15_acceptance_20260810/codex_luna_acceptance.md`
The runner owns that path. Never write it through tools; return the complete report and let the runner persist it.

Isolation rule: do not read `runs/`, `logs/`, `reviews/`, `metrics/`, worker reports, manager reports, prior Codex conclusions, or other conference participant output. Grade the current files, not their authors' claims.

Hard boundaries:
- Read-only. No source/test/report edits.
- Do not start services, install packages, access production/runtime data, use network/browser, or run security/adversarial/hygiene/source-baseline tests.
- Do not run a directory-wide test suite. You may run only the three named test files above or narrower individual tests, with `PYTHONPATH=services/api:packages:.`, `-W error`, and `-p no:cacheprovider`.
- Do not inspect or alter any medical-monitoring file.

Acceptance contract to challenge, not merely confirm:
1. Domain events and immutable artifacts are business truth; checkpoints are only execution location.
2. Event envelope/payload/chain integrity and schema evolution fail closed. Unknown event types and unknown versions/upcasters cannot enter a successful replay.
3. A nondeterministic upcaster cannot silently replay the same persisted event into different materialized state. Assess both the practical runtime guard and whether mutable registries can invalidate an already-constructed engine's closed-world assumptions.
4. Successful replay of StudyDefinition or SemanticDocument returns the exact authoritative Task 1.4 revision hash, not a convenient generic material hash.
5. If event committed but checkpoint did not, event replay reconstructs truth. If checkpoint claims state without the matching event/artifact, or sequence/hash directions disagree, quarantine/fail closed; no silent checkpoint advance.
6. CAS save + domain event append + outbox enqueue are atomic under the documented unit-of-work usage. Challenge whether callers can accidentally bypass the required context and whether the API makes that contract explicit.
7. A fresh process can discover durable DISPATCHED messages from the repository and recover them without retaining pre-crash Python objects. Recovery must not duplicate remote calls when an inbox result already exists.
8. Inbox idempotency semantics are honest. Explicitly analyze the crash window after a semantic handler effect but before `mark_consumed`. If the implementation cannot guarantee exactly-once without a transaction spanning the business mutation or a caller-provided idempotency key/handler, treat any unconditional exactly-once claim as a defect and state the smallest acceptable repair.
9. Composition uses public APIs; idempotency-key conflicts fail closed; repeated retry/restart does not create duplicate records.
10. Tests exercise the real contracts rather than only in-memory object reuse or tautological helpers.

You may create ephemeral snippets only through standard input to `python3 -` and must leave no workspace artifact. Try concrete counterexamples for any plausible defect. Rerun the permitted focused tests as an anchor.

Return exactly:
# Independent Acceptance: Protocol v3 Task 1.5
## Verdict
`READY` or `NOT_READY`
## Findings
For every P0-P4 finding: severity, exact file/line or symbol, reproduced observation, why it violates the frozen contract, smallest repair, and decisive retest. Write `none` for severities with no findings.
## Contract Matrix
One row for each of the ten contracts above: PASS/FAIL/PARTIAL, evidence, uncertainty.
## Commands And Anchors
Exact commands and observed results. Distinguish executed evidence from inference.
## Boundary Check
Confirm no edits, prohibited tests, services, installs, network, security work, or medical-monitoring access.
## Next Step
State whether Codex may accept Task 1.5. Do not propose later-phase implementation.
