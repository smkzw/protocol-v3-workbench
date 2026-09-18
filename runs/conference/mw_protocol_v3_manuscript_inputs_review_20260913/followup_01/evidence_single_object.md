This is a targeted verification of the owner repairs, not a new GLM opinion. I’ll re-read the follow-up freeze, then check phase-conflict visibility, heading classification, proposed-plan behavior, and the unresolved-branch diagnostic choice.The follow-up freeze has 16 files. I’ll verify those hashes, then read the repaired plan, parser, pinned-source reader, and the tests that now encode owner decisions A and B.I’ll compute whether any raw-contract required facts are actually inactive-conditional, then probe the alias-hiding and heading/v1–v2 cases in scratch.# Conference Output: mw_protocol_v3_manuscript_inputs_review_20260913 - evidence_single_object

## Output

**Fallback / identity:** 本节点仍是 Codex 指定的 `grok-build` / `grok-4.6` 有界续核，不是 GLM 意见。只读；未递归委派、未调产品模型、未启动常驻服务、未查凭证、未清理。Scratch 仅在 `runs/conference/mw_protocol_v3_manuscript_inputs_review_20260913/followup_01/scratch/`。Runner 落盘。不主张最终产品/医学/Word 验收。前端仍在范围外。

**核验：** followup_01 清单 **16/16 SHA256 匹配**。允许 pytest **29 passed / 2.61s**。复现脚本：`followup_01/scratch/followup_verify.py`。

---

### A. 期别冲突可见 vs「未决分支不执行 raw-contract 义务」

**证据（owner A 已满足）**

- `plan_manuscript_chapters` 在 `ApplicabilityResolutionError` 之后额外 `bind_chapter_input`（原合同），仅当 `fact_alias_conflict` 时并入 errors 并把状态升为 `invalid_input`（`manuscript_plan.py` 52–64）。注释写明：不激活条件义务，不按原合同裁判缺失/inactive。
- 同时写入 `framing.study_phase=Ⅱ期` 与 `framing.structured_design.phase=Ⅲ期`：`v2_n_1_1` 与 `v2_n_4_1` 均为 `invalid_input` 且含 `fact_alias_conflict`；设计章仍保留三条 `conditional_applicability_unresolved`（interim/stratification/substudy）。研究 JSON 未变。`test_phase_conflict_stays_visible_when_design_conditions_are_unknown` 覆盖此点。
- 严格计划负例仍在：`test_proposed_facts_cannot_exclude_a_chapter_from_the_plan` 对 `plan_manuscript_chapters(proposed)` 仍要求 `applicability requires confirmed study facts`。

**证据（对该选择的具体失败，不是空反驳）**

1. **未决分支把「永远 required」的缺口一起吞掉。**  
   `v2_n_4_1` 的 `conditional_fact_paths` 只有 interim/stratification/substudy；**9 个无条件 required**（`structured_design`、hypothesis、phase、design_type、arms、duration、allocation、masking、centers）不在 inactive 集合里。稀疏 confirmed 研究下设计章只有三条 unresolved，`missing_required_fact` **不出现**。同一研究在内层规则被明确否决后，这些缺口才以 `missing_required_fact` 出现。  
   **解释：** owner 担心的是「raw required ∩ 条件路径」被误判为缺失。这在现行目录里**真实存在**（13 章，如 `v2_n_11_4_9` 的 interim 细节、`v2_n_12_7` 的 future_use、`v2_n_4_5` 的揭盲/随机化）。但实现是「未决时丢掉所有非 alias 的 `FactBindingError`」，比该理由宽。设计骨架未填会被显示成「先去填分层/期中」，不是事实齐备记账。

2. **先抛出的绑定错误会压死 owner 要求必须看见的期别冲突。**  
   `bind_chapter_input` 按 sorted paths 遇错即 raise（`fact_bindings.py` 260–274）。`framing.structured_design` 排在 `framing.structured_design.phase` 之前。对该键写入 NaN 后：设计章仍是 `needs_information` + 三条 unresolved，**没有** `fact_alias_conflict`，也**没有** `fact_type_mismatch`。  
   **解释：** 诊断分支只收留 alias；任何更早的 type/member 错误既被丢弃，又让 alias 检查根本跑不到。这与「A 必须暴露期别冲突」直接冲突。NaN 偏合成，但代码路径对任何非 json 失败的更前路径同样成立。

**建议（保留 inactive 谨慎，收窄吞咽）**

- 继续：未决规则的 `conditional_fact_paths` **不要**当成 raw required 缺失。
- 仍要并入：`fact_alias_conflict`（已做）、`fact_type_mismatch` / `fact_member_invalid`（已有值是错的）。
- 仍要并入：`missing_required_fact` 中 **不属于** 当前未决规则 `conditional_fact_paths` 的路径（设计章那 9 个无条件键）。
- 诊断读取应收齐冲突，不要依赖 `bind_chapter_input` 的第一枪；或先扫 alias，再扫其余。

