# Codex Execution Plan: mw_protocol_v3_phase1_task18_20260811

Objective: 实施并量化验收冻结 Task 1.8 存储 PoC

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 建立数据库中立 contract suite、冻结 benchmark schema 与 SQLite 3.53.1 adapter，证明 CAS/outbox/replay/backup/restore/crash/rollback | `runs/execution/mw_protocol_v3_phase1_task18_20260811/worker_01.md` |
| `worker_02` | 在隔离本地 PostgreSQL 18 环境实施相同 adapter/migrations/backup-restore，记录驱动、许可、部署和失败证据 | `runs/execution/mw_protocol_v3_phase1_task18_20260811/worker_02.md` |
| `worker_03` | 建立跨 memory/SQLite/PostgreSQL 一致性测试、量化决策记录与 selected storage 工厂，反证数据库私有语义未泄漏 | `runs/execution/mw_protocol_v3_phase1_task18_20260811/worker_03.md` |

## Manager

| Role | Provider | Model | Report |
|---|---|---|---|
| `finite_code_manager_cursor` | `cursor-cli` | `auto` | `runs/execution/mw_protocol_v3_phase1_task18_20260811/manager.md` |

## Codex Acceptance

TODO: verify artifacts, tests, source claims, rendered surfaces, blockers, and user-facing completeness.
