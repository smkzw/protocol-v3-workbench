# Execution Context: mw_protocol_v3_phase1_task13_20260810

Created: 2026-08-10 11:50:25
Objective: 按批准计划实现 Protocol v3 repository、artifact 与 unit-of-work ports 及内存/本地实现，证明幂等内容寻址与 CAS，不开展安全性测试
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

- Approved implementation plan: `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.3.
- Approved design: `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, especially Sections 6, 18 and 19.
- Canonical contracts: `packages/contracts/workbench_contracts/protocol_v3.py` at Task 1.1 commit `2817687`.
- Stable workflow errors: `services/api/app/protocol_workflow/errors.py` at Task 1.2 commit `76c0b78`.
- Current worktree and focused functional tests are implementation truth. Global and repository `AGENTS.md` govern execution. The user explicitly stopped all security testing.

## Allowed Writes

- Worker 01: `services/api/app/protocol_workflow/ports/repositories.py` only.
- Worker 02: `services/api/app/protocol_workflow/ports/artifacts.py`, `services/api/app/protocol_workflow/ports/unit_of_work.py`, `services/api/app/protocol_workflow/storage/memory.py`, and `services/api/app/protocol_workflow/artifacts/local_store.py` only.
- Worker 03: `tests/protocol_v3/test_repository_contract.py` and `tests/protocol_v3/test_artifact_store.py` only.
- Runner-owned reports/logs are persisted by the runner. Workers must not write them directly. No worker may edit another worker's assigned files.

## Success Criteria

- Ports are Python `Protocol`/abstract contracts without SQLite/PostgreSQL-specific behavior.
- Repository ports cover get-current, append-event, CAS-save, outbox/inbox, execution reservation and read-model operations with explicit project/aggregate identities.
- Artifact storage is content-addressed: identical bytes replay to the same immutable identity; new bytes under one logical key create a new revision without overwriting prior content.
- The memory implementation enforces current revision CAS, append-only event ordering, idempotent outbox/inbox/reservation identity and project isolation as ordinary functional behavior.
- Unit of work provides explicit commit/rollback semantics and does not expose repositories to Agent/harness contracts.
- Local artifact storage never becomes canonical clinical truth; returned metadata binds logical key, revision, content SHA-256, media type, size and creation time.
- `tests/protocol_v3/test_repository_contract.py` and `tests/protocol_v3/test_artifact_store.py` pass, followed by Task 1.1/1.2 focused regression tests, compilation and diff checks.
- No medical-monitoring path changes.

## Risk Boundaries

- No production/runtime writes, service startup, package installation, credential handling, browser/model/OCR/translation calls or external account changes.
- Do not import or change legacy medical-writing services in this task. Do not modify any medical-monitoring path.
- Do not perform security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state or penetration testing. Tests are limited to the approved functional storage contracts.
- Agent/harness access is a static application boundary: repository objects are application-service dependencies, not fields of `NodeExecutionContract` or worker input/output.
- Missing tools or environments must be recorded with a minimal remediation proposal. Worker and manager outputs are evidence for Codex, not completion authority.
- Dispatch workers serially in dependency order 01 → 02 → 03. Launch each declared route once, retain its session and use long hard waits; do not fallback for latency.

## Work Items

1. 定义 get-current、append-event、CAS-save、outbox/inbox、reservation 与 read-model repository ports
2. 定义 artifact content-addressed port 和 unit-of-work port，并实现内存 repository 与本地 artifact store
3. 新增 repository/artifact functional contract tests，证明 hash 幂等、revision、CAS 和应用服务边界

## Completion And Cleanup

Codex reviews the manager report and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker/manager reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.

## Completion Checkpoint

- Worker outputs: `worker_01` defined repository ports; `worker_02` defined artifact/UoW ports and adapters; `worker_03` added functional contracts. Worker 02/03 same-session follow-ups repaired and proved project-bound reservation isolation.
- Manager session `a5364812-8aa2-456f-a0b0-2fb3f82a9589` returned `READY` for the scoped repair confirmation; it was not treated as independent final acceptance.
- Codex then closed Git-ignore, frozen-plan, deterministic hash binding and UoW lifecycle gaps and ran `151 passed` in a writable environment.
- Fresh Luna verifier round 1 returned `NOT_READY` with three P1 findings. Fresh Luna round 2 session `019fea1d-25df-7982-8df6-9a914d4b5615` returned `READY` after independent source/probe/format/hash checks.
- Native Luna spawn was explicitly rejected by the current App capability surface, so the required labeled CLI compatibility route `/Applications/ChatGPT.app/Contents/Resources/codex exec -m gpt-5.6-luna` was used; no model substitution occurred.
- No service, production runtime, medical-monitoring path, OCR/translation/model workflow or security test was run.
