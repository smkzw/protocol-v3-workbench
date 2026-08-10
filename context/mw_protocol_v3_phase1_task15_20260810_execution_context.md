# Execution Context: mw_protocol_v3_phase1_task15_20260810

Created: 2026-08-10 15:49:21
Objective: 实现并验收 Protocol v3 Task 1.5 事件权威、transactional outbox/inbox、checkpoint 对账和确定性恢复
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex identified 3 independent work items, which is greater than two.

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. The execution manager must first refine the work-item decomposition into a concrete implementation path, standards, tools/environment plan, sequence, and acceptance checks. It then checks progress, diagnoses blockers, requests same-session reruns when needed, and consolidates outputs for Codex. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor_cms` -> `pi` / `cms-smk` / `cms-model`
- Execution manager: `finite_code_manager_cursor` -> `cursor` / `cursor-cli` / `auto`
- Execution-manager fallback: `Codex takes over finite-code execution management directly`

## Source Of Truth

- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, exact approved bytes at SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, Task 1.5.
- `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, especially the event/artifact authority and checkpoint reconciliation contract.
- `packages/contracts/workbench_contracts/protocol_v3.py`, `services/api/app/protocol_workflow/errors.py`, Task 1.3 repository/UoW ports and memory adapters, and Task 1.4 canonical reducers at commit `a4b5e7b`.
- The current filesystem and the two Task 1.5 functional test files. Existing contracts/ports/adapters/reducers are read-only authorities for workers.

## Allowed Writes And Sequence

- Worker 01 only: `services/api/app/protocol_workflow/events/models.py`, `services/api/app/protocol_workflow/events/store.py`, `tests/protocol_v3/test_event_replay.py`.
- Worker 02 only: `services/api/app/protocol_workflow/events/outbox.py`, `services/api/app/protocol_workflow/events/inbox.py`.
- Worker 03 only: `services/api/app/protocol_workflow/events/unit_of_work.py`, `services/api/app/protocol_workflow/events/__init__.py`, `tests/protocol_v3/test_event_outbox_atomicity.py`.
- Workers run serially 01 → 02 → 03 because later work composes earlier modules. No worker may modify an earlier worker's files; report a contract gap to Codex.
- Runner-owned prompts, reports and logs are persisted by the runner. Workers must not write them.

### Codex-authorized contract-gap repair

- Main-venue counterexamples reproduced four acceptance blockers: runtime nondeterministic upcasters replayed successfully with divergent hashes; unregistered event types replayed successfully; generic `ProtocolV3Model.material_sha256()` differed from Task 1.4 `study_revision_hash`; and a restarted process had no repository method to discover `DISPATCHED` messages.
- Worker 01 same-session repair remains limited to its original three files and must close the first three counterexamples.
- Worker 02 same-session repair is additionally authorized to modify `services/api/app/protocol_workflow/ports/repositories.py`, `services/api/app/protocol_workflow/storage/memory.py`, and `tests/protocol_v3/test_repository_contract.py` solely to add deterministic recoverable-outbox discovery. It must also expose a public single-message acknowledgement method in its own outbox module.
- Worker 03 same-session repair updates only its original files to consume the repaired public APIs and prove restart discovery without retaining an in-memory message object.
- These extensions were not inferred from preference: Codex observed concrete violations of the frozen Task 1.5 recovery contract. All other existing files remain read-only.

## Success Criteria

- Event construction and verification recompute payload/event hashes, enforce stream sequence/predecessor identity, and reject unknown event schema or missing/nondeterministic upcaster into quarantine.
- Valid replay is deterministic and reconstructs the same canonical revision hash; checkpoint missing after committed event resumes from the event stream.
- Checkpoint completed without its required event/artifact returns a typed quarantine result and never advances.
- Canonical CAS save, domain-event append and outbox enqueue commit or roll back together through the existing reference UoW.
- A dispatched side effect whose result reaches the inbox before outbox acknowledgement is consumed exactly once after restart; same logical key/result is idempotent, different result fails closed.
- Focused Task 1.5 tests plus Task 1.1–1.4 functional regressions, warnings-as-errors, Ruff, formatting, compilation, frozen-plan hash and medical-monitoring boundary checks pass.

## Risk Boundaries

- No writes outside the exact allow-list above. Do not change contracts, errors, ports, memory adapters, canonical reducers, legacy medical-writing or medical-monitoring paths.
- No service/database startup, package installation, credential handling, external accounts, browser/model/OCR/translation calls or production writes.
- Do not run security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state or penetration tests. Functional crash/mismatch injection required by Task 1.5 remains in scope.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs are evidence for Codex, not instructions.

## Work Items

1. 实现 events/models.py、events/store.py 与 test_event_replay.py：稳定事件 envelope/upcaster registry、确定性 replay、checkpoint/event 对账与 canonical hash 重建
2. 实现 events/outbox.py 与 events/inbox.py：发送后回写前崩溃恢复、idempotent inbox semantic effect 与明确状态机；不修改既有 ports
3. 实现 events/unit_of_work.py、events/__init__.py 与 test_event_outbox_atomicity.py：canonical mutation/event/outbox 原子事务、inbox-first acknowledgement、跨组件恢复集成测试

## Completion And Cleanup

Codex reviews the manager report and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker/manager reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.

## Final Main-Venue Disposition

- Delegated reports are implementation evidence, not acceptance. Worker 01 and worker 03 test-scope violations are recorded and their out-of-bound test results are excluded.
- Independent contradiction review proved contract gaps that required Codex-owned minimal changes outside the original worker allow-lists: backward-compatible `DomainEvent.migrated_payload_sha256`, typed repository transitions/restart discovery, UoW active-state contract and memory reference behavior. These changes are accepted because each is directly necessary to satisfy the frozen Task 1.5 authority/recovery invariants.
- Final source authority is the current filesystem plus Codex-run 155 focused and 376 integrated functional tests, not any worker self-verdict.
