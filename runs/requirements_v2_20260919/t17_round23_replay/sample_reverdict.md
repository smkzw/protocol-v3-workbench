# 样本重判（wave=0）：NCT02176291 忠度阻断项复核证据（2026-09-27）

## 一、结论（先看这里）

**实判 = confirmed（维持原判）。**

- 样本条目：`wref_translation_item_c561fdf957b2132967c662b1`（NCT02176291，第14次尝试阻断，译文 rev=1）。
- 初判两码：`unit_1:numeric_tokens_changed` + `unit_1:source_abbreviation_missing`。
- 本轮用确定性检查器对重建出的单元级证据做零模型重放：**两码逐字复现，无一推翻，无一不可验**（1/1 单元 confirmed）。
- 处置边界未动：条目仍在 `fidelity_blocked`，未发生任何自动晋级；是否放行由用户医学人工门裁定。

## 二、本轮实际执行的核对链（每步均为本轮亲跑）

| # | 步骤 | 命令/口径 | 结果 |
|---|---|---|---|
| 1 | 仓库基线 | `git log --oneline -1` | HEAD=`06b5155`（=恢复基线，满足≥） |
| 2 | 运行面指纹（重启前） | `GET /api/runtime-readiness` | 旧进程报 `api-a91f7ece9407c5cc`（18:07启动，早于本轮代码改动） |
| 3 | 本地树指纹 | `runtime_readiness.backend_build_id()` | `api-be195048893005bd`（≠旧进程 → 确认必须重启） |
| 4 | 重启5301 | 原样env（隔离runtime目录+AI设置+PYTHONPATH），SIGTERM→uvicorn | 新PID 49961，启动日志 0 Traceback/ERROR |
| 5 | 运行面指纹（重启后） | `GET /api/runtime-readiness` | `ready: True, build_id: api-be195048893005bd` —— **与本地树一致** |
| 6 | 谱系行在库核对（只读） | sqlite SELECT `writing_reference_translation_chunks` | `chunk_df9edbb9fc35d2fe3e156ace:blocked` 在库，K3项目谱系行 **0→1**，仅新增、未改任何旧行 |
| 7 | 重建幂等复验 | `rebuild_blocked_chunk_lineage.py rebuild --project proj_user_fad9f64f3151 --integration-id integration_b542359e30925effe7753312` | **`data_missing: blocked_chunk_not_replayable_from_plan`**（见第四节说明；不落任何行，fail-closed符合设计） |
| 8 | **样本重判** | `rebuild_blocked_chunk_lineage.py reeval-evidence`（同上限定范围） | **confirmed 1 / overturned 0 / unverifyable 0**，重放码=存储码 |
| 9 | 审计核对 | sqlite SELECT `writing_reference_audit_chain` | 本轮证据事件已落：`blocked_fidelity_reeval_evidence` @13:42:39Z（21:42本地） |
| 10 | 未晋级核对 | `medical-queue`（只读） | 样本仍在待医学处置队列（attempt 14，两码原样），无晋级 |
| 11 | FAST定向自查 | pytest：谱系+切分+复检绑定+G5范围+流水线+对齐+主批处理 | **299 passed + 20 subtests，0失败**（含21:22切分修复后的最终代码树） |

本轮证据文件（同目录）：`sample_rebuild_rerun_wave0.json`、`sample_reeval_wave0.json`、`medical_queue_k3_wave0.json`、`backend_5301_round23_restart.log`、`full_suite_gate_wave0.json`（全量门结果，见第六节）。

## 三、重判细节（confirmed 的依据）

- 谱系行（`translation_strategy=rebuilt_offline_blocked_lineage`）自带身份校验：其输入哈希与自身持久化源文 sha256 一致（工具内置校验，不一致即 `unverifyable`）。
- 证据链逐环核验（本轮亲跑，零模型）：①集成行 `blocked_raw_provider_output`（146字符，sha256与记录一致；为无标记碎片，直接重放共享解析函数得空——如实记录）；②其 `blocked_aligned_output`（181字符，sha256一致）即管线当时对齐出的带标记版本，与谱系行 `translated_text` 逐字相同；③用共享函数 `_blocked_lineage_unit_targets` 对 aligned 输出重放 → 单元1目标文本与谱系行 `unit_targets` **逐字节一致**；④对单元1目标重跑确定性忠度检查器 → 恰好复现初判两码。
- 该单元的重建目标文本即当时被阻断的146字符碎片（与初判记录的碎片长度一致），证据自洽。
- 全库口径下 K3 项目谱系行从0变1：缺口由离线重建补上，写侧能力（新翻译落库同步持久化对齐单元）已在5301当前运行面生效（指纹核对通过），后续新阻断不再产生同类缺口。

