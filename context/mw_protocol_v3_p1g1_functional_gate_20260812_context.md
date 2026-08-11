# Task Context: mw_protocol_v3_p1g1_functional_gate_20260812

Created: 2026-08-12 05:02:57
Objective: 只读核验 P1-G1 全部非安全谓词，显式记录 Task 1.11 为 USER_EXCLUDED，不运行安全测试，并给出是否可进入 Phase 2 功能性 PoC 的可审计结论
Task type: `high_risk_contradiction_review`
Risk: `high`
Selected agent route: `codex` / `gpt-5.6-luna` / `max`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Current user instruction: continue the approved implementation plan, but do not perform any security testing; focus on user-facing functional implementation/testing. This later instruction supersedes execution of Task 1.11 but does not turn unexecuted security work into PASS.
- Frozen plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, especially Phase 0 gates, Tasks 1.1–1.11 and Gate P1-G1. SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`.
- Accepted Task 1.1–1.10 review, metric, acceptance-checkpoint and commit evidence in `reviews/`, `metrics/`, `runs/`, `context/` and current Git history.
- Current code/tests under `services/api/app/protocol_workflow/`, `packages/contracts/workbench_contracts/protocol_v3.py`, `tests/protocol_v3/`, storage PoC records and Phase 0 acceptance records.
- Current filesystem and executed non-security checks outrank historic prose. No live database is an evidence source.
- This audit may classify a predicate as PASS, FAIL, UNVERIFIED or USER_EXCLUDED. It must never call Task 1.11 PASS.

## Scope

- In scope: read-only matrix of every P1-G1 predicate except the explicitly excluded security tests; provenance to accepted Task 1.1–1.10 evidence; current non-security test/hash/diff checks; P0-CORE/P0-WORD state; selected-storage decision; legacy-write/replay evidence; recommendation whether an explicitly amended `P1-G1_FUNCTIONAL` permits Phase 2 PoC work.
- Allowed writes: only this task's `context/`, `prompts/`, `runs/`, `reviews/` and `metrics/` records by Codex/runner. The verifier itself is read-only and returns its report to the runner.
- Out of scope: all Task 1.11 files and tests; prompt injection, SSRF, path traversal, secret scanning or any other security check; source edits; service startup; live/runtime database access; route mounting; frontend/browser/visual work; medical-monitoring; Phase 2 implementation.

## Success Criteria

- Build an exact P1-G1 matrix: canonical/repository/event/reservation tests; application/API/Agent⑤ boundary; migration; selected-storage decision with quantitative/license/version/failure/rollback evidence; zero legacy-store writes; artifact/event replay hash; P0-CORE; P0-WORD/NO_RELEASE state.
- For each predicate cite the current file/commit/test evidence or mark it UNVERIFIED/FAIL; do not rely on a prior READY label alone.
- Record the security predicate as `USER_EXCLUDED`, not PASS, and state the consequence for the original frozen P1-G1 versus an explicit current-instruction functional amendment.
- Run only the smallest decisive non-security checks needed to validate drift. Do not rerun every historic suite when current aggregate tests and immutable commits suffice.
- Return `P1-G1_FUNCTIONAL_READY` only if every non-security predicate is grounded and Phase 2 PoC can proceed without claiming full frozen-gate or release readiness; otherwise return `P1-G1_FUNCTIONAL_NOT_READY` with the exact owning gap.

## Risk Boundaries

- Read-only product audit. Do not write source, config or tests.
- Do not run any security test, scan or adversarial security probe, including Task 1.11.
- Do not inspect or mutate live/runtime databases or start services.
- Strictly protect medical-monitoring and unrelated user changes.
- Do not silently reinterpret the frozen gate: distinguish original `P1-G1` from user-amended `P1-G1_FUNCTIONAL`.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-12 05:02:57: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-12 05:04 CST: Task 1.10 commit `9602458` accepted after two independent same-session verifier rechecks and Codex final tests. Frozen Task 1.11 is security-only and conflicts with the current explicit exclusion; Codex opened this audit instead of silently running or bypassing it.
- 2026-08-12 05:08 CST: Required current-session native Luna probe was explicitly rejected: `Unknown model gpt-5.6-luna` (available native choices Sol/Terra). Per global route policy, use the labeled `cli_compatibility_fallback` with `/Applications/ChatGPT.app/Contents/Resources/codex exec -m gpt-5.6-luna`, preserve max effort and long wait, and do not substitute models or route through Hermes.
- 2026-08-12 05:20 CST: Luna CLI session `019ff2a4-2a79-7921-9d01-6c0ef07273f1` returned `P1-G1_FUNCTIONAL_NOT_READY`: Task 1.1–1.10 functional predicates pass, but no accepted H0/H1/H3 aggregate record exists. Codex reproduced the gap: all 51,035 immutable inventory rows still carry the Task 0.2 read-only occupancy placeholder.
- 2026-08-12 05:25 CST: Codex bound a supplemental occupancy check to the accepted inventory/protected hashes. Inventory has zero mutation-eligible/authorized targets and zero unknown owners; built-in occupancy check over the exact empty target set reports zero blockers. Positive P0-CORE checks pass 35/35 and temporary-directory restore rehearsal passes 6/6. Candidate record `runs/MW_PROTOCOL_V3_P0_CORE_FUNCTIONAL_CLOSURE_CANDIDATE_20260812.md` awaits same-session Luna recheck; no live file was moved or deleted.
- 2026-08-12 05:33 CST: Original Luna session `019ff2a4-2a79-7921-9d01-6c0ef07273f1` accepted the additive H0/H1/H3 evidence and returned `P1-G1_FUNCTIONAL_READY`. Original frozen P1-G1 remains incomplete because Task 1.11 is `USER_EXCLUDED`; only repository/PoC-bound Phase 2 work may proceed, with product storage activation, live migration, security acceptance and release still blocked.
