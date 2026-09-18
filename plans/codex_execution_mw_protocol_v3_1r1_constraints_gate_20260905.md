# Codex Execution Plan: mw_protocol_v3_1r1_constraints_gate_20260905

Objective: Task 1R.1约束完整性修复及真实复验；保留原失败包，不改历史回执，不关闭任务。

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 修复SQLite产品adapter对同名同列但丢失主键、唯一或非空约束的数据库误接纳，并运行现存反例与回归。 | `runs/execution/mw_protocol_v3_1r1_constraints_gate_20260905/worker_01.md` |

## Manager

No execution manager is dispatched for this route; Codex reviews the worker outputs directly.

## Codex Acceptance

Pending. Re-run the eight independent probes, focused and full Protocol v3 tests against frozen returned hashes, inspect constraints and foreign-file safety, obtain independent storage review, and audit this actual execution packet. Earlier failed execution history remains failed and retained. No UI/service/clinical or full-product acceptance is implied. This one coherent work item uses the latest global policy and live guard's one-worker route; no fabricated manager or extra work items.
