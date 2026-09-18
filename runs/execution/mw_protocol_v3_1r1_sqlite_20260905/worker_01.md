# 执行输出：mw_protocol_v3_1r1_sqlite_20260905 - worker_01

## 边界与上下文检查

- H-R 门检查（编辑前置条件）：已接受 2026-09-05，记录位于 `plans/mw_protocol_v3_execution_tracking_20260905.md` 第 13 行 — 在进行任何编辑前已验证。
- 上下文/计划阅读完整：`context/mw_protocol_v3_1r1_sqlite_20260905_execution_context.md`，`plans/codex_execution_mw_protocol_v3_1r1_sqlite_20260905.md`，`../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260809_111313.md`（Task 1R.1 章节），`plans/mw_protocol_v3_review_amendment_20260905.md`。
- 证据来源（只读）：`ports/repositories.py`，`ports/unit_of_work.py`，`storage/memory.py`，`storage/selected.py`，PoC `sqlite_adapter.py` + `decision.md`，`application/service.py`，`events/unit_of_work.py`，`events/models.py`，`packages/contracts/.../protocol_v3.py`，现有测试 `test_repository_contract.py`（73 通过，已验证），`test_selected_storage_contract.py`。
- 写入路径严格限于授权集：`storage/sqlite.py`（新建），`storage/selected.py`（已修改），`tests/protocol_v3/test_repository_backends.py`（新建），`tests/protocol_v3/test_sqlite_product_storage.py`（新建），`runs/mw_protocol_v3_1r1_20260905/`（证据）。Git 范围检查：无其他写入；现有的被跟踪修改早于分发；PoC/main/frontend/monitoring/旧测试未受影响；无包安装；未启动服务；数据库仅存在于测试拥有的 tmp 目录中。运行器报告未通过工具写入。
- 运行时：`/opt/homebrew/bin/python3.12` = Python 3.12.13，链接 SQLite **3.53.4**（门控 ≥3.51.3 已满足并强制执行）。

## 已执行工作

Task1R.1 已完成，遵循红-绿顺序：先进行失败的测试，捕获红色证据，然后进行最小化的产品实现，最后进行全套回归测试。

1. **产品适配器** (`services/api/app/protocol_workflow/storage/sqlite.py`，新建)：所有七个端口上的端口契约存储库 + UoW，镜像了已接受的 PoC 算法，无 PoC 导入，无基准测试机制（无 crash child / checkpoint / quarantine / retry driver / auto-retry）。预创建门控（在创建任何文件/目录之前）断言 SQLite ≥3.51.3；每个连接均使用 WAL + `synchronous=FULL` + `foreign_keys=ON` + 已验证的 `busy_timeout` + `temp_store=MEMORY`；`journal_mode=WAL` 在引导时设置一次（持久化）。显式 `schema_version` 表：全新的数据库在**一个**事务中引导（中断的首次初始化不会导致损坏）；升级在各自的 `BEGIN IMMEDIATE` 中应用有序迁移，并进行事务内版本重检；重复初始化安全；未来模式版本失败关闭且不进行重写；外部/遗留数据库和非数据库文件被拒绝，不做采用，字节相同。导入无副作用（在空当前工作目录中进行子进程导入：未创建文件/目录/工作进程）。UoW：每个 UoW 一个连接，`BEGIN IMMEDIATE`，单个事务覆盖 CAS+events+outbox，嵌套 `with` 仅在最外层提交，关闭的 UoW 在所有变更器上拒绝 `UnitOfWorkClosedError`。事件批次在写入前行前进行完全验证，因此事务内部捕获的失败不会泄露部分批次。读模型变更器符合应用程序调用者名称（`replace_chapter_coverage` / `replace_decision_graph`，具有清除陈旧行功能，`upsert_workflow_run_status`）。
2. **选定表面** (`storage/selected.py`)：通过新的 `create_product_unit_of_work_factory(config)` 进行显式产品路由，提供真正的构建器；模块级导入适配器（现有结构测试唯一合法的选项 — 它禁止在内存测试路由之外进行函数作用域导入，并禁止 SQL/journal token；无导入技巧）。所有现有行为保持字节相同，包括 `StorageNotReadyError` 阻塞消息（负面测试断言其子字符串）；内存仍仅用于测试路由；注入钩子兼容。
3. **双后端契约套件** (`test_repository_backends.py`)：24 个测试 × {内存， sqlite}，覆盖：两种聚合类型上的 CAS 创建/历史/精确前置条件/冲突；跨项目的相同聚合 ID；事件排序、哈希链接、head/from_sequence，所有五个链违规拒绝完整批次，事务内部捕获的批次失败不泄露部分内容，跨项目的流隔离；outbox/inbox 幂等重放、相同键不同内容拒绝、声明/完成/失败/非法转换、列表分发只读性、项目作用域声明；保留幂等性、输入冲突、尝试谱系附加、未知结果阻塞、非法转换、会话保留 + 拒绝恢复会话更改、find_unresolved/unknown 作用域；读模型替换清除陈旧行和项目隔离；UoW 提交原子性（CAS+event+outbox 在一起）、回滚丢弃所有三个、嵌套一次提交、提交后变更失败关闭、回滚幂等、关闭后进入引发异常；运行时可检查的端口一致性。
4. **产品特定套件** (`test_sqlite_product_storage.py`)：24 个测试 — 真实文件的持久重新打开，文件级持久 WAL，连接编译指示，正向整数/仅 FULL 的配置验证，门控前无创建的门控失败，模式 v1 引导 + 重复初始化 + 无重写的未来模式 + 永不采用外部数据库，无基准测试表，导入纯度（子进程），无 PoC 导入（源代码扫描），以及所有负面路径的产品路由（非选定后端、无配置、无效适配器配置传播类型化阻塞、默认工厂保持无构建器未就绪、注入路径兼容）。

