# Task Context: mw_protocol_v3_phase1_task11_20260810

Created: 2026-08-10 11:01:51
Objective: 按批准计划实现独立Protocol v3 canonical合同模块、严格状态转换和material hash，并保持旧医学写作API兼容
Task type: `code_scoped_patch_plan`
Risk: `high`
Selected agent route: `codex` / `codex-main` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Approved implementation plan: `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.1.
- Approved design: `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, especially Sections 6, 8.4, 9.6, 11, 12, 15, 18 and 19.
- Current repository and tests are the implementation truth; legacy medical-writing exports in `packages/contracts/workbench_contracts/models.py` remain compatible and unchanged.
- Global and repository `AGENTS.md` files govern execution. The user has explicitly stopped all security testing for this workstream.

## Scope

- In scope: create the isolated Protocol v3 canonical contract module, export it from the package, add focused contract tests, and run the two named legacy medical-writing compatibility suites.
- Allowed writes: `packages/contracts/workbench_contracts/protocol_v3.py`, `packages/contracts/workbench_contracts/__init__.py`, `tests/protocol_v3/test_contract_models.py`, and this task's `context/`, `runs/`, `reviews/`, and `metrics/` records.
- Adjacent source-closure remediation authorized by the functional compatibility gate: restore the five immutable medical-writing corpus/glossary assets under `services/api/assets/`, add those exact paths (no directory wildcard) to `scripts/qc/protocol_v3/build_source_baseline.py`, and extend `tests/protocol_v3/test_source_baseline.py`.
- Legacy-test cleanup authorized by the compatibility gate: promote the deterministic IBDQ schema constructor from a historical `records/active_slices/` script into `tests/_real_ibdq_study_schema_fixture.py` and point only the importing test in `tests/test_medical_writing_study_schema.py` to the clean fixture. The historical process tree remains absent.
- Out of scope: repositories, reducers, services, API routes, frontend, runtime/model calls, OCR/translation, production data, and all medical-monitoring files.
- Out of scope: security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state, and penetration testing.

## Success Criteria

- The complete Task 1.1 minimum contract set exists in the independent module and is importable from `packages.contracts.workbench_contracts`.
- Every contract is strict (`extra=forbid`), schema-versioned, uses stable domain IDs and timezone-aware timestamps where timestamps exist.
- Invalid state, partial identity, malformed SHA-256, duplicate IDs and unknown evidence classes fail deterministically.
- Canonical state transitions follow `raw -> normalized -> proposed -> confirmed -> frozen -> superseded/quarantined` without regression or silent overwrite.
- Material hashes ignore display-only progress, `updated_at` and journey counters while retaining substantive identity.
- `tests/protocol_v3/test_contract_models.py`, `tests/test_medical_writing_study_schema.py` and `tests/test_medical_writing_document_session.py` pass without modifying legacy fixtures.
- No medical-monitoring path changes.

## Risk Boundaries

- Preserve the legacy API surface and avoid importing Protocol v3 into old service code in this task.
- Do not rewrite existing baselines or generated fixtures to make checks pass.
- Do not start services or invoke external AI/OCR/translation runtimes.
- Do not perform any security testing; validation is limited to user-facing functional contracts and compatibility.
- Codex owns final diff, test and medical-monitoring-boundary acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-10 11:01:51: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-10: Re-anchored Task 1.1 against the approved design and plan; constrained writes and functional-only validation recorded before implementation.
- 2026-08-10: The named legacy compatibility suites stopped during import because the isolated source baseline omitted `services/api/assets/medical_writing_glossary/regulatory_translation_glossary_v1.json`. Read-only tracing found the same baseline policy also omitted the two company-corpus assets and their two manifests used by product services. The five files are immutable functional inputs (4.8 MB total), not runtime/test output. Exact-path restoration and source-policy closure were added as the smallest functional unblocker; no service or model runtime was started.
- 2026-08-10: After the five assets were restored byte-for-byte, 41/42 legacy compatibility tests passed. The remaining test imported a pure schema constructor from a cleaned historical `records/active_slices/` process script. The constructor was promoted to a stable test fixture and the test import was redirected; restoring the process tree was rejected because it would reintroduce obsolete execution records into the clean worktree.
- 2026-08-10: Task 1.1 focused tests passed: 16 Protocol v3 contract tests and 42 named legacy compatibility tests. Four positive source-baseline closure tests also passed. No service, OCR, translation, browser, security, adversarial or destructive-state test was run.
- 2026-08-10: The requested native `gpt-5.6-luna:max` reviewer capability probe was explicitly rejected by the current App backend (`Unknown model gpt-5.6-luna`). Per the global route contract, review used the labeled CLI compatibility route `/Applications/ChatGPT.app/Contents/Resources/codex exec -m gpt-5.6-luna`; session `019fe9aa-804d-7b50-b9de-6186e418d9f6` was retained for the repair review.
- 2026-08-10: Independent review initially found one P1: an original `SourceArtifact` could carry only one side of the parent identity. The validator now rejects parent ID/hash XOR, forbids any complete parent identity on originals, requires both fields for derived artifacts, and retains the valid original-empty and derived-complete cases. The same Luna session independently rechecked the seven-case matrix and returned `READY`.
- 2026-08-10: Task 1.1 acceptance evidence is recorded in `reviews/codex_mw_protocol_v3_phase1_task11_20260810_review.md` and `runs/codex_mw_protocol_v3_phase1_task11_independent_luna.md`. Next safe action after the Task 1.1 commit is Task 1.2 stable error-code contracts; it remains functional-only and must not add security testing.
