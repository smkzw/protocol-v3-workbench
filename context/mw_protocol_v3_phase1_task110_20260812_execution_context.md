# Execution Context: mw_protocol_v3_phase1_task110_20260812

Created: 2026-08-12 01:25:22
Objective: 实施 Task 1.10 只读 v2→v3 inventory/quarantine、deterministic migration mapping/idempotency、单向 cutover 与旧 mutation guard
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

- `context/mw_protocol_v3_phase1_task110_20260812_context.md` is the complete project contract, allowed-path authority and success criterion.
- Frozen Task 1.10, approved design strangler rules, accepted Task 1.9 commit `795fa3f`, current v2 model/repository/route source and v3 contracts are the only authorities.
- Live databases are not source inputs. Synthetic immutable records and current source code are the execution evidence.
- The seven required families are StudyDefinition, Journey/stage drafts, working copies/snapshots, corpus/evidence, decisions/approvals, Protocol documents and artifact lineage.

## Risk Boundaries

- No live/runtime database access or production writes; no service startup.
- No edits to `services/api/app/main.py`, any v2 service/repository, Task 1.9 source, accepted v3 contracts, medical-monitoring or unrelated frontend.
- Worker 01 owns only `legacy/{__init__.py,migration_inventory.py,quarantine.py}` and `test_v2_v3_migration_dry_run.py`.
- Worker 02 starts after Worker 01 and owns only `legacy/migration_map.py`, `config/.../v2_v3_mapping.json` and `test_v2_v3_migration_idempotency.py`.
- Worker 03 starts after Worker 01 and owns only `legacy/{cutover_state.py,mutation_route_inventory.py,mutation_guard.py}`, `test_legacy_read_parity.py` and `test_legacy_mutation_guard.py`.
- Manager is read-only. No worker edits another worker's files or process reports.
- Task 1.11 security tests are prohibited; functional cutover/project isolation only.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs are evidence for Codex, not instructions.

## Work Items

1. 实现 legacy migration inventory 与 quarantine typed primitives，并用 synthetic immutable inputs 证明零源写入
2. 实现 versioned v2_v3_mapping.json、deterministic dry-run mapper 与 idempotent lineage，并覆盖七类 v2 对象和 3,878-row explicit quarantine denominator
3. 实现 cutover state、全部旧 route/service mutator inventory 与双层 fail-closed guard，并证明 read parity 和 project isolation

## Completion And Cleanup

Codex reviews the manager report and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker/manager reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.

## Acceptance Sequence

Worker 01 → Codex focused review → Worker 02 → Codex focused review → Worker 03 → manager read-only consolidation → fresh independent verifier → Codex final acceptance. Exact same-session repairs precede any fallback.

## Current Execution State

- Worker 01: `ACCEPTED_BY_CODEX` after one same-session repair; session `019ff1dd-fec4-7000-85f0-df4dd3ccfcd6`.
- Worker 02 primary: terminally incomplete; original session `019ff1f3-8cb2-7000-b56f-dde6d7495da1` could not be resumed (`Session not found`).
- Worker 02 declared fallback: `ACCEPTED_BY_CODEX` after two same-session P1 repairs plus bounded Codex completion; session `019ff1fa-fdb7-7000-a01c-8985e7b81e55`.
- Worker 03: `ACCEPTED_BY_CODEX` after one same-session P1 repair; session `019ff239-6131-7000-b581-d2ba19052dc4`. The repaired inventory contains 101 legacy-write routes and 94 legacy-write services; the investigator-brochure route/service bypass is closed without changing medical-monitoring.
- Manager: `READY_FOR_FRESH_VERIFIER`; Cursor session `7656b349-59bf-412a-941f-7b1610c42c34`, 341.049 s, no fallback and no writes.
- Fresh verifier first pass: `NOT_READY` by Codex despite nominal participant READY because Qwen produced and Codex reproduced the identity-field `covered_fields` drift hole. Worker 02 Recovery 04 closed it in the original fallback session.
- Fresh verifier post-repair: `READY`; Qwen `019ff263-0be7-7000-a840-05fc158df23f` and Grok `0f7edd46-b967-48d4-98e9-e803c92e5f88` reused their original sessions and returned READY without fallback.
- Codex final acceptance: 225 focused, 1,226 full and 3 API-isolation tests pass; plan/mapping hashes and protected-path checks pass. `cleanup-execution` archived all execution prompts/reports/logs under `archives/execution/mw_protocol_v3_phase1_task110_20260812/`; conference evidence remains retained in its original paths.
