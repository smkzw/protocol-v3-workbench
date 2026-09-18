# 3R.4B 条件规则对账提案（worker_01 proposal — 非已接受医学结论）

- 任务：`mw_protocol_v3_3r4b_condition_matrix_20260913` / `worker_01`
- 日期：2026-09-13
- 交付物：本文件 + `proposed_matrix.json`（49 行，与基座矩阵规则集与顺序完全一致，已程序校验）
- 生成器：`build_proposed_matrix.py`（本目录内，仅读授权输入，仅写本目录）
- 状态：`worker_proposal_pending_codex_adjudication`。本提案是给 owner/Codex 的证据与建议，不是合同修订、不是 checker 实现、不是最终裁定。

## 1. 输入与方法

- 计划依据：`plans/mw_protocol_v3_implementation_plan_v3_20260912.md` §3R.4B（含"完成证据"行）。
- 基座：`runs/mw_protocol_v3_3r4b_20260912/applicability_obligation_matrix.json`（`source_inventory_only_not_executable`，49 规则 / 14 事实交集；每行 true/false/unknown 仅有聚合 activated/release_candidates，`not_yet_adjudicated`）。
- 合同：`chapter_contracts/*.json` 中承载规则的 27 个节点（49 条 `conditional_applicability_rules`）。
- 源文本：授权只读 DOCX（sha256 `018d28d…43756`，经与 `statistics_source_window.json`/`oversight_reference_source_window.json` 逐条核对一致），以标准库 zip/XML 读取 body-child 段落；`node_tree.json` 提供 node→body_child_index 映射。无 OCR、无下载、无模型抽取。
- 谓词/执行语义（只读上下文）：`services/api/app/protocol_workflow/registries/applicability.py` —— `FactPredicate{fact_path, members, expected}` 严格同型比较（`False` 永不等于 0；缺失/null/异型 → CONDITIONAL）；谓词必须 ⊆ `triggering_fact_paths`；声明须以 `source_rule_sha256 == rule.material_sha256()` 绑定现行规则；NOT_APPLICABLE → 跳过，CONDITIONAL → `conditional_applicability_unresolved`；**释放无条件义务只能走合同修订，不能运行期减法**。

## 2. 触发编码清单（核心约束）

fact_bindings 核验结果：**49 个触发事实中仅 10 个 `value_type=boolean`，36 个为 `json`，3 条规则触发为同一 json 事实的复用**。`FactPredicate(expected=true)` 对 json 型事实永远 CONDITIONAL —— 这正是计划"不能从名字推断布尔"的落点：

- **executable_boolean_declared（10 条规则，谓词可执行）**：`ae.oncology_progression_exception_applicable`、`statistics.sample_size.interim_applicable`、`quality.risk_management_plan_applicable`、`quality.remote_monitoring_applicable`、`quality.oversight_charter_applicable`、`references.foreign_sources_present`、`appendix.ecog_assessment_applicable`、`appendix.nyha_assessment_applicable`、`exploratory.immunogenicity_applicable`、`irc.applicable` —— 合同 rationale 均明示"裸 true/false"。
- **unresolved_json_encoding_proposed_member（19 条）**：语义确为"是否适用"（pk/pd/er、interim、multiplicity.no_adjustment、future_use、central_lab、injection_reaction、endpoint_disposition、dose/background/randomized_day/unscheduled/hold 族、labeling、pregnancy_contraception），提议 `members=("applicable",) expected=true` 或 owner 直接改型 boolean；**编码声明前不可落码**。
- **unresolved_requires_owner_schema（18 条）**：载体型触发（`framing.structured_design`、`picos.inclusion/exclusion_modules`、`picos.study_epochs`、`picos.population_summary`、`population.screen_failure.definition`、diagram/soa/design 族、front 族）恒存在 → 规则空洞；需逐特征显式 boolean（如 `features.interim_analysis_applicable`、`masking`、`randomized`）。
- **unresolved_non_scalar_condition（2 条）**：`v2_n_3_1_2_4:strategy-crosscheck`（条件是比较 ICE 策略内容，非触发事实取值）、`v2_n_5_5:active`（真实开关是 `population.recruitment.compensation_applicable`，需加入触发路径）——提议专用 boolean 事实作显式触发。

