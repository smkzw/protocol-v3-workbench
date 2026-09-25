# K3 批次点火诊断 — 快照权限门三层孤儿数据排查（2026-09-25）

批次：`wref_translation_batch_79e7f4e51e7270b75688e8e9`（830 项 = 574 failed_retryable / 256 excluded，S01-S07 数据源）
项目：`proj_user_fad9f64f3151`
runtime：isolated_runtime（build `api-abc188a01c8bafa0`，readiness / runtime-build.json / 5186 代理三处一致）
结论：**点火真实发生但被产品级快照权限门拦截；门根因已定位（读侧强校验要求 from_zero bootstrap 从未保证写入的 `journey.search_plan`），修复列入下批代码修复，本轮不做数据回填（红线3维持）。**

## 1. 三层孤儿数据排查经过

### 第一层：项目未注册（404）— 已由主会话恢复
- 实测：`POST /api/projects/proj_user_fad9f64f3151/.../translation-batches/wref_translation_batch_79e7f4e51e7270b75688e8e9/retry`（KEY=`k3ignite-1790350834-16201`）→ HTTP 404 `{"detail":"project not found: proj_user_fad9f64f3151"}`
- 抛出点：`services/api/app/main.py:2759-2764`（`_canonical_project_id` → `project_source_manifest_service.canonical_project_id` KeyError）
- `GET /api/projects` 14 项中无该项目；`isolated_runtime/user_projects.sqlite3` 的 `user_projects` 表为空
- 恢复（主会话执行）：从权威备份 `isolated_runtime/user_projects.sqlite3.pre-cleanup-20260924_040239` 按原值 INSERT 注册行 `proj_user_fad9f64f3151`（project_code=MW-II-3FE41099，idempotency_key=`create-project-1790184089104-8f14c9ebc153d`，created_at=2026-09-23T17:21:29.109231+00:00），纯新增恢复；恢复后 `GET /api/projects` 计 15 项含该项目

### 第二层：authoring journey 行缺失（KeyError）— 已按同模式恢复
- 第一次点火（KEY=`k3ignite-1790351196-29766`）→ HTTP 202，批次 attempt 1→2，durable job `mwjob_ca5908ffab7676e621af4138`（`durable_mw_jobs` reference_translation 37→38 行）
- 574 项全部在处理入口即失败，逐项栈（mw_backend_5301.log:81192 起，约 5.4 万行）：
  ```
  writing_reference_translation_batch.py:4116 → journey_service.get(project_id)
  medical_writing_authoring_journey.py:1117 get → :5418 _current_row
  KeyError: 'medical-writing authoring journey not found: proj_user_fad9f64f3151'
  ```
- 恢复（本调度员按主会话授权的同模式执行）：从同一事件备份 `isolated_runtime/medical_writing_authoring_journey.sqlite3.pre-cleanup-20260924_040239` 按原值 INSERT（ATTACH bak → BEGIN IMMEDIATE → INSERT...SELECT → COMMIT，changes()=1）：
  - 行主键：`mwjourney_f234ada236f028ce9849`，revision=6
  - created_at=2026-09-23T17:21:29.118334+00:00（与项目注册同刻，bootstrap 创建）
  - updated_at=2026-09-23T19:03:45.390969+00:00
  - create_idempotency_key=`project-bootstrap-create-project-1790184089104-8f14c9ebc153d`（与第一层恢复的注册行同源同事件）
  - payload_json 长度 97465 字节
  - 纯新增、原值、不改任何既有行（红线3合规）

### 第三层：journey payload 缺 `search_plan` → 快照权限门拦截（当前根因，未修）
- 第二次点火（KEY=`k3ignite-1790351710-4308`）→ HTTP 202，批次 attempt 2→3，durable job `mwjob_a290cfb203bdd9e81652a54b`（reference_translation 38→39 行）
- 574 项全部在快照权限门即失败（mw_backend_5301.log 全量累计该 ValueError **3444 次** = 两 job 各 3 次全量执行 × 574 项，精确吻合）：
  ```
  ValueError: batch translation requires either finalized corpus triage or a confirmed discovery basket projection for the locked snapshot
  ```
