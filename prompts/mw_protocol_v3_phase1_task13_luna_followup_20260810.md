复核你上一轮列出的三项 P1 是否已按根因关闭。保持只读，不修改文件，
不运行任何安全、对抗、权限、路径或恶意输入测试，不启动服务，不触碰医学监查。

重点查看实际差异和新增反例：

1. `InMemoryArtifactStore.read_by_sha256` 是否与 local adapter 一样，按
   `(created_at, logical_key, revision)` 选择确定性绑定，并由双插入顺序测试证明；
2. reservation `_by_id` 是否改为 `(project_id, execution_reservation_id)`，
   同一 ID 跨项目是否独立，逻辑查询不再串项目；
3. 一个 UoW 的全部 mutator 是否共享 `_MutationGuard`，commit/rollback 后
   预先取得的 CAS/event/outbox/inbox/reservation/read-model/artifact 句柄均抛
   `UnitOfWorkClosedError`，而读取仍可用于确定性检查；
4. 主会场已经在可写临时目录环境执行聚焦测试，结果为 151 passed；你可按
   当前只读环境能力复核，不要把只读沙箱无法创建 tmp 误判为产品失败。

同时核对 frozen plan hash、Git 可见性、编译、ruff/diff 状态。只报告仍真实
存在的 P0-P4，给出 READY/NOT_READY。本轮仍是 Task 1.3 confirmatory
acceptance，不计入未来两轮 fresh P0-P4 discovery。
