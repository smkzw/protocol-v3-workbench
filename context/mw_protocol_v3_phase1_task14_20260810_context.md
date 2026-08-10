# Task Context: mw_protocol_v3_phase1_task14_20260810

Created: 2026-08-10 13:33:48
Objective: 按批准计划实现 Protocol v3 canonical reducers 与 CAS，使 StudyDefinition v3 成为唯一事实源、SemanticDocumentRevision 成为唯一文字结构版式工作版本，并以纯 reducer 与功能测试证明重放、stale、冻结事实和 fact proposal 纪律；不开展安全性测试
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `cms-smk` / `cms-model` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Frozen plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md` at SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, Task 1.4.
- Approved design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, especially Sections 6, 10, 14 and 15.
- Canonical value contracts `packages/contracts/workbench_contracts/protocol_v3.py` at Task 1.1 commit `2817687`.
- Stable error registry `services/api/app/protocol_workflow/errors.py` at Task 1.2 commit `76c0b78`.
- Repository/UoW ports and memory adapters at Task 1.3 commit `2b530cd`.
- Current filesystem and the three new Task 1.4 functional test files are implementation truth.

## Scope

- In scope: pure canonical hashing, StudyDefinition reducer, decision CAS reducer, SemanticDocument reducer, typed fact proposal for protected-fact edits, and focused functional tests.
- Out of scope: repository/storage changes, domain-event/outbox implementation (Task 1.5), workflow graph, services/runtime/API/UI, OCR/translation/model calls, legacy medical-writing integration and medical-monitoring files.

## Success Criteria

- Reducers are deterministic pure functions: no repository, clock, filesystem, network or model side effects; callers pass all identities, timestamps and expected revisions explicitly.
- Same `decision_id + snapshot_sha256 + expected_state_revision` and same payload replays the original DecisionRecord; stale revisions and same identity with conflicting payload fail with stable typed errors.
- StudyDefinition revisions use exact CAS lineage, do not lose prior facts, and cannot silently replace frozen confirmed facts; accepted decisions are the only fact-mutation authority.
- SemanticDocumentRevision remains a projection bound to one exact StudyDefinition revision/hash. Summary, SoA, tables, figures and body blocks reference fact paths/revision instead of becoming a second fact authority.
- Free-text or block edits that may alter protected facts return a typed fact proposal and do not silently commit a document revision.
- The three Task 1.4 test files plus Task 1.1–1.3 focused regressions, compilation, formatting and diff checks pass; no medical-monitoring path changes.

## Risk Boundaries

- Authorized product writes are limited to `services/api/app/protocol_workflow/canonical/{hashing,study_definition,decisions,document}.py`.
- Authorized tests are limited to `tests/protocol_v3/test_{study_definition_reducer,semantic_document_reducer,decision_cas}.py`.
- Do not modify existing contracts, errors, repositories, storage adapters, legacy medical-writing or medical-monitoring paths. Propose a contract gap to Codex instead of broadening writes.
- Do not run services or any security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state or penetration test.
- The delegated agents are not final authority; Codex owns verification and acceptance. Execution is serial in dependency order; no fallback for latency.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-10 13:33:48: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-10: External solution discovery was not reopened because the approved design and frozen implementation plan already settled this bounded canonical-kernel method and no material assumption changed.
- 2026-08-10: The execution manager rejected worker self-completion and supplied concrete replay/CAS/immutability counterexamples. Codex repaired the minimal implementation surfaces.
- 2026-08-10: Independent Luna round 1 reproduced three P1 and one P2 defect and additionally exposed shallow-frozen StudyDefinition facts. Codex widened the product write boundary only to `packages/contracts/workbench_contracts/protocol_v3.py` to make contract-owned values deeply immutable while preserving the schema.
- 2026-08-10: The same Luna session repeated the original counterexamples after repair and returned `READY`, P0–P4 all none. Main-venue integrated functional regression reached `279 passed` with warnings-as-errors; Task 1.4 is ready for final archival/commit.
