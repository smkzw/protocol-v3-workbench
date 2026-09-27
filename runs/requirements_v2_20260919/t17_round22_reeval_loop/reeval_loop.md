# 忠度复检闭环证明（零模型，R22，2026-09-27）

样本项：`wref_translation_item_c561fdf957b2132967c662b1`（批次 `wref_translation_batch_79e7f4e51e7270b75688e8e9`，项目 `proj_user_fad9f64f3151`）。
全程零模型调用；未清库、未删历史、未动不可变行；未翻转任何项状态；574 项重放维持暂停。

---

## 一、5301 重启与指纹核对

- 重启前：PID 6369，`/api/runtime-readiness` 报 `backend_build_id = api-fd293ef99d7acf3d`（**旧代码**）。
- 本地按当前工作树（HEAD d3682a9 + 未提交各轮改动）计算指纹：`api-a91f7ece9407c5cc`（`runtime_readiness.backend_build_id()`，对后端源码树的 sha256）。
- 按 `HANDOFF_0924V2_BATCH1.md §一` 配方（经 `HANDOFF_0926_CONVERGENCE.md` 指引）重启：杀 5301 旧监听 → `python3.14 -m uvicorn app.main:app --host 127.0.0.1 --port 5301`，env 五件套照抄原进程（`WORKBENCH_RUNTIME_DIR` / `WORKBENCH_AI_SETTINGS_PATH` / `WORKBENCH_AI_ROLE_SETTINGS_PATH` 均指向 `runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime`，`WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED=1`，`WORKBENCH_PROTOCOL_V3_WORKFLOW_DB=<…>/protocol_v3_product.sqlite`；前端 5186 未触碰）。
- 重启后：新 PID 28484，`ready: True`，`build_id: api-a91f7ece9407c5cc` —— **与本地当前树指纹一致**（加载了当前代码，含 409 修复轮与冻结时钟轮的未提交改动）。启动日志与请求日志见同目录 `backend_5301_restart.log`（0 Traceback/ERROR）。

## 二、复检执行（零模型）

```
POST /api/projects/proj_user_fad9f64f3151/medical-writing/references/translation-batches/wref_translation_batch_79e7f4e51e7270b75688e8e9/fidelity-reeval
body: {"actor":"medical_manager"}
→ HTTP 200，响应原样：{"admitted":0,"rejected":0,"data_missing":1}
```

响应留档：同目录 `reeval_response_20260927.json`。

### 计数（本批 1 个 fidelity_blocked 项 = 样本项）

| 口径 | 计数 | 说明 |
|---|---|---|
| admitted | 0 | 无项被放行（未触任何状态翻转） |
| confirmed（重判=初判） | 0 | 未到达重判，见下 |
| overturned（重判≠初判） | 0 | 未到达重判，见下 |
| rejected（检查器给出失败码） | 0 | 未到达重判，见下 |
| data_missing | **1** | 服务返回原样；fail-closed，原因见③② |

## 三、四点核对结论

### ① 复检沿翻译链精确绑定到 revision=1 —— **成立**

审计明细（见④留档）`binding = "translation_chain"`、`integration_id = integration_b542359e30925effe7753312`，与 `writing_reference_translation_records` 中 revision=1 行的 `chapter_integration_result_id` **逐字一致**。G3 绑定修复按设计工作：不再走"计划/章节+前缀"启发式回退，绑定阶段不再 data_missing。

### ② 确定性检查器真实重跑并给出判定 —— **未达成：fail-closed 为 data_missing（与预期不符，如实报告）**

绑定到的集成行是一个 **Hy-blocked 诊断碎片**：
- `blocked_raw_provider_output` 非空；
- `chunk_ids = []`；
- `integrated_text_sha256 = e3b0c442…b855`（空串哈希）；
- 且项目全域 `writing_reference_translation_chunks` 为 **0 行**。

`_evaluate_integration_for_reeval`（`services/api/app/writing_reference_translation_batch.py:9153-9160`）按设计 fail-closed：对 Hy-blocked 章节重跑对齐检查会伪造整章级遗漏（代码注释原意），空 chunk 列表同样直接 data_missing——绝无启发式放行。因此本轮**没有产出 confirmed/overturned 重判**。

定性：这不是 G3 代码缺陷（①已证明绑定精确），而是该样本项**持久化谱系的数据缺口**——初判两码（unit_1:numeric_tokens_changed + unit_1:source_abbreviation_missing）所依据的对齐单元数据不在可复检谱系里，正是 0926 HANDOFF §四.2 记录的"集成行 chunk_ids 为空"缺口族在本样本上的实锤。

可选的真实再生成交叉验证（ask 预授权路径）本轮**未执行**：再生产生的是新译文（新数据），只能交叉验证检查器本身，无法对 revision=1 的同一判定做重判确认；且会在 live 样本上新增 attempt 与新行。是否以一次样本级再生补证，留给用户的人工门决策；另一条补证路径是先重建 revision=1 的 chunk 谱系（若可从 composite pipeline runs 重建）再复检。

### ③ 审计落库 —— **成立**

`writing_reference_audit_chain` sequence_no=8623（项目序），event=`translation_batch_item_fidelity_reeval_data_missing`，actor=medical_manager，at=2026-09-27T10:08:06.783354+00:00，detail 原样：

```json
{
  "actor": "medical_manager",
  "batch_id": "wref_translation_batch_79e7f4e51e7270b75688e8e9",
  "binding": "translation_chain",
  "candidate_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "checker_version": "fidelity-numeric-strict-2026-0926v1",
  "chunk_ids": [],
  "failure_codes": ["unit_1:numeric_tokens_changed", "unit_1:source_abbreviation_missing"],
  "integration_id": "integration_b542359e30925effe7753312",
  "previous_failure_codes": ["unit_1:numeric_tokens_changed", "unit_1:source_abbreviation_missing"]
}
```

### ④ 项状态不翻转 —— **成立**

复检后样本项仍为 `fidelity_blocked`，attempt=14，`fidelity_failure_codes` 两码原样，translation_id/revision=1 不变；批次仍 `partial_failure`（attempt=3）。忠度晋级门保持暂停，样本项的医学处置仍属用户人工门。

## 四、结论

确定性复检闭环的**链路与门语义**已证明：重启加载当前代码 → 沿翻译链精确绑定 revision=1 → fail-closed 判定（不猜测、不放行）→ 审计留痕 → 状态零改动。样本项的**重判确认**（②）因持久化谱系数据缺口（Hy-blocked 碎片行 + 全项目零 chunk 行）本轮不可达，需先补谱系或经用户明示的样本级再生后才可闭环。