## 3. 14 项事实交集逐条裁定（提议）

| # | 规则 | 交集事实 | 提议动作 | 源依据 |
|---|---|---|---|---|
| 1-3 | pk/pd/er (11_4_6) | endpoint_linkage, sampling_schedule, model_assumptions ×3 | promote_to_conditional_drop_unconditional（另：`confirmatory_analysis_link` 在规则内属过要求，仅"确证性使用"需链接） | src[262] PK 分钟/小时窗；src[584] 9.3"如果适用…否则注明不适用"；src[798] 仅剩片段（源薄弱） |
| 4 | multiplicity (11_4_8) | applicability_disposition | remove_from_conditional_keep_unconditional（任何项目都须记录处置；src[803] 条件句"如…多于一个"→ family/ordering/alpha/dependencies/procedure 对单终点项目属过要求，建议新增 `multi_confirmatory_endpoints` boolean 重建对称分支） | src[803] |
| 5 | interim (11_4_9) | 10 个 interim.* 事实 | promote_to_conditional_drop_unconditional；**必须同时处理 canonical_reference + 表格 + claims（见 §4.1），不能只释放 10 个交集字段** | src[805]/[806] |
| 6 | future-use (12_7) | 7 个 future_use.* + separation claim | promote_to_conditional_drop_unconditional；false 须显式"不留存/销毁"处置；src[831] GCP 检测禁令保留 | src[830]"如研究结束后将保留…" |
| 7 | background-rescue (3_1_2_3) | rescue_treatment_handling | remove_from_conditional_keep_unconditional（节点标题即"伴有或不伴有…"——无背景治疗也须显式处置） | 节点标题 src[318] |
| 8 | dose-modification (6_1_2) | hold_criteria/reduction/restart/permanent_discontinuation ×4 | promote_to_conditional_drop_unconditional + false 处置事实（"固定剂量、无调整路径"） | src[430]"如果适用…剂量调整" |
| 9 | escalation/DLT (6_1_2) | dose_escalation_or_dlt_logic（自触发） | promote_to_conditional_drop_unconditional；声明层与内容层同名异层需命名区分 | src[430]"如果适用，需描述剂量递增方案" |
| 10 | background (6_4_2) | background_therapy_rules | promote_to_conditional_drop_unconditional（推荐）或保留无条件处置式负值；false 处置="无必须背景治疗"（src[479]"否则注明不适用"） | src[479] |
| 11 | randomization-day (7_2) | randomization_day_rules | promote_to_conditional_drop_unconditional（非随机化设计不得虚构） | src[489] D1 示例 |
| 12 | individual-hold (8_1) | individual_hold_criteria, personal_hold | promote_to_conditional_drop_unconditional；applicability 事实升为 required 以显式承载"确实无暂停路径" | src[500]/[511]；"暂时暂停"细则源支持薄弱 |
| 13 | hold-to-stop (8_1) | permanent_stop_criteria.participant, permanent_stop_recording | remove_from_conditional_keep_unconditional（任何试验都可能有参试者永久停药）；规则残余价值=暂停→永久转换链，建议专用事实或降级为交叉核对 | src[500]/[511] |
| 14 | central-lab (9_2) | lab_units_and_reference_ranges, special_assay_purposes | remove_from_conditional_keep_unconditional（本地实验室同样必需）；中央实验室专属义务缺位，须新增 facts（见 §4.2） | src[572]/[574] |

**claim 级交集（计划"14"只数了事实路径）**：`multiplicity_procedure`、`pk_pd_er_analysis`、`interim_analysis_plan`、`future_use.separation`、`lifestyle_restriction`、`inclusion_predicate`、`exclusion_predicate`、`recruitment_plan`、`retention_plan`、`screen_failure_record`、`rescreening_eligibility`、`design_description`、`design_rationale`、`control_choice_decision`、`dose_regimen_rationale`、`study_follow_up_definition`、`overall_study_end_definition`、`allocation_procedure`、`masking_procedure`、`individual_cessation_rules` 等同为无条件 required —— 各行 `overlap_disposition.claim_items` 已逐条给出动作（多为 remove_from_conditional_keep_unconditional；随机化/盲法两条为 promote_to_conditional，见 §4.7）。

