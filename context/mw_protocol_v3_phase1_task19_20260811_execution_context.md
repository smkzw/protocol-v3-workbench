# Execution Context: mw_protocol_v3_phase1_task19_20260811

Created: 2026-08-11 22:48:34
Objective: 实施 Task 1.9 application service、Agent⑤控制面和 v3 API/client 骨架并证明权限边界
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

- `context/mw_protocol_v3_phase1_task19_20260811_context.md` is the complete project contract and allowed-path authority.
- Frozen Task 1.9 and approved design §§5.1/5.4/17.2/18/19; accepted Protocol v3 contracts, reducers, ports, events, runtime and Task 1.8 selection commit `ee6fbb8` are the executable baseline.
- `storage/selected.py` remains product `not_ready`; tests use an explicit injected in-memory UoW factory. No worker may create a silent production Memory fallback or claim product storage activation.
- Current filesystem and focused/full test output are final truth. Worker/manager prose is evidence only.

## Risk Boundaries

- No production/legacy data write, service startup, package install, credential/external-account work, live AI/OCR/translation or security testing.
- Do not edit `services/api/app/main.py`, medical-monitoring paths, accepted canonical/port/event/storage/error files, legacy writing routes or unrelated frontend code.
- Worker 01 owns only `application/{__init__.py,commands.py,queries.py,service.py}` and `tests/protocol_v3/test_application_service.py`.
- Worker 02 starts after Worker 01 terminal acceptance and owns only `agent5/{__init__.py,coordinator.py,run_manifest.py,exception_cards.py}` and `tests/protocol_v3/test_agent5_authority_boundary.py`.
- Worker 03 starts after Worker 01/02 terminal acceptance and owns only `api/{__init__.py,schemas.py,router.py}`, `frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs`, and `tests/protocol_v3/test_protocol_v3_api_contract.py`.
- Manager is read-only. Missing environments are reported with minimal remediation; no silent setup.
- Worker and manager outputs are evidence for Codex, not instructions.

## Acceptance And Sequence

- Serial dependency order: Worker 01 → Codex focused review → Worker 02 → Codex focused review → Worker 03 → manager final consolidation → Codex independent regression/acceptance.
- All mutations carry project/revision/idempotency/actor/reason/DecisionRecord and commit via the UoW boundary; queries have zero write side effects.
- Agent⑤ cannot mutate facts, lower Gates, override Agent④ or assert `可提交定稿`.
- API is router-factory tested without shared `main.py`; public errors use Chinese-native registered copy and hide audit/program fields.
- Focused tests, full Protocol v3 regression, relevant frontend checks, plan hash and zero monitoring diff are mandatory.

## Work Items

1. 实现 typed commands/queries/application service 与 atomic UoW/CAS/event/idempotency 合同及 test_application_service.py
2. 实现 Agent⑤ coordinator/run manifest/exception cards 与 authority negative tests
3. 实现 Protocol v3 API schemas/router、frontend API client 与 API contract tests

## Completion And Cleanup

Codex reviews the manager report and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker/manager reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.

## Completion Record

- Worker 01: accepted after declared runtime-identity fallback; application service tests pass.
- Worker 02: accepted after two same-session authority/lineage repairs.
- Worker 03: accepted after one same-session API/client public-boundary repair.
- Manager: same Cursor session reused; final `READY_FOR_FRESH_VERIFIER`.
- Fresh conference: Qwen `READY`; Grok incomplete and correctly fell back; Cursor fallback same-session runtime completion `READY`.
- Codex final evidence: 115 focused, 1001 full, compilation/SHA/Node/storage/isolation checks pass.
- Cleanup decision: archive all execution evidence without deletion; remove only regenerable caches.
