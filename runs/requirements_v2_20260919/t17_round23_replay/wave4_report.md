# 第4波有界放量报告（wave=4，2026-09-27）——与波2/3同构：重试通道空转

## 一、结论

按指令派发范围限定重试（nct_ids=波4七研究），**空转（no-op），零副作用**：7研究均为新研究，项目内条目数=0（直接SQL查证），重试通道按设计只重挑既有 failed_retryable 条目。批状态/attempt/counts派发前后逐字一致（partial_failure / 4 / candidate_ready=14、fidelity_blocked=38、failed=522），无durable任务创建、零模型调用。按"无进展即停"停住。

## 二、执行与核实（本轮亲跑）

- 幂等键=`wave4-bounded-volume-20260927T145813Z`；响应 `durable_job_id=''`；durable任务表无wave4键记录（COUNT=0）。
- 文档状态：7研究各有1份已摄取文档（NCT03079297/NCT03559192/NCT03181529/NCT02553915/NCT02192099/NCT04244253/NCT02458690）。

## 三、25研究放量全景（三波同构后的总结）

- **存量重试波（波1）已收官**：52项 → +14 ready / +37 blocked（入医学队列）/ 剩1 failed_retryable（item b5414a819…，NCT03283670）。
- **新研究波（波2/3/4，共22研究）结构性不适用重试通道**：22研究均有文档（各1份）但零翻译条目；唯一正确通道=新建翻译批次（`POST .../translation-batches`，绑定G6快照 wref_search_4d2c5d3b8476515fc38b + anchor_filter先核范围 + 幂等键），创建后走durable翻译。是否放行属编排器/用户决策。
- 医学门队列：38项待用户人工处置（medical_queue_k3_after_wave1_corrected.json），处置前无任何晋级。

## 证据文件

`wave4_dispatch_key.txt`、`wave4_dispatch_response.json`
