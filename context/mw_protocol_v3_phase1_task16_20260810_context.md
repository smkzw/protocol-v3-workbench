# Task Context: mw_protocol_v3_phase1_task16_20260810

Created: 2026-08-10 19:15:37
Objective: 按冻结计划 Task 1.6 实现 ExecutionReservation：长副作用统一 completed/failed/unknown_outcome、同输入完成复用、unknown 不自动重派、同会话回收与显式新 attempt
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `cms-smk` / `cms-model` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Frozen plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md` at SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, Task 1.6.
- Approved design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, sections 17.2 and 18: append-only reservation authority; completed/failed/unknown_outcome only; no automatic redispatch after unknown outcome; same-session/provider recovery before an explicit new attempt; provider fallback is repackaged from canonical source without prior scratchpad or raw sensitive payload.
- Existing contract and repository authority: `packages/contracts/workbench_contracts/protocol_v3.py`, `services/api/app/protocol_workflow/ports/repositories.py`, `services/api/app/protocol_workflow/storage/memory.py`, and stable errors in `services/api/app/protocol_workflow/errors.py`.
- Local comparison semantics already proved by `tests/test_medical_writing_authoring_prefill_ai.py`, `services/api/app/ocr_fallback_orchestrator.py`, and `tests/test_writing_reference_translation_batch.py`.
- Current filesystem and focused Task 1.6 functional tests are implementation truth.

## Scope

- In scope: a storage-agnostic reservation coordinator and deterministic idempotency/fallback input helpers; completed-result reuse; timeout/no-receipt classification; restart blocking; same-session/provider reconciliation; explicit retry creating an append-only new attempt; focused comparison and runtime tests.
- Out of scope: provider-specific adapters, live model/CLI/OCR/translation/download/export calls, LangGraph, role/skill/harness registries (Task 1.7), database-vendor adapters, API/UI, service startup, legacy-path rewrites, and all medical-monitoring files.

## Success Criteria

- The three named legacy surfaces are encoded as local comparison tests or explicit contract assertions without invoking their live runtimes.
- A completed reservation with the same logical work and input hash returns the existing output and causes zero physical redispatches.
- A timeout or missing transport receipt after dispatch produces `unknown_outcome`, never a retryable `failed` surrogate.
- Restart over preserved repository state refuses automatic redispatch of an unresolved unknown outcome.
- Same-session/provider recovery may attach a recovered output to and complete the same reservation without creating a new physical call.
- Only an explicit, auditable retry decision may create attempt `N+1`; attempt `N` remains immutable and queryable, and concurrent duplicate decisions cannot create duplicate attempts.
- Provider fallback payload is rebuilt from canonical input and excludes previous-provider scratchpad/session transcript/raw sensitive payload; an unsafe package fails closed.
- Focused Task 1.6 tests plus named Task 1.1-1.5 functional regressions, Ruff, compilation, formatting, frozen-plan hash, diff and medical-monitoring boundary checks pass.

## Risk Boundaries

- Initial product writes are limited to `services/api/app/protocol_workflow/runtime/reservations.py`, `services/api/app/protocol_workflow/runtime/idempotency.py`, `services/api/app/protocol_workflow/runtime/__init__.py` if an export surface is needed, and `tests/protocol_v3/test_execution_reservations.py`.
- Existing contracts, stable errors, repository ports, memory adapters and legacy comparison surfaces are read-only for delegated workers. A test-proven append-only-attempt gap must be reported to Codex before widening writes.
- Do not start services or databases; do not invoke browsers, external accounts, model/CLI/OCR/translation/download/export runtimes, or production paths.
- Do not run security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state or penetration tests. Functional crash/restart/concurrency/fallback-data-shaping tests required by Task 1.6 remain in scope.
- No legacy medical-writing or medical-monitoring file may be modified.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-10 19:15:37: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-10: External discovery was not reopened because the approved design and frozen plan already fix the bounded reservation method, and Task 1.6 is an internal implementation of that approved contract.
- 2026-08-10: Re-anchored the local comparison semantics: prefill treats timeout and post-dispatch persistence loss as unknown and preserves the old call across restart; Paddle OCR falls back only after verified rejection/failure and re-raises outcome-unknown; downstream translation never repeats a model call when restart cannot prove its outcome and can resume from an immutable persisted chunk.
- 2026-08-10: Static inspection found a known contract gap: the current in-memory repository indexes one reservation per `(project, logical_call_id, idempotency_key)`, while Task 1.6 requires an explicit retry decision to create a new append-only attempt and preserve the old reservation. The delegated round must first prove the runtime surface and report any required port/storage widening; it may not overwrite or mutate the prior attempt into the new one.
- 2026-08-10: Worker 03's first specification pass created 28 black-box tests and the expected missing-runtime collection failure. Codex found two false-positive tests (ambiguous `None` receipt and a rejection fake that incremented dispatch before raising). A malformed resume invocation replayed the original assignment before the targeted follow-up and overwrote the untracked test with a different 23-test API; raw tool evidence is preserved in the follow-up stdout. Codex restored the exact first-pass file from the runner's original `write` tool call, then surgically replaced the two false positives with an explicit default-receipt sentinel and a `preflight` error-code interface. The restored authority has 28 tests, compiles, and still fails only because the runtime export surface is not yet created.
- 2026-08-10: Worker 01 created only `runtime/idempotency.py`; repository `.gitignore` currently ignores any directory named `runtime/`, so the product file exists but is not visible in ordinary `git status`. Task 1.6 acceptance must explicitly make the Protocol v3 runtime subtree trackable without unignoring unrelated runtime/cache directories.
- 2026-08-10: Worker 02 first pass and same-session repair were rejected as final authority. The first pass dispatched before reservation persistence. The repair persisted only after preflight, encoded transport attempt 1 in `RESERVED`, inferred duplicate retry identity from input hashes instead of an explicit decision ID, omitted the approved repository state machine/list lineage, temporarily created `runtime/__init__.py`, and ran a prohibited directory-wide test set. Raw tool calls and both runner reports are preserved.
- 2026-08-10: Codex authorized the test-proven minimal repository widening: `transition(..., transport_attempts=...)`, closed `RESERVED -> RUNNING|FAILED`, `RUNNING -> COMPLETED|FAILED|UNKNOWN_OUTCOME`, `UNKNOWN_OUTCOME -> COMPLETED` state machine, and deterministic append-only `list_attempts`. The reference adapter now atomically owns a reservation before preflight, moves it to RUNNING/attempt 1 before dispatch, preserves RUNNING after terminal persistence failure, rejects automatic restart dispatch, enforces unique attempt numbers, and revalidates every updated contract before commit.
- 2026-08-10: Explicit retry now requires a durable `retry_decision_id`; repeating one decision is idempotent, while distinct decisions append attempts 2 and 3 even with identical material input. The canonical input digest excludes the decision/idempotency key. Cross-provider packaging treats provider/region identifiers as opaque allowlist values and rejects forbidden fragments recursively.
- 2026-08-10: Worker 03 same-session integration created only the runtime public export facade as product code. Its 35 runtime and 70 repository tests passed, but its raw log shows it also wrote the runner-owned report path despite claiming otherwise; retain as an execution-discipline discrepancy, not product acceptance evidence.
- 2026-08-10: Codex-run acceptance anchors currently pass: 35 Task 1.6 runtime tests, 71 repository contract tests after the revalidation counterexample, and the integrated named Task 1.1-1.6 functional set (pending one final recount after the latest test) with warnings as errors. Ruff, format, compile, diff, frozen-plan hash and medical-monitoring boundary checks are clean. Manager and isolated contradiction review remain pending.
- 2026-08-10: Cursor execution manager returned READY but found one P3 recovery-discovery gap: a RUNNING row left by terminal persistence failure was absent from `find_unknown_outcome`. Codex closed it with the explicit project-scoped `find_unresolved` port/coordinator/reference-adapter contract for RESERVED/RUNNING/UNKNOWN rows and pinned it in repository tests.
- 2026-08-10/11: Isolated Qwen review initially returned NOT_READY with two reproducible P3 and three P4 contract gaps. Codex reproduced them, then required explicit provider+region for RESTRICTED fallback, disposed dangling RESERVED/0 shells as immutable zero-dispatch FAILED attempts, documented/pinned live receipt-session adoption versus UNKNOWN recovery binding, pinned cross-coordinator duplicate retry fail-closed/convergence, and pinned that later retry completion never rebinds the original UNKNOWN idempotency key.
- 2026-08-11: Qwen same-session round 2 independently executed 112 focused tests and 31 deterministic probes and returned READY with no open P0-P4. Native Grok Build session `6fe64da8-28d6-4f82-8cd8-b82519ce070c` returned `stopReason=cancelled` on the initial pass and both permitted same-session recovery passes without a usable report. Only after that evidence was retained did the declared Cursor `cursor-grok-4.5-high` fallback run; it returned READY by independent static falsification, with live pytest unavailable under its Ask-mode shell gate.
- 2026-08-11: Codex final authority executed the exact Task 1.1-1.6 named suite: 423 passed with warnings as errors. The focused Task 1.6/repository pair is 112 passed. Ruff check/format, in-memory compilation of 11 Python files, `git diff --check`, runtime trackability, frozen-plan SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, and medical-monitoring change count 0 all passed. Task 1.6 has no open P0-P4; next safe frozen-plan micro-step is Task 1.7 registry/entry-point authority, not a live provider or service run.
