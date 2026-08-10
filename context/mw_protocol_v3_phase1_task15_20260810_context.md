# Task Context: mw_protocol_v3_phase1_task15_20260810

Created: 2026-08-10 15:48:28
Objective: 按冻结计划 Task 1.5 实现 domain event、transactional outbox/inbox、checkpoint/event 崩溃恢复与确定性 replay；保护医学监查并且不运行安全性测试
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `cms-smk` / `cms-model` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Frozen plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md` at SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, Task 1.5.
- Approved design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, especially the authority/recovery contract: events plus immutable artifacts are business truth; checkpoints are execution position only.
- Task 1.1 contracts in `packages/contracts/workbench_contracts/protocol_v3.py`, Task 1.2 stable errors, Task 1.3 repository/UoW ports and memory adapters, and Task 1.4 canonical reducers at commit `a4b5e7b`.
- Current filesystem and focused Task 1.5 functional tests are implementation truth.

## Scope

- In scope: immutable event envelope helpers, event schema/upcaster registry, deterministic event replay, checkpoint/event reconciliation, transactional canonical-event-outbox application boundary, outbox dispatch/inbox consumption coordination, and focused functional tests.
- Out of scope: database vendor adapters, LangGraph selection, workflow graph, reservations (Task 1.6), role/harness registry, API/UI, legacy medical-writing integration, service startup, OCR/translation/model calls, and all medical-monitoring files.

## Success Criteria

- A committed event with a missing checkpoint resumes by deterministic event replay and does not reapply an already recorded semantic effect.
- A checkpoint that claims completion without its required event/artifact is quarantined with the stable checkpoint/event mismatch error; it never advances the workflow.
- Canonical mutation, domain-event append and outbox enqueue commit or roll back together in the in-memory reference UoW.
- Dispatch completion is recorded through an idempotent inbox key before the outbox completion acknowledgement; a crash after external dispatch but before acknowledgement cannot duplicate the semantic effect on restart.
- Unknown event type/schema or missing/nondeterministic upcaster fails closed into quarantine; no guessed replay.
- Replaying a valid event stream reconstructs the same canonical revision hash as the original projection.
- Task 1.5 tests plus focused Task 1.1–1.4 regressions, Ruff, compilation, formatting, frozen-plan hash, diff and medical-monitoring boundary checks pass.

## Risk Boundaries

- Authorized product writes are limited to `services/api/app/protocol_workflow/events/{models,store,outbox,inbox,unit_of_work}.py` and an `events/__init__.py` export surface if needed.
- Authorized tests are limited to `tests/protocol_v3/test_event_outbox_atomicity.py` and `tests/protocol_v3/test_event_replay.py`.
- Existing contracts, stable errors, ports, memory adapters and canonical reducers are read-only authority for delegated workers. Any proven contract gap must be reported to Codex before widening writes.
- Do not run services, databases, browsers, OCR, translation or model runtimes. Do not run security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state or penetration tests; functional injected crash/mismatch cases required by Task 1.5 remain in scope.
- No medical-monitoring or legacy medical-writing path may be modified.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-10 15:48:28: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-10: External solution discovery was not reopened because the approved design and frozen implementation plan already fixed this bounded event/outbox method, and no material assumption changed.
- 2026-08-10: Initial inspection confirmed Task 1.3 already provides storage-agnostic event/outbox/inbox/UoW ports and in-memory repositories; Task 1.5 must compose and verify these contracts rather than invent a second persistence authority.
- 2026-08-10: Delegated execution created the event/replay, outbox/inbox and UoW composition surfaces. Worker 01 and worker 03 each crossed the declared test boundary during exploration; those broad/directory-wide results are excluded from acceptance. Their source changes were independently inspected and re-tested by Codex.
- 2026-08-10: Main-venue counterexamples required bounded contract repairs in `DomainEvent`, repository/UoW ports and the memory adapter. The immutable event now binds `migrated_payload_sha256`; replay/checkpoint use closed registries, exact stream/event/artifact/node identity and Task 1.4 authoritative revision hashes; public outbox acknowledgement verifies persisted lifecycle before side effects.
- 2026-08-10: Initial isolated Luna acceptance returned `NOT_READY` (8 P1, 2 P2, 2 P3). Two same-session repair reviews narrowed the final defect to checkpoint prefix replayability. Complete-prefix double replay then closed unknown-schema predecessor and pairwise-stateful upcaster counterexamples.
- 2026-08-10: Final panel found and closed a P3 recovery-taxonomy defect (`DISPATCHED` with no handler was misclassified as failed) and a P4 stale docstring. `DEFERRED_NO_HANDLER` now remains recoverable and is tested through both direct dispatch and recovery.
- 2026-08-10: Accepted evidence: 2 targeted tests, 155 Task 1.5 tests and 376 Task 1.1–1.5 functional tests pass with warnings as errors and no pytest cache; Ruff check/format, in-memory compilation and `git diff --check` pass; frozen plan hash is unchanged; medical-monitoring diff count is zero. Final isolated Cursor fallback verdict is `READY`, with no open P0–P4.
