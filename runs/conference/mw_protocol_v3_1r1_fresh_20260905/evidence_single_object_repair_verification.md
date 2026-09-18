# 会议输出: mw_protocol_v3_1r1_fresh_20260905 - evidence_single_object

## 输出

对修复后候选（四文件当前冻结哈希已复核）的独立再评审。评审基准不变：`ports/repositories.py`、`ports/unit_of_work.py` 为合同权威，`storage/memory.py` 为参考行为，实际调用方 `application/service.py`、`events/unit_of_work.py`（本轮 git 确认零改动）。

### 建议: NOT_READY（单一阻断项 R1；R2 需显式处置）

上一轮暴露的四个缺陷类（异库 schema_version 采纳、进入前自动提交、被捕获的复合写半批提交、同名无约束克隆库）**已全部用可执行证据确认关闭**，当前 v1-only 行为正确、全部测试绿。但我用自写探针实证了一个新的结构性缺陷：**schema 迁移框架的前向迁移路径按构造就是断的**——这正是任务指令要求区分“当前 v1 约束”与“未来 schema 迁移要求”的点，且迁移框架本身是 1R.1 的显式验收项（修正案："schema migrations"），故阻断。

### 已解决（可执行证据）

1. **异库/畸形 schema 采纳**：`_preflight_owned_database`（sqlite.py:654-746）在只读 URI 连接（:603-614）上完成全部核验后才开读写连接。伪版本 0/1、重复/零前缀历史、缺列、真产品库旁加无关表、空历史全部拒绝且主文件字节不变（Codex 探针 + `TestForeignSchemaAdoption`；`_assert_rejected_untouched` 还断言预存 sidecar 保留、新 -wal 必须为空——诚实处理了只读打开 WAL 库的 sidecar 边界）。
2. **约束完整性**：指纹 = 每列 (声明类型, NOT NULL, DEFAULT, PK 序号)（`PRAGMA table_info`，:474-486）+ PK/UNIQUE 索引结构（`PRAGMA index_list/index_info`，:489-502），参考指纹由**同一份**迁移 DDL 在临时内存连接派生（:508-533，单一事实源）。CTAS 全克隆、event_stream 去 PK+UNIQUE、outbox 去 UNIQUE、reservation 单列去 NOT NULL 均被拒；未篡改产品副本正控制通过（`TestConstraintIntegrityPreflight` + Codex CTAS 探针）。
3. **进入前自动提交**：`_Guard.ensure_active`（:875-883，经 :1987 绑定 UoW depth）；逐一核对全部 13 个 mutator 均已改用 `ensure_active`，读/诊断保持 `ensure_open`。六类 mutator 进入前全部 `UnitOfWorkClosedError`，重开库为空，嵌套语义回归通过（`TestPreEntryMutationRejection` + Codex 探针）。未进入时 `commit()` 现镜像 memory 的 no-op 关闭（:2086-2092）。
4. **被捕获的复合写 SQL 失败**：事件批（:1102-1123）与两个读模型替换（:1806-1835, :1849-1879）均在 SAVEPOINT 内；触发器注入的第二行失败/替换中途失败被捕获后提交，批次零残留、前次投影完整、同事务无关工作存活（`TestSqlFailureAtomicity` + Codex 两个探针文件）。
5. **易失路径**：`:memory:`（str 与 Path 形式）在配置期拒绝于任何 I/O 之前；相对路径仍可用（`TestVolatilePathRejection`）。
6. **naive 时间戳**：`_dt_to_iso` 对 naive 输入显式 raise（:806-815）；aware 偏移时间归一化为同一时刻（`TestTimestampSerialization`）。
7. **我上轮 F1（参数化错位）**：批次现在只含 bad 事件本身（test_repository_backends.py:529），5 个具名违规各自作为首违规被触发；新增 `test_batch_prefix_rolls_back_to_committed_head_on_later_violation`（:580-620）覆盖 (good, gapped) 前缀违规并验证失败后同事务内流仍可继续追加。
8. 我上轮 F5/F6/F7（无行分支未测、窄版本注释、过时 NotReady 文案、异库 WAL checkpoint 边界）均已相应修复或有测试钉住。

### 残留缺陷

**R1 [阻断 | 结构性，当前 v1-only 不显现，1R.2 追加首个迁移即触发]**
- 位置：`services/api/app/protocol_workflow/storage/sqlite.py:728-743`（指纹环遍历 `sorted(reference)` 全量参考）与 `:508-533`（`_reference_schema_fingerprint` 由**全部** `_MIGRATIONS` 构建）；对照 `:700-706` 的 `expected_tables` 是按已应用版本累积的。
- 复现器：`runs/mw_protocol_v3_1r1_fresh_20260905/repair_verification/test_verifier_residual_probes.py::TestForwardMigrationAdoption`——用真实工厂建 owned v1 库→进程内 monkeypatch 追加合成迁移2（1R.2 式 allowlist 表）→ `build_unit_of_work_factory` 抛 `SqliteStorageConfigurationError: owned table 'project_allowlist' ... does not carry the product column semantics`→**存量 v1 库被拒、无法前向迁移**；恢复注册表后同一库正控制采纳成功（排除探针伪影）。ALTER 式迁移2（扩列）同样会被 :715-723 列集检查拒绝——两条前向路径均断。
- 影响：1R.2 声明路径（project allowlist 表进入 SQLite durable 存储）一旦追加迁移，所有已部署 v1 库变砖。现有测试全部在单迁移注册表下运行，无法捕获；1R.3 端到端用全新库，也会漏到 cutover 才暴露。
- 补救：指纹比对按已应用版本收敛——参考签名只对 `expected_tables` 中由 `mig_version <= DB版本` 的迁移拥有的表生成（`_MIGRATIONS[.][3]` 的每迁移指纹已存在，签名可按版本一并捕获），或参考连接只应用 ≤ 当前版本的迁移再introspect。修复后用本探针（或等价的注册表注入测试）作为 1R.2 前置回归。