## 4. 专项裁定

### 4.1 期中分析 false（含 canonical_reference 与表格）— 计划步骤 3
- **true**：timing/information_fraction/purpose/rules/decision_responsibility/final_analysis_impact 六项为源要求（src[806]）；`efficacy_alpha_spending`/`safety_review_alpha_separation` 仅当期中目的含有效性/双审查时适用（复合条件待 owner 类型化事实）；`idmc_responsibilities` 仅当设立委员会（否则记录实际决策主体，不得虚构）；`endpoint_irc_responsibilities` **属过要求**——IRC 未设立时不应要求，提议拆分 interim×IRC 复合规则（`irc.applicable` 已是可执行 boolean，mode=all 可表达）。
- **false**：释放 10 事实 + `canonical_reference` + 全部表格义务（11 单元格）+ `interim_analysis_plan`/`interim_final_analysis_impact` claims；**保留** `statistics.interim.applicable=false` 判定本体、全部 forbidden（stale_reference_pointer/marketing_claim/timing_alpha_inconsistent）、与 `statistics.sample_size.interim_applicable` 的跨合同一致；**新增** `statistics.interim.not_planned_disposition`（真实"不计划开展"处置与依据），canonical_reference 改指该处置记录身份；正文残留计划期中参数即矛盾，须显式处理。
- **canonical_reference 目标（缺陷 D3，计划步骤 5 确认）**：合同 word_rule 要求把过时"14.6"解析为"数据监查委员会 **v2_n_13_x 载体族**"——实际 13.x 是伦理族（13_1 伦理规范 / 13_2 知情同意 / 13_3 保密和隐私 / 13_4 补偿赔偿保险），**不存在 IDMC 载体**；真实载体是 `v2_n_14_7` 安全性监督（现模板 14.7），而旧"14.6"现指向方案偏离。提议：canonical 目标 = `contract:v2-n-14-7` 或项目确认的现行 IDMC 章节身份；字面 `v2_n_13_x` 永不视为已解析。

### 4.2 中央实验室 vs 本地实验室（9_2）
- 缺陷 D1：触发事实 `safety.central_lab_applicable` **未在本合同 fact_requirements 声明**（fact_bindings 仅指向规则）——无人有义务记录判定。
- src[574]：单位/参考范围、检测方法指定、多实验室项目分配、实验室资质是**本地与中央通用义务** → 两个交集事实保留无条件，从规则中移除；中央实验室专属义务（资质+承担项目）缺位 → 新增 `central_lab_qualification`、`assay_site_assignment`、`ecg_reading_location`（src[572] ECG 中心分析→收集/传输/归档；本地阅读→处理方法与格式）。
- false 分支：不释放本地义务；提议 `safety.lab_strategy`（central|local|mixed）显式记录策略——"确实不适用"与"适用但材料缺失"由此分开。

### 4.3 永久停药 vs 暂时暂停（8_1）
见 §3 表 12/13 行。要点：permanent_stop 两事实无条件保留；个体暂停细则的源支持薄弱（src[500] 为研究级列举、src[511] 只确立"干预中止≠研究中止"），`individual_hold_*` 两事实建议条件化 + applicability 事实升为 required 显式承载否定。

### 4.4 多重性（11_4_8）
规则只覆盖 no-adjustment 分支且与无条件义务重复；"需调整"分支义务藏在无条件事实里对单终点项目过要求（src[803] 条件句）。提议 `statistics.multiplicity.multi_confirmatory_endpoints` boolean 重建对称结构；applicability_disposition 保持无条件。

