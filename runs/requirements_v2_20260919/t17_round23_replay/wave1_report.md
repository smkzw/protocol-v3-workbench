# 第1波有界放量报告（wave=1，2026-09-27）

## 一、结论

波1（3研究，52个可重试条目）已派发并收敛：**14项转candidate_ready，37项被忠度门拦入医学队列，1项仍未过（failed_retryable），durable任务终态failed（内部3次尝试用尽）**。全程零越界（范围核实52项全属波1研究）、零清库零改历史、忠度自动晋级未发生（blocked项只进队列）。

## 二、派发与范围核实（本轮亲跑）

- 命令：`POST /api/projects/proj_user_fad9f64f3151/medical-writing/references/translation-batches/wref_translation_batch_79e7f4e51e7270b75688e8e9/retry`，body=`{actor: offline_lineage_tool, idempotency_key: wave1-bounded-volume-20260927T141445Z, nct_ids: [NCT02176291, NCT03283670, NCT03113968]}`。响应 202，`status=running`，`durable_job_id=mwjob_63c5033bb91a953223d06d85`。请求模型无reason字段，"有界放量第1波"记录于幂等键与本文件。
- durable范围核实（`durable_mw_jobs.payload_json`）：`failed_item_ids`共**52项**，与波1派发时刻三研究的failed_retryable全集逐一相符（NCT03113968=45 + NCT03283670=7；样本NCT02176291当时已是fidelity_blocked、正确地**未**被选入），**零越界、零遗漏**（脚本核对：dispatched⊆wave且wave failed_retryable全覆盖）。
- 编排器：任务期间MTPLX被自动拉起（gateway provider=mtplx），后端日志零Traceback/零429。

## 三、观察过程（分段轮询，见 wave1_observer.log）

- 14:14Z派发；前6分钟NCT03283670先出结果（1项candidate_ready）；中段NCT03113968逐项消化；14:49Z左右收敛：durable job终态**failed**（err="batch has failed_retryable items"，worker内部attempt 1→retry_wait→failed，max_attempts=3用尽），瞬态条目清零。批状态=`partial_failure`（非running）。
- 注：首轮观察器曾以"连续2轮无变化"提前停止，检查后端日志确认worker活跃（每项模型调用耗数分钟）后按40分钟预算放宽为3轮继续，直至真收敛。

## 四、增量（基线 → 终局，按研究）

| 研究 | 基线 | 终局 | 增量 |
|---|---|---|---|
| NCT03113968 | 45 failed_retryable (+16 excluded) | 13 candidate_ready + 32 fidelity_blocked | **ready +13，blocked +32** |
| NCT03283670 | 7 failed_retryable (+32 excluded) | 1 candidate_ready + 5 fidelity_blocked + 1 failed_retryable | **ready +1，blocked +5，failed 剩1**（item b5414a819…，attempt 14→16） |
| NCT02176291 | 1 fidelity_blocked | 1 fidelity_blocked（未动，待医学门） | 无 |
| **合计** | 52 可重试 | | **ready +14，blocked +37，failed 剩1**（14+37+1=52 ✓） |

## 五、医学门队列增量（目标④）

- K3项目fidelity_blocked队列：1 → **38**（NCT03113968=32、NCT03283670=5、NCT02176291=1）。逐项清单（含忠度码）见 `medical_queue_k3_after_wave1_corrected.json`。
- 常见忠度码：comparison_direction_changed、numeric_tokens_changed、source_abbreviation_missing、unit_sequence_changed、numbered_criterion_cardinality_changed、regulatory_chinese_term_calque等——均为确定性检查器原样输出，**是否可接受由用户医学人工门裁定，系统不自动晋级**。
- ⚠️ 工具caveat（如实上报）：`rebuild_blocked_chunk_lineage.py medical-queue` 用 `immutable=1` 快照读，在活跃WAL库上会漏看未合并的新写入（实测36 vs 真值38，漏wref_translation_item_dc9d87440e81aee19036cf19与ebe2139cc13b752b219a0df7）。本报告以普通连接修正版清单为准；工具本身的修正建议交集成人后续处理。

## 六、写侧谱系能力实战验证（目标①，超出预期的正面结果）

- 波1期间写侧谱系落库在真实流量上生效：新增9条`:blocked`诊断谱系行（strategy=hy_mt2_blocked_diagnostic）+多条正常完成谱系行（hy_mt2_aligned_units / hy_mt2_bounded_unit_batches），K3项目谱系行1→16+。今后每个忠度阻断都会自带单元级证据，不再需要离线重建。

## 七、边界与未尽事项

- 1项NCT03283670条目（wref_translation_item_b5414a8194730c3771643d89）三次尝试后仍failed_retryable：按"无进展即停"未追加派发；是否单独重试交下一波决策。
- 被拦的37项加上样本1项共38项在医学队列中等待人工处置；处置前不发生任何晋级。
- 波2（8新研究）未启动：按红线待本波结果核对后再放。

## 证据文件（同目录）

`wave1_dispatch_key.txt`、`wave1_dispatch_response.txt`、`wave1_observer.py`、`wave1_observer.log`、`medical_queue_k3_after_wave1.json`（immutable快照，caveat见上）、`medical_queue_k3_after_wave1_corrected.json`（修正版，38项）
