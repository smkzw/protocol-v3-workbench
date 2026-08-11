# Execution Context: mw_protocol_v3_phase1_task18_20260811

Created: 2026-08-11 16:54:33
Objective: 实施并量化验收冻结 Task 1.8 存储 PoC
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex identified 3 independent work items, which is greater than two.

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. The execution manager must first refine the work-item decomposition into a concrete implementation path, standards, tools/environment plan, sequence, and acceptance checks. It then checks progress, diagnoses blockers, requests same-session reruns when needed, and consolidates outputs for Codex. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor_cms` -> `pi` / `cms-smk` / `deepseek-v4-flash` / `max`; historical Worker 01/02 session IDs are retained and receive an in-session route update rather than replacement sessions.
- Execution manager: `finite_code_manager_cursor` -> `cursor` / `cursor-cli` / `auto`
- Execution-manager fallback: `Codex takes over finite-code execution management directly`

## Source Of Truth

- `context/mw_protocol_v3_phase1_task18_20260811_context.md` is the complete task contract and contains the frozen thresholds, official sources, local capability observations and allowed paths.
- Frozen plan Task 1.8 and approved design §§5.2/23.3; accepted repository/UoW/event contracts and in-memory implementation are the executable baseline.
- Current filesystem, pinned install receipts, deterministic benchmark JSON, real database backup/restore/replay evidence and Codex's rerun are final truth.

## Risk Boundaries

- No production writes.
- No credential handling, external account changes, security testing, service startup outside an isolated transient PostgreSQL cluster, or medical-monitoring edits.
- Exact open-source setup is authorized for Worker 02 only: Homebrew `postgresql@18` and a task-local disposable Python 3.12 environment with pinned `psycopg==3.3.4` (LGPL-3.0-only). Record versions/licenses/paths, start PostgreSQL without a persistent LaunchAgent, and stop it in a finally/cleanup path.
- SQLite tests must use `/opt/homebrew/bin/python3.12` linked to fixed SQLite 3.53.1; affected 3.50.4/3.51.0 runtimes fail the candidate preflight.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs are evidence for Codex, not instructions.

## Work Items

1. 建立数据库中立 contract suite、冻结 benchmark schema 与 SQLite 3.53.1 adapter，证明 CAS/outbox/replay/backup/restore/crash/rollback
2. 在隔离本地 PostgreSQL 18 环境实施相同 adapter/migrations/backup-restore，记录驱动、许可、部署和失败证据
3. 建立跨 memory/SQLite/PostgreSQL 一致性测试、量化决策记录与 selected storage 工厂，反证数据库私有语义未泄漏

## File Ownership And Sequence

- Worker 01 may write only `pocs/protocol_v3/storage/{__init__.py,contract_suite.py,sqlite_adapter.py}` and exact task-local benchmark artifacts under `pocs/protocol_v3/storage/results/`.
- Worker 02 may write only `pocs/protocol_v3/storage/postgres_adapter.py`, task-local migration/fixture files under `pocs/protocol_v3/storage/postgres_migrations/`, exact benchmark artifacts under `pocs/protocol_v3/storage/results/`, and a disposable ignored temp cluster/environment. It must not create product `postgres.py` or deployment migrations before selection.
- Worker 03 starts only after Worker 01 and Worker 02 are terminal. It may write `pocs/protocol_v3/storage/decision.md`, `services/api/app/protocol_workflow/storage/selected.py`, `tests/protocol_v3/test_selected_storage_contract.py`, and only after an evidence-backed PostgreSQL selection may create `services/api/app/protocol_workflow/storage/postgres.py` plus `deploy/medical_writing_local/protocol_v3/migrations/`.
- Workers do not edit one another's files. Manager is read-only unless Codex sends a bounded remediation instruction.

## Acceptance And Stop Conditions

- Thresholds are immutable: 8 writers, 1,000 CAS operations, 10,000 events, zero lost/duplicate/hash-chain defects, exact count/hash migration, committed-event RPO 0, exact restore/replay hash, backup→restore→replay under 15 minutes, local CAS p95 ≤500 ms or explicit impact decision.
- No candidate receives PASS from mocks, skipped rows, an unavailable driver/server, affected SQLite runtime, or an untested backup/rollback path.
- Stop on any production/legacy path resolution, medical-monitoring diff, database-private change to domain ports, or inability to stop the transient PostgreSQL cluster.

## Completion And Cleanup

Codex reviews the manager report and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker/manager reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.

## Current Execution State — 2026-08-11 21:36 CST

- Work item 1 (SQLite): CODEX-ACCEPTED after original-session Recoveries 01–04, including one rejected incomplete report and one rejected undeclared OMP model substitution. Final accepted runtime identity was `deepseek/deepseek-v4-flash:max` in original session `019ff00a-9afc-7000-80c9-eaa0a9e136c9`.
- Codex independently reran two fresh full suites, focused lifecycle/crash negative probes and full Protocol v3 regression; exact evidence is in the task context and metrics.
- Work item 2 (PostgreSQL): next. Install/verify the previously authorized open-source runtime without a persistent service, then resume original Worker 02 session `019ff00a-9af3-7000-b7ab-0e0cf2021adb` on the current declared route.
- Work item 3 and manager remain held until PostgreSQL reaches a terminal evidence state.

## Final Execution State — 2026-08-11 22:47 CST

- Work item 1: accepted SQLite 3.53.1 candidate, including two Codex fresh runs and fail-closed crash/version probes.
- Work item 2: accepted PostgreSQL 18.4 candidate after two Codex Unix-socket-only fresh reruns; all disposable clusters stopped/deleted.
- Work item 3: accepted SQLite selection, storage-neutral `selected.py`, Memory 5/8 executable receipt and focused contract tests. Worker 03 retained session identity through the night-route switch.
- Execution manager: original Cursor session recovery verdict `READY`; read-only and independently grounded in source/JSON/tests.
- Codex: seven digests recomputed, Memory fresh run 5 pass/3 explicit fail, 16 focused and 886 full tests passed, plan hash stable, monitoring diff zero, PostgreSQL absent.
- Product storage is intentionally `not_ready` until the post-selection product SQLite adapter is implemented; this is not a Task 1.8 PoC blocker.
- Task 1.8 status: `ACCEPTED / READY FOR ATOMIC COMMIT`; next planned task after commit/archival is Task 1.9.
