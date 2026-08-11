# Task Context: mw_protocol_v3_phase2_task21_20260812

Created: 2026-08-12 05:29:18
Objective: 按冻结计划 Task 2.1 定义 eligibility、objective-estimand-endpoint、sample-size 三条高风险编排 PoC 的 typed case contracts、deterministic fakes、precondition/output/side-effect/Gate/owner 与恢复并发注入点，并用聚焦测试验收
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `opencode-go` / `deepseek-v4-flash` / `max`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Frozen Task 2.1 in `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`.
- Approved design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`: application-owned clinical truth, replaceable orchestration, immutable artifacts, typed Gates and Agent⑤ authority boundary.
- Accepted Phase 1 contracts and current source: `packages/contracts/workbench_contracts/protocol_v3.py`; `services/api/app/protocol_workflow/{canonical,events,ports,application,agent5,agent_runtime,storage,legacy}/`; Task 1.6 reservations and Task 1.7 role/skill/harness registries.
- Accepted functional gate commit `d3a7b5f`: `P1-G1_FUNCTIONAL_READY`; Task 1.11/security remains `USER_EXCLUDED`; product SQLite, live migration, product route mounting and release remain blocked.
- Task 2.1 is a PoC contract task. No scheduler/framework is selected or adopted here. Fresh external solution discovery cannot change the frozen contract-only objective; LangGraph/open-source version/license discovery belongs to Task 2.3 before adoption.
- Current filesystem and executed tests outrank delegated prose. No live database, model provider or service is an authority for this task.

## Scope

- In scope: immutable typed case/node contracts for eligibility, objective–estimand–endpoint and sample-size workflows; deterministic clock/ID/decision/artifact fakes; explicit preconditions, output schemas, side-effect keys, Gate/owner, dependency edges and branch/project identity; declared kill-before/kill-after/duplicate-resume/concurrent-decision/old-graph-migration injection points; focused tests.
- Allowed product/PoC writes: `pocs/protocol_v3/orchestrator/__init__.py`, `pocs/protocol_v3/orchestrator/cases/__init__.py`, `pocs/protocol_v3/orchestrator/cases/eligibility.py`, `pocs/protocol_v3/orchestrator/cases/objective_estimand_endpoint.py`, `pocs/protocol_v3/orchestrator/cases/sample_size.py`, `pocs/protocol_v3/orchestrator/fakes.py`, `pocs/protocol_v3/orchestrator/tests/test_case_contracts.py`, and this task's context/plans/prompts/runs/reviews/metrics/archives.
- Out of scope: LangGraph or any orchestrator adapter; typed-facade execution (Task 2.2); package installation; product API/UI; product storage activation; live provider/LLM/OCR/translation; clinical recommendations; services; live databases; Task 1.11/security testing; medical-monitoring; frontend/Word/browser.

## Success Criteria

- Every case is a closed, immutable graph definition with deterministic graph/version hash and explicit project/branch identity; no executable scheduler or clinical truth is stored in graph state.
- Every node declares stable node ID, typed precondition/input contract, typed output artifact/schema, dependency IDs, stable side-effect key template, Gate, owner and allowed failure/retry semantics.
- Eligibility case exposes criterion design, source/evidence binding, cross-criterion contradiction and eligibility lock/review points without making a clinical decision itself.
- Objective–estimand–endpoint case explicitly couples objective, estimand attributes, endpoint definition/assessment/timepoint and cross-objective consistency; it cannot accept a missing link as a complete result.
- Sample-size case binds assumptions/hypothesis/alpha/power/effect/variance/dropout/design inputs to a deterministic calculation artifact, independent statistical review and approved decision; no invented numeric default is treated as fact.
- All four injection classes and old-graph version migration are explicit per case; duplicate/restart/concurrent paths use stable logical keys and must be representable without duplicate semantic effects.
- Branch/project isolation and deep immutability are tested. Unknown node/owner/Gate/schema/dependency or cyclic graph fails closed. Existing product modules are imported read-only or not at all; no service/storage/provider side effects.
- Focused tests, full Protocol v3 regression, compile, plan hash and medical-monitoring/protected diff checks pass. Independent verifier owns READY; Codex owns acceptance.

## Risk Boundaries

- No writes outside the exact PoC/task-record allowlist. Existing Protocol v3 and all medical-monitoring paths are read-only.
- No live services, databases, network/provider/model calls, package installation or product configuration.
- No Task 1.11 or other security testing. Functional project/branch isolation and deterministic replay contracts are allowed.
- Do not encode clinical design recommendations, numeric sample-size assumptions or patient-level data; use labeled synthetic values only.
- Do not depend on LangGraph, scheduler-private state or database-private semantics.
- Workers have disjoint write ownership; shared integration tests are owned only by the final integrator.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-12 05:29:18: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-12 05:35 CST: Task contract frozen around three serial work items: (1) shared immutable case/fake vocabulary; (2) eligibility + objective/estimand/endpoint cases; (3) sample-size case + integrated tests. This order prevents shared-file conflicts. No external dependency is adopted.
- 2026-08-12 07:08 CST: All three execution work items completed. Worker 01 required four same-session repairs; Worker 03 added four final regressions after the fresh verifier's blockers. Final focused result is 75 passed; full Protocol v3 result is 1,226 passed plus 101 subtests.
- 2026-08-12 07:08 CST: Fresh Qwen first vetoed hidden-cycle and mutable-record defects, then returned `TASK21_READY` in the same session after owning-session repair. Grok same-session recovery was exhausted without a usable verdict. Codex accepted Task 2.1 as a functional PoC with degraded second participant; no claim of unanimous conference acceptance.
- 2026-08-12 07:08 CST: User requested no-loss pause. Task 2.2 remains pending and must not start until resume. All runner prompts/reports/stdout/tool events are retained in place; no cleanup, service, provider, database, product wiring, medical-monitoring or security action was performed.
