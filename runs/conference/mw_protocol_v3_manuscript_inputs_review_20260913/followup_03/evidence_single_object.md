This is follow-up 03: I’ll freeze the 26 hashes first, then reassess the shared diagnostic contract, source-prep failure/retry identity, and the new chapter-prepare HTTP binding.Hashes match. I’ll read `diagnose_applicable_input`, the source-prep tests, and the new chapter HTTP/product binding next.# Conference Output: mw_protocol_v3_manuscript_inputs_review_20260913 - evidence_single_object

## Output

**Identity:** 本节点仍是 `grok-build` / `grok-4.6` 有界续核。只读；未委派、未调真模型/OCR/翻译、未改源、未启常驻服务、未查凭证、未清理。Scratch 仅 `runs/conference/mw_protocol_v3_manuscript_inputs_review_20260913/followup_03/scratch/`。Runner 落盘。不主张临床/产品/Word 验收。

**清单与限度：** followup_03 **26/26 SHA256 匹配**。允许 pytest **17 passed / 3.02s**。未复跑 owner 所称 346。默认挂载 `protocol_workflow_config_from_env().enabled is False`。未做双进程并发对打。

---

### A. `diagnose_applicable_input`（上次剩余项复评）

**已核实的事实**

- 计划在 `bind_applicable_chapter` 抛 `ApplicabilityResolutionError` **或** `FactBindingError` 时，都走 `diagnose_applicable_input`（`manuscript_plan.py` 49–59）。严格路径仍是 `_resolved_input_contract(..., collect_findings=False)` + `bind_chapter_input` 的 `errors[0]`。
- `diagnose_applicable_input` 与绑定共用 `_resolved_input_contract(..., collect_findings=True)`，再对 **投影后的 effective 合同** 跑 `diagnose_chapter_facts`（`applicability.py` 312–365）。未决规则不激活义务；`APPLICABLE` 兄弟的 `required_when_active` 会写进 effective required。
- 有限 JSON boolean 夹具（非 NaN），三种投影（scratch + `test_unresolved_design_keeps_unconditional_missing_and_all_present_errors`）：

| 条件 | 计划可见 | interim_analysis missing | stratification missing | arms missing |
|---|---|---|---|---|
| 未决 | unresolved + type + alias + missing | 否 | 否 | 是 |
| 内层全 false | type + alias + missing（无 unresolved） | 否 | 否 | 是 |
| interim=true，features 未决 | 2 条 unresolved + type + alias + missing | **是** | 否 | 是 |

- 同一研究上严格 `bind_applicable_chapter` 仍第一枪（未决时 ApplicabilityResolutionError；内层 false 时 `fact_type_mismatch`）。计划不再跟着第一枪变瞎。上次 followup_02 的两条核心失败（兄弟义务被 defer、条件决断后 alias/missing 消失）**在计划层已不成立**。

**仍存在的缺口（非计数）**

- `_resolved_input_contract` 在 `collect_findings=True` 时仍会对「active 条件事实却 forbidden」直接 `raise ValueError`（`applicability.py` 334–335），计划只捕 Applicability/FactBinding，整单会失败。罕见，但是诊断与绑定未对齐。
- 投影 inactive 仍只读 `canonical_path in study.facts`，legacy-only 键可能漏 `inactive_conditional_fact_present`（旧残留）。
- 严格 binder 默认未改——符合 owner；开写路径仍一次一个错。

**建议：** 计划层 A 可收口。若要诊断永不炸整单，把 forbidden+active 收进 findings，不要裸 ValueError。不要为了「一次看清单」去改严格 `errors[0]`。

---

### 来源准备：已知失败 / 未知结局 / `:retry:1`

**已核实的事实**

- `execution_contract_factories={'prepare-sources': lambda base: base}`，I/O 走配置执行器；`allowed_attempts=1`（`source_preparation.py` 31, 146–149）。
- 仅 `except OSError` 写成 completed 节点输出 `source_preparation_failure.code=chapter_source_read_failed`。`RuntimeError` 探针：`blocked` + `dispatch_exception`，`can_retry=False`，再 `resume` 不二次调用（`test_source_read_failure_reports_durable_blocked_state_without_silent_reprocessing`，calls==1）。
- 显式子 run：`{parent}:retry:1`，root 为原 payload + `retry_decision_id`。父输出仍保留 `chapter_source_read_failed`；子 1 次 attempt。成功后同 id 再 retry 幂等、库不变。完成恢复读事件包与原 `extracted_at`，不读源、不写 study/semantic。
- 挂载 API：`POST .../manuscript-sources` 202 + 后台 resume；失败 GET `failed/can_retry`；retry 后 GET `retry_run_id=run:retry:1` 且 completed；研究资料变更后 POST 409，GET 原包不变；假 HTTP opener 仅 seed 1 次。默认 composition 关。

