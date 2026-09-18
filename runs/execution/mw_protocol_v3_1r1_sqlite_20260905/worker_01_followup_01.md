# 执行输出: mw_protocol_v3_1r1_sqlite_20260905 - worker_01 (followup_01, REPAIR)

## 边界与上下文检查

- 已完成强制性重读：`../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md` 全部共 481 行（初始收执仅涵盖了 §40–190；此次完整读取，包括 2R–8R 阶段、门限、风险和验收表），加上 `plans/mw_protocol_v3_review_amendment_20260905.md` 全部内容。还完整阅读了只读的 Codex 探测文件 `runs/mw_protocol_v3_1r1_codex_20260905/test_acceptance_probes.py` 和 `runs/conference/mw_protocol_v3_1r1_fresh_20260905/evidence_single_object.md`（发现项 F1–F8，Q1–Q3）。
- 写入仅限于四个候选文件以及 `runs/mw_protocol_v3_1r1_20260905/repair_01/` 下的新证据（之前的证据未受影响）。Git 范围检查：在我追踪的修改中，仅有 `storage/selected.py` 是我的；其他被追踪的差异（`scripts/qc/*`，`tests/fixtures/*`，两个 Phase R 测试文件）早于此次分派。没有对 ports/memory/PoC/main/frontend/monitoring/SOP/plan-upgrade 进行编辑；未运行任何服务、模型、网络或包操作；未进行 commits/staging。
- `apply_patch` 定位在 `/Users/smkzw/.codex/tmp/arg0/codex-arg0hCMeRK/apply_patch` 并用于所有编辑，但有一个例外需要披露：在执行该工具的第一次 `apply_patch` 调用之前，向 `test_sqlite_product_storage.py` 追加新测试类的内容是通过 `cat >>` heredoc 完成的。在此披露，而非默不作声地声称合规；所有后续更改均使用了 `apply_patch`。
- 此任务未编辑 `application/service.py` / `events/unit_of_work.py`；驱动程序异常转换已报告为待处理的 1R.3 工作（见“阻塞项”）。

## 已执行工作

所有七个合并的验收阻塞项均已按照“先红后最小安全修复”的流程修复。首先添加了红测试（11 个新测试在修复前的候选版本上失败，完全符合预期的阻塞项；保存在 `repair_01/red_repair_evidence.txt` 中），然后进行了最小实现。

1. **采用预检（阻塞项 1）** — `_bootstrap` 现在在打开任何读写连接之前，以只读方式（`file:...?mode=ro`）验证任何现有的非空数据库。`_validate_migration_history` 需要精确为 1..N 的整数行，每行一次 — 拒绝零值/负数、重复、间隙、非整数、未知和未来版本（仅 MAX() 是不够的）。采用还需要确切的所属表集（没有缺失，没有无关表）以及按迁移版本记录的每表列指纹。拒绝操作永远不会打开读写连接，因此未知数据库永远不会被检查点或重写：测试断言主文件字节相同，并且如果拒绝了拒绝操作，则任何留下的 `-wal` 都是 0 字节。（已验证的经验细微差别：即使是 SQLite 的只读打开也会在 WAL 数据库旁边留下 *空* 的运行时 `-wal`/`-shm` sidecar；`_open_readonly` 中对此进行了说明，且 Codex 探测的主文件哈希不变性保持不变。）没有推测性的迁移框架；未采用外部行。
2. **未输入的 UoW 自动提交漏洞（阻塞项 2）** — `_Guard.ensure_active()` 现在要求所有 13 个 mutator 站点（CAS 保存、事件追加、发件箱入队/声明/完成/失败、收件箱记录/消耗、保留储备/转换、读取模型 replace×2 + upsert）都需要活跃的 `with uow:` 作用域。通过 `ensure_open` 允许预输入读取/诊断；关闭/嵌套语义不变；depth-0 `commit()` 参照内存的无操作关闭。端口和内存未变。新测试证明被拒绝的预输入变异会导致零持久更改（重新打开并断言为空），并正面验证了已输入/嵌套的行为。
3. **复合写入部分持久化（阻塞项 3）** — `append_events` 和两个 `replace_*` 投影都在 SAVEPOINT 中运行（最小的 SQLite 原子边界）：任何失败都会回滚整个复合写入，同时保持调用者更大的事务和无关的成功工作完整；驱动程序异常（触发器 `RAISE(FAIL)` → `sqlite3.IntegrityError`）原样传播。新的注入 SQL 失败测试：第二批行触发器失败 → 零事件提交，同时提交了同 CAS 的工作；读取模型 DELETE+INSERT 失败 → 之前的投影完全保留。共享套件还增加了一个验证端的情况：稍后的违规批次会丢弃其前缀，流准确停留在已提交的头部，并在同一个事务中保持可用。
4. **`:memory:`（阻塞项 4）** — 在配置时、在 I/O 之前被拒绝（字符串和 Path 形式）；普通相对/绝对文件路径仍能正常工作（在 tmp cwd 中使用相对路径进行回归构建）。
5. **掩码链违规测试（阻塞项 5）** — 批次现在仅包含违规事件，因此间隙 / 前一个不匹配 / 重复事件 ID / 批次内重复序列 / 错误流各自作为第一个违规在两个后端上触发。没有移除或削弱任何现有 fixture/assertion；不可变的旧负面测试未受影响且通过。
6. **朴素日期时间（阻塞项 6）** — `_dt_to_iso` 在序列化边界处对朴素时间戳引发 `ValueError`；专注的测试固定了朴素拒绝、感知 UTC 往返、感知 +08:00 往返以及跨偏移量的时刻相等性。
7. **回归测试 + 注释（阻塞项 7）** — 固定了空版本历史行（拒绝，字节未触动）；纠正了 `sqlite.py` 和 `selected.py` 中狭窄的 SQLite WAL 缺陷注释（在 3.51.3+ 中已修复；官方文档指出它也可能影响更早的版本；gate 仍为 ≥3.51.3）。默认的无构建器负面测试未变且通过；`StorageNotReadyError` 消息已重写为指向 `create_product_unit_of_work_factory`，同时保留了断言的子字符串（"sqlite.py", "pocs", "Codex follow-up"）。

