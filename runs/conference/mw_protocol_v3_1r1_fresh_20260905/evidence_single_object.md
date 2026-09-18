# 会议输出: mw_protocol_v3_1r1_fresh_20260905 - evidence_single_object

## 输出

独立验收 Task 1R.1（产品 SQLite adapter 与双后端合同）。审查基准：`ports/repositories.py` + `ports/unit_of_work.py`（合同权威）、`storage/memory.py`（参考可观察行为）、实际调用方 `application/service.py` 与 `events/unit_of_work.py`、plan v2 Task 1R.1 微步 + 评审修正案 1R.1 行。未读 worker 报告或其推理日志。

### 建议: READY（附处置项）

1R.1 全部验收项均已用真实证据核实，未发现破坏合同的数据一致性或失败关闭缺陷。下列发现均为测试质量、错误翻译与跨后端行为差异问题，不破坏 1R.1 合同；其中 #1、#2 建议在 1R.3 前显式处置。

### 已执行的检查（实际命令与结果）

| 检查 | 结果 |
|---|---|
| `shasum -a 256` 四个冻结文件 | 全部与声明值一致（见下） |
| 运行时引擎实测 | Python 3.12.13，SQLite **3.53.4**（≥3.51.3；与修正案"当前3.53.4而非历史candidate 3.53.1"一致） |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:. /opt/homebrew/bin/python3.12 -m pytest tests/protocol_v3/test_repository_backends.py tests/protocol_v3/test_sqlite_product_storage.py -q -p no:cacheprovider --tb=short` | **104 passed** in 1.34s |
| 同命令扩至全量 `tests/protocol_v3` | **1344 passed, 101 subtests passed, 0 failed** in 23.18s（2 个预存 deprecation 警告：tar extractall、TestClient import，与本任务无关） |
| 6 项补充探针（证据：`runs/mw_protocol_v3_1r1_fresh_20260905/reviewer_probes_20260905.txt`） | 见各项发现；产品源码零修改，DB 均在临时目录 |
| 不可变测试 git status | `test_repository_contract.py`、`test_selected_storage_contract.py` 未修改 |
| 产品内 PoC 引用 grep（`rg "storage\.sqlite\|import pocs"` services/api packages） | 仅 `selected.py:44` 引用产品 adapter；无 PoC 引用 |

四个源哈希（实测=声明）：
- `services/api/app/protocol_workflow/storage/sqlite.py` = `8eeaa92410adf9b7b79a09856cd3f90e10fa4648ec0e9f30162f0e0cd57cd685`
- `services/api/app/protocol_workflow/storage/selected.py` = `803e07fde2b3996acda16099b2cf90a14f52fc8da4c63da184bf3abeccbb93f8`
- `tests/protocol_v3/test_repository_backends.py` = `01c3f54d1f4357532e760a14516e3e1667d8ef64aab2b0818131adab3bd103d6`
- `tests/protocol_v3/test_sqlite_product_storage.py` = `411e8fa9911c12fc10cba73016ccd0f6c0c1ca0cc8997cb68e58ca4f6e358c62`

### 验收项核对（证据，逐项）

1. **七端口双后端合同**：`test_repository_backends.py` 以参数化 fixture 在 memory+SQLite 上运行同一套件，覆盖 CAS/历史、事件链、outbox/inbox 幂等与状态机、reservation 三态/血统/会话保持、读模型替换、嵌套/关闭/回滚——104 项全绿。静态比对确认 SQLite 各检查顺序与 memory 参考一致（stream→重复id→重复seq→prev链→gap）。
2. **WAL/FULL/busy_timeout/schema migrations**：真实文件级验证（`test_wal_mode_is_persistent_at_file_level`、`test_uow_enforces_durability_pragmas` 断言 synchronous==2/FULL、foreign_keys==1、busy_timeout 可配置且仅正整数、synchronous 仅接受 FULL）；迁移序列原子（每迁移独立 BEGIN IMMEDIATE + 版本行同事务，`_apply_migration` 事务内复读版本防并发双应用；fresh bootstrap 单事务）。
3. **版本门在 I/O 前生效**：`_bootstrap` 先 `assert_sqlite_version()`（sqlite.py:486）再 `path.is_dir()`/`mkdir()`/connect；测试 monkeypatch 3.51.2 后断言 `tmp_path` 为空。运行时实测 3.53.4。
4. **schema 历史/畸形/未知版本/异库不写**：future 版本 fail-closed 且数据原样（版本999+1行保留）；异库（legacy 表）拒绝且内容未动；非数据库文件拒绝不改写；`schema_version` 有表无行分支正确（探针 F）。
5. **import 纯度**：子进程在空目录 import sqlite+selected 零产物；无 PoC import（源码级 AST/regex 双重验证）；无 crash/checkpoint/quarantine 基准表。
6. **产品激活配置精确**：`create_product_unit_of_work_factory` 是唯一真实 builder 路由；默认 `create_unit_of_work_factory` 无 builder 仍 `StorageNotReadyError`；memory 仅经显式 test factory；未知配置键/非法值/空路径/目录路径全部 fail-closed 于文件系统触碰之前。
7. **不可变标准不受损**：`test_repository_contract.py`/`test_selected_storage_contract.py` 未修改且全量通过。关键点：不可变测试的 selected 模块级 deny-list（sqlite3/psycopg/pocs/storage.memory）不含 `storage.sqlite`，故产品 builder 的模块级导入字面合规；函数级导入反而会被"仅限 memory 路由"断言拒绝——worker 的接线方式是唯一可行路径。

### 发现（优先级 / file:line / 证据 / 补救）

**F1 [MEDIUM] 测试缺陷：参数化链违规用例 4/5 未真正命中具名违规**
`tests/protocol_v3/test_repository_backends.py:494-539`。`batch = (e1, bad)` 中 e1 已在前一步提交，验证循环处理批次第一个元素 e1 时即因重复 `domain_event_id` 抛错——gap、prev_mismatch、duplicate_event_id、wrong_stream 四个参数实际测的都是"重复前缀事件"，具名检查从未作为首个违规被执行（双后端同序，故双后端都"错得一致"而通过）。探针 A/B/C 证明适配器对具名违规本身正确拒绝（gap→`sequence gap expected_seq=2 actual=3`；wrong_stream→`does not match append target`；in-batch 异 id 同 seq→`duplicate sequence=1`）。补救：每个参数用"全新合法前缀事件+具名违规"或单事件批次重建用例；同时补 SQLite 后端独有首违规用例（内存版不可变套件有、SQLite 版目前缺 gap/wrong_stream 首违规直接覆盖）。

**F2 [MEDIUM] SQLite 原生错误逃逸应用服务错误目录**
`services/api/app/protocol_workflow/application/service.py:813-824`（`_EXCEPTION_MAP` 不含 `sqlite3.Error`/`SqliteStorageError`）；`services/api/app/protocol_workflow/events/unit_of_work.py:289-298`（CAS 步仅捕 `RevisionConflictError`/`UnitOfWorkClosedError`）与 `:310-322`（outbox 步仅捕两类）——注意 event_append 步 `:303` 捕 `Exception` 是全量的。COMMIT 失败（如 busy 超时后的 `OperationalError`）与 CAS/outbox 步的驱动级异常会以原始 sqlite3 异常穿透 service 的翻译层，违反"public/program text never leaves this layer"合同。行为仍是 fail-closed（抛出+with 块回滚），但 1R.3 的"错误 envelope 稳定"会踩中。补救：三个步骤统一捕 `Exception` 包装为 `MutationAbortedError`，并在 `_EXCEPTION_MAP` 增加 `sqlite3.Error`→P1 族映射。建议随 1R.3 错误 envelope 工作处置（这两个文件在冻结四文件之外，本审阅保持只读）。

**F3 [LOW-MEDIUM] naive datetime 被静默按本地时区重释（跨后端分歧）**
`services/api/app/protocol_workflow/storage/sqlite.py:551-554`。`_dt_to_iso` 的 `astimezone(timezone.utc)` 对无 tzinfo 输入按本地时间解释。探针 D：同一 naive `2026-01-01 12:00`，memory 原样返回 naive，SQLite 返回 `04:00+00:00`（Asia/Shanghai -8h 静默偏移）。当前产品调用方全部使用 tz-aware UTC 时钟（service.py:213-214、events/unit_of_work.py:597-603），今日无生产影响；但分歧是静默的而非 fail-closed。补救：`_dt_to_iso` 对 naive 输入显式 raise，或在 adapter 合同中固化"UTC 规范化"语义并加测试钉住。

**F4 [LOW] `with` 外变更的跨后端不对称**
`storage/sqlite.py:1759-1785`（`isolation_level=None` 下未 `__enter__` 即变更=自动提交持久化）。探针 E：SQLite 上 enqueue-未进入-rollback 后数据存活；memory 同样误用时被构造时快照恢复。端口不要求 mutator 检查 `is_active`（ports/unit_of_work.py:189-196 仅为调用方守则），协调器已强制（events/unit_of_work.py:580-589）、service 全部走 `with`，现无受影响调用方。补救（择一）：SQLite guard 对 mutator 同时要求活动事务；或文档化该不对称。

**F5 [LOW] 未测分支：`schema_version` 有表无版本行**
`storage/sqlite.py:513-517`。探针 F 确认正确 fail-closed（`refusing to touch it`），但两个新测试文件均未钉住。补救：`test_sqlite_product_storage.py` 补一条。

**F6 [LOW] 过时/误导文案**（推断，非行为缺陷）
- `storage/sqlite.py:129-131` 与 `selected.py:79-81` 注释仍称缺陷"仅 3.51.0–3.51.2 受影响"；修正案源纠正#6 指出官方说明可能涉及更早版本。门值 (3,51,3) 正确，仅因果注释过窄。
- `selected.py:281-290` 的 `StorageNotReadyError` 消息仍指示"implement …storage/sqlite.py"，该文件现已存在，应改指 `create_product_unit_of_work_factory`。
- `readiness_report()` 默认无 builder 时报 `not_ready`——产品路由已存在，语义上"not wired"已不真实（docstring 有说明，但易误导运维）。

**F7 [INFO] 边界与特性记录**（不构成缺陷）
- 异库拒绝路径以读写连接探测后 close：若异库为 WAL 模式且有未 checkpoint 的 -wal 且无其他连接，close 可能触发 checkpoint 改写主文件——"never adopted or renamed"仍成立，"byte-untouched"在该窄场景不严格保证。可选补救：探测阶段用只读 URI 连接。
- `claim_pending` 排序跨后端不同（memory 插入序 vs SQLite (created_at,id)）；端口仅钉 `list_dispatched` 排序，各自确定，合规。
- 每个 SQLite UoW（含纯查询）`__enter__` 即 `BEGIN IMMEDIATE` 取写锁：正确性无虞，读串行化于写后，1R.3 集成时注意 busy_timeout(默认5000ms) 特征。
- outbox/inbox id 生成 `MAX(rowid)+1` 在单写者序列化下安全（无删除路径）。

**F8 [INFO] 与 plan v2 微步的偏差（决策点，见问题）**：微步2写"保留环境变量显式开启"；实现为显式产品函数路由。推断：修正案（更晚权威）的边界"生产配置缺失/非法继续 fail-closed，memory 仅显式 test factory"已满足且未提环境变量，函数路由比环境变量更显式、可审计。

### 对 Codex 的最重要质疑与问题

1. **Q1（F8）**：是否确认"修正案取代 plan v2 微步"的解释——环境变量开启方式被显式产品函数路由替代？影响后续 1R.2 挂载的配置约定。安全暂定路径：维持现状（函数路由），1R.2 沿用。
2. **Q2（F2）**：驱动级错误翻译缺口是在 1R.1 内立即修复（需另一验证者，因涉冻结四文件之外的 service/协调器），还是登记为 1R.3 错误 envelope 工作的强制前置项？我的建议：后者，但须在 1R.2 开工前的执行跟踪里立为显式 pending 项，避免"通过计数处置发现"。
3. **Q3（F1）**：F1 属于新测试自身缺陷，修复会改动冻结哈希文件 `test_repository_backends.py`。是否授权在 1R.1 验收记录中登记该测试修复为下一最小动作（由执行模块完成、重新冻结哈希），还是接受探针 A/B/C 证据作为本任务内的等效覆盖？

### 局限

- 未逐行 diff 产品 adapter 与 PoC adapter；合同权威（ports+memory 参考行为）是审查基准（上下文允许 PoC 仅作对照）。
- 未做多连接并发/崩溃/备份探针——新套件头部与计划均将其划归 PoC 证据 + Task 1R.3。
- 未跑全仓 pytest（上下文明确排除；legacy main 依赖闭合是独立待办）。
- 验证者隔离为家族级：本审阅与执行者同属 GLM 家族（不同型号 GLM-5.3 vs GLM-5.3-Flash），模型独立性不超出声明身份。
- 探针产物在 `runs/mw_protocol_v3_1r1_fresh_20260905/reviewer_probes_20260905.txt`（允许的附加证据路径）；未写 runner 管理的报告路径，未修改任何源码/测试/fixture。
- 不声称产品/UI/临床/监管/生产验收；Codex 保留最终裁定权。
