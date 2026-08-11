# Worker 01 同会话定向修复

Hard boundaries:
- Work only inside the current workspace root (`.`).
- Read these files only as the initial set: `AGENTS.md`, `context/mw_protocol_v3_phase2_task21_20260812_execution_context.md`, `plans/codex_execution_mw_protocol_v3_phase2_task21_20260812.md`, and the three files below. Additional evidence reads must remain within the same Task 2.1 PoC boundary and be reported.
- Do not touch product source, medical-monitoring, services, databases, security testing, or other workers' case files/tests.
- Tools stay enabled. Do not install dependencies.
- Runner-managed report path: `runs/execution/mw_protocol_v3_phase2_task21_20260812/worker_01_repair.md`. Never write this report with a tool; return the complete report in your final response for the runner to persist.

你正在原 Worker 01 会话中修复 Codex 对你产物的反例验证结果。不得改变原任务边界、路由或拥有权。

Exact write ownership 只允许修改：

- `pocs/protocol_v3/orchestrator/__init__.py`
- `pocs/protocol_v3/orchestrator/fakes.py`
- 必要时 `pocs/protocol_v3/orchestrator/cases/__init__.py`

已证实的缺陷：

1. `CaseGraph._assert_closed_vocabulary()` 先用 `_schema_names()` 转成 `frozenset`，导致重复 `SchemaDecl.name` 被提前去重，实际未拒绝。必须从 `self.schemas` 原始序列检查重复，稳定错误码保持 `CC_SCHEMA_DUPLICATE`。
2. `FakeContractError` 的 docstring/报告声称继承 `CaseContractError`，但实际继承 `ValueError`。改为真正继承 `CaseContractError`，不要复制独立的错误字段实现。
3. 为了关闭同类歧义，重复 `root_inputs` 必须 fail closed，使用稳定错误码 `CC_ROOT_INPUT_DUPLICATE`。
4. 同一 `InjectionKind` 的重复声明必须 fail closed，使用稳定错误码 `CC_INJECTION_KIND_DUPLICATE`，从而每个 case 对五类注入各且仅有一个定义。

修复后运行聚焦反例，证明上述四项都拒绝，并重跑你原来的正例、哈希稳定性、深层不可变、项目/分支隔离与幂等性检查。不得新增测试文件，不得修改 case 定义、产品源码、医学监查、服务、数据库或安全性相关内容。

返回紧凑修复报告：变更、检查、实际结果、未解决项。
