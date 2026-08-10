# Task Context: mw_protocol_v3_phase0_task08_20260810

Created: 2026-08-10 09:24:54
Objective: 比较并实现Protocol v3 Word receipt producer候选，在目标macOS与Microsoft Word上对任务副本完成功能性真实PoC，生成可恢复、可审计回执和决策；不得进行任何安全、对抗、权限或破坏性测试，不触碰医学监查
Task type: `code_scoped_patch_plan`
Risk: `high`
Selected agent route: `codex` / `codex-main` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Current candidate filesystem at commit `2a9d127`, approved Task 0.8 in `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, and the accepted Task 0.7 contract in `pocs/protocol_v3/word_receipt/`.
- Approved design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md` for Microsoft Word native delivery, final-style fidelity and immutable edit/reimport/export lineage.
- Read-only Word samples: user-provided TP-MA-07 template; legacy D017 skeleton exact artifact; legacy `evidence/mw_docx_release_gate_20260727/CMS-UC-301_代表性完整临床试验方案_V0.1_正式导出.docx`; any additional task-created complex fixture must remain in ignored `results/`.
- Primary Microsoft Word Add-in, JavaScript/OOXML/custom XML and VBA/desktop automation documentation already pinned in the Task 0.7 README. Candidate claims must be verified against the installed target Word and actual artifacts rather than marketing statements.

## Scope

- In scope: producer-neutral base contract, conditional AppleScript bridge if target Word supports the required functional object model, candidate matrix runner, decision record and task-owned ignored runtime results.
- In scope: read-only inventory; only then task-copy open/update fields/TOC/repaginate/bookmark/ref/save/close/reopen/PDF/page-evidence/OOXML-fingerprint; exact idempotency/recovery; TP-MA-07, D017 and CMS-UC-301 matrix evidence.
- In scope: Computer Use for visible Microsoft Word state and final artifact acceptance. Shell inspection may be used for read-only metadata and deterministic artifact hashing.
- Out of scope: product/API wiring, Office Add-in construction if no existing compatible scaffold is present, source artifact overwrite, frontend work, Phase 1+, source-baseline repair, production deployment and medical-monitoring files.

## Success Criteria

- Candidate comparison records exact mechanism/version/licensing/integration constraints and distinguishes documentary capability from real target-machine proof.
- At least one candidate either emits a Task 0.7-valid native Word receipt for a representative complex Protocol task copy or is rejected with a typed, evidenced blocker; no failed candidate is silently called PASS.
- The original TP-MA-07, D017 and CMS-UC-301 hashes remain unchanged; all generated DOCX/PDF/PNG/state/receipt files are immutable task-owned outputs.
- Same idempotency key reuses a valid receipt without reopening/editing Word. A partial/unknown state is reconciled from exact artifact evidence and is never blindly rerun.
- Actual Word open, field/TOC update, repagination, bookmarks/cross-references, save/reopen and PDF are visible or machine-evidenced; page evidence and normalized OOXML fingerprint validate through Task 0.7.
- Focused producer tests and matrix validation pass. `decision.md` gives PASS/FAIL and keeps `P0-WORD=NO_RELEASE_WORD_BLOCKED` unless the full contract is met.

## Risk Boundaries

- Writes are limited to `pocs/protocol_v3/word_receipt/`, ignored `pocs/protocol_v3/word_receipt/results/`, and this task's context/review/metrics inside the candidate repository. External Protocol samples and sibling workbench remain read-only.
- Never overwrite a source or existing user Word file. Work only on newly copied, hash-verified task artifacts with distinct filenames and close only the task document.
- Do not start services, OCR, translation, browser test suites or product runtimes.
- Per the user's explicit correction, do not run or dispatch security, adversarial, permission, path, symlink, TOCTOU, malicious-input or destructive-state tests. Do not probe or change macOS privacy/accessibility/automation permissions; if a normal Word action is unavailable, record a functional blocker.
- Do not touch, copy or repair medical-monitoring modules. The adjacent source-only import-closure defect is recorded for a later functional remediation and is not part of Task 0.8.
- Codex is the direct worker and final authority. Any later independent acceptance receives only artifacts, criteria and evidence, never private worker reasoning.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-10 09:24:54: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-10 09:27: Task anchored to the accepted receipt contract and real Word task-copy boundary. Computer Use skill was loaded for visible Word operations; no desktop or Word action has yet occurred.
- 2026-08-10 09:30–10:10: Implemented target-scoped AppleScript bridge, deterministic
  postprocess recovery, local PDF page evidence, normalized OOXML fingerprint and focused tests.
  TP-MA-07 reached a 62-page candidate but page 2 footer clipping prevented finalization. D017
  completed Word processing but returned `WR_BOOKMARK_EVIDENCE`; same request resumed without
  another Word invocation. CMS-UC-301 completed 27-page Word native verification.
- 2026-08-10 10:20–10:24: Performed an actual Word wording-only edit on the task copy
  (“监管管理部门”→“药品监督管理部门”), froze source/edited/reimport/re-export identities,
  produced a new semantic revision and finalized all 27 pages. Replay returned the same receipt
  without reopening Word. Existing three user Word documents were restored unchanged.
- 2026-08-10 10:26–10:39: Independent conference completed. Pi/cms-model returned `READY`.
  Grok Build required two same-session recovery passes after cancelled progress-only outputs, then
  returned `READY_WITH_RESIDUALS`; no fallback. Codex resolved lineage terminology and current
  producer pin in `decision.md`.
- 2026-08-10 10:40: Moved 17 superseded TP debugging directories with no candidate/final receipt
  to macOS Trash. The five decisive result directories remain; removal is recoverable.
- 2026-08-10 10:45–10:49: Codex self-review added exact staged-file hash, semantic-revision,
  reservation, candidate and final-receipt lineage replay checks. The new implementation identity
  required and received a fresh Word-native roundtrip run. All 27 pages were visually reinspected,
  the receipt was finalized, replay returned without another Word invocation, and the three user
  Word documents remained unchanged. Six decisive result directories now remain; the prior r2
  receipt is immutable historical evidence.

## Outcome

- Gate: `P0-WORD_TECHNICAL_PASS_WITH_RESIDUALS`.
- Current producer identity SHA-256:
  `9e214a167b7f0bf67e417e0c75e4b71b8a6c9b98cf5b5e3b5f81aba7f90fc12b`.
- Current roundtrip receipt: `mwwr_v1_75c4311dfc1ac8c0af0d908726e34525`.
- Focused tests: 67 passed. Current and initial CMS receipts pass the frozen validator; the prior
  r2 receipt remains historical because its producer identity predates lineage replay hardening.
- Word/version: Microsoft Word for Mac 16.111.3. Page evidence renderer:
  pypdfium2 5.12.1 (`Apache-2.0 OR BSD-3-Clause`, local/no egress).
- Residuals: current proof is target-workstation/corpus bound; text-frame, comment and tracked-change
  corpus coverage remains future scope. Product/API/A+C/Phase 6–8 and Protocol content release are
  not implied.
- No security test was run or dispatched. No medical-monitoring file was read or changed.

## Next Safe Action

Complete the targeted same-session functional acceptance update, commit Task 0.8 evidence, and
proceed to the already recorded functional import-closure repair for
the legitimate medical-writing protected-token modules before Phase 1. Do not touch the similarly
named medical-monitoring modules.