## 工件与证据

- `services/api/app/protocol_workflow/storage/sqlite.py` — 产品适配器（导出：`SqliteStorageError`/`SqliteStorageConfigurationError`/`SqliteSchemaVersionError`, `MIN_SQLITE_VERSION`, `assert_sqlite_version`, `parse_sqlite_version`, `SCHEMA_VERSION_LATEST`, `SqliteUnitOfWork` + `connection_pragmas()`, `build_unit_of_work_factory`）。
- `services/api/app/protocol_workflow/storage/selected.py` — + `create_product_unit_of_work_factory`（`__all__`，真实构建器导入，docstring 真实性更新）。
- `tests/protocol_v3/test_repository_backends.py` (48) 和 `tests/protocol_v3/test_sqlite_product_storage.py` (24)。
- `runs/mw_protocol_v3_1r1_20260905/`：`red_evidence.txt` (exit 2; `ModuleNotFoundError: No module named 'app.protocol_workflow.storage.sqlite'`; `ImportError: cannot import name 'create_product_unit_of_work_factory'`), `green_focused.txt` (**104 passed**), `green_full_suite.txt` (**1344 passed, 101 subtests passed, 0 failed**; R.3 基线 1240+101 + 104 新增 = 1344 ✓), `runtime_identity.txt` (SQLite 3.53.4), `evidence_summary.md`（设计决策 + 组合 API 交接）。

**给 Codex 组合的精确配置 API：**
```python
{"backend": "sqlite", "path": "<non-empty path>", "busy_timeout_ms": 5000, "synchronous": "FULL"}  # keys beyond path optional; unknown keys rejected
factory = create_product_unit_of_work_factory(config={...})   # explicit product route
create_unit_of_work_factory(config={...})                     # still StorageNotReadyError (no builder)
create_unit_of_work_factory(config={...}, adapter_builder=build_unit_of_work_factory)  # injection compatible
```

## 命令与观察

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:. /opt/homebrew/bin/python3.12 -m pytest <files> -q -p no:cacheprovider --tb=short` — red（收集错误，保存），然后在修复后为绿色。
- 聚焦运行中的迭代：3 轮修复 — (a) 测试辅助 `SemanticBlockKind.NARRATIVE` 在契约中不存在（旧的 `test_repository_contract.py` 助手有相同的陈旧属性但从未被调用；我的文件现在使用 `PARAGRAPH`）；(b) 契约验证器：`StudyDefinitionV3.facts` 必须非空，且版本 >1 的记录需要 `previous_revision_sha256` — 测试记录已更正；(c) 适配器：`PRAGMA synchronous` 报告整数 `2`（测试预期已调整），垃圾文件路径引发了 `UnboundLocalError`，因为在 `_bootstrap` 中包装前连接被 `finally` 引用（已修复：连接创建被包装，因此非数据库文件产生 `SqliteStorageConfigurationError` 且不重写）；终端 FAILED 转换离开无会话保留在两个后端上都引发 pydantic `ValidationError`（已记录为可观察行为，符合内存语义）。
- 全套测试：`... -m pytest tests/protocol_v3 -q -p no:cacheprovider --tb=short` → **1344 通过 + 101 子测试**，包括所有现有的负面/结构测试（选定表面 token 扫描、`test_no_silent_fallback_without_builder`、就绪报告、`test_no_product_file_imports_pocs`）保持绿色。根据上下文，未运行全仓 pytest（遗留的 main 导入）。

## 阻碍或缺失环境

无。环境完整（固定运行时，SQLite 3.53.4 ≥ 门控）。两个刻意的、已记录的与 PoC 模式的偏差均在 `evidence_summary.md` 中：项目作用域的标识主键 (PK)（端口将保留/发件箱/收件箱 ID 视为项目作用域；PoC 的全局主键在跨项目的相同 ID 上会引发 IntegrityError，而内存允许）和预插入尝试冲突检测（内存引发 `IdempotencyConflictError`；PoC 泄露 `sqlite3.IntegrityError`）。

## 重新运行请求或下一步

无重新运行请求。此工作者不关闭 Task 1R.1 并声称产品验收；Codex 和新的验证器拥有该门控。剩余的 Codex 决策：1R.2 组合根是否应调用 `create_product_unit_of_work_factory` 或通过注入钩子传递 `build_unit_of_work_factory`；多写者/崩溃/备份证明仍归 PoC 证据 + Task 1R.3 所有；全仓 pytest 在此任务后按计划进行。
