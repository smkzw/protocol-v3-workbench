# [MW-ENTRY-DIAG] 26项 failed_retryable 真实异常抓取报告（2026-09-25）

目标批次：`wref_translation_batch_da229e6a87e48135b2f59aa5`（project_id=`proj_user_a5f104df6d03`）
结论先行：**本次触发被系统在派发之前拒绝（HTTP 422），没有任何派发、没有新 attempt、没有新 stage run。**
真实异常栈已抓到（最内层为 pydantic 校验器）：

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for WritingReferenceTranslationBatchItem
  Value error, document-plan retry generation, parent, and source item must coexist
```

这不是 adapter/provider 路由问题——失败发生在**读侧反序列化**，任何模型调用都不会发生。

---

## 1. 加的诊断（旁路，未改任何失败写入语义）

文件：`services/api/app/writing_reference_translation_batch.py`

1. **claim 之后执行入口** `_process_claimed_item`（定义在 :4683 附近，编辑后）：
   - 入口 `logger.warning("[MW-ENTRY-DIAG] enter item=%s batch=%s attempt=%s stage=%s active_upper=%s", ...)`；
   - 原有 `try:` 保护体（`_validate_frozen_lineage` → `_process_with_composite_pipeline`）外包一层
     `try/except Exception: logger.exception("[MW-ENTRY-DIAG] item=%s 阶段=%s attempt=%s unhandled before failure-write", ...); raise`。
   - 原 `_OwnershipLostError` / `StaleLineageError` / `ModelCallOutcomeUnknownError` / `DocumentPlanValidationError` / `Exception` 各分支与其 `_fail_claim` 写入完全未动；0924V2 §5 既有旁路日志（`logger.error("translation item %s failed with full stack:...")`）也保留。
2. **retry 入口** `retry()`（:1004 附近，编辑后）：方法体抽到 `_retry_with_entry_diag`，外层
   `try/except Exception: logger.exception("[MW-ENTRY-DIAG] retry batch=%s idempotency_key=%s unhandled before dispatch", ...); raise`。
   - **为什么加第二处（超出 ask 步骤1的字面位置，特此说明）**：预检查发现该批次的失败发生在 item 反序列化（`get()`），claim 入口根本到不了；不在 retry 入口包一层就抓不到栈。同样只是 log+re-raise，语义零改动。此偏离已在 notes 里如实申报。

语法自查：`python3 -m py_compile services/api/app/writing_reference_translation_batch.py` → `PY_COMPILE_OK`（未跑全量 pytest，按红线5由统一测试门负责）。

## 2. 重启与 build id 核对（已执行）

- 按 ask 配方杀 5301 并重启（新 PID 17098），vite 5186 同步重启（`VITE_API_PROXY_TARGET=http://127.0.0.1:5301`，因 vite 在启动时一次性计算 expectedBackendBuildId，`frontend/vite.config.mjs:38-55`）。
- `GET /api/runtime-readiness` → `status: ready`, `backend_build_id: api-811a359d3bd5f214`
- `GET :5186/runtime-build.json` → `expectedBackendBuildId: api-811a359d3bd5f214`
- **两者一致** ✅

## 3. curlRecipe（可重复执行，每次真实新派发）

```sh
BASE="http://127.0.0.1:5301"
PROJECT="proj_user_a5f104df6d03"        # 来自 sqlite3: SELECT DISTINCT project_id FROM writing_reference_translation_batch_items WHERE batch_id='wref_translation_batch_da229e6a87e48135b2f59aa5';
BATCH="wref_translation_batch_da229e6a87e48135b2f59aa5"
# idempotency_key 每次用 date +%s + $RANDOM 生成新值（schema 要求 ≥8 字符，
# packages/contracts/workbench_contracts/models.py:9466-9478 WritingReferenceTranslationBatchRetryRequest），
# 保证不命中幂等重放、每次都是新的一次重试请求：
KEY="entrydiag-$(date +%s)-$RANDOM"
curl -s -m 30 -w "\nHTTP_STATUS:%{http_code}\n" \
  -X POST "$BASE/api/projects/$PROJECT/medical-writing/references/translation-batches/$BATCH/retry" \
  -H "Content-Type: application/json" \
  -d "{\"actor\":\"diag_engineer\",\"idempotency_key\":\"$KEY\"}"
```

实际执行：KEY=`entrydiag-1790331937-13149`，响应 **HTTP 422 Unprocessable Content**（端点定义 `services/api/app/main.py:5839-5844`，expected 202）。

## 4. 抓到的完整栈（logs/mw_backend_5301.log 原文）

```
[MW-ENTRY-DIAG] retry batch=wref_translation_batch_da229e6a87e48135b2f59aa5 idempotency_key=entrydiag-1790331937-13149 unhandled before dispatch
Traceback (most recent call last):
  File ".../services/api/app/writing_reference_translation_batch.py", line 1017, in retry
    return self._retry_with_entry_diag(project_id, batch_id, request)
  File ".../services/api/app/writing_reference_translation_batch.py", line 1060, in _retry_with_entry_diag
    current_batch = self.get(project_id, batch_id)
  File ".../services/api/app/writing_reference_translation_batch.py", line 3408, in get
    WritingReferenceTranslationBatchItem.model_validate_json(item["payload_json"])
  File ".../pydantic/main.py", line 782, in model_validate_json
    return cls.__pydantic_validator__.validate_json(...)
pydantic_core._pydantic_core.ValidationError: 1 validation error for WritingReferenceTranslationBatchItem
  Value error, document-plan retry generation, parent, and source item must coexist [type=value_error, input_value={'active_upper_layer_stag...on_status': 'confirmed'}, input_type=dict]
```

