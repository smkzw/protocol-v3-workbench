全部验证完成：全量 1372 passed + 101 subtests，四文件前后哈希一致。输出最终裁决。

# Conference Output: mw_protocol_v3_1r1_fresh_20260905 - evidence_single_object

## 输出

对 R1/R2 窄修复的独立再验证（第三轮）。合同权威与调用方（ports、application/service.py、events/unit_of_work.py、storage/memory.py）本轮 git 确认零改动；评审基准不变。

### 建议: READY（限 Task 1R.1）

R1、R2 均已用源码审查+原复现机制的独立闭合探针+新增正回归确认关闭；上两轮全部守卫（异库/约束/事务/八探针）复跑全绿；无剩余阻断项。未来义务（1R.2/1R.3）单列，不做主张。

### R1 解决（前向迁移指纹）

- **源码**：`_reference_schema_fingerprint(version)`（sqlite.py:505-525）现在只将 `mig_version <= version` 的迁移应用到临时参考连接（:517），预检以数据库实际验证版本调用（:720）；bootstrap 级全局缓存 `_REFERENCE_SCHEMA_FINGERPRINT` 已整体移除（全文件 grep 无残留；新测试以 `raising=False` 的 monkeypatch 承认其不存在）。修复为参数+循环守卫的极小改动，无新增架构层——未缓存意味着每次 bootstrap 重建一次性内存参考，代价有界且消灭了陈旧签名类别。
- **新增正回归**（test_sqlite_product_storage.py:1153 起）：`test_owned_v1_migrates_and_reopens_without_losing_rows` 参数化 冷/热 × 加表(1R.2式allowlist)/加列(ALTER outbox_message)——v1 升级成功、业务行跨升级+两次重开全等保留、版本行恰为 `[(1,),(2,)]` 不重复、integrity_check ok；`test_failed_upgrade_preserves_v1_and_can_resume`——失败迁移的 DDL 与版本行随 `_apply_migration` 的 BEGIN IMMEDIATE 事务回滚（版本保持 [(1,)]、migration_probe 表不存在、integrity ok），修复后的迁移安全续迁。
- **独立闭合探针**：`runs/mw_protocol_v3_1r1_fresh_20260905/final_storage_verification/test_verifier_closure_probes.py::TestR1ClosureForwardMigration` 以我第二轮的**同一 allowlist 场景与热身步骤**、正确判据重跑——原先抛 `SqliteStorageConfigurationError` 的调用现在完成迁移、数据保留、版本行精确、integrity ok。2 passed。
- 边界确认：当前 `_MIGRATIONS` 仍仅 v1；合成迁移2是前向路径证明，**不是** 1R.2 产品激活。

### R2 解决（claim 原子性）

- **源码**：`claim_pending`（sqlite.py:1228-1264）整个领取循环包入 `SAVEPOINT protocol_v3_outbox_claim`，BaseException 时 `_undo_savepoint` 回滚全部领取/attempt/dispatched_at，成功后 RELEASE——与事件批、投影替换同一模式。
- **新增正回归**：`test_caught_claim_failure_rolls_back_entire_claim_only`——lk:2 触发器失败被外层事务内捕获后提交，lk:1/2/3 全部回到 `(pending, 0, None)`，同事务无关工作（异项目 lk:other）存活。
- **独立闭合探针**：`TestR2ClosureClaimAtomicity` 以第二轮同场景、正确判据重跑——整批领取回滚、无关工作保留。通过（并入上述 2 passed）。

### 守卫完整性（准则3）

三个 Codex 探针文件（异库版本拒绝、投影原子性、CTAS 约束克隆）+ 两个测试文件复跑：**140 passed**（较上轮 +6 = 新回归）。预检/约束/事务逻辑除版本参数化外结构未变，异库/畸形/未来库拒绝仍在只读连接上字节不变。全量 `tests/protocol_v3`：**1372 passed + 101 subtests，0 failed**（较上轮 +6）。

### 旧探针处置（准则4）

`runs/mw_protocol_v3_1r1_fresh_20260905/repair_verification/test_verifier_residual_probes.py` **原样保留、未编辑、未作为门运行**——它断言旧断裂行为（部分领取存活、v1 库被拒），对修复后代码按设计会失败，属历史证据。被移除的私有缓存变量非公开产品合同。当前门为产品新回归 + 我的闭合探针（正确判据）。

### 实际命令与结果

| 命令 | 结果 |
|---|---|
| `pytest runs/.../final_storage_verification/test_verifier_closure_probes.py -q` | **2 passed** |
| `pytest runs/mw_protocol_v3_1r1_codex_20260905/test_acceptance_probes.py test_projection_atomicity_probes.py test_schema_constraint_probe.py tests/protocol_v3/test_repository_backends.py tests/protocol_v3/test_sqlite_product_storage.py -q` | **140 passed** |
| `pytest tests/protocol_v3 -q` | **1372 passed, 101 subtests, 0 failed**（2 个预存无关 deprecation 警告） |
| 运行时身份 | zcode/GLM-5.3（会话内不可切换）；Python 3.12.13 / SQLite **3.53.4**（≥3.51.3 门，实测） |

**前后哈希**（检查前=检查后=声明值）：
- `storage/sqlite.py` = `18770a1c277f8808258280260cb84c04ed6bce96f4c8cf73bc7dc45eb389275e`
- `tests/protocol_v3/test_sqlite_product_storage.py` = `6710dd96865f2272b2b83ba0f5f615f453625983a404daca1e1bb56406a7c069`
- `storage/selected.py` = `153fc687d1414ca41218daec7b1777a73e98dbf8476491ba926a91c3d9d7a6d3`（未变）
- `tests/protocol_v3/test_repository_backends.py` = `0b1dd33b2b551fb6b144d3df1bff652d886e51edf76b82bff94420d6c1d044f5`（未变）

### 剩余阻断项

无。非阻断记录（沿前轮，状态未变）：预检→写相 TOCTOU 仅以版本复读收窄（sqlite.py:770-776）+ 迁移内 BEGIN IMMEDIATE 版本复核（单进程产品边界情形）；内省不覆盖触发器/视图/collation/非唯一索引（owned DDL 无 CHECK/FK 可指纹）；`readiness_report()` docstring 措辞略滞后（行为被不可变测试钉住，无实际问题）。

### 未来义务（明确不做完成主张）

- **1R.2**：追加真实 allowlist 迁移（含每迁移指纹）、composition root 挂载、main 入口隔离与旧库零写入——本探针的前向路径证明是前置条件已满足，非 1R.2 本身。
- **1R.3**：驱动异常分类（原始 `sqlite3.Error` 穿透 `application/service.py:813-824` 的 `_EXCEPTION_MAP`、CAS/outbox 步窄 except、COMMIT 失败传播——fail-closed 但未翻译）仍为显式 pending；API 错误 envelope、端到端集成、备份恢复同属 1R.3。HTTP 未挂载，未主张。

### 局限与源边界

仅隔离 checkout；初始读集四文件全读，ports/调用方/memory 经 git 确认未动；未读 worker 报告/日志/推理；未启动服务、未 import main、未装依赖、未 commit。唯一写入为 `final_storage_verification/test_verifier_closure_probes.py`（apply_patch 添加）；旧探针文件未触碰。验证者隔离仍为家族级（GLM-5.3），独立性以可执行复现而非模型差异实现。本裁决限 Task 1R.1 存储验收，不关闭整体产品任务，不主张产品/UI/Word/临床/监管/生产验收；Codex 保留最终裁定权。
