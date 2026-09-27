# 第3波有界放量报告（wave=3，2026-09-27）——与波2同构：重试通道空转

## 一、结论

按指令派发范围限定重试（nct_ids=波3七研究），**空转（no-op），零副作用**：这7个研究同样是新研究，项目内条目数=0（`writing_reference_translation_batch_items` 直接查询），重试通道按设计只重挑既有 failed_retryable 条目，空集→空转返回。批状态/attempt/counts派发前后逐字一致（partial_failure / 4 / candidate_ready=14、fidelity_blocked=38、failed=522），**无durable任务创建、零模型调用**。按红线"无进展即停"停住。

## 二、执行与核实（本轮亲跑）

- 幂等键=`wave3-bounded-volume-20260927T145730Z`；响应 `durable_job_id=''`；durable任务表无wave3键记录（COUNT=0）。
- 文档状态：7研究各有1份已摄取文档（NCT02473289/NCT03053362/NCT03697603/NCT02674529/NCT00088699/NCT03726658/NCT02660528）——同波2，缺的是"新建翻译批次"步骤而非摄取。
- 结论与波2报告（wave2_report.md）完全同构：新研究放量需走 `POST .../translation-batches`（绑定G6快照 wref_search_4d2c5d3b8476515fc38b + anchor_filter 先核范围）新建批次，属编排器/用户决策。

## 证据文件

`wave3_dispatch_key.txt`、`wave3_dispatch_response.json`
