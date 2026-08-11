# Codex Execution Plan: mw_protocol_v3_phase2_task21_20260812

Objective: 实施冻结计划 Task 2.1 三条高风险 orchestrator PoC typed case contracts 与 deterministic fakes，不接调度器或产品运行时

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 建立 shared immutable graph/node/injection contracts 与 deterministic fakes，仅写 orchestrator __init__/cases __init__/fakes | `runs/execution/mw_protocol_v3_phase2_task21_20260812/worker_01.md` |
| `worker_02` | 基于 shared contracts 实现 eligibility 与 objective-estimand-endpoint case definitions，仅写两份 case 文件 | `runs/execution/mw_protocol_v3_phase2_task21_20260812/worker_02.md` |
| `worker_03` | 实现 sample-size case 并编写唯一 integrated test_case_contracts.py，核验三图闭合、恢复并发注入、隔离和 fail-closed | `runs/execution/mw_protocol_v3_phase2_task21_20260812/worker_03.md` |

## Manager

| Role | Provider | Model | Report |
|---|---|---|---|
| `finite_code_manager_cursor` | `cursor-cli` | `auto` | `runs/execution/mw_protocol_v3_phase2_task21_20260812/manager.md` |

## Codex Acceptance

Serial execution only. Verify immutable typed graph/node/output/injection contracts; graph/version hash determinism; closed enum/schema/dependency/cycle validation; three clinically meaningful synthetic case topologies; stable side-effect keys; kill/restart/concurrent/old-graph injection points; project/branch isolation; deep immutability; no scheduler/product/provider/storage/security side effects; focused/full tests; plan hash and protected-path diff. Manager and fresh verifier are read-only; Codex owns acceptance.
