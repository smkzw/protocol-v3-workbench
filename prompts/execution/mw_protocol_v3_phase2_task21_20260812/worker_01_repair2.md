# Worker 01 同会话底座收口修复

Hard boundaries:
- Work only inside the current workspace root (`.`).
- Read these files only as the initial set: `AGENTS.md`, `context/mw_protocol_v3_phase2_task21_20260812_execution_context.md`, `plans/codex_execution_mw_protocol_v3_phase2_task21_20260812.md`, `pocs/protocol_v3/orchestrator/__init__.py`, `pocs/protocol_v3/orchestrator/fakes.py`, `pocs/protocol_v3/orchestrator/cases/__init__.py`.
- Exact write ownership remains only `pocs/protocol_v3/orchestrator/__init__.py`, `pocs/protocol_v3/orchestrator/fakes.py`, and if strictly necessary `pocs/protocol_v3/orchestrator/cases/__init__.py`.
- Do not edit either Worker 02 case, sample-size, tests, product source, medical-monitoring, services, databases, or security-related files.
- Tools stay enabled; install nothing.
- Runner-managed report path: `runs/execution/mw_protocol_v3_phase2_task21_20260812/worker_01_repair2.md`. Never write that report with tools; return it as the final response.

继续原 Worker 01 会话，修复 Codex 在 Worker 02 验收中证实的共享底座漏洞：

1. `CaseGraph.model_copy(update={"edges": ("junk",)})` 能制造未重校验的非法图，且后续只到 hash 才以非类型错误崩溃。在 PoC 合同基类中关闭这一绕过：覆写 `model_copy` 或提供等价的强制重验证实现，使任何 `update` 都经过完整 Pydantic 验证与所有 model validators；不带 update 的 copy 也不得破坏不可变性。
2. `FakeArtifactStore.put` 与 `FakeReservationLedger.reserve` 必须拒绝未知 `node_id`。ArtifactStore 还必须拒绝 `schema_name != graph.node(node_id).output_schema`，不能只检查 schema 在图中存在。使用稳定的统一合同错误族。
3. fake 内部所有状态替换不得使用不重验证的 `model_copy(update=...)`。已证实 `complete(..., "bad")` 会接受非 64 hex 输出哈希，`fail(..., "")` 会接受空错误码。改为经完整模型验证的替换路径，并确保完成/失败/unknown-outcome 的终态字段组合一致。
4. 保持原有四项修复、确定性、哈希稳定、项目/分支隔离和幂等语义。

运行聚焦反例，明确证明：非法 graph copy、未知 node、错配 output schema、非法 output hash、空 error code 全部 fail closed；正常的 graph copy/预留/启动/完成/失败/unknown-outcome 及幂等恢复仍通过。不新增测试文件。

返回紧凑修复报告：变更、错误码、实际正反例结果、未解决项。
