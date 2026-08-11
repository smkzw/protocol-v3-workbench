# Worker 01 同会话 helper 收口修复

Hard boundaries:
- Work only inside the current workspace root (`.`).
- Read these files only as the initial set: `AGENTS.md`, `context/mw_protocol_v3_phase2_task21_20260812_execution_context.md`, `plans/codex_execution_mw_protocol_v3_phase2_task21_20260812.md`, `pocs/protocol_v3/orchestrator/__init__.py`, and the three case modules as read-only fixtures.
- Exact write ownership: only `pocs/protocol_v3/orchestrator/__init__.py`.
- Do not edit fakes, case definitions, tests, product source, medical-monitoring, services, databases, or security files.
- Tools stay enabled; install nothing.
- Runner-managed report path: `runs/execution/mw_protocol_v3_phase2_task21_20260812/worker_01_repair3.md`. Never write it via tools; return it in the final response.

继续原 Worker 01 会话，修复 Worker 03 发现且 Codex 已复现的两个同源 helper 缺陷：

1. `CaseGraph.topological_order()` 的 indegree 按不同上游 node 计数，但弹出 source 后却按每条 typed edge 重复递减。同一 source→target 同时有 DATA/GATE 边时会过早释放 target。改为每个已完成 source 对每个 distinct target 最多递减一次，并保持 node_id 确定性 tie-break。
2. `node_dependencies()` 的契约是返回依赖 node IDs，同一依赖的 DATA/GATE 并行边不得造成重复 ID。返回确定性排序的 distinct source IDs。

修复后在三张现有图上证明：
- helper 顺序包含所有 node 且每条 edge 的 source 严格早于 target；
- sample-size 的 `statistical_review` 早于 `sample_size_decision_lock`；
- `node_dependencies()` 与 node 声明的 distinct `depends_on` 完全一致；
- 无环图、并行 typed edge 图、cycle fail-closed 及哈希稳定性回归通过。

不新增测试文件。返回紧凑修复报告。
