# Protocol v3 Task 1.8 验收检查点

时间：2026-08-11 22:47 CST
状态：`ACCEPTED / SQLITE_SELECTED / PRODUCT_ACTIVATION_FAIL_CLOSED`

## 结论

- 本地/私有单工作站目标存储锁定为 SQLite 3.53.1。
- PostgreSQL 18.4 通过同一套 8/8 不变量，保留为多机/高并发 scale-up 路径，不在本任务激活。
- Memory 在同一公共 suite 中通过 5 个功能不变量，并对 crash、backup/restore、pre-switch rollback 三项耐久能力显式 fail closed。
- `selected.py` 只暴露存储中立的选择/能力/工厂表面；产品 adapter 未接线，运行时继续 `not_ready`，无静默回退。

## 决定性证据

- SQLite digest：`64a56f66e4300b318f6586803151f475e2ad8de9a74d0acfad14fe46a81adad8`。
- PostgreSQL digest：`fce59b62be3dc94d069affe9c76cdd0d9f41e8340459cb9fc9336ff96fde8630`。
- Memory digest：`8fc8a060a7ab1d27f1f780287e0895c97c7f76b49f8bb5b5226ee7423fc84a7b`；5 pass / 3 explicit fail。
- Codex：7/7 digest 重算；focused 16 passed；full 886 passed + 101 subtests；plan SHA `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`；monitoring diff 0；PostgreSQL process 0。
- Cursor manager 原 session `22119497-40ea-428d-b7e8-a4f0d66dce6e`：Recovery 01 `READY`。

## 会话与证据保留

- Worker 01：`019ff00a-9afc-7000-80c9-eaa0a9e136c9`。
- Worker 02：`019ff00a-9af3-7000-b7ab-0e0cf2021adb`。
- Worker 03：`019ff120-5bc1-7000-be3d-4e7e0fb1db71`。
- Manager：`22119497-40ea-428d-b7e8-a4f0d66dce6e`。
- 全部 prompts、stdout、失败/拒绝/接受报告保留；不删除工具调用证据。
- 验收后仅删除可再生的 14 MB task-local PostgreSQL venv 与 Python `__pycache__`；安装/许可/benchmark/runner 证据完整保留。
- 执行过程证据已归档至 `archives/execution/mw_protocol_v3_phase1_task18_20260811/`；`cleanup_manifest.json` 记录原路径与归档根。

## 下一安全动作

1. 原子提交 Task 1.8。
2. 归档 execution 过程文件但不删除证据。
3. 进入冻结计划 Task 1.9：application service、Agent⑤控制面与 v3 API 骨架。
4. Task 1.9 不得把产品存储误报为已激活；若其集成需要真实持久化 UoW，应先按已接受 SQLite PoC 实现产品 adapter/version gate，或保持明确 fail-closed。
