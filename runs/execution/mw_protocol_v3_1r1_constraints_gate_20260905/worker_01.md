# 执行输出：mw_protocol_v3_1r1_constraints_gate_20260905 - worker_01

## 边界与上下文检查

- 已完整阅读初始读取集：`context/mw_protocol_v3_1r1_constraints_gate_20260905_execution_context.md` 和 `plans/codex_execution_mw_protocol_v3_1r1_constraints_gate_20260905.md`。已按要求阅读三个 Codex 探测文件（`test_acceptance_probes.py`、`test_projection_atomicity_probes.py`、`test_schema_constraint_probe.py`）以及当前的 `storage/sqlite.py`、`storage/selected.py` 和两个测试文件（Plan v2 和修订版本已在之前的会话记录中完整阅读；上下文确认这是第 1R.1 阶段范围内的限定性修正）。
- 使用的运行时（按指示）：`runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python` — Python 3.12.13，SQLite 3.53.4 (≥3.51.3 门限)，pytest 8.4.2，pydantic 2.13.4；已验证 `packages.*` 导入解析。另外使用 `/opt/homebrew/bin/python3.12` (pytest 9.1.1) 进行了交叉检查，以便与历史记录进行同口径对比。
- 本任务的手动编辑：仅通过 `apply_patch` 对 `services/api/app/protocol_workflow/storage/sqlite.py` 和 `tests/protocol_v3/test_sqlite_product_storage.py` 进行了修改（未使用原生 Write/Edit，没有使用 cat 追加，没有重定向写入源文件）。`selected.py`、共享测试、Codex 探测、计划、历史报告以及工作流工具未被触动。修复前留下的已追踪差异保持不变。写入的证据仅限于 `runs/mw_protocol_v3_1r1_20260905/repair_02/` 下的 pytest 生成的输出。未触及历史失败包；未执行清理；任务未关闭。

## 已执行工作

**首先重现（编辑前）：** `runs/mw_protocol_v3_1r1_codex_20260905/test_schema_constraint_probe.py` 如报告所述失败 —— `test_same_names_without_product_constraints_are_rejected` 提出提醒 `DID NOT RAISE SqliteStorageError`：一种保留所有表/列名称和迁移行的 CTAS 克隆被采用预检接受，因为之前的指纹仅验证了名称（`repair_02/red_schema_constraint_probe.txt`）。

**编辑前添加了红测试回归** (`tests/protocol_v3/test_sqlite_product_storage.py`，新增类 `TestConstraintIntegrityPreflight`，全部通过 `apply_patch` 实现)：CTAS 全模式克隆被拒绝；`event_stream` 在主键 (PRIMARY KEY) + 唯一 (UNIQUE) 约束丢失时被拒绝（保持类型/非空 NOT NULL 以隔离约束系列）；`outbox_message` 在 `UNIQUE (project_id, logical_key)` 丢失时被拒绝（保留主键 PK）；`execution_reservation` 在 `input_sha256` 的非空 (NOT NULL) 丢失时被拒绝（保留主键 PK + 唯一约束 UNIQUEs）；正向控制 — 未修改的拥有数据库的副本仍被接受（防止过度拒绝）。修复前：4 个失败 / 1 个通过 (`repair_02/red_constraint_regressions.txt`)。

**`storage/sqlite.py` 中的最小修复**（仅限 SQLite 原生元数据，无 SQL 解析器，无依赖项）：
- `_column_signature(conn, table)` — 有序的每列 `(name, declared type, NOT NULL, DEFAULT, PRIMARY KEY ordinal)`，来自 `PRAGMA table_info`。
- `_unique_index_signature(conn, table)` — 排序后的唯一索引结构 `(origin, ordered columns)`，来自 `PRAGMA index_list` + `index_info`，记录复合主键 (autoindex origin `pk`) 和唯一约束 (origin `u`)。
- `_reference_schema_fingerprint()` — 惰性构建一次，通过在瞬态内存中连接执行相同的 `_SCHEMA_VERSION_DDL` + 迁移语句，从而生成拥有模式的 DDL（单一事实来源，无需复制常量；根据上下文，这仅用于内部自省，不会启用任何基于内存的产品存储）。
- `_preflight_owned_database` 现在在现有的迁移历史验证、精确的表集检查和列名检查之后，对比每个拥有表的列语义和唯一索引结构，对于名称匹配但缺失/更改了主键/唯一/非空（或类型/默认值）语义的数据库，给出精确的 `SqliteStorageConfigurationError`，且从未打开读写连接（保持字节未变的拒绝机制与 `repair_01` 相比未变）。

