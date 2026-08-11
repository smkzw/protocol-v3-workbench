# Task 1.8 — Protocol v3 目标存储决策

日期：2026-08-11
状态：`STORAGE_SELECTED_SQLITE_3_53_1` / `PRODUCT_ACTIVATION_FAIL_CLOSED`
边界：仅锁定本地/私有部署目标存储的候选比较与选择；不是产品 cutover 完成，
不是 Gate P1-G1 的最终验收（Codex 拥有验收）。

## 决策

为 approved multi-Agent Protocol workflow 的 **本地/私有单工作站部署**
（`deploy/medical_writing_local`）选择 **SQLite 3.53.1**（stdlib `sqlite3`，
Python 3.12.13 Homebrew 运行时）作为 canonical/event/outbox/checkpoint 目标存储。

- PostgreSQL 18.4 通过全部冻结阈值（8/8 不变量），但作为 **已量化证据保留的
  scale-up 路径**，不在本任务激活为产品存储。
- Memory 保持 **test/reference 实现** 角色，不进入产品路径。
- `selected.py` 是存储中立的选择/工厂/能力表面；产品 adapter 尚未接线，
  **产品激活 fail-closed**（见「产品 cutover 与阻塞」）。

设计 §5.2 将 PostgreSQL 列为"首选目标"，§23.3 要求以真实 PoC 锁定该选择；
Task 1.8 的 Objective 正是"不让数据库选择污染领域合同"地比较两者。实测证据
表明：目标规模下 PostgreSQL 的 MVCC 并发优势并不需要，而其运维负担与依赖
打包成本是真实的；因此不因架构偏好选择 PostgreSQL，也不因"已可用"选择 SQLite
（选择依据见「选择理由」逐项论证）。

## 候选与环境（精确版本/许可证）

| 候选 | 引擎/驱动 | 版本 | 许可证 | 身份 | 确定性 digest |
|---|---|---|---|---|---|
| SQLite（**选择**） | SQLite / stdlib `sqlite3` | 3.53.1（`/opt/homebrew/bin/python3.12`，Python 3.12.13） | public domain（sqlite.org/copyright.html） | `sqlite_3_53_1` | `64a56f66e4300b318f6586803151f475e2ad8de9a74d0acfad14fe46a81adad8` |
| PostgreSQL（未选择，保留） | PostgreSQL 18.4（`/opt/homebrew/opt/postgresql@18`）/ psycopg 3.3.4（LGPL-3.0-only） | 18.4 | PostgreSQL License；psycopg `LGPL-3.0-only` | `postgresql_18_4` | `fce59b62be3dc94d069affe9c76cdd0d9f41e8340459cb9fc9336ff96fde8630` |
| Memory（test/reference） | 进程内 | — | 项目自有 | `memory` | `8fc8a060a7ab1d27f1f780287e0895c97c7f76b49f8bb5b5226ee7423fc84a7b`（5 passed / 3 fail-closed，receipt：`results/memory_candidate.json`） |

环境事实：`brew list --versions postgresql@18` = `18.4`，`brew services` = `none`；
任务 venv `pocs/protocol_v3/storage/.task18_pg_venv` 仅含 psycopg 3.3.4
（suite 以系统 python3.12 + venv site-packages 前置运行，pydantic 2.13.4）；
PostgreSQL 临时集群为 `initdb --data-checksums`、Unix socket 仅 trust、无
LaunchAgent，证据采集后已 `pg_ctl -m fast` 停止并删除（`pgrep -fl postgres`
为空）。SQLite 版本门：`MIN_SQLITE_VERSION=(3,51,3)`（3.51.0–3.51.2 含
multi-connection reset 缺陷，3.51.3+ 修复）。该门由 **PoC adapter 的
`assert_sqlite_version` 强制**（fail-closed）；`selected.py` 仅**声明**
`SELECTED_MIN_ENGINE_VERSION` 作为元数据。**产品路径尚无 preflight**：产品
运行时强制要等未来产品 `sqlite.py` 接线 `assert_sqlite_version` 后才生效。
运行时资格事实：Homebrew Python 3.12 链接 3.53.1（合格）；系统 Python 3.9.6
链接 3.51.0、Codex 捆绑 Python 3.12 链接 3.50.4（均受影响，不可用于产品
运行时）。

## 冻结阈值与实测结果

