# Execution Context: mw_protocol_v3_phase1_task14_20260810

Created: 2026-08-10 13:34:51
Objective: 实现并验收 Protocol v3 Task 1.4 canonical reducers 与 CAS，保持 StudyDefinition 唯一事实源、SemanticDocumentRevision 唯一文字工作版本
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

- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, exact approved bytes at SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, Task 1.4.
- `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, Sections 6, 10, 14 and 15.
- `packages/contracts/workbench_contracts/protocol_v3.py`, `services/api/app/protocol_workflow/errors.py`, and Task 1.3 repository/UoW ports/adapters at commit `2b530cd`.
- Current filesystem and focused functional tests. Existing canonical contracts and stable errors are read-only authority for workers.

## Allowed Writes

- Worker 01 only: `services/api/app/protocol_workflow/canonical/hashing.py`, `services/api/app/protocol_workflow/canonical/study_definition.py`, `tests/protocol_v3/test_study_definition_reducer.py`.
- Worker 02 only: `services/api/app/protocol_workflow/canonical/decisions.py`, `tests/protocol_v3/test_decision_cas.py`.
- Worker 03 only: `services/api/app/protocol_workflow/canonical/document.py`, `tests/protocol_v3/test_semantic_document_reducer.py`.
- Shared serial export surface: `services/api/app/protocol_workflow/canonical/__init__.py` may be updated by each worker only to add/remove exports for its own accepted module. This exception was authorized by Codex after the manager identified the generated allow-list omission.
- Runner-owned prompts, reports and logs are persisted by the runner. Workers must not write those paths or another worker's files.

## Success Criteria

- All reducers are deterministic and pure: no repository, filesystem, network, clock or model side effects; identity/time/expected revision are explicit inputs.
- Same decision identity/snapshot/expected revision and same payload replay the exact prior `DecisionRecord`; stale revision or conflicting payload fails with a stable typed error.
- `StudyDefinitionV3` remains the only fact authority: exact revision/CAS lineage, no lost facts, and no direct overwrite of frozen facts outside an accepted decision.
- `SemanticDocumentRevision` is a fact-revision-bound projection. Summary, SoA, tables, figures and body blocks reference exact StudyDefinition identity/hash/fact paths and cannot become a second fact store.
- The existing contract is not widened with a numeric StudyDefinition revision field in this task. Instead, `study_definition_sha256` must use one shared canonical revision hash that includes stable aggregate identity, numeric revision, predecessor hash, canonical state and material hash; it must change when revision changes even if fact material is unchanged. StudyDefinition and document predecessor hashes use the same revision-bound discipline.
- Any free-text/block edit touching or possibly touching protected facts returns a typed fact proposal and does not silently create a document revision.
- The three Task 1.4 tests plus Task 1.1–1.3 focused regressions, compilation, Ruff and diff checks pass. No medical-monitoring path changes.

## Risk Boundaries

- No production/runtime writes, service startup, package installation, credential handling, browser/model/OCR/translation calls or external account changes.
- Do not edit existing contracts, error registry, repositories/storage, legacy medical-writing or medical-monitoring paths. Report a contract gap rather than widening the write set.
- Do not run security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state or penetration tests. Functional invalid-state/CAS tests required by Task 1.4 remain in scope.
- Workers run serially in dependency order 01 → 02 → 03. Launch once and use long waits; latency is not fallback authority.
- Missing tools or environments must be recorded with the smallest remediation proposal. Worker and manager outputs are evidence for Codex, not final acceptance.

## Work Items

1. 实现 canonical hashing 与 StudyDefinition 纯 reducer/CAS，新增 test_study_definition_reducer.py
2. 实现 DecisionRecord 幂等/CAS reducer，新增 test_decision_cas.py
3. 实现 SemanticDocument 纯 reducer、fact revision 绑定和 typed fact proposal，新增 test_semantic_document_reducer.py

## Completion And Cleanup

Codex reviews the manager report and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker/manager reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.

## Completion Record

- Initial manager verdict: `NEEDS_RERUN`; worker green tests were not accepted as proof.
- Codex remediation closed CAS identity/payload, replay lineage, frozen-`None`, deep immutability and revision-bound document projection gaps.
- Independent Luna round 1 vetoed; same-session round 2 returned `READY` after all counterexamples passed.
- Final acceptance requires the recorded integrated functional suite, Ruff/format/compile/hash/diff/boundary checks and execution archival. No security tests or runtime/service work are part of this task.
