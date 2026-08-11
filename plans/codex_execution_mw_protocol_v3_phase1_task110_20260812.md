# Codex Execution Plan: mw_protocol_v3_phase1_task110_20260812

Objective: 实施 Task 1.10 只读 v2→v3 inventory/quarantine、deterministic migration mapping/idempotency、单向 cutover 与旧 mutation guard

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 实现 legacy migration inventory 与 quarantine typed primitives，并用 synthetic immutable inputs 证明零源写入 | `runs/execution/mw_protocol_v3_phase1_task110_20260812/worker_01.md` |
| `worker_02` | 实现 versioned v2_v3_mapping.json、deterministic dry-run mapper 与 idempotent lineage，并覆盖七类 v2 对象和 3,878-row explicit quarantine denominator | `runs/execution/mw_protocol_v3_phase1_task110_20260812/worker_02.md` |
| `worker_03` | 实现 cutover state、全部旧 route/service mutator inventory 与双层 fail-closed guard，并证明 read parity 和 project isolation | `runs/execution/mw_protocol_v3_phase1_task110_20260812/worker_03.md` |

## Manager

| Role | Provider | Model | Report |
|---|---|---|---|
| `finite_code_manager_cursor` | `cursor-cli` | `auto` | `runs/execution/mw_protocol_v3_phase1_task110_20260812/manager.md` |

## Codex Acceptance

- Verify each worker's exact write set and preserve other worker/user changes.
- Run four focused Task 1.10 files plus full `tests/protocol_v3/`, compilation, JSON schema/content checks, plan SHA and medical-monitoring/shared diff.
- Falsify silent drops, fabricated semantic nodes, source mutation, non-deterministic hashes, duplicate semantic effects, lineage overwrite, cutover skip/reverse, project confusion and unclassified mutator drift.
- No rendered surface exists in Task 1.10; browser/visual acceptance is not applicable and will not be claimed.
- Fresh verifier owns `READY`; Codex owns final commit and cleanup.