阈值不可变：8 独立 writer、1,000 CAS、10,000 事件；lost update=0、重复
semantic effect=0、hash-chain break=0；同一 repository contract 在
memory/SQLite/PostgreSQL 上一致；migration count/hash=100% 且 quarantine；
committed event RPO=0；10× 参考规模 backup→restore→replay < 15 分钟且
canonical hash 一致；本地 CAS p95 ≤ 500 ms 或记录真实用户影响；未安装
driver/migration stack 不算 PostgreSQL PASS。

| 不变量 | 阈值 | SQLite 3.53.1 | PostgreSQL 18.4 | Memory |
|---|---|---|---|---|
| cas_concurrency | 8 writers/1,000 ops，lost/dup=0 | PASS，p95 1.666/1.687 ms（Codex 复跑；PoC run0/1 = 0.603/1.727 ms），0 conflicts，8 distinct conns，overlap 8；busy retry 实测 range：canonical/run0 = 1、run1 = 0（见「SQLite 并发机制与 busy 说明」） | PASS，p95 97.791/94.118 ms（Codex 复跑；PoC run0/1 = 88.37/88.507 ms），conflicts 2820/2924（PoC run0/1 = 2622/2611），8 conns，overlap 8 | PASS，p95 19.27 ms（receipt `8fc8a060…`），0 conflicts（后端锁串行化），8 distinct conns，overlap 8 |
| event_chain | 10,000 events，break=0，hash 一致 | PASS，replay `d80c1f03…` | PASS，同 hash `d80c1f03…` | PASS，同 hash `d80c1f03…`（确定性载荷与 SQLite/PG 逐字段一致） |
| transaction_outbox_atomicity | commit 同持久/rollback 同丢弃 | PASS | PASS | PASS（确定性载荷一致） |
| checkpoint_isolation | 200 events，count/hash 不变，run/project 隔离 | PASS | PASS | PASS（确定性载荷一致） |
| migration_quarantine | 10 families，100% 记账，quarantine 保留 | PASS，10 families，全部 hash match | PASS，同（deterministic body 字节相等） | PASS，10 families，全部 hash match（确定性载荷一致） |
| crash_recovery | RPO=0，SIGKILL 验证，dup=0 | PASS，WTERMSIG=9，return -9，300 events，replay `d61bd649…` | PASS，同证据画像 | FAIL-CLOSED（`UnsupportedCapabilityError`，receipt 稳定错误） |
| backup_restore_replay | 10× 规模 <15 min，hash 一致 | PASS，63 ms（canonical measured_ms 344 ms），hash `d966720f…` | PASS，501 ms（canonical measured_ms 1,142 ms），pg_dump -F c / pg_restore，hash `d966720f…` | FAIL-CLOSED（`UnsupportedCapabilityError`，receipt 稳定错误） |
| rollback_to_snapshot | 恢复 pre-switch 快照，hash 精确回退 | PASS，`ecc3d268…` 精确恢复 | PASS，同 hash | FAIL-CLOSED（`UnsupportedCapabilityError`，receipt 稳定错误） |

- SQLite 全量：3 次 PoC + 2 次 Codex fresh runs 全部 8/8 PASS。
- PostgreSQL 全量：3 次 PoC + 2 次 Codex fresh runs（Unix-socket-only 一次性
  cluster）全部 8/8 PASS；pg_dump/pg_restore 10k 事件 exact replay
  （dump 3,689,149 bytes，checksums v1，hash `b37b2bed…`）。
- 回归：两候选各自完整 `tests/protocol_v3/` = **870 passed, 101 subtests**。

### SQLite 并发机制与 busy 说明（事实修正）

- 不存在 application 级共享 `RLock`。每个 UoW 使用**独立 SQLite 连接**；写入
  以 **WAL + `BEGIN IMMEDIATE`** 串行化（SQLite 引擎自身单写者模型），读为
  并发。`sqlite_adapter.py` 明确写 "no application-side serialization (no
  shared RLock)"。
- PoC 默认 `busy_timeout_ms=100`（`_conn_for` / `SqliteUnitOfWork` 实际值），
  adapter 模块 docstring 已同步为 `100`。
- busy retry 是**实测、调度相关**的量，不是固定机制事实：`sqlite_candidate.json`
  （canonical）与 `run0` 各记录 `busy_retries_total=1`，`run1` 记录 `0`。
  不把"一次 busy retry"描述为机制保证。

## 跨候选一致性（Worker 03 独立复核）

- `workload` 字典字节相等（writers=8, cas=1000, events=10000, backup=10000,
  reference=1000, scale=10）。
