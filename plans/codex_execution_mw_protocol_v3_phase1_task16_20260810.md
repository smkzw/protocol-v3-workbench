# Codex Execution Plan: mw_protocol_v3_phase1_task16_20260810

Objective: 实现并验收 Protocol v3 Task 1.6 ExecutionReservation 的 completed/failed/unknown_outcome、恢复、显式新 attempt 与安全 fallback 输入纪律

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 实现 runtime/idempotency.py：canonical input hash、logical work/idempotency identity、跨 provider fallback 的最小重新打包与敏感上下文剥离 | `runs/execution/mw_protocol_v3_phase1_task16_20260810/worker_01.md` |
| `worker_02` | 实现 runtime/reservations.py：completed 复用、unknown fail-closed、同会话回收、显式 retry decision 新 attempt 与并发幂等协调 | `runs/execution/mw_protocol_v3_phase1_task16_20260810/worker_02.md` |
| `worker_03` | 实现 runtime/__init__.py 与 test_execution_reservations.py：固化三条旧语义、崩溃重启/并发/恢复/显式重试/fallback 的端到端功能反证 | `runs/execution/mw_protocol_v3_phase1_task16_20260810/worker_03.md` |

## Manager

| Role | Provider | Model | Report |
|---|---|---|---|
| `finite_code_manager_cursor` | `cursor-cli` | `auto` | `runs/execution/mw_protocol_v3_phase1_task16_20260810/manager.md` |

## Codex Acceptance

Codex must inspect every diff, reproduce focused functional checks, challenge state-transition legality, restart/concurrency idempotency and old-attempt immutability, verify the frozen-plan hash and medical-monitoring boundary, and obtain an isolated high-risk contradiction verdict before accepting Task 1.6. Worker self-reports cannot close the task.