**R2 [非阻断，需显式处置 | 同已修复缺陷类]**
- 位置：`sqlite.py:1236-1266` `claim_pending` 的逐行 UPDATE 循环无 SAVEPOINT。
- 复现器：同文件 `::TestClaimPendingAtomicity`——触发器使第二行领取失败且被捕获后提交，观测到 `lk:1 DISPATCHED/attempt=1`、`lk:2/lk:3 PENDING` 的**部分领取**存活。端口合同措辞为 "Atomically claim"。
- 影响有界：DISPATCHED 是可恢复状态（`list_dispatched`/acknowledge/recover 路径），不丢工作、不破链，实质轻于已修复的事件批/投影情形——据此列为非阻断。但本会商已确立的同类缺陷标准（上轮因此拒过 READY），建议趁 savepoint 模式现成一并修复（环绕循环或改为单条 UPDATE）。
- 补救：同事件批/投影的 savepoint 包裹。

**遗留（沿自上轮，冻结四文件之外，未变）**
- F2：驱动级异常翻译缺口——CAS/outbox 步骤的窄 except（`events/unit_of_work.py:289-298, 310-322`）与 COMMIT 失败的原始 `sqlite3.Error` 仍会穿透 `application/service.py:813-824` 的 `_EXCEPTION_MAP`（event_append 步已宽捕）。fail-closed 但违反"程序文本不出本层”合同；应随 1R.3 错误 envelope 工作处置并立为显式 pending 项。

### 内省边界（按实陈述，不冒充安全完成）

指纹覆盖：声明类型、NOT NULL、DEFAULT、PK 序号、PK/UNIQUE 索引结构。当前 owned DDL 无 CHECK/FK 声明，故无对应可校验内容（无损）。**未**内省：触发器、视图、collation、非唯一索引、生成列——在被篡改的 owned 库上加触发器可通过预检（触发器不在比对范围）；该门是约束结构等价检查，不是防篡改。另：预检（只读）→读写相之间的 TOCTOU 仅以版本复读收窄（:779-784）+ 迁移内 `BEGIN IMMEDIATE` 版本复核，未在写相全指纹复验（单进程产品下属边界情形）。`readiness_report()` docstring 措辞略滞后（不可变测试钉住了无 builder→not_ready 语义，行为无问题）。

### 实际命令与结果

| 命令 | 结果 |
|---|---|
| `shasum -a 256` 四文件（评审前+后） | 前后一致：sqlite.py `c971cb00…`、selected.py `153fc687…`、test_repository_backends.py `0b1dd33b…`、test_sqlite_product_storage.py `411c9c77…`（均匹配本轮声明值；旧会话哈希已按指令视为历史） |
| `pytest runs/mw_protocol_v3_1r1_codex_20260905/test_acceptance_probes.py test_projection_atomicity_probes.py test_schema_constraint_probe.py tests/protocol_v3/test_repository_backends.py tests/protocol_v3/test_sqlite_product_storage.py -q` | **134 passed** |
| `pytest runs/mw_protocol_v3_1r1_fresh_20260905/repair_verification/test_verifier_residual_probes.py -q -s` | **2 passed**（打印 R1 拒绝消息原文） |
| `pytest tests/protocol_v3 -q` | **1366 passed, 101 subtests passed, 0 failed**（较上轮 +22，为修复新增测试；2 个预存无关 deprecation 警告） |
| 运行时引擎 | Python 3.12.13 / SQLite **3.53.4**（≥3.51.3；实测非元数据推断） |

### 裁决摘要

- R1 修复并重新冻结四文件哈希、以我的前向迁移探针（或等价注册表注入回归）验证通过后，1R.1 即可 READY；R2 建议同批修复，至少登记显式处置。R1/R2 补救均涉及冻结文件，须由执行模块完成并重走独立验证——本会话保持只读。
- 不主张产品/UI/Word/临床/监管/生产验收；Codex 保留最终裁定权。

### 局限与源边界

仅在隔离 checkout 内工作；读取限于声明源、三个 Codex 探针文件与合同/调用方；未读执行 worker 报告/日志/推理；未启动服务、未调用产品模型/OCR/翻译、未安装依赖、未 commit/stage；唯一写入为 `runs/mw_protocol_v3_1r1_fresh_20260905/repair_verification/test_verifier_residual_probes.py`（apply_patch 添加，含控制组）。探针的注册表 monkeypatch 仅进程内并在 finally 恢复。验证者隔离仍为家族级（GLM-5.3 vs 执行者 GLM-5.3-Flash），独立性不超出声明身份。
