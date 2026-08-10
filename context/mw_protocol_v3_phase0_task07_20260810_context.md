# Task Context: mw_protocol_v3_phase0_task07_20260810

Created: 2026-08-10 09:13:20
Objective: 建立Protocol多Agent重构Phase 0 Word原生验收回执PoC合同，证明只有Microsoft Word原生打开、域更新、分页、书签与交叉引用核验、保存重开、PDF页证据和OOXML指纹齐备时才可升级；仅离线功能合同与测试，不启动Word或服务，不运行安全性测试
Task type: `code_scoped_patch_plan`
Risk: `medium`
Selected agent route: `codex` / `codex-main` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Current candidate filesystem at commit `bbfc8ec` and approved Task 0.7 in `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`.
- Approved design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, especially the Microsoft Word native delivery and immutable round-trip requirements.
- Existing candidate receipt seam in `packages/contracts/workbench_contracts/models.py`, `services/api/app/medical_writing_word_verification_repository.py`, and focused Word verification tests. These are compatibility evidence, not the new full native receipt contract.
- Read-only historical producer evidence in sibling `workbench/evidence/mw_docx_release_gate_20260727/run_word_native_gate.py` and the three 2026-08-02 Word receipt reviews. Historical traces do not contain reopen, bookmark/cross-reference, complete field-update, page-evidence dependency, OOXML fingerprint, or edit/reimport/export lineage proof and therefore cannot be upgraded.
- Primary Microsoft references for Word Add-ins, Word JavaScript/OOXML/custom XML, VBA field update/repagination/bookmark checks/save/PDF export. Source URLs and decision implications are pinned in `pocs/protocol_v3/word_receipt/README.md`.

## Scope

- In scope: an offline, machine-decidable Task 0.7 contract, representative fixtures, focused functional tests, and a Chinese technical decision record under `pocs/protocol_v3/word_receipt/`; task context/review/metrics only.
- In scope: exact Microsoft Word producer identity, open-without-repair, all-story field update, TOC, repagination, bookmarks, cross-references, immutable save/reopen/PDF/page evidence, normalized OOXML fingerprint, source/revision binding, deterministic idempotency, staleness and edit/reimport/export lineage.
- Out of scope: choosing or implementing AppleScript/add-in/bridge producers, starting Microsoft Word or services, modifying existing receipt/API/repository semantics, live DOCX mutation, external-edit execution, product wiring, Phase 1+, frontend work, and medical-monitoring files.

## Success Criteria

- The contract rejects missing/unknown fields and any non-Microsoft-Word producer, repaired open, incomplete field scope/error, missing TOC/repagination/reopen, failed or empty bookmarks/cross-references, absent/noncontiguous PDF page evidence, unqualified page-evidence provenance, invalid OOXML fingerprint, mutable artifact identity, bad timestamps, or idempotency mismatch.
- Exact changes to source snapshot hash, input DOCX hash, semantic document revision or template revision produce typed staleness reasons.
- External Word edits require distinct immutable source, edited, reimported and re-exported artifact identities and a new merged semantic revision; the source is never overwritten.
- Historical trace limitations are tested as non-upgradeable rather than inferred as success.
- `python3 -m pytest pocs/protocol_v3/word_receipt/tests -q` passes, the module compiles, fixture parsing is deterministic and `git diff --check` passes.

## Risk Boundaries

- Writes are limited to `pocs/protocol_v3/word_receipt/` and this task's context/review/metrics inside the isolated candidate repository.
- The sibling workbench, historical Word artifacts and existing product contracts are read-only. Medical monitoring is untouched.
- Do not launch Word, services, browser, OCR, translation, model calls or external producer code in Task 0.7.
- Per the user's explicit correction, do not run or dispatch security, adversarial, permission, path, symlink, TOCTOU or destructive-state tests. Focused functional contract validation only.
- Page-image tooling is not selected by this task. A future producer must independently verify the exact dependency/version/license before product adoption; historical PyMuPDF use is not inherited as approval.
- Codex is the sole worker and final authority for this bounded task; no external execution/conference route is needed.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-10 09:13:20: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-10 09:16: Contract anchored to approved Task 0.7, current candidate seams, read-only historical Word evidence and primary Microsoft documentation. Security/adversarial testing and all live Word/runtime operations are explicitly excluded.
- 2026-08-10 09:25: Implemented a producer-neutral strict receipt contract, representative current/legacy fixtures and 55 focused functional tests. The contract binds exact PDF pages with a manifest and binds the normalized OOXML fingerprint to the Word-saved artifact.
- 2026-08-10 09:27: Focused Task 0.7 tests, Python compile, JSON parse and diff check passed. An adjacent legacy receipt test command failed during collection before any test ran because the isolated source-only candidate lacks `packages/contracts/workbench_contracts/protected_tokens.py`. Read-only root-cause tracing found that `build_source_baseline.py::_looks_sensitive` excludes every filename containing `token`, including three medical-writing functional source/test files. This is a pre-existing source-closure defect, not a Task 0.7 regression; no monitoring file, baseline policy or live source was changed in this task. `P0-CORE` must not be called complete until a separate functional source-completeness remediation is verified without security/adversarial testing.