- 全部 8 个不变量 `deterministic` 载荷逐字段字节相等（含 migration 每 family
  source/migrated/quarantine/hash 与 quarantine 原因码）。
- canonical hash 跨候选一致：event replay `d80c1f03…`、backup replay
  `d966720f…`、checkpoint `89b29a0c…`、crash replay `d61bd649…`、rollback
  `ecc3d268…`/`7e9eb0f1…`、migration family hash（如 SDR `8fbd7355…`）。
- digest 重算复核：以 `{candidate, workload, invariants[name,passed,deterministic,error]}`
  为载荷的 SHA-256 与 6 份结果 JSON 记录值逐一 MATCH；两候选 digest 差异仅由
  `candidate` 名参与 digest 载荷造成。精确值：**不含 candidate 的完整
  deterministic 载荷** = `177ae8b89c767c0740e55ab57dd15774495be881c8743e6715398dbd33e87862`
  （SQLite/PG 相同）；**仅 invariant deterministic 载荷列表**（按套件顺序）的
  SHA-256 = `bce2cd929a60fc1c1bcf440b7e521d567efd1cff431530752e5f399a97e21dcc`。
  → 接受证据中的"候选 digest 仅因候选名参与而不同"成立。
- Memory 候选（`results/memory_candidate.json`，digest
  `8fc8a060a7ab1d27f1f780287e0895c97c7f76b49f8bb5b5226ee7423fc84a7b`）：5 个
  支持不变量（cas/event/atomicity/checkpoint/migration）的 deterministic 载荷
  与 SQLite、PostgreSQL 逐字段一致；3 个持久不变量以稳定
  `UnsupportedCapabilityError` 显式 fail-closed，无静默跳过/通过。

## 选择理由（逐项，第一性原理）

| 因素 | SQLite 3.53.1 | PostgreSQL 18.4 | 结论 |
|---|---|---|---|
| 持久性 | WAL + synchronous=FULL，commit 前 fsync；RPO=0 实测（SIGKILL 后重开 hash 精确） | 默认同步提交 + fsync；RPO=0 实测 | 平手 |
| 实际独立 writer | 独立连接 + WAL + `BEGIN IMMEDIATE` 的单写者串行化（**无共享应用锁**），8 conns/overlap 8，lost/dup=0；busy retry 实测 1/0 | 真 MVCC，~2,600–2,900 conflicts/1,000 ops 全部重试成功，lost/dup=0 | 两者都满足冻结合同；目标写速率（医学写作人工规模）下串行化不构成瓶颈 |
| 多 Agent/进程轨迹 | WAL 支持多进程并发读 + 单写者，PoC 默认 `busy_timeout_ms=100`；crash child 证明跨进程重开 | 完整多进程并发 | 单机部署两者均成立；写路径经 application service→UoW→CAS 汇流，SQLite 队列在人工规模下不可感知 |
| 本地/私有部署 | 单文件、零服务、零 socket/端口、零生命周期 | server 进程、initdb cluster、端口/socket、pg_ctl 生命周期、升级纪律 | **决定性**：lazy expert user 单机部署，SQLite 运维≈0 |
| backup/restore | 在线 `Connection.backup` / 文件复制，63 ms @10k 事件 | pg_dump -F c / pg_restore（3.7 MB，501 ms）+ PITR 选项 | 均大幅低于 15 min 阈值；SQLite 单文件复制更贴近 lazy user |
| rollback | pre-switch 快照恢复，hash 精确回退 | pre-switch dump 恢复，hash 精确回退 | 平手 |
| p95 用户影响 | ~1.7 ms（阈值 500 ms） | ~88–98 ms（阈值 500 ms），~60× 于 SQLite，且每次 CAS 平均 ~3 次 conflict-retry churn | 两者交互影响都可忽略；SQLite 更优且无重试税 |
| 运维负担 | stdlib 驱动、零依赖、文件级备份 | psycopg 打包、server 生命周期、socket/端口、pg_dump 纪律、版本升级 | **决定性**：对 lazy expert user，PostgreSQL 负担与目标规模不匹配 |
| 许可证/依赖打包 | public domain，stdlib，零新依赖，不改 requirement 文件 | psycopg==3.3.4（LGPL-3.0-only）**不在** `requirements-protocol-v3.in/.lock`（该文件许可证组限定 MIT/BSD-3-Clause/Apache-2.0）；加入 LGPL 是未授权的打包/许可合同变更 | **决定性**：SQLite 零变更；PostgreSQL 激活被依赖打包阻塞（见「产品 cutover 与阻塞」） |
| 可逆性与迁移风险 | 保留 repository 抽象（ports），切换=换 adapter；唯一约束是运行时 SQLite ≥3.51.3（PoC `assert_sqlite_version` 强制；`selected.py` 声明；产品路径待产品 `sqlite.py` 接线后强制；Homebrew Python 3.12 = 3.53.1 满足） | 选择即承诺 LGPL 依赖 + server 生命周期 + deploy/ migrations；可逆成本高 | SQLite 可逆性显著更优 |

