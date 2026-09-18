# Protocol v3 — 1R.2 产品入口与持久项目开关

## Goal

让已验收的产品 SQLite 内核可从真实 main API 入口到达，同时默认全部项目维持旧行为。仅构建隔离产品，不激活 live 或真实项目。

## Requirements

- 权威：Plan v2 Task 1R.2 与附加 Plan 同号修订；前置 1R.1 已验收，四文件 hash 本轮复验一致。
- 实际 main include_router 挂载 /api/projects/{project_id}/protocol-workflow。
- 显式环境开关默认 off，加 durable SQLite 项目 allowlist；空表和未列项目不得进入新链。
- 重启保留 allowlist；不能复用内存 CutoverStateRegistry，不代表正式 cutover 授权。
- 延迟构造；新增 import/挂载不启动 worker、不写旧库，既有 main 副作用需隔离验证。
- 用户允许个人使用 PyMuPDF，依赖恢复限隔离环境，版本和用途可核查。

## Acceptance Criteria

- [ ] 默认 off 与 legacy 路由/错误处理行为一致，新链不打开数据库或启动工作。
- [ ] 显式开启但空 allowlist、非准入项目拒绝新链；准入项目实际 HTTP 可达 SQLite。
- [ ] allowlist 重启持久；与产品库共库须版本化迁移，旧行和事件 hash 不变。
- [ ] 新 validation handler 不影响旧 API validation 响应。
- [ ] H6实际入口/挂载、全仓和protocol_v3回归有真实输出；依赖错误不算通过。
- [ ] fresh verifier 按源码及实际证据验收，worker 不自关任务。

## Notes

不做1R.3全套replay/backup、1R.4简化、新UI、产品模型/Word/OCR/翻译或生产激活。
无未决用户范围项，已批准Plan和连续Goal允许实施；技术细节由源码及失败测试确定。

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
