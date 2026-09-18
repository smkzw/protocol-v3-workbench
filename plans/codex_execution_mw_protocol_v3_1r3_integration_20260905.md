# Codex Execution Plan: mw_protocol_v3_1r3_integration_20260905

Objective: 实现Protocol v3 Task1R.3真实SQLite与API集成测试，依据当前Trellis PRD/design/implement。仅合成临时数据，不启动服务/模型或修改live；产品缺陷先报告红测，禁止改旧expected。

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 补真实SQLite事务/重启/回放/WAL一致backup-restore/幂等及实际挂载API集成测试；仅写tests/protocol_v3/integration和新测试证据，具体读集与边界见context。 | `runs/execution/mw_protocol_v3_1r3_integration_20260905/worker_01.md` |

## Manager

No execution manager is dispatched for this route; Codex reviews the worker outputs directly.

## Codex Acceptance

TODO: verify artifacts, tests, source claims, rendered surfaces, blockers, and user-facing completeness.
