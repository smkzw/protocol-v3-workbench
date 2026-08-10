# Task Context: mw_protocol_v3_phase0_source_closure_20260810

Created: 2026-08-10 10:56:55
Objective: 修复Protocol v3 source-only候选中三个医学写作protected-token功能文件被误排除导致的导入闭包，验证可复现重建且严格不触碰医学监查模块
Task type: `code_scoped_patch_plan`
Risk: `medium`
Selected agent route: `codex` / `codex-main` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Current candidate commit `03c54c1`, approved Implementation Plan and Task 0.7 review/context that
  records the collection failure.
- Read-only legacy source root
  `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/workbench/`:
  `packages/contracts/workbench_contracts/protected_tokens.py`,
  `services/api/app/medical_writing_protected_tokens.py`, and
  `tests/test_medical_writing_protected_tokens.py`.
- Current candidate `scripts/qc/protocol_v3/build_source_baseline.py`, its source-candidate
  functional contract, and actual Python import/test collection behavior.

## Scope

- In scope: restore only the three omitted medical-writing functional files byte-for-byte; replace
  the filename-wide false positive with an exact source-policy exemption for only these paths;
  add focused functional coverage and task records.
- Allowed writes: the three restored files, `scripts/qc/protocol_v3/build_source_baseline.py`,
  `tests/protocol_v3/test_source_baseline.py`, and this task's context/review/metrics/prompt/run.
- Out of scope: every medical-monitoring module/test/record, mutable/frozen authority fixture
  regeneration, service startup, Word/browser/OCR/translation, Phase 1 implementation, broad token
  detector redesign, and every security/adversarial/permission/path/symlink/TOCTOU/destructive test.

## Success Criteria

- Candidate copies match all three authoritative legacy SHA-256 values exactly.
- `is_source_candidate` and a temporary functional manifest include exactly the three required
  medical-writing token files without broadly changing other policy behavior.
- `packages.contracts.workbench_contracts.models`, service compatibility exports and the restored
  focused medical-writing token tests import and pass; the Task 0.7 collection error is gone.
- No medical-monitoring path changes. No frozen/mutable baseline fixture is rewritten; this is a
  declared repair of a pre-existing source-copy omission, not a silent baseline rewrite.
- Python compile, focused functional tests and `git diff --check` pass; current Word/user/runtime
  state is not invoked or changed.

## Risk Boundaries

- The legacy workbench is read-only; restoration occurs only in the isolated Git candidate.
- Medical-monitoring files must not be read as source inputs or changed. Name similarity is not
  authorization.
- Do not run or dispatch security-oriented source-baseline tests; use only the named positive
  source-selection and application functional tests.
- Exact legacy hashes and current filesystem are acceptance authority. Codex owns verification.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-10 10:56:55: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-10 10:58: Reproduced the precise omission: all three medical-writing token files are
  absent, while `_looks_sensitive` rejects every filename containing `token`. Authoritative legacy
  hashes are `ac0042ec…`, `5a95fd41…`, and `82d8f002…`; no file has been restored yet.
- 2026-08-10 11:00–11:03: Restored the three files byte-for-byte with authoritative hashes. Bumped
  source policy to v3 and added an exact three-path exemption plus positive source-candidate and
  manifest tests. The exemption does not use a suffix/prefix wildcard. Sixteen focused token/
  source-closure tests passed, both contract/service imports succeeded, and the formerly blocked
  Word verification/repository pair passed 8/8.

## Outcome

- Import closure restored. Candidate hashes equal legacy source exactly:
  `ac0042ec2cf90dac1b373d949175095e61390dbccfd9485c84ce7e539bd6d0dc`,
  `5a95fd414b7fa3e1d9423d6ee6fb5dd301b0e67b1d72c63c91a6fe4aa6a3c1d1`, and
  `82d8f002291eed87c3e21a1bc0b5af6418f3757c6458a6fe3c33e473972c4a16`.
- `16 passed` for focused source-policy + protected-token behavior; `8 passed` for the exact Word
  verification/repository compatibility pair that previously failed at collection.
- No baseline fixture was rewritten. No medical-monitoring file was read as an implementation
  source or changed. No security test was run or dispatched.

## Next Safe Action

Complete Codex review gate and commit this Phase 0 source-closure erratum, then begin Phase 1
Task 1.1 canonical Protocol v3 contracts from the clean candidate state.
