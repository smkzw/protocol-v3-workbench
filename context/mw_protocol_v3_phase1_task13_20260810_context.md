# Task Context: mw_protocol_v3_phase1_task13_20260810

Created: 2026-08-10 11:50:05
Objective: 按批准计划实现 Protocol v3 repository、artifact 与 unit-of-work ports 及内存/本地实现，证明幂等内容寻址与 CAS，不开展安全性测试
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `cms-smk` / `cms-model` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Frozen implementation plan SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, Task 1.3.
- Approved design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, Sections 6, 18 and 19.
- Task 1.1 contracts at commit `2817687` and Task 1.2 stable errors at commit `76c0b78`.
- Current filesystem, focused functional tests and runner-owned reports under `runs/execution/mw_protocol_v3_phase1_task13_20260810/`.

## Scope

- In scope: storage-agnostic repository/artifact/UoW ports; in-memory repositories/UoW; local content-addressed artifact store; functional contract tests; precise Git visibility and immutable-plan restoration.
- Out of scope: services/runtime startup, legacy medical-writing integration, OCR/translation/model calls, medical-monitoring files, production data, and every security/adversarial/permission/path/malicious-input test.

## Success Criteria

- CAS, append ordering, project isolation, idempotent outbox/inbox/reservation and commit/rollback are deterministic.
- Identical artifact bytes replay without revision growth; changed bytes retain prior immutable revisions; hash lookup is order-independent across memory/local adapters.
- Replayed or closed UoW handles cannot write after commit/rollback, while reads remain inspectable.
- Agent/harness contracts never carry repository, artifact-store or UoW handles.
- Focused tests, compilation, formatting, diff checks, Git visibility and plan hash pass; medical-monitoring remains unchanged.

## Risk Boundaries

- Do not write to production paths until Codex review gate passes and writable paths are explicit.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-10 11:50:05: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-10: Three serial execution workers and one Cursor manager implemented/reviewed the bounded surfaces. Same-session repair passes closed reservation project isolation.
- 2026-08-10: Codex restored the immutable plan content, made the local artifact adapter Git-visible, hardened deterministic hash lookup and thread replay, and added shared UoW mutation closure.
- 2026-08-10: First fresh Luna verifier (`019fea0c-d72e-7d41-b020-eec9da28d7c5`) vetoed three P1 defects: insertion-order hash binding, reservation identity collision across projects, and stale pre-obtained UoW mutators.
- 2026-08-10: All three P1 root causes were repaired and regression tests added. Second fresh Luna verifier (`019fea1d-25df-7982-8df6-9a914d4b5615`) returned `READY`; P0/P1/P3/P4 none. Its only P2 was a read-only sandbox temp-directory limitation, not an assertion failure.
- 2026-08-10: Codex writable-environment focused suite passed `151`; Ruff check/format, compilation, diff check, plan SHA and Git visibility passed. Task 1.3 accepted; future two-round P0-P4 clearance remains a later phase gate.
