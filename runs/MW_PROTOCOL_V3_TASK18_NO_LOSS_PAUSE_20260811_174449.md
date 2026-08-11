# Protocol v3 Task 1.8 无损暂停检查点

暂停时间：2026-08-11 17:44:49 CST（Asia/Shanghai）
状态：**PAUSED — NOT ACCEPTED / NOT COMMITTED / NO TASK-RELATED ACTIVE RUNNER**
下一任务：仍为冻结 Implementation Plan 的 Phase 1 Task 1.8；不得跳到 Task 1.9。

## 1. 权威锚点

- 工作区：`/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313`
- 冻结计划：`.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`
- 冻结计划 SHA-256：`fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`
- 当前 HEAD：`f8eae6d0627b feat(protocol-v3): add role skill and harness registries`（已验收并提交 Task 1.7）。
- Task 1.8 主合同：`context/mw_protocol_v3_phase1_task18_20260811_context.md`
- Task 1.8 执行合同：`context/mw_protocol_v3_phase1_task18_20260811_execution_context.md`
- 当前文件系统为最终真相；worker 自述和 runner `ok` 都不是验收。

## 2. Task 1.8 已完成的可恢复工作

### 2.1 跟踪、外部决策依据与执行编排

- 已通过 workflow guard 初始化 high-risk tracked task 和三个串行工作包的 execution。
- 已在主合同中冻结：8 个独立 writer、1,000 次 CAS、10,000 个 DomainEvent、lost update/duplicate semantic effect/hash-chain break 均为 0、迁移 count/hash 100%、committed-event RPO 0、10 倍参考规模 backup→restore→replay 少于 15 分钟、CAS p95 不高于 500 ms或说明影响。
- 已记录 SQLite/PostgreSQL/Psycopg 官方文档、版本和许可证依据；没有扩大到安全测试。
- SQLite 候选只允许使用链接 SQLite 3.53.1 的 `/opt/homebrew/bin/python3.12`；系统 SQLite 3.51.0 与 bundled Python SQLite 3.50.4 因官方 WAL-reset 缺陷范围而 fail closed。
- 已创建并 preflight 通过 Worker 01、02、03、manager 及两个同会话恢复提示；所有提示、报告和日志必须保留。

### 2.2 Worker 01 初始 SQLite PoC

- 原 session：`019ff00a-9afc-7000-80c9-eaa0a9e136c9`（保留；下一次必须同会话续接）。
- 初始报告：`runs/execution/mw_protocol_v3_phase1_task18_20260811/worker_01.md`
- 初始完整 stdout：`logs/execution/mw_protocol_v3_phase1_task18_20260811/worker_01_stdout.txt`
- 已创建但**未验收**：
  - `pocs/protocol_v3/storage/__init__.py`
  - `pocs/protocol_v3/storage/contract_suite.py`
  - `pocs/protocol_v3/storage/sqlite_adapter.py`
  - `pocs/protocol_v3/storage/results/memory_baseline.json`
  - `pocs/protocol_v3/storage/results/sqlite_candidate.json`
- 初始候选自报 all_passed，但 Codex 反证后明确不得接受，原因见第 3 节。

### 2.3 Worker 02 PostgreSQL 尝试

- 原 session：`019ff00a-9af3-7000-b7ab-0e0cf2021adb`（保留；在公共合同通过后才允许同会话续接）。
- 初始报告：`runs/execution/mw_protocol_v3_phase1_task18_20260811/worker_02.md`，仅 4 字节 `...`，失败。
- 初始 stdout：`logs/execution/mw_protocol_v3_phase1_task18_20260811/worker_02_stdout.txt`
- Recovery 01 报告：`runs/execution/mw_protocol_v3_phase1_task18_20260811/worker_02_recovery_01.md`，仍只是未完成说明，失败。
- Recovery 01 stdout：`logs/execution/mw_protocol_v3_phase1_task18_20260811/worker_02_recovery_01_stdout.txt`
- 两次 `brew install postgresql@18` 均未完成：首次 600 秒超时，Recovery 01 的长安装被 OMP bash 15 分钟上限取消。`brew list --versions postgresql@18` 退出 1，故 PostgreSQL **未安装**。
- 下载缓存被有意保留以便续传：PostgreSQL 18.4 bottle 已完整缓存约 20 MB；ICU 78 bottle 仍为约 25 MB `.incomplete`。缓存不是安装成功证据。
- 没有创建 `postgres_adapter.py`、PostgreSQL migration、PostgreSQL result JSON、driver venv 或产品 `postgres.py`；没有启动持久服务或遗留 task-local PostgreSQL 进程。

## 3. 已确认但尚未修复的 Worker 01 验收缺口

恢复提示已经存在并通过 preflight：
`prompts/execution/mw_protocol_v3_phase1_task18_20260811/worker_01_followup_01.md`

必须保持以下问题为失败，直到真实证据修复：

