This is follow-up 02 verification of the shared diagnostic binder and the new source-preparation runtime. I’ll freeze the 19 hashes first, then check alias/missing collection and GraphRuntime persistence against the owner decisions.Hashes match. Next I’ll read the shared diagnostic binder and GraphRuntime semantics for first-error vs collected errors, reopen, and concurrency.# Conference Output: mw_protocol_v3_manuscript_inputs_review_20260913 - evidence_single_object

## Output

**Identity:** 本节点仍是 `grok-build` / `grok-4.6` 有界续核，不是 GLM 意见。只读；未委派、未调产品模型/OCR/翻译、未改源、未启动常驻服务、未查凭证、未清理。Scratch 仅 `runs/conference/mw_protocol_v3_manuscript_inputs_review_20260913/followup_02/scratch/`。Runner 落盘。不主张产品/临床/Word 验收。前端仍在范围外。

**核验范围与信心：** followup_02 清单 **19/19 SHA256 匹配**。允许 pytest **66 passed / 2.90s**（`test_manuscript_chapter_plan`、`test_manuscript_plan_api`、`test_chapter_fact_binding`、`test_chapter_source_preparation`、`test_pinned_chapter_sources`）。未复跑 owner 所称 369；以下只挑战实测行为。Graph 并发未做双进程对打，结论来自源码路径 + 失败/重开探针。

---

### A. 共享绑定路径与诊断收集

**事实**

- `_chapter_binding_paths` / `_resolve_fact_values` 被 `bind_chapter_input` 与 `diagnose_chapter_facts` 共用（`fact_bindings.py` 213–338）。严格绑定在 `errors` 非空时 **`raise errors[0]`**（318–319）。诊断收集路径上的 type/member/alias，再汇总 unsupported/missing/empty。
- `diagnose_chapter_facts` 把 `required - deferred_required_paths` 交给同一解析器；未决时计划把**本章全部规则**的 `conditional_fact_paths` 当作 deferred（`manuscript_plan.py` 56–63）。不编译 ready input，不把未决规则当 false。
- 有限 JSON 复现不再依赖 NaN：测试把 `framing.structured_design` 临时改成 **boolean**，写入字符串 `'invalid boolean'`，同时放期别冲突（`test_manuscript_chapter_plan.py` 65–83）。实测设计章同时有 `fact_type_mismatch`、`fact_alias_conflict`、`missing_required_fact`（含 `arms`）、`conditional_applicability_unresolved`；**不含** `stratification`。严格 `bind_chapter_input` 对同一研究只抛出 **`fact_type_mismatch`（`framing.structured_design`）**。
- 未决分支下 `diagnose_alias_count=1`（设计章路径只有 `structured_design.phase`，不会对 `study_phase` 再报一次）。

**解释：inactive 没有被静默提升**

- 对 `v2_n_4_1`，deferred 正好是 interim/stratification/substudy。未决时这些不进 missing。这挡住了「raw required ∩ 条件路径」的假缺失（目录里仍有 13 章存在该交集）。
- Owner 选择是「本章规则的全部 `conditional_fact_paths`」，不是「仅未决规则」。

**解释：单次用户可见性仍不完整（具体失败）**

1. **已适用的兄弟条件义务被一起 defer。**  
   `statistics.interim.applicable=True` 且 `features` 缺失：计划只有 stratification/substudy 的 unresolved + 无条件 `missing_required_fact`（如 arms）。**`framing.structured_design.interim_analysis` 不在 missing 中**，尽管 interim 规则已经 APPLICABLE。用户补分层后才会在下一轮看到期中细节。这与「一次看清单」冲突；它是当前 defer 口径的直接后果，不是测试计数问题。

2. **条件一旦全部决断，计划退回严格第一枪。**  
   同一 boolean 类型错误 + 期别冲突，再把 interim=false、features 分层/子研究=false：设计章 errors **只剩** `fact_type_mismatch`。alias 与无条件 missing 从计划里消失。`diagnose_chapter_facts` 只挂在 `ApplicabilityResolutionError` 分支；`FactBindingError` 分支仍只记 `exc` 这一条（`manuscript_plan.py` 64–67）。用户把未决条件填完后，信息量变差。

**建议**

- 未决时 deferred **仅** = 状态为 `CONDITIONAL` 或 `NOT_APPLICABLE` 的规则的 `conditional_fact_paths`；`APPLICABLE` 规则的 `required_when_active` 应进入诊断 required。
- `bind_applicable_chapter` 失败于 `FactBindingError`、或投影后绑定失败时，仍跑 `diagnose_chapter_facts`（deferred = 已否决规则的条件路径），不要只用 `errors[0]` 填计划。严格 binder 可继续第一枪，供真正开写；**计划记账**应始终用诊断全集。
- 继续不要把未决/否决规则的条件路径当成 missing。

