# Task Context: mw_protocol_v3_phase0_task06_20260810

Created: 2026-08-10 09:03:11
Objective: 按已批准实施计划建立 Protocol v3 永久功能失败 corpus 与跨层回归身份，固化 r17 薄弱准入、空白骨架、零检索、批量拒绝复活、未知结果和 checkpoint/event 不一致，不触及医学监查或任何安全测试
Task type: `code_scoped_patch_plan`
Risk: `medium`
Selected agent route: `codex` / `codex-main` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Current candidate filesystem at commit `a6c1c44` and the approved plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 0.6.
- Read-only durable evidence in the sibling legacy workbench: `runs/mw_protocol_p0_max_clean_rounds_20260805.md`, `runs/role_acceptance/mw_protocol_p0_20260805_round17_engineer_cursor_full_protocol_semantic_span_selection.md`, and `runs/MW_SYSTEM_REARCHITECTURE_AUDIT_CHECKPOINT_20260808.md`.
- Approved design `workbench/plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md` for Gate E3/W1 and failure identities.
- The deleted `/private/tmp/mw-p0-engineer-r18.fWUe1r` runtime is not available and must not be described as recovered. Any r17 content reconstruction is explicitly `provenance=evidence_reconstructed`.

## Scope

- In scope: the eight Task 0.6 JSON fixtures, deterministic builder, manifest, and focused tests under `tests/fixtures/protocol_v3/failure_corpus/`, `scripts/qc/protocol_v3/build_failure_corpus.py`, and `tests/protocol_v3/test_failure_corpus.py`; task context/review/metrics only.
- In scope: stable failure identity, provenance, source locator, expected gate, owner, non-vacuous reason, positive controls, deterministic rebuild, and deletion/expected-gate/xfail drift detection.
- Out of scope: legacy workbench writes, runtime/service/browser/Word execution, network/OCR/translation, Task 0.7+, medical-monitoring files, and all security/adversarial/destructive-boundary testing.

## Success Criteria

- Manifest enumerates all eight required failure classes with stable cross-layer identities and pins each fixture hash.
- r17 thin eligibility and heading-only/no-objectives evidence are clearly reconstructed from durable reports and cannot be mistaken for recovered verbatim runtime rows.
- D017 skeleton records the controlled 106-heading/2,627-character/2-table/0-figure failure without copying the historical directory.
- A short evidence unit with a target claim, valid locator/context and allowed source role passes as a positive control, proving length is not the acceptance proxy.
- Missing class, changed expected gate, xfail/skip downgrade, duplicate identity, fixture deletion, or fixture/hash drift fails deterministically.
- `python3 -m pytest tests/protocol_v3/test_failure_corpus.py -q` passes; the new builder/test modules compile and the checked-in corpus passes deterministic `--check`. No application import or runtime path is changed.

## Risk Boundaries

- Writes are limited to the candidate paths listed in Scope plus this task's context/review/metrics. Sibling `workbench/` is read-only evidence; medical monitoring is untouched.
- Do not start services or mutate project/runtime data. Do not rerun historical r17, OCR, translation, download or Word workflows.
- Do not perform or dispatch any security, permission, path, symlink, TOCTOU or destructive-state probe. Only functional contract fixtures and ordinary deterministic tests are allowed.
- Fixtures must not contain credentials, raw runtime databases, deleted-session claims, or whole historical artifacts.
- Codex is the sole worker and final authority for this medium-risk direct task; no external execution or conference route is needed.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-10 09:03:11: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-10 09:05: Task contract anchored to Task 0.6 and durable read-only evidence; security-test lane explicitly excluded by the user's latest correction.
- 2026-08-10 09:10: Built eight pinned fixtures and one short substantive positive control. D017 source artifact was read-only matched to 106 headings / 2,627 paragraph characters / 2 tables / 0 figures / 28 rendered pages and SHA-256 `bae34f096ef5769a8d025ac03f72d9dfed06278d03faef97dff33beaae9705e9`.
- 2026-08-10 09:10: Focused functional verification passed: 19 pytest cases, deterministic corpus `--check`, Python compile and `git diff --check`. No broader Phase 0 safety/adversarial suite was rerun after the user's explicit stop instruction.