**已验证的内容：** 列顺序/名称、声明类型、非空标志、默认值、主键序数，以及完整的唯一索引结构（主键 + 唯一约束、列顺序、约束来源）。诚实记录的剩余局限：`CHECK` 子句和外键未被 `PRAGMA table_info/index_list` 捕获；拥有的迁移 DDL 未声明任何内容，因此在这些维度上形状完全相同的数据库仍然会被采用。针对指定的约束系列（主键、唯一、非空）加上类型语义，该实现是完整的；没有接受任何历史形状。

**保留所有 `repair_01` 的保障措施**：只读的外部文件预检（带字节标识断言）、迁移历史验证、保存点复合写入、需要活动事务的 mutators、`:memory:` 拒绝、朴素日期时间拒绝 —— 已通过完整测试套件验证，未削弱任何现有的断言（测试差异仅为增加内容 + `import shutil`）。

## 工件与证据

- 已更改：`services/api/app/protocol_workflow/storage/sqlite.py` — SHA256 `c971cb0057c7adf03ec4d7bddd96d2700454afa16c469ba02c408e763ea5941f`；`tests/protocol_v3/test_sqlite_product_storage.py` — SHA256 `411c9c77da86dd8030be25548bdaccc9d04f4ce7162e596c06c0b3a6ef66b5b3` (`repair_02/final_hashes.txt`)。`selected.py` 在本任务中未更改（保留了其 `repair_01` 哈希值 `153fc687…`）。
- `repair_02/red_schema_constraint_probe.txt`, `repair_02/red_constraint_regressions.txt` — 真实的修复前失败。
- `repair_02/green_all_probes.txt` — 所有三个 Codex 探测文件：**8 个通过** (5 个验收 + 2 个投影原子性 + 1 个模式约束)。
- `repair_02/green_focused.txt` — 专注的仓库 + 产品测试：**126 个通过** (venv python)。
- `repair_02/green_full_suite.txt` — 完整的 `tests/protocol_v3` (venv python)：**1366 个通过，1 个警告**。
- `repair_02/green_full_suite_homebrew.txt` — homebrew python 交叉检查：**1366 个通过，2 个警告，101 个子测试通过**（与 `repair_01` 接收的 1361+101 同口径，加上 5 个新测试）。
- `repair_02/green_probes_focused_homebrew.txt` — 探测 + 专注的组合：**134 个通过**。

## 命令与观察

- 红色（修复前）：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest runs/mw_protocol_v3_1r1_codex_20260905/test_schema_constraint_probe.py -v -p no:cacheprovider` → 1 个失败（DID NOT RAISE）。
- 红色（新回归，修复前）：相同的 venv 命令，针对 `TestConstraintIntegrityPreflight` → 4 个失败 / 1 个通过。
- 绿色（修复后，venv）：`-m pytest <三个探测文件> -v` → 8 个通过；专注的 → 126 个通过；完整测试套件 → 1366 个通过。
- 绿色（修复后，homebrew 交叉检查）：完整测试套件 → 1366 个通过 + 101 个子测试；探测 + 专注的 → 134 个通过。
- 观察：venv 的 pytest 8.4.2 没有 subtests 插件，因此 101 个子测试折叠到了它们的父项下（与 homebrew pytest 9.1.1 的“101 个子测试通过”横幅相比，没有横幅）；测试项总数 1366 = 1361 + 5 在两个运行时中完全一致。预期值未更改；没有删除任何失败。
- 使用的工具：Read（探测、上下文、计划）、Bash（`apply_patch`、pytest 运行、`shasum`、git 状态、venv 检查）。所有文件编辑仅通过 `apply_patch`。

## 阻塞项或缺失环境

无。venv 按指示工作；不需要任何包。剩余事项仅记录待办，非阻塞项：(a) `CHECK`/外键子句未被指纹捕获（拥有的 DDL 未声明任何；已记录为诚实的剩余局限）；(b) 之前通过的用户段 `process-audit` 失败（后续声明格式 + 输出回执绑定）属于历史且不可变 —— 本包未对其进行处理，也不应追溯性地重新标记。

## 重新运行请求或下一步

无重新运行请求。最初失败的模式约束探测现在通过了，并且引入的新反例（CTAS 克隆、主键丢失、唯一丢失、非空丢失）在每个运行时上都被拒绝，且字节未变；未修改的拥有数据库的正向控制仍然通过。根据任务合同，我不关闭 Task 1R.1 或声称已接受 —— Codex 加上独立评审员拥有那八个探测、专注的和完整测试套件对冻结哈希 `c971cb00…` / `411c9c77…` 的验收，外加独立存储评审。
