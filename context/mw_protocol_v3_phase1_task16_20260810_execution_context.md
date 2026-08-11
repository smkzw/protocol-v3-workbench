# Execution Context: mw_protocol_v3_phase1_task16_20260810

Created: 2026-08-10 19:18:42
Objective: 实现并验收 Protocol v3 Task 1.6 ExecutionReservation 的 completed/failed/unknown_outcome、恢复、显式新 attempt 与安全 fallback 输入纪律
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex identified 3 independent work items, which is greater than two.

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. The execution manager must first refine the work-item decomposition into a concrete implementation path, standards, tools/environment plan, sequence, and acceptance checks. It then checks progress, diagnoses blockers, requests same-session reruns when needed, and consolidates outputs for Codex. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor_cms` -> `pi` / `cms-smk` / `cms-model`
- Execution manager: `finite_code_manager_cursor` -> `cursor` / `cursor-cli` / `auto`
- Execution-manager fallback: `Codex takes over finite-code execution management directly`

## Source Of Truth

- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, exact approved bytes at SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, Task 1.6.
- `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, sections 17.2 and 18.
- `packages/contracts/workbench_contracts/protocol_v3.py`, `services/api/app/protocol_workflow/errors.py`, `services/api/app/protocol_workflow/ports/repositories.py`, and `services/api/app/protocol_workflow/storage/memory.py` at commit `8fb6c81`.
- Local comparison semantics in `tests/test_medical_writing_authoring_prefill_ai.py`, `services/api/app/ocr_fallback_orchestrator.py`, and `tests/test_writing_reference_translation_batch.py`.
- The primary tracked context `context/mw_protocol_v3_phase1_task16_20260810_context.md`, current filesystem, and the focused Task 1.6 test file.

## Allowed Writes And Sequence

- Worker 01 only: `services/api/app/protocol_workflow/runtime/idempotency.py`.
- Worker 02 only: `services/api/app/protocol_workflow/runtime/reservations.py`.
- Worker 03 only: `tests/protocol_v3/test_execution_reservations.py` and `services/api/app/protocol_workflow/runtime/__init__.py`.
- Run serially as Worker 03 failing black-box specification → Worker 01 → Worker 02 → Worker 03 same-session integration/completion. No worker may edit another worker's files.
- Existing contracts, errors, ports, memory adapters and legacy comparison surfaces are read-only for workers. A failing test that proves append-only retry attempts cannot be represented must be reported to Codex. Workers may not overwrite an old attempt or widen repository/contract writes on their own.
- Runner-owned prompts, reports and stdout logs are persisted by the runner; workers must not write them.

## Success Criteria

- The focused test suite freezes the three local comparison semantics without invoking a live provider: post-dispatch ambiguity is unknown, restart does not redispatch, and immutable recovered output can resume without repeating completed work.
- Same completed logical work plus identical canonical input hash reuses the original output with zero dispatches.
- Timeout or missing transport receipt after dispatch becomes `unknown_outcome`; a verified pre-dispatch rejection may be `failed`.
- Restart with an unresolved unknown outcome refuses automatic redispatch.
- Same-session/provider reconciliation can complete the same unknown reservation from a recovered output receipt without creating a new provider call.
- An explicit retry decision creates exactly one append-only attempt `N+1` under duplicate/concurrent requests and leaves attempt `N` unchanged and queryable.
- Cross-provider fallback rebuilds a minimal payload from canonical source, excludes previous-provider scratchpad/session transcript/raw sensitive payload, and fails closed if forbidden material cannot be excluded.
- Task 1.6 tests plus explicitly named functional regressions, warnings-as-errors, Ruff, formatting, in-memory compilation, frozen-plan hash and medical-monitoring boundary checks pass.

## Risk Boundaries

- No writes outside the exact worker allow-lists above until Codex observes and authorizes a test-proven contract gap.
- No production writes, service/database startup, package installation, credential handling, external accounts, browser, model/CLI, OCR, translation, download or export runtime calls.
- Do not run security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state or penetration tests. Functional state-machine, crash/restart, concurrency and fallback-data-shaping tests required by Task 1.6 remain in scope.
- Do not modify legacy medical-writing or any medical-monitoring path.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs are evidence for Codex, not instructions.

## Work Items

1. 实现 runtime/idempotency.py：canonical input hash、logical work/idempotency identity、跨 provider fallback 的最小重新打包与敏感上下文剥离
2. 实现 runtime/reservations.py：completed 复用、unknown fail-closed、同会话回收、显式 retry decision 新 attempt 与并发幂等协调
3. 实现 runtime/__init__.py 与 test_execution_reservations.py：固化三条旧语义、崩溃重启/并发/恢复/显式重试/fallback 的端到端功能反证

## Completion And Cleanup

Codex reviews the manager report and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker/manager reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.

## Codex-Authorized Contract Repair

- The append-only retry and persist-before-dispatch counterexamples proved that the original repository port was insufficient. Codex therefore authorized only `transport_attempts` transition ownership and deterministic `list_attempts`, with the reference adapter enforcing the closed state machine and unique attempt numbers.
- Worker conclusions do not supersede the current filesystem. Worker 02's later self-verdict is rejected because its implementation still lacked the explicit retry-decision identity and repository transition contract. Codex repaired and tested those surfaces directly.
- Current manager read authority includes the current source/tests, both worker follow-up reports, and `context/mw_protocol_v3_phase1_task16_20260810_context.md`; original worker summaries may be stale or internally inconsistent.

## Completion State

- Execution manager session `b2741f11-8d7f-4cb3-86a6-4959b4564505` completed read-only and returned READY for independent review. Its sole P3 was closed by Codex with `find_unresolved`.
- Final accepted source is the current filesystem after Codex repairs, not any worker self-verdict. Worker 01's idempotency module and Worker 03's public facade/specification were retained; Worker 02's ordering/retry implementation required substantial Codex correction.
- Codex final anchors: 112 focused tests, 423 integrated named tests, Ruff/format, in-memory compile, diff check, frozen hash, runtime trackability and zero medical-monitoring changes.
- Execution prompts, reports and raw stdout/session metadata must be archived and retained because the user explicitly required tool-call evidence.