## 四、如实说明：重建通道对"旧样本"的幂等复验现为 fail-closed

- 前序会话 20:43 完成重建时（切分器修复之前），重放匹配 → 报 `already_present`（见 `../t17_round23_blocked_lineage_0927/sample_rebuild_rerun.json`）。
- 本轮 21:22 之后的代码树含长段切分修复（4865字符整段 → 2块），计划重放不再复现旧样本当初的单一整块 → 本轮重跑报 `data_missing: blocked_chunk_not_replayable_from_plan`，**不猜测、不落行**。
- 这不是错误：谱系行本身完好且经哈希校验，重判通道（reeval-evidence）按设计改为从谱系行自身持久化源文取单元，对重切分鲁棒，本轮 confirmed 即由此通道产出。
- 对放量的含义：新翻译走写侧落库（不依赖离线重建）；仅历史阻断项需要离线重建，且凡重放不匹配一律 fail-closed 上报，不会产出错误谱系。
- 批级复检通道（HTTP `fidelity-reeval`）实测：本轮经重启后的5301调用，返回 `{"admitted":0,"rejected":0,"data_missing":1}`——这是**设计内护栏**：`_evaluate_integration_for_reeval` 对任何带 `blocked_raw_provider_output` 的集成无条件报 data_missing（`writing_reference_translation_batch.py:9291-9295`，注释明言：拿诊断碎片冒充全章复检会伪造全章遗漏、掩盖单元级根因）。即阻断项**永远不经该通道自动晋级**，其重判证据一律由离线工具的 `reeval-evidence` 通道产出（本文件第二节的 confirmed 即此通道），处置归医学人工门。条目重查仍在阻断队列（count=1），未晋级。

## 五、医学门待处置队列（wave=0 范围）

- K3 项目（本轮样本所属）：1 项待医学裁定 = 样本项本身（NCT02176291，attempt 14，两码：数值记号变更 + 原文缩写缺失RCT）。
- 全库口径（前序 20:44 只读快照，`../t17_round23_blocked_lineage_0927/medical_queue_live_all.json`）：共 390 项 fidelity_blocked，分布：proj_user_d872d3d33fda=246、proj_user_4ea6ade6a8b1=76、proj_user_96ad0da010bc=28、其余6个项目合计40。
- 另：本轮真实模型诊断性重放（`truncation_fix.md` 第四节）对新译文另产出10条单元级发现（含比较方向、顺序、概念新增等实质项），一并待医学人工判定；裁定前不发生任何晋级。

## 六、全量门（收尾跑一次）

本轮收尾重新执行了一次全量验收门（`tools/acceptance/run_acceptance_gate.py run`，21:46–22:09，1378秒，覆盖21:22切分修复后的最终代码树），结果见本目录 `full_suite_gate_wave0.json`：

- 运行 11268 项，0 收集错误，跳过 35，verdict=FAIL，失败 32 项。
- **与前序 20:44–21:07 那次全量门逐项比对：32 个失败 ID 完全同一集合**（脚本比对 `failed_ids` 集合相等，无一如旧、无一新增）——即最终代码树相对前序运行**零新增失败**。
- 32 项构成：27 项疑似指纹漂移（工作树带未提交改动，源码指纹类契约测试与基线提交的指纹不一致所致，门自身标注为"疑似"类）+ 3 项安全哨兵拦截 + 2 项前端检查包装器测试；known_matched=202、dissolved=198。
- 判读：该门的 FAIL 是相对"已知失败基线"（`known_failures_0926v1.json`，取自旧基线提交，门已标注 `matches_head: false`）的既有稳定状态，不是本轮改动引入；是否把这32项纳入新基线/修复，属集成人后续决策，本轮不越权处理。

## 七、未尽事项

- 处置权在用户：confirmed/overturned 仅是证据，任何晋级/放行须医学人工门执行。
- 25研究放量（wave≥1）待 wave=0 结论核对后按红线分波派发，本轮未启动。
- 全量门结果与基线判读见第六节补记。
