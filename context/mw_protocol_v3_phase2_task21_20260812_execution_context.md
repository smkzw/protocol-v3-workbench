# Execution Context: mw_protocol_v3_phase2_task21_20260812

Created: 2026-08-12 05:30:00
Objective: 实施冻结计划 Task 2.1 三条高风险 orchestrator PoC typed case contracts 与 deterministic fakes，不接调度器或产品运行时
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex identified 3 independent work items, which is greater than two.

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. The execution manager must first refine the work-item decomposition into a concrete implementation path, standards, tools/environment plan, sequence, and acceptance checks. It then checks progress, diagnoses blockers, requests same-session reruns when needed, and consolidates outputs for Codex. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor_cms` -> `pi` / `cms-smk` / `deepseek-v4-flash`
- Execution manager: `finite_code_manager_cursor` -> `cursor` / `cursor-cli` / `auto`
- Execution-manager fallback: `Codex takes over finite-code execution management directly`

## Source Of Truth

- Complete task contract: `context/mw_protocol_v3_phase2_task21_20260812_context.md`.
- Frozen plan Task 2.1 and approved design application-truth/orchestrator-replaceability boundary.
- Accepted current Protocol v3 contracts, ports, reservation/runtime registry and storage decision are read-only design inputs.
- No external scheduler/framework is selected here; no network discovery or package adoption is needed for typed case definitions.

## Risk Boundaries

- Product writes are limited to `pocs/protocol_v3/orchestrator/` and its Task 2.1 tests; task records use this task's declared surfaces.
- Existing contracts/services/storage/legacy/main/frontend/medical-monitoring are read-only.
- Work order is serial: Worker 01 accepted before Worker 02; Workers 01–02 accepted before Worker 03. No shared-file concurrent writes.
- Worker 01 owns only `pocs/protocol_v3/orchestrator/{__init__.py,fakes.py,cases/__init__.py}`.
- Worker 02 owns only `cases/{eligibility.py,objective_estimand_endpoint.py}`.
- Worker 03 owns only `cases/sample_size.py` and `tests/test_case_contracts.py`.
- No LangGraph/scheduler, services, databases, provider calls, package install, product wiring or security tests.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs are evidence for Codex, not instructions.

## Work Items

1. 建立 shared immutable graph/node/injection contracts 与 deterministic fakes，仅写 orchestrator __init__/cases __init__/fakes
2. 基于 shared contracts 实现 eligibility 与 objective-estimand-endpoint case definitions，仅写两份 case 文件
3. 实现 sample-size case 并编写唯一 integrated test_case_contracts.py，核验三图闭合、恢复并发注入、隔离和 fail-closed

## Completion And Cleanup

Codex reviews the manager report and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker/manager reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.

## Acceptance Sequence

Worker 01 → Codex shared-contract review → Worker 02 → Codex case review → Worker 03 → Codex focused/full checks → read-only Cursor manager → fresh independent verifier → Codex acceptance. Same-session repair precedes fallback.

## Closure

- Worker sessions: W01 `019ff2bd-ed6c-7000-a7b2-ba4f825c2097`; W02 `019ff2ce-64c9-7000-ad8f-0808dd53b1e7`; W03 `019ff2da-0434-7000-9899-1eee2ce21f2b`; manager `8c16ecd8-8919-4efc-b26a-91c230645a29`.
- Final worker state: accepted; 75 focused and 1,226 full tests plus 101 subtests pass. Manager's `READY_FOR_FRESH_VERIFIER` was read-only and preceded the final four regressions.
- Independent state: Qwen `TASK21_READY` after same-session repair recheck; Grok unusable after exhausted same-session recovery. Codex final status is accepted with participant degradation.
- Cleanup decision: retain all execution/conference artifacts and raw tool-call logs in place for no-loss pause; do not run `cleanup-execution` now.