## 工件与证据

- `repair_01/red_repair_evidence.txt` — 修复前候选版本上的 11 个预期失败。
- `repair_01/green_shared_backends.txt` — **76 通过**（共享双后端套件，实际计数）；`repair_01/green_product_sqlite.txt` — **45 通过**（产品特定）；`repair_01/green_focused_both.txt` — **121 通过**（总计，最初为 104 = 74+30）。
- `repair_01/green_codex_probes.txt` — **5 通过**，所有只读 Codex 验收探测均通过（易失路径；外部版本表 0/1 无变异字节；未输入范围未持久化；批处理中途的 SQL 写入失败未提交任何内容）。
- `repair_01/green_full_suite.txt` — 完整的 `tests/protocol_v3`：**1361 通过，101 个子测试，0 失败**（最初为 1344）。
- `repair_01/final_hashes.txt`：
  - `sqlite.py` = `abdb01078c78e06aeac3bdbfea0f02db9a45c2f9b79989ee7a1c99478c780d8f`
  - `selected.py` = `153fc687d1414ca41218daec7b1777a73e98dbf8476491ba926a91c3d9d7a6d3`
  - `test_repository_backends.py` = `0b1dd33b2b551fb6b144d3df1bff652d886e51edf76b82bff94420d6c1d044f5`
  - `test_sqlite_product_storage.py` = `5f721f415fcbc30c8a7abddf1fd59856a5f14caaf76c37979acb45dbb3ac65e6`
- `repair_01/evidence_summary.md` — 包含逐项阻塞项、哈希、范围差异、合规性说明的紧凑交接。

实际记录的配置/生命周期行为：config `{backend:"sqlite", path (非空, 非目录, 非 `:memory:`), busy_timeout_ms (正整数), synchronous (仅 "FULL"), 无未知键}`；gate → 只读采用预检 → 原子全新创建或有序的待处理迁移 → WAL pragma；读取/诊断在输入前允许，mutators 需要已输入的作用域，嵌套仅在最外层提交一次，depth-0 提交是无操作的关闭，关闭的 UoW 拒绝变异。

## 命令与观察

- 红色：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:. /opt/homebrew/bin/python3.12 -m pytest tests/protocol_v3/test_repository_backends.py tests/protocol_v3/test_sqlite_product_storage.py -q -p no:cacheprovider --tb=no` → 11 失败 / 110 通过（退出码 1）；输出已保存。
- 绿色：针对两个文件（121 通过）、仅每个文件（76 / 45）、Codex 探测（5 通过）、完整测试套件（`... -m pytest tests/protocol_v3 -q -p no:cacheprovider` → 1361 通过 + 101 子测试）的相同环境命令。未进行全仓运行。
- 已修复的迭代观察：`ChapterCoverageRecord` 从端口导入，而不是契约；我的 sidecar 断言最初比 SQLite 的实际 ro-open 行为更严格（空运行时 sidecar）— 已针对真正的审计不变量进行更正（主文件字节相同，无检查点内容）；在一条新消息中发现了 `'. '` 拼写错误，并在同一次传递中修复。

## 阻塞项或缺失环境

无阻塞项。范围外待处理事项，仅报告，未编辑：用于 `sqlite3.Error`/`SqliteStorageError` 的驱动程序级异常转换在 `application/service.py` (`_EXCEPTION_MAP`) 和 `events/unit_of_work.py` 的 CAS/发件箱步骤中是必须的 1R.3 工作（会议发现 F2 — 今天仍然失败关闭：原始驱动程序异常传播且 `with` 块回滚）。1R.2 主组合根切换仍然是产品激活 gate；显式函数路由不取代它（会议 Q1/F8 在 Codex 的裁决下保持开放）。

## 重新运行请求或下一步

无重新运行请求。通过只读 Codex 探测文件的所有五个验收探测均通过；full suite 为绿色。此后续操作未声称任务关闭或产品验收 — Codex 和独立的最新验证器拥有 done 权限。建议的下一步：针对 `repair_01/final_hashes.txt` 重新冻结验收记录，并注册 1R.3 驱动程序异常转换项。
