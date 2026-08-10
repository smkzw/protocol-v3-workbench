# Codex Execution Plan: mw_protocol_v3_phase1_task13_20260810

Objective: 按批准计划实现 Protocol v3 repository、artifact 与 unit-of-work ports 及内存/本地实现，证明幂等内容寻址与 CAS，不开展安全性测试

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 定义 get-current、append-event、CAS-save、outbox/inbox、reservation 与 read-model repository ports | `runs/execution/mw_protocol_v3_phase1_task13_20260810/worker_01.md` |
| `worker_02` | 定义 artifact content-addressed port 和 unit-of-work port，并实现内存 repository 与本地 artifact store | `runs/execution/mw_protocol_v3_phase1_task13_20260810/worker_02.md` |
| `worker_03` | 新增 repository/artifact functional contract tests，证明 hash 幂等、revision、CAS 和应用服务边界 | `runs/execution/mw_protocol_v3_phase1_task13_20260810/worker_03.md` |

## Manager

| Role | Provider | Model | Report |
|---|---|---|---|
| `finite_code_manager_cursor` | `cursor-cli` | `auto` | `runs/execution/mw_protocol_v3_phase1_task13_20260810/manager.md` |

## Codex Acceptance

- Inspect every changed source/test file and manager report.
- Run the two Task 1.3 tests, Task 1.1/1.2 regression tests, compilation and `git diff --check`.
- Confirm no medical-monitoring path changed and no runtime/cache artifact remains.
- Obtain an isolated verifier verdict before acceptance; worker/manager self-review is not proof of done.
