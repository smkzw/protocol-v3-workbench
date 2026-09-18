# Protocol v3 — 1R.3 真实存储集成与恢复验证

## Goal

验证当前产品SQLite链在真实事务、重启、回放、备份恢复和重复提交时保留同一研究定义与事件来源。

## Requirements

- 原Plan1R.3与增补Plan为权威；依赖1R.1已验收、1R.2功能已独立验证。历史全仓对账仍在P1R-G1前完成，不冒充通过。
- 新增integration/test_sqlite_end_to_end.py及API集成测试，通过产品adapter而非PoC。
- CAS、领域事件与outbox同事务；重开连接/新进程读取，事件回放canonical hash一致；重复logical key无新增业务效果。
- SQLite backup API用于一致副本，覆盖提交仍位于WAL的情况；恢复后integrity_check、规范状态、事件链与项目数一致。
- 实际挂载API mutation→GET；GET无业务写入；故障错误明确回滚与unknown，unknown先对账。
- 禁止产品模型/OCR/翻译/Word调用、服务启动、live/监查修改、历史清理；不新增安全专项。

## Acceptance Criteria

- [ ] 真实SQLite事务/重启/回放/幂等与一致备份恢复证据。
- [ ] 实际API路径与GET无写入；不是仅mock/helper测试。
- [ ] 错误归类与恢复义务验证，无未知提交自动重派。
- [ ] 全protocol_v3回归及独立verifier；当前测试目录被pytest.ini递归收集。
- [ ] 历史全仓对账另列状态，未解决不记PASS。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