**具体缺陷**

1. **成功后的 retry 身份不校验。** 子 run 已 completed 时，`retry()` 第一句 `if status=='completed': return read()`（`source_preparation.py` 117）。scratch 用 **另一个** `retry_decision_id` 仍返回同一 bundle，未抛 `chapter_source_retry_identity_mismatch`。HTTP 同样：`status==completed` 直接回状态（`manuscript_sources.py` 97）。身份只在子 run **未成功完成** 时强制。不改写历史，但会把「用了错误 retry id」藏成成功读取。
2. **`LookupError('chapter_source_not_found')` 走未知 blocked，不能显式 retry。** 与 OSError 的 durable known failure 不对称。源稍后出现也无法 `:retry:1`。这是可用性/正确重试，不是要新安全套件。
3. **HTTP retry 响应体是调度前快照。** 202 可能仍是 `failed`；TestClient 会跑完后台任务，随后 GET 才是真相。争用 `graph_reservation_contended_retryable` 被吞；**不同** `retry_decision_id` 抢同一 `:retry:1` 会 `graph_root_inputs_conflict`，后台 `raise`（`manuscript_sources.py` 100–104）。fail-closed，但调用方可能只看到 202。

**建议：** completed 后若带了不同 `retry_decision_id`，应 mismatch，不要静默当读。`LookupError`/`chapter_source_projection_changed` 是否升为 known failure + 可 retry，请 Codex 拍板（建议：与 OSError 一样可 retry 一次，未知异常仍不可）。

---

### 章节产品 HTTP：当前研究 vs 历史请求

**已核实的事实**

- `prepare_manuscript_chapter`：读当前 SQLite 研究；`revision_sha256` 必须等于请求；`source_preparation.project_id` 必须匹配；`research.input_context.source_intake_sha256` 必须等于 **source-prep 根上的** `prepared_seed.input_sha256`；再 `read()` 完成包 + **当前** `load_current_template` → `prepare_study_chapter`（`service.py` 753–777）。prepare 只算 `expected_workflow_run_id`/`input_sha256`，库 dump 不变，opener.calls==0。
- start：先 `prepared_request(expected_workflow_run_id)`；没有才 fresh，且 `run_id(request)==expected`。recover 只走 original，缺记录 404。当前 `source_material` 必须等于保存的章节请求（`chapter_drafts.py` 47–58, 69–98）。
- 研究事后改 interim：recover/start 用**原** `study_revision_sha256` 仍返回原 `needs_content_review`；不带 expected 的 prepare 409；dump 与 opener.calls 不变。
- `ChapterDraftCoordinator.run_id` 钉 `project/branch/study_id/study_sha256/prepared.input_sha256`；`require_bound_input=True`（`coordinator.py` 27–41；`product.py` 39）。lazy factory 在 default composition 中接入，**flag 默认关**；测试显式 `enabled=True` + FakeOpener + 既有 probe 收据，无新 probe、无真模型。
- 不是全文调度、医学准入、编辑器或 Word。未声称、不要求生产开通。

**具体缺陷 / 残留**

- `fresh()` 对尚未 `facts_ready` 的章会让 `bind_applicable_chapter` 冒泡；`checked()` 只翻译少数 ValueError → 易变成通用 422，不像计划那样给出诊断全集。
- `original()` 里对未知 `source_run_id` 的 `GraphRunError` 被说成「没有找到原写作记录」（`chapter_drafts.py` 28–30），来源缺失与章节缺失语言混用。测试允许 404/409。
- 章节绑定核对的是 `source_intake_sha256`；来源准备 POST 核对的是整份 `regimen_input_context`。多字段 context 变更时，两层 409 口径不一致（来源 API 更严）。

**建议：** 不把 prepare/start 当开写许可，除非计划该章已 `facts_ready`。recover 继续只读历史请求。不要把 lazy 挂载理解成默认生产已开。

---

### 给 Codex 的决策点

1. 成功完成后，错误的 `retry_decision_id` 是 mismatch 还是幂等读？建议 mismatch。  
2. `LookupError` 类已知本地失败是否允许一次 `:retry:1`？建议允许，与 OSError 对齐。  
3. 章节 `/prepare` 对非 facts_ready 章是 409+诊断，还是维持绑定异常？建议 409 并指向 manuscript-plan。

**安全暂行路径：** 计划 errors 在三种条件投影下已可一次看 type/alias/无条件 missing 与已激活兄弟义务。来源包只在 `state.status==completed` 且无 `source_preparation_failure` 时当可恢复。章节 recover 只信 `expected_workflow_run_id` + 原 revision 钉死的请求，不信后来的 study。

**未做：** 未改源；未写 runner 报告文件；未跑 346；未做真模型/OCR/浏览器/Word；未双进程抢 `:retry:1`。
