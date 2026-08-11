# Worker 03 同会话测试收口

Hard boundaries:
- Work only inside the current workspace root (`.`).
- Read these files only as the initial set: `AGENTS.md`, `context/mw_protocol_v3_phase2_task21_20260812_execution_context.md`, `plans/codex_execution_mw_protocol_v3_phase2_task21_20260812.md`, `pocs/protocol_v3/orchestrator/__init__.py`, `pocs/protocol_v3/orchestrator/tests/test_case_contracts.py`, and the three case modules.
- Exact write ownership: only `pocs/protocol_v3/orchestrator/tests/test_case_contracts.py`; `sample_size.py` may be changed only if a new regression proves a defect in that file.
- Do not edit shared contracts/fakes, Worker 02 cases, product source, medical-monitoring, services, databases, or security files.
- Tools stay enabled; install nothing; do not start services.
- Runner-managed report path: `runs/execution/mw_protocol_v3_phase2_task21_20260812/worker_03_repair.md`. Never write it via tools; return it in the final response.

Worker 01 已在原会话修复 `topological_order()` 对并行 typed edges 重复递减 indegree 的缺陷，并使 `node_dependencies()` 返回 distinct source IDs。继续原 Worker 03 会话做最小测试收口：

1. 将 `test_topological_order_helper_returns_deterministic_permutation` 升级为真正的 helper contract 测试：除了确定性/全节点，必须断言每条 typed edge 的 source 严格早于 target。
2. 增加或加强断言：每个 node 的 `graph.node_dependencies(node_id)` 等于确定性排序的 distinct `node.depends_on`，并且 sample-size 中 `statistical_review` 早于 `sample_size_decision_lock`。
3. 如果现有并行 DATA/GATE 边还未被明确作为回归 fixture，利用三张真实图中已有边直接覆盖，不另造一套产品实现。
4. 重跑聚焦 Task 2.1 测试、compile 以及不含安全性测试的 Protocol v3 功能回归。保护路径 diff 必须仍为空。

返回紧凑修复报告：变更的测试、实际计数/结果、保护路径、未解决项。