校验器出处：`packages/contracts/workbench_contracts/models.py:9927-9935` ——
`document_plan_retry_generation > 0` 时 `document_plan_retry_parent_stage_run_id` 与
`document_plan_retry_source_item_id` 必须同时非空。

## 5. 为什么没有任何派发（如实记录，不硬凑）

触发即同步 422，之后观察 ≥30s：无 durable job、无 audit、无 item 变化。原因链：

1. **门拒绝（主因）——26/26 个 failed_retryable 项全部违反 retry-lineage 共存不变式**。
   实测 SQL（全 26 项）：
   `gen>0 且 parent/source 为空: 26`，`gen=0 但带 parent/source: 0`，`一致: 0`。
   这些 payload 是历史批次 attempt 22（2026-09-25T07:55:40Z）写入的——写路径
   `_prepare_document_plan_contract_lineage`（retry() 内 :1190 附近）用 `model_copy` 更新后落库，
   model_copy 不重新校验，因此非法 payload 入库；此后任何 `get()`（:3408）/`_item_ids`（:4563 附近）
   反序列化即炸。
2. durable 侧同样证据：`medical_writing_durable_jobs.sqlite3 durable_mw_jobs` 中该批次 22 个历史 retry job
   全部 `status=failed, attempt_count=3/3`；其中 21 个早期 job 真实跑过（error_summary=`batch has failed_retryable items`，
   对应 item 层失败），**最新一个 `mwjob_5454217c202ab7b58f0bb3cf`（07:57:02Z）error_summary 与本次 422 同一 ValidationError**
   ——即 lineage 写坏之后，任何重试都在解析期死亡，`writing_reference_upper_layer_stage_runs` 自然 0 新行。
3. **第二道门（即使解析通过也会拒）**：批次行 `status=running, attempt=22`（上轮进程被杀后残留的 running 标记；
   230 项中无 running 项），`retry()` :1062-1065 会抛 `cannot retry a translation batch that is currently running`。
4. 幂等复用/attempt 耗尽均不成立：本次 key 全新且未落幂等表（audit=0）；26 项 item attempt 均为 64，
   代码未见 item 级 max-attempt 门（`grep max_attempt` 该文件无命中）；durable job 级 3/3 属历史 job。

## 6. 关于"裸 product_ai_provider_transient"的历史真相（供根因修复参考）

- 该裸消息只存在于**较早轮次**的 audit（`writing_reference_audit_chain` 中 760 条
  `event_type='translation_batch_item_failed'`，`exc_type=ChapterTranslationPipelineError`，
  `exc_message=product_ai_provider_transient`，attempt=46 时期）。
- 成因（代码层证据）：stage-run 执行失败后，upper-layer 执行器把 provider 错误收敛为 `UpperLayerTransientError`，
  其 `code` 经 `_safe_failure_code` 只留稳定码（`writing_reference_upper_layer_execution.py:83-90,206-216`，
  docstring 明言"Raw provider error text stays in the caller's operational logs"）；pipeline 在
  `chapter_translation_pipeline.py:698` `raise ChapterTranslationPipelineError(failure_code)` —— 只带码、不带原因链，
  audit 随之只记录裸码。adapter 两处 `f"product_ai_provider_transient: {exc}"`（`writing_reference_upper_layer_adapters.py:531,837`）
  修的是更上游一层，且这两处消息本身带原因，与裸码形态对不上。
- **最近的 item 级失败其实已经不是裸码**：最新 audit 显示 57 条
  `exc_type=WritingReferenceConflictError, exc_message="upper-layer idempotency result changed"`（`writing_reference_repository.py:5521`）。
  即 26 项经历了三代失败形态：裸 product_ai_provider_transient → upper-layer 幂等冲突 → 现在的解析期 ValidationError（item 级栈从未有机会产生）。

## 7. No-op 确认（触发后实测）

- 计数 SQL 触发前后不变：`candidate_ready|38, excluded|2, failed_retryable|26, fidelity_blocked|164`
- 26 个失败项 attempt 触发后仍为 64（`MIN=MAX=64`），无新增
- 26 项名下 stage runs：历史 160 行，本次 0 新增
- durable_mw_jobs 中 `business_key LIKE '%entrydiag%'`：0 行

## 8. 遗留（超出本次诊断边界，未动）

- 26 项非法 lineage payload 与批次 `running` 残留的修复属根因修复，按"只加诊断"边界未做；DB 历史未改（红线3）。
- `_process_claimed_item` 的入口诊断本次未能触发（失败在其上游），保留在现场，供下一轮真正派发时抓 item 级栈。
