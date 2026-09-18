# Task Context: mw_protocol_v3_review_phaseR_20260905

Created: 2026-09-05 12:41:43
Objective: Protocol v3 工程复核与 Plan v2 Phase R 重锚定；本阶段仅确定性离线检查与授权修复，不派发模型、不启动服务，live 与 monitoring 只读。
Task type: `code_open_audit`
Risk: `high`
Selected agent route: `codex` / `codex-main` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- User request 2026-09-05: complete engineering review, cross-review, recommendations, updated plan/goal and continuous implementation. Plan v2 supersedes the old recovery-only request and Task 2.2 resume pointer.
- Read in full: global/project AGENTS, design v1.3, Plan v2, execution handoff, frozen 1940-line plan, Task 2.1 pause, P1 functional gate review. Five supplied authority hashes independently match.
- Immutable upgrade directory: ../plan-upgrade-20260905/. Current execution authority: mw_protocol_v3_implementation_plan_v2_20260905.md, SHA 040eb6ad323047737e8be6a3a23344fdb719dc85230ef7994b96c9af29257607.
- Current isolated HEAD 3d6772f, clean before task initialization, 26 commits (handoff says 25; count corrected by git rev-list --count HEAD).

## Scope

- In scope: Phase R sequential R.1 locator amendment, R.2 source-only drift reconciliation, R.3 injected occupancy probes and deterministic regression; then fresh verification and review before gated Phase 1R onward.
- Out of scope during Phase R: product service/model/OCR/translation/Word automation, cleanup, external writes, live/monitoring mutation, old record rewrites. USER CLARIFICATION 2026-09-05: the model-call ban applies only to the product under construction; engineering review subAgents may run. Independent review/verification may now be dispatched through current guard.
- Declared Phase R paths: scripts/qc/protocol_v3/build_frozen_authority_manifest.py, scripts/qc/protocol_v3/authority_locator_amendment.py (new), scripts/qc/protocol_v3/reconcile_source_drift.py (new), scripts/qc/protocol_v3/apply_repository_hygiene.py; additive config/medical_writing/protocol_v3/authority_amendment_20260905.json; tests/protocol_v3/test_authority_locator_amendment.py, test_repository_hygiene_mutator.py, test_source_drift_reconciliation.py, test_frozen_authority_manifest.py (only historical baseline locator adjustment if needed; original expected values preserved); mutable_source_baseline.json plus byte-identical historical baseline copy. New task-owned context/plans/runs/reviews/metrics/prompts only. Additional paths require an explicit recorded impact amendment before editing.

## Success Criteria

- R.1 all 13 migrated CMSS hashes match; additive new asset inventory; no historical immutable bytes change; frozen authority and new negative tests pass.
- R.2 compare live read-only and isolated source; classify monitoring/shared/v2 changes without merging; preserve old baseline and unknown-diff detection.
- R.3 zero failed Protocol v3 regression, Task 2.1 hashes retained, protected-path zero diff; no service started. H-R remains pending until fresh verification, never worker self-acceptance.
- Engineering review must distinguish current observed source/tests from plan statements; UI/runtime and clinical/export acceptance cannot be inferred from unit tests.
- Keep required design decisions visible: sqlite single writer, unknown outcome fail closed, project isolation, source authority, high-risk human decisions, <=15 key clicks, <=3 mandatory free text, >=14px body / >=12px UI. Regulatory factual assertions need primary-source verification.
- Stop at a genuine decision boundary, including Task 3R.6; preserve evidence with no-loss pause if needed.

## Risk Boundaries

- Do not write to production paths until Codex review gate passes and writable paths are explicit.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, malformed output, or a stale/incomplete catalog must be recorded and followed by one real route attempt. Explicit user-selected routes are not blocked merely because the catalog does not list them; only a missing executable or native transport boundary may stop before that attempt.

## Loop Log

- 2026-09-05 12:41:43: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- Native goal inspected: old objective remains paused; available goal API supports creation or terminal status only, not updating an unfinished objective/resuming. Do not modify runtime databases or mark old objective complete. Current user instruction and this durable execution contract control work.
- R.1 red baseline: test_frozen_authority_manifest.py = 3 failed, 12 passed in 1.82s. All failures caused by missing historical CMSS root. 13/13 relocated assets independently match. An initial shell path-substitution escaping error was corrected; it was a command error, not evidence of asset drift.
