# G2 验证矩阵：准备批次创建/复用/事实与shortlist变化（A201-A206）· 0927V1

仓库 protocol-v3-workbench，验证时 HEAD=5b4c8c11692fc3118eb21bfe80877f5ce9d76c65（全程未变）。
方法：真实服务 + 临时 SQLite（A20，非mock业务写入；唯一的假件是公开文档HTTP下载边界 ControlledDocumentClient，沿用仓库既有测试模式）。测试文件 `tests/test_writing_reference_preparation_batch_g2.py`，七组场景。
一句话结论：**计划怀疑的"同键重试旁路"属实并已修复**——修复前同一幂等键下研究设计（study facts）变了仍静默拿旧批次；修复后同键同事实照常复用、同键事实变化明确报冲突。其余六组场景（含并发双提交）修复前即绿。

## 一、红先反例（修复前，红线8）

命令：`python3 -m pytest tests/test_writing_reference_preparation_batch_g2.py -q -p no:cacheprovider`
结果：**1 failed（仅A203）, 6 passed**。失败即反例本体：

- A203用例：同幂等键第一次create成功后，把authoring journey的研究事实（研究药物/靶点）改为v2，再以**同一键**create——期望 `WritingReferenceConflictError`，实际**未抛**（静默复用陈旧范围批次）。日志：`g2_red_before_fix.log`（"WritingReferenceConflictError not raised"）。
- 源码根因（修复前实读）：`create()` 先用仅含 `{snapshot_id, stage_size}` 的 request_hash 查重放（writing_reference_preparation_batch.py:219-229），命中即返回旧批次；冻结身份（study_facts_sha256/scope_entries）在 :231 之后才计算——重放判定**看不见**冻结输入的变化。而仓库层冲突机制本是完备的（writing_reference_repository.py:5848-5869：hash不同即抛冲突），只是永远够不着。

## 二、修复（单点，最小diff）

`services/api/app/writing_reference_preparation_batch.py create()`：
`_frozen_scope`（连同 scope_sha256 计算）前移到重放检查**之前**；request_hash 改为 `_payload_hash({snapshot_id, stage_size, scope_sha256})`。事务内二次重放检查（:293-306 一带）自动使用同一新hash。batch_id 算法**不变**（本就含 scope_sha256+幂等键，:256-263），避免存量身份漂移。

## 三、修复后矩阵（同一命令 → 7 passed，日志 g2_green_after_fix.log）

| 编号 | 场景 | 期望 | 实跑 | 证据节点 |
|---|---|---|---|---|
| A201 | 干净库首次create（真实链：锁定快照+相关性决定+journey锁→create） | 批次accepted、scope_sha256 64位、retained正确、幂等行恰1条 | 修复前后均绿 | test_a201_first_create_on_clean_store |
| A202 | 同命令完全重放（同键+同事实） | 同batch_id、同scope、条目不重复、幂等行唯一 | 修复前后均绿（语义保持） | test_a202_exact_replay_same_key_reuses_batch |
| A203 | 同键+研究事实v1→v2 | **WritingReferenceConflictError**，原批次scope不被改动 | 修复前红（静默复用）→ **修后绿** | test_a203_same_key_changed_facts_conflicts |
| A204 | 新键+事实变化 | 新scope_sha256+新batch_id，旧批次可查，审计链两批齐全 | 修复前后均绿（batch_id本含scope身份） | test_a204_new_key_changed_facts_new_scope |
| A205 | 冻结范围一次读取不拼接（首次读后facts即翻转到v2） | retained与facts hash来自**同一次**journey读取（无跨版本拼接） | 修复前后均绿（:585-597一次读取设计成立；首次修测试假件曾误报，系假件revision随读自增，已按真实语义修正） | test_a205_frozen_scope_one_shot_read_is_tear_free |
| A206 | 同快照两prep批次 + 翻译绑定 | 新翻译批显式绑定latest（prep2）；旧翻译批保留存储的prep1绑定；其对prep2存在下的恢复按stale_lineage终态失败，**绝不**在新scope下翻译 | 修复前后均绿 | test_a206_two_preparations_translation_binds_latest_and_old_stays |
| 并发 | 同键双连接+栅栏同时create | 恰一个批次；另一路径由BEGIN IMMEDIATE串行化+事务内重放返回同一批次 | 修复前后均绿（无sleep时序断言） | test_concurrent_same_key_double_submit_single_batch |

## 四、旁路审计（源码实读+行为验证）

1. **request_hash 组成（已修）**：修前 `{snapshot_id, stage_size}`；修后 `{snapshot_id, stage_size, scope_sha256}`。scope_sha256 本身绑定 project/snapshot/retained/entries/study_facts_sha256（:234-248）——冻结身份自此进入重放判定。
2. **admit_next_stage 第二hash面（:787-792）**：含 batch_id、阶段索引等，绑定具体批次——不受本缺陷影响，无需改动（现状=期望）。
3. **翻译对latest()的依赖**：调用点 writing_reference_translation_batch.py:4163（本轮rg实读仅此一处产品调用）；`latest()` 实现在 prep:451-468（created_at DESC, rowid DESC）。语义=新翻译任务隐式绑最新批次；旧行为由**存储的 preparation_batch_id**（建批写入，translation_batch:941/:952）+ `_validate_frozen_lineage`（:7531-7545：latest变了→StaleLineageError→item标 failed_terminal/stale_lineage :4744-4750）兜底。A206用例已按此行为断言：旧行恢复绝不串到新scope下执行。
4. **未跑面（A12如实声明）**：本轮验证范围=preparation_batch + translation_batch 两文件及直接依赖；`_validate_frozen_lineage` 的其余分支（artifact失效、验证记录漂移等）由既有测试覆盖，不在本轮复验清单。

## 五、语义变化与迁移说明（集成人决策点）

- **同键重试语义变化**：facts变化后同键重试从"静默拿旧批次"变为"明确冲突"。这是矩阵裁决要求的方向；同模块族回归确认绑定/恢复路径无恙（见下）。
- **存量幂等行**：既有幂等行按旧公式记hash，修复后同键重试会命中冲突而非重放——属一次性切换语义。本切片全部用临时库验证，未触碰 live 库（isolated_runtime）；若需兼容窗口，由集成人定迁移策略。
- **成本**：每次create（含重试）都会先算冻结范围（多几次SQLite只读）。G2套件7用例全程4秒内，实测开销有界。

## 六、回归证据

- 模块族回归：`python3 -m pytest tests/test_writing_reference_preparation_batch.py tests/test_writing_reference_translation_batch.py -q` → **82 passed, 18 failed**。18个失败与 623ff21 基线中该文件的18条记录**节点集合完全一致**（A03逐节点比对通过，纯现存债务，非本批引入；translation_batch零失败）。日志：g2_family_regression.log。
- 验收车道：`python3 -m pytest tests/acceptance -q` → **57 passed**（前批门修复/三车道/A11回归全部保持绿）。
- 边界遵守：全程离线零模型（A16）；临时SQLite，未碰live库与隔离runtime；未跑全量（红线5，收尾脚本统一）；单点修改在单一集成人授权文件内（红线4）。