综合：目标为本地/私有单工作站、多 Agent 进程、人工规模写速率、lazy expert
user。SQLite 在持久性/正确性不变量/备份恢复/回滚上与 PostgreSQL 等价，在
p95 延迟、运维负担、依赖打包、可逆性与迁移风险上更优；PostgreSQL 的 MVCC
并发与 PITR 优势在目标规模下无用户可见收益。**选择 SQLite 3.53.1。**

## 拒绝理由（保留角色）

- **Memory**：非持久、非跨进程；`backup_restore_replay` / `crash_recovery` /
  `rollback_to_snapshot` 三个不变量以稳定 `UnsupportedCapabilityError`
  **显式 FAIL-CLOSED**（可执行 receipt：`results/memory_candidate.json`，
  digest `8fc8a060…`；5 passed / 3 fail-closed；5 个支持不变量确定性载荷与
  SQLite/PostgreSQL 逐字段一致）。它是现有参考与测试实现
  （`test_repository_contract.py` 等既用），**保留** test/reference 角色，
  仅经 `create_test_memory_unit_of_work_factory()` 显式测试路由可达；
  生产 factory 拒绝 `backend="memory"`。
- **PostgreSQL（非选中但合格）**：通过全部冻结阈值，但按上表逐项理由不作为
  本目标存储；**保留** 为已量化、可复现的 scale-up 路径（postgres_adapter.py、
  postgres_migrations/、结果 JSON 均为冻结证据）。若未来多机/高并发/服务化
  部署需要，Codex 授权 psycopg==3.3.4（LGPL-3.0-only）打包后可基于该证据
  实现产品 adapter 与 deploy/ migrations，不重跑 PoC。

## 限制与失败证据（含被拒/未完成的 worker pass）

- Worker 01 初始 SQLite 结论被拒：database-neutrality、真实多连接并发、
  duplicate-effect、跨进程 crash、持久 checkpoint、完整 migration-family、
  10,000 事件 backup、可复现 receipt 均未成立。
- Worker 01 Recovery 01 被 runner 拒收：身份检查把当前 turn 与历史
  `cms-model` 事件合并；Codex 复现并修复全局 runner（历史模型仍可审计、
  仅当前 turn 决定 route 身份）——即 **loopback rerun**；随后静态审查发现
  P1 缺陷：真实连接未关闭、CAS 身份/p95 来自非 workload 探针、busy-timeout/
  报告不一致、过度宽泛 retry 掩盖、migration/quarantine 覆盖不全、
  crash 证据非 fail-closed/self-exit、fixture hash 随机化、deterministic
  字段依赖调度。
- Worker 01 Recovery 02 被拒：runner 报告止于实现意图；crash recovery
  自退出并默认 commit 证据。
- Worker 01 Recovery 03 被拒：OMP 内部替换未声明模型（`opencode-go/mimo-v2.5`）
  被 runner 正确拒收；SIGKILL 断言只证明信号送达、未证明 wait 状态。
- Worker 01 Recovery 04 接受：`waitpid` fail-closed 验证
  （WIFSIGNALED && WTERMSIG==9，派生 return -9），真实负向探针（正常退出、
  SIGTERM）。Codex 另修复 `run_lifecycle_probe()` 自举 SQLite 候选的缺陷，
  两次 fresh 全量 8/8 + digest `64a56f66…`。
- Worker 02 初始 + Recovery 01 失败：PostgreSQL 未安装、无候选产物。
  Recovery 02 完成：3 次 fresh 8/8（digest `fce59b62…`）、pg_dump/pg_restore
  证据、集群停止删除、870/101 回归；修复 schema_version 建表顺序、
  `psql.Identifier` 字符串化、crash-child venv site 传递三个缺陷。
- 已知限制：任务 venv 缺 pydantic（suite 以系统 python3.12 + venv
  site-packages 运行，未静默装包）；ruff/mypy 未安装（以 py_compile +
  import smoke + 全量回归作静态检查）。

