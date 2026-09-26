# G1 A109 受影响候选盘点（只盘点，不晋级）

- **采样时间（UTC）**：2026-09-26T07:06:39Z（快照口径，ACCEPTANCE_MATRIX.md:118；批次仍在自行消化，不预测最终数字）
- **库**：`runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime/writing_reference.sqlite3`（`sqlite3 -readonly`，只读）
- **检查器身份**：本次 G1 收紧后的 `fidelity-numeric-strict-2026-0926v1`（`CHECKER_HASH=55a1ace9e2d3936b`，见 `services/api/app/writing_reference.py`）。库内现有记录 **0 条**携带该身份——G1 未对任何存量候选执行重评，未翻转任何状态（红线3：复检只报覆盖率，晋级是 G3 之后的事）。

## 目标批 `wref_translation_batch_da229e6a87e48135b2f59aa5`（230 项）

| generation_status | payload 含 numeric_tokens_changed | 小计 | 说明 |
|---|---:|---:|---|
| candidate_ready | 0 | 60 | **旧检查器静默放行集**＝A109 追加评估候选对象（新 checker 重评时其中数值等价性将首次被精确核验） |
| fidelity_blocked | 59 | 165 | 59 项含 numeric 拦截证据（旧规则产出，含误报可能，属 G3 解绑范围）；其余 106 项为其他码拦截 |
| failed_retryable | 0 | 3 | |
| excluded | 0 | 2 | |
| **合计** | | **230** | |

## K3 批 `wref_translation_batch_79e7f4e51e7270b75688e8e9`（830 项）

| generation_status | 数量 |
|---|---:|
| excluded | 256 |
| failed_retryable | 574 |
| admitted/candidate_ready | **0** |

574 项重放保持暂停（红线3），盘点未触发任何处理。

## 追加评估计划（只写计划，不执行）

1. **触发条件**：G3 复检来源绑定修复落地后，经既有复检通道（`reevaluate_fidelity_blocked` 语义族）对 60 项 candidate_ready 按新 checker（`fidelity-numeric-strict-2026-0926v1`）重评。
2. **顺序**：先报可复检覆盖率（eligible/evaluated/admitted/rejected/data_missing 分列、分母一致），**不翻转状态、不做批量豁免、不改写任何既有评价**（RECOVERY_AND_FIDELITY_SPEC §4：一份候选可有多份按版本追加的评估，旧评估保留）。
3. **165 项 blocked** 维持原状；59 项 numeric 拦截证据的旧误报如需解除，走 G3 证据通道逐项核对，不批量解除。
4. 每份新评估记录 `checker_version/checker_hash`（A109 已在 `writing_reference_translation_batch.py` 的 integration 结果与 revision 构造点写入），与 `legacy-null`（空版本）旧记录可区分。

## G1 修复自证（同一时间窗内）

- 反例先红：`tests/test_writing_reference_numeric_fidelity.py` 修复前 7 failed/5 passed；A107 扩展后 8 failed/10 passed（`g1_step2_a107_prefix_red.txt`）。
- 修复后：数字集 18/18 绿；A108/A109 文件 128→含新增用例全绿（`g1_step4_a108_a109_postfix.txt`）；控制组（116 million→1.16亿、635 billion→6350亿、2.50亿拦截）绿；5 文件绿基线 **327 passed + 30 subtests** 原样保持（`g1_step3_green_baseline_5files_postfix.txt`）。