- 门代码：`services/api/app/writing_reference_translation_batch.py:4109-4148`（`_snapshot_scope`），双权威路径实测：

| 路径 | 要求 | 实测（恢复行 payload 实际值） | 结果 |
|---|---|---|---|
| A（post-PICOS） | `journey.corpus_triage.status=="finalized"` 且 snapshot 匹配 | `corpus_triage={status:"pending", snapshot_id:""}` | ❌ |
| B（pre-PICOS） | `journey.discovery_basket_projection.confirmation_id` 非空 且 其 snapshot_id==批次 snapshot 且 `journey.search_plan.latest_snapshot_id==批次 snapshot` | `confirmation_id="ct_conf_ebb394de59fb68021378"` ✓、`snapshot_id="wref_search_4d2c5d3b8476515fc38b"` ✓ 与批次一致，**但 payload 无 `search_plan` 键 → journey.search_plan is None** | ❌ |

- journey 行 payload 关键摘录（/tmp/k3journey.json 实测导出）：顶层键含 `corpus_gate, corpus_triage, created_at, current_stage, discovery_basket_projection, document_creation_reservation, entry_mode, framing, framing_complete, framing_draft, invalidated_dependents, journey_id, picos, picos_complete, picos_corpus_alignment, picos_draft, prefill_package, project_id, research_pipeline, revision` —— **无 `search_plan`**
- `journey.get()` 直接反序列化 payload（`medical_writing_authoring_journey.py:1117-1120`），无跨表组装

## 2. 关键佐证

- **权威快照行存在**：`writing_reference_search_snapshots` 有 K3 项目行 `wref_search_4d2c5d3b8476515fc38b`（created 2026-09-23T17:21:39，与项目 bootstrap 同刻）；K3 批次 locked snapshot 即该 id；prep 批次 `wref_prep_cc8a67c458de4225cd09ce38` 在
- **该缺失非清理丢失**：备份行（09-24 04:02，rev=6，updated 09-23 19:03）从未含 `search_plan`；K3 批次 09-23 18:55 创建当时 574 项即 failed_retryable——说明门在创建时点即以同样方式失败。**与 26 项已定位根因同族：写侧（from_zero bootstrap 流程）不保证写入，读侧（`_snapshot_scope`）强校验**
- **durable 派发真实发生审计**：`durable_mw_jobs`（isolated_runtime/medical_writing_durable_jobs.sqlite3）：
  - `mwjob_ca5908ffab7676e621af4138` status=failed attempt_count=3/3 error="batch has failed_retryable items" started 15:46:40Z finished 15:47:57Z
  - `mwjob_a290cfb203bdd9e81652a54b` status=failed attempt_count=3/3 error="batch has failed_retryable items"
  - job_type=reference_translation 行数 37→39；两 job 均经 worker 真实执行（各次执行逐项进入，见 [MW-ENTRY-DIAG] enter 行，项 attempt 4→7）
- **项级终态**：574 项全部 `7@failed_retryable`，error_code=translation_generation_failed；批次 status=failed attempt=3
- **attempt 边界**：未扩任何 max_attempts（job 3/3、项 attempt 涨至 7 为 job 循环自然结果）；按裁定本轮不再点火，重新派发待门修复落地后按"关联原 job 的新恢复尝试"语义执行

## 3. 修复建议（列入下批，代码级）

`from_zero` bootstrap 流程（`MedicalWritingAuthoringJourneyService` 创建路径）需在创建时写入 `search_plan`（至少 `latest_snapshot_id` 对齐 bootstrap snapshot），或 `_snapshot_scope` Path B 在 `search_plan is None` 时降级采用 `writing_reference_search_snapshots` 的权威行（数据已存在且与批次一致）。走 planner→评审→实现→测试门→重放标准路径。