## 部署/回滚流程（选中 SQLite）

1. **Preflight（版本门）**：PoC 以 `assert_sqlite_version` 强制运行时 SQLite
   ≥3.51.3（受影响 3.50.4/3.51.0 直接失败）；`selected.py` 声明
   `SELECTED_MIN_ENGINE_VERSION`；**产品路径的强制要等未来产品 `sqlite.py`
   接线 `assert_sqlite_version` 后才生效**（本任务不存在产品 preflight）。
   当前合格运行时：`/opt/homebrew/bin/python3.12`（3.53.1）。
2. **激活前置（本任务未完成，见下）**：产品 adapter 实现并接线后，
   factory 才可构建 UoW；在此之前 `create_unit_of_work_factory` 抛
   `StorageNotReadyError`（fail-closed，无任何回退）。
3. **首次 cutover**：写第一笔前冻结 pre-switch snapshot（数据库文件 +
   checkpoint 的 WAL 检查点 TRUNCATE）；初始化 schema（镜像 PoC
   `_SCHEMA_SQL` 与版本门）；application service 经 `selected.py` factory
   获取 UoW。
4. **备份**：在线 `Connection.backup` 或单文件复制（备份前 checkpoint）；
   可验证 canonical event replay hash。
5. **回滚**：恢复 pre-switch snapshot 文件，重放事件重建 canonical 状态，
   核对 hash 链；新链历史保留，不改写旧 immutable rows（§5.2）。
6. **停止条件**：任一不变量失败、lost/duplicate effect 非 0、hash-chain
   break、运行时 SQLite <3.51.3、medical-monitoring diff → 停止并 fail-closed。

## 产品 cutover 与阻塞（PoC 接受 ≠ 产品激活）

- **本任务交付**：PoC 证据锁定选择（`decision.md`）、存储中立选择/工厂/能力
  表面（`selected.py`）、聚焦测试。**不包含**产品 adapter 接线；不得声称产品
  SQLite 已激活——只有 PoC adapter 存在。
- **阻塞（Codex 后续项）**：实现并接线产品 adapter
  `services/api/app/protocol_workflow/storage/sqlite.py`（镜像已接受 PoC：
  ports 合同、版本门 ≥3.51.3、持久化纪律、CAS/outbox/backup），并在
  `selected.py` factory 注入其 builder。PoC adapter 是证据，永不被产品代码
  import。
- **依赖打包**：SQLite 选择零 requirement 变更（stdlib）。PostgreSQL 若未来
  激活：需 Codex 授权 `psycopg==3.3.4`（LGPL-3.0-only）加入
  `requirements-protocol-v3.in` 并重生成 `.lock`（本任务未静默编辑
  requirements，也未创建产品 `postgres.py`/deploy migrations）。

## 残余风险

- 产品 adapter 未接线 → 生产激活 fail-closed（有明确阻塞信息）。
- 部署约束：运行时 SQLite 版本门（≥3.51.3）由 PoC 强制、由 `selected.py`
  声明；错误打包的 Python 链接受影响版本时，产品路径在 adapter 接线前尚无
  preflight，接线后应 fail-closed 拒绝而不是静默降级。
- 单写者串行化是并发上限：若未来写并发升至 server 规模，需切换 scale-up 路径
  （PostgreSQL 证据已冻结）。
- PostgreSQL 路径的 LGPL-3.0 psycopg 打包需 Codex 授权；PITR/pg_dump 纪律
  在目标规模不需要。
- 加密/密钥放置（§23.3 PoC 矩阵项）仅作为**未来部署元数据**记录（如 SQLite
  file 权限/目录策略、密钥由环境注入）；本任务不做安全分析或测试。
- 本任务未运行或派发安全/对抗/权限/路径/符号链接/恶意输入测试（按风险边界）。

## Gate 建议

SQLite 候选：CODEX-ACCEPTED（含 Codex 两次 fresh 8/8 与 digest）。PostgreSQL
候选：CODEX-ACCEPTED（含 Codex 两次 fresh 8/8 与 digest）。Memory：可执行
receipt `8fc8a060…`（5 passed / 3 fail-closed，与 SQLite/PG 支持不变量逐字段
一致）。选择：SQLite 3.53.1 作为本地/私有目标存储。最终 Gate P1-G1 验收、
产品激活与 cutover 由 Codex 拥有；本记录为决策输入，不是验收结论。