### 4.5 IRC（9_4）
谓词可执行（裸 boolean）。true：scope_endpoints/adjudication_method 为源要求（src[588]/[589]），charter_independence/roles_conflict 为合同派生。false：四事实释放；src[587]"如不适用，删除本节，或对其他第三方独立评估进行描述"→ 保留本节时提议 conditional claim `alternative_independent_assessment`；`irc_equals_safety_committee`/`recist_universal_method` 禁令保留。

### 4.6 PK/PD（11_4_6 ×3、1_3、9_3）
- 11_4_6 三规则：触发 json 编码未声明；三个共有事实 promote 条件化；`confirmatory_analysis_link` 属规则内过要求（仅确证性使用）；src[798] 仅剩片段"则同既往方案描述内容。"（源薄弱标记，owner 需决定合同升版依据）。
- 1_3（SOA PK 采血）：pk_timing_units 条件化（src[262] 分钟/小时窗）。
- 相邻发现（不在 49 条内）：v2_n_9_3 无条件 required `exploratory.population_pk`/`exposure_response` vs src[584]"如果适用…否则注明不适用"——疑过要求。

### 4.7 妊娠/避孕（5_2 ref、5_3）
- 缺陷 D2：5_2 规则要求 `population.exclusion.contraception_criterion_ref`，但该事实**未在 v2_n_5_2 fact_requirements 声明**——激活时无处承载；须合同增列（json 引用纳入载体标准身份；不复制逆命题、不设通用期限）。
- 5_3：`population.lifestyle.contraception_duration` 无条件 required vs src[391]"对于有生育能力的女性…"条件措辞——同类过要求，建议条件化（不在 14 项事实交集内，单列）；lifestyle 四事实无条件保留（src[409]）。

### 4.8 供应商/服务方（front_4）
谓词 json 编码待声明；true：`contact.service_parties` 条件化必填（src[87]"如适用"+src[92] 参与单位及相关部门，含中心实验室/IWRS）；false：释放服务方行，申办者/研究者联系方式与表格本体保留（src[88]/[90]）。

## 5. 缺陷与未决清单（需 owner/Codex 决定）

**缺陷（建议随 3R.4A 串行合同修订修复）**
- D1：v2_n_9_2 触发事实 `safety.central_lab_applicable` 未声明（无判定义务载体）。
- D2：v2_n_5_2 规则引用未声明事实 `population.exclusion.contraception_criterion_ref`。
- D3：v2_n_11_4_9 word_rule 的"v2_n_13_x 载体族"为虚拟目标（13.x=伦理族；真实载体 v2_n_14_7）。
- D4：36 个 json 触发路径在编码声明前谓词不可落码（永久 CONDITIONAL）。
- D5：claim 级交集未被"14"覆盖，已逐条列入 proposed_matrix（多为规则冗余）。

**未决（owner 源核实/设计决定，行内 `unresolved[]` 共 33 行非空）**
- src[798] 探索性统计节源薄弱；src[324] 五要素示例与四属性表述潜在冲突（3_1_2_4 rationale 自认）。
- `procedure.phone_visit_linkage`、`picos.intervention_dose_regimen.maximum_dose`、v2_n_9_3 PopPK/E-R、v2_n_1_2 O[figure]（src[246]"流程图为可选项目"）等无条件义务与源条件措辞的张力。
- 处置式负值编码（rescreening、background_therapy、dose_modification 的"确实不适用"取值）是否纳入事实 schema。
- interim×IRC 拆分规则、hold_to_stop_conversion 等新增规则/事实是否立项。

## 6. 验证记录

- 规则集/顺序与基座矩阵逐一相等；14 交集行与基座 `unconditional_required_overlap` 集合相等（程序断言通过）。
- 全部 executable 谓词的目标事实经 fact_bindings 核验为 `value_type=boolean`。
- 源引用：src[n] = 授权 DOCX body-child 零基索引，已与两个 source window 文件逐条比对一致；DOCX sha256 与授权值一致。
- 未做：合同/skill/fixture 修改、checker 实现、全量组装/lint（属 owner 3R.4A/3R.4B 后续步骤）；本目录外零写入。
