# Task Context: mw_protocol_v3_phase1_task12_20260810

Created: 2026-08-10 11:33:19
Objective: 按批准计划实现 Protocol v3 稳定错误码、typed exception 与用户可解释失败合同，不开展安全性测试
Task type: `code_scoped_patch_plan`
Risk: `high`
Selected agent route: `codex` / `codex-main` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Approved implementation plan: `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.2.
- Approved design: `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, especially Sections 17–19.
- Task 1.1 canonical contracts at commit `2817687`; the new error contract must remain independent of legacy medical-writing services.
- Current repository and focused functional tests are implementation truth. Global and repository `AGENTS.md` govern execution; the user explicitly stopped all security testing.

## Scope

- In scope: create `services/api/app/protocol_workflow/errors.py`, define stable code parsing/registry/typed exception/public payload behavior, and add `tests/protocol_v3/test_error_codes.py`.
- Allowed product writes: only the two Task 1.2 files above plus minimal package markers if importability requires them. Task records may be written under this task's `context/`, `runs/`, `reviews/`, `metrics/`, and `prompts/` paths.
- Out of scope: repositories, reducers, API routes, frontend, workflow execution, runtime/model calls, OCR/translation, legacy error rewrites, and all medical-monitoring files.
- Out of scope: security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state and penetration testing.

## Success Criteria

- `MW-PRO-<GATE>-<OBJECT>-<CAUSE>` codes parse deterministically and round-trip to the canonical string.
- A finite catalog covers Phase 0–8 gates and the approved E0/E1/E2/E3/D1/W1/Q1/F1, CAS, STALE, UNKNOWN_OUTCOME, CHECKPOINT_EVENT_MISMATCH and WORD_RECEIPT_STALE causes.
- Every catalog definition declares owner, retryability, recovery action and native-Chinese public message.
- Typed exceptions retain code, object identity, owner, retryability, attempt and audit detail without placing audit detail in the public payload.
- Functional tests prove unknown codes and incomplete runtime failure identity are rejected, and public messages contain no paths, prompts, credentials, backend/log labels or raw audit details.
- Focused tests, compilation, diff check and medical-monitoring boundary check pass.

## Risk Boundaries

- Do not import the new module into legacy APIs in this task.
- Do not let exception `str()` or public payload expose audit detail by default; audit serialization is explicit and separate.
- Do not create free-text or dynamically registered error codes; the finite registry is the Phase 1.2 authority.
- Do not start services or invoke external AI/OCR/translation runtimes.
- Do not perform any security testing; validation is limited to functional error contracts and user-facing message behavior.
- Codex owns final diff, tests and medical-monitoring-boundary acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-10 11:33:19: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-10: Re-anchored against the approved Task 1.2 and design Sections 17–19. Existing legacy errors are inconsistent free-text exceptions; Task 1.2 therefore remains an isolated Protocol v3 module and does not rewrite legacy service behavior.
- 2026-08-10: Implemented a finite 32-code registry covering phases 0–8 and E0/E1/E2/E3/D1/W1/Q1/F1, including exact CAS, STALE, UNKNOWN_OUTCOME, CHECKPOINT_EVENT_MISMATCH and WORD_RECEIPT_STALE causes. Public Chinese content and complete audit context have separate serializers.
- 2026-08-10: Focused functional tests passed 25/25. They cover parser/registry closure, missing runtime identity, owner/retryability consistency, public/audit separation, native-Chinese copy registration, and post-construction immutability. Compilation and `git diff --check` passed. No service, OCR, translation, browser or security test was run.
- 2026-08-10: Native Luna was already explicitly rejected by the current App session during the immediately preceding Task 1.1 acceptance. Per global policy, the independent review used the CLI compatibility route with `gpt-5.6-luna:max`, session `019fe9c0-5888-7953-9ee7-eb7ec79ae44f`; no alternate model was substituted.
- 2026-08-10: Independent review first found mutable exception fields (P1) and engineering-style Chinese copy (P2). The runtime error is now sealed after construction with read-only properties. “基线/构建/产物/内容位置对应”等表达已改为医学写作者可理解的资料版本、已确认内容、章节写作要求和核验记录，并加入 registration-level regression guard. Two bounded same-session repair reviews were used; final verdict is `READY`.
- 2026-08-10: Task 1.2 acceptance evidence is recorded in `reviews/codex_mw_protocol_v3_phase1_task12_20260810_review.md` and `runs/codex_mw_protocol_v3_phase1_task12_independent_luna.md`. Next safe action after commit is Task 1.3 repository/artifact/unit-of-work ports.