**不确定：** SQLite JSON 是否能写入 NaN；不影响「第一枪掩盖 alias」的代码事实。未对 13 个 overlap 章逐条演示误报，overlap 列表来自现行 contract×rules。

---

### B. 数字/basedOn 样式、v1/v2、钉住历史

**证据（owner B 已满足）**

- 默认 `PARSER_VERSION='protocol-docx-xml.v2'`；显式 v1 仍可解析；其它版本 `unsupported_docx_parser_version`（`docx_parse.py` 19, 95–110, 219）。v2 才读 `styles.xml` 段落样式，沿 `basedOn` 看名称含 heading / 以「标题」开头，或样式大纲 0–8。
- 同一 DOCX：v1 角色 `['body','body','body']`；v2 `['heading','heading','body']`。v2 的 `evidence` 只有「可引用正文」；parse 仍保留「数字样式标题」且 role=`heading`。v1 升格证据会含标题（旧种子投影）。`test_numeric_and_inherited_heading_styles_are_context_not_body_evidence` 钉死 v2。
- `read_pinned_chapter_sources`：按种子里的 `parser_version` 再 parse 一次做投影比对，然后用**当前默认 v2** 编 `prepare_chapter_source_material`（`pinned_sources.py` 27–36）。Scratch：v1 种子 payload 不变、SQLite dump 不变、后继版本正文不进证据、当前 bundle `parser_version=v2`、标题在 parse 不在 evidence。允许测试覆盖「后继版本仍读原始字节、无库写入」。

**解释：** 历史种子不被重写；现行全文材料用 v2 角色。标题留在完整结构里，不当 body 证据。v1 仅用于核验旧投影，这是有意的双轨，不是漏修。

**残留（B 修复外）**

- 无 `styles.xml` 时数字 styleId 仍会当 body（v2 也一样）。属源包不完整，不是 basedOn 漏实现。
- 修订插入仍是 body 文本 + `tracked_changes_present`（`test_revision_markers_are_reported_not_silently_accepted_as_clean`；scratch 相同）。**这是后续来源 QC，不是本次 A/B 修复失败。** 证据数组仍不携带 diagnostic code；只拿 `evidence[]` 会把修订句当可引用 proposed 正文。`quality_score=0` 与 `medical_admission=not_assessed` 未改，按 owner 声明视为未评估，不是临床质量分。

---

### Proposed API 视图 vs 确认后严格计划

**证据**

- 读路径改为 `manuscript_preparation_view`（`service.py` 741–748）。confirmed/frozen → 严格 `plan_manuscript_chapters`；其它状态 → 111 行 `applicability=unresolved` / `status=needs_information` / `errors=[{code:study_not_confirmed}]` / `applicability_snapshot=None`（`manuscript_plan.py` 24–32）。
- Proposed + `appendix.ecog_assessment_applicable=False`：视图 111 行、无 `not_applicable`、无 `facts_ready`、`all_applicable_inputs_ready=False`。严格函数仍 raise。Frozen 同事实走严格计划，ECOG 为 `not_applicable`。
- GET proposed：200、111、`snapshot is None`、全部 `study_not_confirmed`、库 dump 不变。不再是通用 422。允许的 API 测试对 confirmed/proposed 参数化；confirmed 负例（proposed 不得进严格计划）仍在单元测试。

**解释：** 未确认不能排除、不能假齐备。确认后严格计划语义未改。Proposed 只是可见未决清单。

---

### 其它边界（按 owner 冻结声明核对）

| 项 | 结论 |
|---|---|
| `facts_ready` ≠ 内容/证据/Word 完成 | 仍成立；`scope=chapter_fact_readiness` |
| source bundle 缓存/生成端点 | 仍未挂载；不要求开通 |
| 医学准入 / 全文调度 / Word | 未声称、未验收 |
| 前端 | 未评 |
| 新安全工程 | 不要求 |

---

### 决策点与有界问题（给 Codex）

1. 未决分支是否改为：**跳过** overlap 条件路径的 missing，**保留** 无条件 missing 与一切「现值非法」（type/member/alias）？建议是。否则设计章事实洞会被「先填条件」挡住。  
2. 诊断 `bind_chapter_input` 是否必须扫完全部 alias 再停？建议是，否则 A 在更前路径 type 失败时再次失明。  
3. 修订插入升格为 proposed body evidence：是否明确留给来源 QC、不纳入本冻结修复？建议是，但应在章节请求里继续依赖 `source_material.diagnostics`，不要只喂 `evidence[]`。

**安全暂行路径：** 在 1–2 落地前，不要把「仅 unresolved、无 missing」读成设计事实已齐；期别冲突要以计划 errors 里是否真有 `fact_alias_conflict` 为准，并意识到它仍可能被更前的绑定异常挡住。Proposed 111 行可当导航，不可当开写许可。

**未做：** 未改源；未写 runner 报告文件；未做真模型/OCR/浏览器/生产 Word 验收。允许测试读取了 `test_agent1_docx_parse.py` 中的既有清洁 DOCX 夹具，只用于解析回归，不当模板权威。