**不确定：** 未把 13 个 overlap 章逐个走一遍「规则已 true + 兄弟未决」。`v2_n_4_1` 已足够证明口径。

---

### B. `source_preparation.py`（GraphRuntime 持久化全文包）

**事实（符合 owner 合同的部分）**

- 身份：`chapter-sources:` + sha256(`project_id`,`branch_id`,`chapter-source-preparation.v1`, `{seed, parser_version}`)。`start` 只 `start_run`/`load_run`，**不**跑节点。探针：`start` 时 source `history`/`read_content` 次数 = **0**；`read(run_id) is None`。
- `resume` 若已有 `graph_node_result` 且 run `completed`，从事件重建 `ChapterSourceMaterial`，不调 source service、不换 clock。允许测试 + 探针：SQLite dump 不变；一年后 clock（2027）的 `input_sha256` 与 `extracted_at` 仍是 **2026-09-13T12:00:00+00:00**。
- 输出是 `prepare_chapter_source_material` 的 payload：`medical_admission=not_assessed`。允许测试确认 `study_definition_repository` / `semantic_document_repository` 对该 project 仍为空。无 `MedicalAdmission` 写入。
- 现用 GraphRuntime：`start_run` 对相同 plan+root 幂等，冲突 fail-closed；节点结果先落事件再 receipt；完成事件丢失时 `_finish_run_if_complete` 可在 reopen 补完成而不重派。`allowed_attempts=1`。
- Router 哈希相对 followup_01 **未变**。这不是挂载 API，也不是全文写作调度。不要求生产开通。

**事实（有意义的失败/恢复/并发）**

- 提取失败：`resume` 在 source service 抛错后 **返回 `None`**，不抛 typed 错。随后用健康 service 再 `resume` 仍是 `None`；`load_run` 状态 **`blocked`**。`allowed_attempts=1` 且失败/阻塞节点不会自动再派（`runtime.py` 414–417, 1159–1161）。显式 `retry_node` 还要新的 retry 身份，并受 attempt 上限约束。
- 并发：同一 logical call 的第二路 dispatch 会 `graph_reservation_contended_retryable`（1128–1136）。Coordinator **不捕获** 该错——比返回 `None` 好，但与失败路径的静默 `None` 不一致。
- `read()` 以 snapshot `completed` 为门；节点结果已在、完成事件未写时，第一次 `resume` 应走 `run_to_completion` → `_finish_run_if_complete`。本会话 **未** 用人工缺完成事件的夹具证明这一点（属既有 runtime 语义，信心中等）。

**解释**

- 成功路径的「start 不抽取 / 完成包钉死抽取时刻 / 重开不读源」成立，且用真 SQLite。
- 失败路径把 Graph 的 blocked/failed 吞成 `None`，调用方无法区分未执行、失败、阻塞。加上 attempt=1，瞬时源失败会卡住同一 seed 身份，除非改 seed 或走 runtime 显式 retry。这是准备层自己的恢复缺口，不是要新开安全工程套件。

**建议（仍不要求挂 API）**

- `resume`/`read` 在非 completed 时返回带 `status`/`stop_reason`/`error_code` 的结果，禁止静默 `None`。
- 若瞬时读源失败应可恢复：要么 `allowed_attempts>1` 且仅对「零 transport 孤儿」走现有 `_recover_zero_attempt_orphan`，要么文档写明必须 `retry_node`。不要在 coordinator 里偷偷再抽一次。

**不确定：** 未做双进程同时 `resume` 未完成 run；争用语义以 runtime 注释与 `UnknownOutcomeConflictError` 映射为准。

---

### 其它边界

| 项 | 结论 |
|---|---|
| Proposed 111 行 / 严格计划 proposed 仍 raise | 允许 API/单元测试仍过；本轮未重做 followup_01 全套 |
| `quality_score=0` / 未评估 / 非医学准入 | source_material 未改（哈希与初冻相同） |
| 修订标记、styles.xml 标题 | 不在本 19 文件差分内；不重复验收 |
| 全文调度 / 生成端点 | 未实现、未要求开通 |

---

### 给 Codex 的决策点

1. 计划在**条件已决**后是否仍必须输出诊断全集（type/alias/无条件 missing）？建议必须，否则 A 的单次清单只在「还缺条件」时成立。  
2. deferred 是否改为「仅未决或否决规则的条件路径」？建议是，否则已适用的 `required_when_active`（如期中分析）会被藏到下一轮。  
3. `SourcePreparationCoordinator.resume` 失败是否保持 `None`？建议否，至少暴露 `blocked`/`failed`。

**安全暂行路径：** 把未决计划里的 errors 当「当前可见洞」，不要当成条件填完后仍完整。source 准备只在 **completed + 相同 input_sha256** 时当可恢复包；`resume is None` 一律当未完成/失败，不要当空成功。

**未做：** 未改源；未写 runner 报告文件；未跑 369；未做真模型/OCR/浏览器/Word 验收。
