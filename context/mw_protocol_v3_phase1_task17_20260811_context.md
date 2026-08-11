# Task Context: mw_protocol_v3_phase1_task17_20260811

Created: 2026-08-11 08:21:35
Objective: 按冻结计划 Task 1.7 建立 Protocol v3 Role、Skill、Harness Registry：四类产品 AI 与 Agent App/CLI 通过版本化最小输入 NodeExecutionContract 运行，并离线证明模型/思考/allowlist/workload-gate/adapter/fallback 纪律
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `cms-smk` / `cms-model` / `high`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Frozen implementation plan: `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, especially Task 1.7.
- Approved architecture: `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md` §§5.3 and 17; approved decisions in `plans/mw_system_rearchitecture_design_decisions_20260808.md`.
- Canonical contracts: `packages/contracts/workbench_contracts/protocol_v3.py` (`SkillDefinition`, `NodeExecutionContract`, `ExecutionReservation`).
- Accepted Task 1.6 runtime: `services/api/app/protocol_workflow/runtime/reservations.py` and `runtime/idempotency.py`, commit `0515361`.
- Existing product adapters/policies inspected read-only: `services/api/app/paddle_ocr_adapter.py`, `services/api/app/omlx_workload_gate_client.py`, and `/Users/smkzw/.codex/tools/omlx_workload_gate.py`.
- Current runtime capability evidence: local `codex exec --help` supports JSONL, output schema, session resume and model selection; local `omp --help` supports provider/model, thinking, non-interactive execution, session resume, enabled tools and long max-time.
- Primary external references used for the consequential adapter decision: PaddleOCR official API Overview/CLI and PaddleOCR-VL-1.6 documentation; JSON Schema Draft 2020-12; Pydantic official strict/config and JSON-schema documentation.
- Current filesystem and test results remain final truth. Retrieved docs and delegated model output are evidence, not authority.

## Scope

- In scope: versioned Role and Skill registries; strict registry loader; a deterministic Harness policy boundary; direct API, local oMLX, Codex App/CLI and OMP CLI adapter contracts where local capability is proven; typed artifact-only inputs/outputs; thinking restrictions; provider/region/sensitivity allowlists; first-use connectivity probes; fallback eligibility; shared workload-gate reconciliation; focused offline tests and compact run/review/metrics evidence.
- Allowed write paths: `config/medical_writing/protocol_v3/{role_registry.json,skill_registry.json}`; `services/api/app/protocol_workflow/registries/`; `services/api/app/protocol_workflow/runtime/{harness.py,adapters/}`; the two Task 1.7 test files under `tests/protocol_v3/`; this task's `context/`, `prompts/`, `runs/`, `reviews/`, `metrics/`, and runner-owned archive surfaces. A minimal coherent edit to `packages/contracts/workbench_contracts/protocol_v3.py` is allowed only if a failing contract test proves the frozen Task 1.7 fields cannot otherwise be represented.
- Out of scope: live provider calls, live OCR/translation, credentials, service startup, frontend/UI changes, legacy project mutation, database/storage selection, Task 1.8+, security testing, release/promotion, and any medical-monitoring file.
- The role registry records the user-approved target profile. It does not claim runtime readiness when the shared gate's current authoritative OCR model differs.

## Success Criteria

- Four product roles are uniquely and strictly registered: LLM and OCR/translation-support may configure thinking/effort; OCR and translation may not.
- The target profile is exact and credential-free: DeepSeek `deepseek-v4-flash`/max for LLM and support, `PaddleOCR-VL-1.6` official document parsing for OCR, and oMLX `dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX` for translation. Runtime receipt, not registry text, owns observed identity.
- Every Skill registry entry validates typed input/output refs, allowed tools/paths, evidence gates, side effect/idempotency policy, error codes, prompt/tool versions, acceptance tests, and rollback.
- Harness accepts only immutable artifact references plus bounded snippets, returns a typed artifact/receipt, rejects credential-shaped values, validates provider/region/sensitivity and role/skill consistency before dispatch, and has no direct canonical repository handle.
- Adapters require a first-use connectivity probe, do not use `max_turns=1`, preserve same-session recovery, and allow fallback only after a recorded terminal/unavailable outcome and policy revalidation.
- oMLX translation requires the shared lease/heartbeat/release contract. The currently observed gate selection (`ocr=GLM-OCR-bf16`) cannot execute a declared Paddle role: mismatch is surfaced as a deterministic error before any invocation. No GLM output can be labeled Paddle.
- Deterministic fakes prove valid paths, negative/cross-product policy cases, no duplicate dispatch on preflight/policy failures, and no secret material in registries/prompts/checkpoints/receipts.
- Focused tests, relevant integrated Protocol v3 tests, lint/format/syntax/import probes, plan-hash check, runtime-trackability check, and zero medical-monitoring diff pass. Independent verifier owns READY.

## Risk Boundaries

- Do not write to production paths or call a real provider. No service, OCR, translation or external model runtime is started in Task 1.7.
- Do not test system security; only deterministic product-boundary validation needed to prevent credential leakage or invalid dispatch is in scope.
- Preserve Task 1.6 reservation semantics and the immutable canonical/application boundary. Adapters submit typed proposals/artifacts only and never write repositories directly.
- Preserve all medical-monitoring files byte-identically and do not run monitoring E2E/QC.
- No credential, token, raw secret, private project payload or previous-provider scratchpad may enter registry, prompt, checkpoint, artifact or fallback payload.
- Do not edit the global shared gate in this task. The OCR mismatch is a fail-closed integration blocker to be explicitly reconciled by the owning policy before live use.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-11 08:21:35: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-11: Re-anchored at clean commit `0515361`; only task-generated tracking files were untracked. Frozen plan hash unchanged and no medical-monitoring diff observed.
- 2026-08-11: Local capability inspection confirmed schema/session/tool-capable Codex and OMP CLIs. Shared oMLX gate currently selects `GLM-OCR-bf16` for OCR and Hy-MT2 for translation; the product OCR target therefore remains fail-closed until policy reconciliation.
- 2026-08-11: External decision record — keep Pydantic v2 strict models/manual closed-set checks as the executable loader boundary and emit/validate declared schema metadata without adding a new dependency in this task; JSON Schema 2020-12 remains the interchange vocabulary. Paddle official documentation identifies `PaddleOCR-VL-1.6` as the document-parsing model and its official API as asynchronous typed job submission/polling, so the role must not be mislabeled as the ordinary OCR endpoint.
- 2026-08-11 09:10 CST: User requested an immediate no-loss pause. All runner sessions were terminal before pause. Current Task 1.7 pair is 149 passed, but Task 1.7 remains NOT_ACCEPTED because Codex identified unresolved common-Harness P1 gaps (registry-bound role policy, exact artifact/schema binding, selected region, unified OCR/translation gate+real lease, mandatory probe injection, common same-session forwarding, typed output receipt, accurate dispatched semantics, and CLI schema URI→local file resolution). Detailed recovery state and exact original session IDs are frozen in `runs/MW_PROTOCOL_V3_TASK17_NO_LOSS_PAUSE_20260811_091044.md`. The prepared Worker 02 same-session repair prompt exists but was deliberately not preflighted or dispatched after the pause request.
- 2026-08-11 16:50 CST: Same-session repairs closed all functional findings. The dispatcher now revalidates authoritative node/skill/role/artifact bindings before every side effect; the four adapters enforce probe, session, fallback, receipt, allowlist, workload-gate and lease contracts without weakening the user-approved model profile.
- 2026-08-11 16:50 CST: Codex verification passed: focused Task 1.7 tests `200 passed`; full Protocol v3 suite `870 passed, 1 warning, 101 subtests passed`; Ruff and format checks passed; nine Task 1.7 Python files compiled in memory; frozen-plan SHA-256 remained exact; `git diff --check` passed; medical-monitoring diff remained empty.
- 2026-08-11 16:50 CST: Fresh-context Luna functional acceptance returned `READY`, `P0=P1=P2=P3=P4=0`, in CLI compatibility session `019fefbf-636b-7462-9720-2b4629f83a80`. Native App spawn had explicitly rejected the unavailable Luna selector, so the declared CLI compatibility route was used. A separate same-session pass that expanded into hostile same-process introspection was stopped as out-of-scope security testing and is not counted as product acceptance evidence.
- 2026-08-11 16:50 CST: Task 1.7 is functionally accepted. No service, live provider, OCR, translation or medical-monitoring workflow was run. The GLM-versus-Paddle shared-gate mismatch remains an intentional fail-closed integration state, not a Task 1.7 defect. Next safe action is frozen-plan Task 1.8 storage PoC.