1. `contract_suite.py` 在 backup/restore/rollback 路径硬编码导入 `SqliteStorageConfig` 和 `sqlite_adapter.new_unit_of_work`，不是数据库中立合同。
2. SQLite 使用单一共享 connection，UoW 全程持有全局 `RLock`；所谓 8 writer 在进入数据库前已完全串行，零冲突不能证明独立 writer 并发。
3. CAS revision 注释/预期值存在 1001 与实现 1000 的矛盾；必须锁定并解释精确语义。
4. duplicate semantic effect 没有被独立计量。
5. backup/restore 只使用 50 个 event；冻结的 10 倍参考 workload 是 10,000 个 event。
6. crash recovery 仅为同进程重新打开 UoW，不是跨进程 kill/crash 后恢复。
7. checkpoint isolation 只是事件尾 hash 计算，没有持久化 checkpoint 表/仓储隔离证明。
8. migration 只覆盖 10 条可迁移、2 条隔离的 synthetic StudyDefinition，未覆盖完整持久化合同对象族。
9. 结果 JSON 混入随机临时路径和瞬态 timing，却被称为 deterministic；必须把稳定 semantic digest 与 measured receipt 分开。
10. SQLite result 指向已删除临时目录中的 backup path，不能作为可核验 artifact。

## 4. 本次用户暂停时的精确中止状态

- Worker 01 Recovery 01 已用原 session 启动，但在用户要求暂停后由 Codex 向 runner PTY 发送 Ctrl-C；runner 以 `KeyboardInterrupt` 退出。
- 该次恢复在暂停前没有修改 `contract_suite.py` 或 `sqlite_adapter.py`：mtime 仍分别为 17:08:05、17:06:43；也没有生成 recovery 报告/stdout 文件。
- 原 Pi session ID 保留，可在下一次用 `--resume-session 019ff00a-9afc-7000-80c9-eaa0a9e136c9` 继续，不得新建替代 session。
- 已核对没有匹配两个 Task 1.8 session 的 runner/OMP 子进程、没有 `brew install postgresql@18`、没有 task-local PostgreSQL/postmaster 进程。
- 机器上仍有其他工作区的独立 runner/OMP 进程；它们不属于本任务，未触碰也不得终止。

## 5. 当前未提交工作范围

`git status --short` 仅显示 Task 1.8 的未跟踪范围：

- `context/mw_protocol_v3_phase1_task18_20260811*.md`
- `metrics/mw_protocol_v3_phase1_task18_20260811*.md`
- `plans/codex_execution_mw_protocol_v3_phase1_task18_20260811.md`
- `prompts/execution/mw_protocol_v3_phase1_task18_20260811/` 与 task prompt
- `reviews/codex*_mw_protocol_v3_phase1_task18_20260811*.md`
- `runs/execution/mw_protocol_v3_phase1_task18_20260811/` 及本暂停记录
- `pocs/protocol_v3/storage/`

没有未提交的 `services/api/app/protocol_workflow/storage/selected.py`、产品 SQLite/PostgreSQL adapter、部署 migration 或 Task 1.8 focused test。`services/api/app/protocol_workflow/storage/memory.py` 仍为已提交基线。

## 6. 唯一下一安全动作

恢复时先读取本文件、Task 1.8 context/execution context、冻结计划 Task 1.8，核对 plan hash、HEAD 和 `git status`，然后严格串行：

1. 用原 Worker 01 session `019ff00a-9afc-7000-80c9-eaa0a9e136c9` 续接已经 preflight 的 `worker_01_followup_01.md`；明确这是用户暂停后的继续，输出到新的 `worker_01_recovery_01.md`/stdout 路径；长等待到终态，不固定重派或 fallback。
2. Codex 核对真实 diff，并独立执行公共合同与 SQLite 候选；上述 10 个缺口任一未闭合都不得接受。
3. 公共合同通过后，由 Codex 先用可观察、明确超时的本地命令续传/安装已经授权的 PostgreSQL 18 依赖，避免再次让 Worker 02 的 bash 触发 15 分钟上限；仍不得启用 `brew services`。
4. 再用原 Worker 02 session `019ff00a-9af3-7000-b7ab-0e0cf2021adb` 做最后一次同会话恢复，只实施 PostgreSQL candidate、transient cluster、Psycopg 3.3.4、真实 `pg_dump`/`pg_restore` 与共同合同。结束必须证明 cluster 已停止。
5. 仅当 Worker 01/02 均 terminal 且证据可比时，才 preflight/dispatch Worker 03；随后 manager 只读整合、独立 conference verifier、Codex 全量验收。
6. 未完成独立验收前不得写 selected storage、commit、cleanup-execution、进入 Task 1.9 或启动产品服务。

## 7. 暂停期禁止动作

- 不得声称 Task 1.8 READY、完成或已提交。
- 不得把当前 `sqlite_candidate.json` 的 `all_passed: true` 当作有效结论。
- 不得把 PostgreSQL bottle 缓存当作安装或运行证据。
- 不得删除本任务 prompt/report/stdout、同会话 ID、未验收 PoC 文件或 Homebrew 续传缓存。
- 不得启动 Worker 03、manager、conference、产品服务、真实 LLM/OCR/translation 或任何安全测试。
- 不得修改医学监查、legacy 数据库、生产数据库、Task 1.9+ 或其他工作区的并行任务。
