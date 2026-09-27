# 第2波有界放量报告（wave=2，2026-09-27）——如实：重试通道对本波为空转

## 一、结论（先看这里）

按指令对K3批以范围限定重试（nct_ids=波2八研究）派发，**实际为空转（no-op）**：这8个研究是新研究，在该项目**从未产生任何翻译条目**（0条，任何状态），而范围限定重试通道按设计只重挑既有 `failed_retryable` 条目。派发返回202、批状态/attempt/counts与派发前逐字一致、**未创建任何durable任务、零模型调用、零条目变更**。按红线"无进展即停"，本波就此停住，如实上报；**零损害**。

## 二、执行与核实（本轮亲跑）

- 派发：`POST .../translation-batches/wref_translation_batch_79e7f4e51e7270b75688e8e9/retry`，幂等键=`wave2-bounded-volume-20260927T145527Z`，nct_ids=8研究。响应：`status=partial_failure`（原样）、`attempt=4`（原样）、**`durable_job_id=''`（未创建durable任务）**、counts原样（candidate_ready=14、fidelity_blocked=38、failed=522——与波1终局完全一致）。
- 空转原因（代码+数据双证）：重试条目选择只取 `generation_status='failed_retryable'`（`writing_reference_translation_batch.py:1253-1263`），再按nct_ids过滤；直接查询该批与全项目：8研究条目数=0（`writing_reference_translation_batch_items`，按nct_id提取），K3批830条目仅涉7研究（G6映射 distinct_studies_touched=7）。空集→通道按设计空转返回。
- "durable派发范围仅含该波条目"成立于空集意义（无durable任务存在）；但对本波意图（让8研究产出译文）**通道不适用**。

## 三、波2研究的实际状态与新通道（供下一指令决策）

- 8研究在项目中**各有1份已摄取文档**（`writing_reference_document_artifacts` 按nct各1条：NCT03915613/NCT02461927/NCT02181231/NCT03505905/NCT05193318/NCT02418195/NCT04821271/NCT06309277）——上游摄取已完成。
- 缺的是"新建翻译批次"这一步：正确通道为 `POST .../translation-batches`（`main.py:5763`，请求含 `snapshot_id`（G6提案即 `wref_search_4d2c5d3b8476515fc38b`）+ `glossary_version` + `anchor_filter` + 幂等键），创建后走durable翻译。是否放行新批（新的一次模型花费，且默认面向快照eligible全集而非仅8研究——范围需用anchor_filter/预览先核）属编排器/用户决策，本ask未越权执行。

## 四、波1后现状（未受本波影响）

- 批内：candidate_ready=14、fidelity_blocked=38（医学门队列，修正清单=medical_queue_k3_after_wave1_corrected.json）、failed_retryable=522、批状态=partial_failure。
- 医学队列、谱系行、审计链均无任何变化（本波零写入）。

## 证据文件（同目录）

`wave2_dispatch_key.txt`、`wave2_dispatch_response.json`
