#!/usr/bin/env python3
"""Build condition_worker/proposed_matrix.json (worker_01 proposal, NOT accepted adjudication).

Reads only:
- runs/mw_protocol_v3_3r4b_20260912/applicability_obligation_matrix.json (owner inventory)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/*.json
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/fact_bindings.json
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json

Writes only: condition_worker/proposed_matrix.json (this directory).
No product/source/test edits. Evidence quotes were extracted from the authorized
readonly DOCX (sha256 018d28d...; stdlib zip/XML) and are embedded verbatim below.
"""
import hashlib
import json
from pathlib import Path

WS = Path(__file__).resolve().parents[3]
CONTRACTS = WS / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts"
BINDINGS = WS / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/fact_bindings.json"
NODES = WS / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json"
BASE = WS / "runs/mw_protocol_v3_3r4b_20260912/applicability_obligation_matrix.json"
OUT = Path(__file__).resolve().parent / "proposed_matrix.json"

# ---------------------------------------------------------------------------
# Per-rule adjudication table (hand-authored by worker_01; evidence-checked).
# status: executable_boolean_declared | unresolved_json_encoding_proposed_member
#       | unresolved_requires_owner_schema | unresolved_non_scalar_condition
# origin: source_required | source_required_conditional_scope
#       | contract_derived_pending_owner_source_review | inherited_overrequirement
#       | proposed_new
# overlap action: promote_to_conditional_drop_unconditional
#               | remove_from_conditional_keep_unconditional
#               | keep_unconditional_as_negative_disposition_record
# ---------------------------------------------------------------------------
A = {}

A["applicability:n-10-1-1:oncology-progression"] = dict(
    pred_status="executable_boolean_declared",
    pred_note="合同 rationale 明示『裸 true/false』且 fact_bindings value_type=boolean；FactPredicate{expected:true} 可执行。",
    true_facts=[("ae.oncology_progression_exception", "promote_from_optional", "source_required", "src[599] 肿瘤进展不记AE除非更重/相关；新发原发恶性肿瘤记AE——例外细节仅肿瘤项目适用")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["ae.oncology_progression_exception"],
    false_retain=["ae.definition（src[599] 的一般性进展措辞仍属AE定义无条件义务）", "forbidden: ae.template_example_*"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[],
    unresolved=[],
)

A["conditional:v2-n-11-1:interim-adjustment"] = dict(
    pred_status="executable_boolean_declared",
    pred_note="rationale『期中样本量调整适用性必须有明确布尔状态』+ value_type=boolean；可执行。",
    true_facts=[("statistics.sample_size.interim_adjustment", "promote_from_optional", "source_required", "src[771]『对于计划的中期分析进行I类错误调整的方法（若有）』"),
                 ("statistics.sample_size.interim_alpha_adjustment", "promote_from_optional", "source_required", "src[771] 同上（若有）")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["statistics.sample_size.interim_adjustment", "statistics.sample_size.interim_alpha_adjustment"],
    false_retain=["sample_size_cross_contract_consistency claim（须与 statistics.interim.applicable 交叉一致）"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[],
    unresolved=["与 statistics.interim.applicable 的跨合同一致性目前只靠 claim，建议 checker 增加显式交叉核对"],
)

A["conditional:v2-n-11-4-6:pk"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="rationale『必须显式声明 PK 分析是否适用』但 fact_bindings value_type=json；expected:true 永不匹配。提议 owner 声明 members=('applicable',) expected=true 或改型 boolean。",
    true_facts=[("statistics.pk_pd_er.endpoint_linkage", "already_unconditional", "source_required", "确证性使用必须链接主要/次要分析（contract rationale）"),
                 ("statistics.pk_pd_er.sampling_schedule", "already_unconditional", "source_required", "src[262] PK 时间窗以分钟/小时计"),
                 ("statistics.pk_pd_er.model_assumptions", "already_unconditional", "source_required", "contract rationale：必须有模型假设"),
                 ("statistics.pk_pd_er.confirmatory_analysis_link", "required_when_active", "inherited_overrequirement", "rationale 限定『确证性使用』才需链接；仅适用（探索性）即要求属过要求")],
    true_claims=[("pk_pd_er_analysis", "already_unconditional", "overlap_note", "claim 亦为无条件 required，与14项事实交集平行")],
    true_objects=[], true_evidence=[],
    false_release_facts=["statistics.pk_pd_er.endpoint_linkage", "statistics.pk_pd_er.sampling_schedule", "statistics.pk_pd_er.model_assumptions", "statistics.pk_pd_er.confirmatory_analysis_link"],
    false_retain=["statistics.exploratory_analysis.endpoints/methods/data_definition（探索性节核心义务）"],
    false_negative_disp=[("statistics.pk_pd_er.not_applicable_disposition", "提议：三个适用事实均为 false 时，必须显式记录不开展 PK/PD/E-R 及理由（参照 src[584]『否则注明不适用』）")],
    ov_facts=[("statistics.pk_pd_er.endpoint_linkage", "promote_to_conditional_drop_unconditional"),
               ("statistics.pk_pd_er.sampling_schedule", "promote_to_conditional_drop_unconditional"),
               ("statistics.pk_pd_er.model_assumptions", "promote_to_conditional_drop_unconditional")],
    ov_claims=[("pk_pd_er_analysis", "promote_to_conditional_drop_unconditional")],
    unresolved=["src[798] 仅剩片段『则同既往方案描述内容。』——本节源薄弱，义务颗粒度主要来自合同；owner 需确认是否接受合同升版依据", "pk/pd/er 三规则共享同一事实集，true 时必须三事实并存而非逐规则重复要求"],
)
A["conditional:v2-n-11-4-6:pd"] = dict(A["conditional:v2-n-11-4-6:pk"])
A["conditional:v2-n-11-4-6:er"] = dict(A["conditional:v2-n-11-4-6:pk"])

A["conditional:v2-n-11-4-8:no-adjustment"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="no_adjustment_applicable value_type=json；提议 owner 声明 boolean 或 members 编码。",
    true_facts=[("statistics.multiplicity.applicability_disposition", "already_unconditional", "source_required", "src[803] 条件句『如…多于一个』→ 任何项目都须记录其多重性处置（含单终点无需调整）")],
    true_claims=[("multiplicity_procedure", "already_unconditional", "overlap_note", "true 时其值必须是显式『无需调整』处置句，而非默认句（contract rationale）")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["statistics.multiplicity.confirmatory_family/ordering/alpha_allocation/dependencies/procedure 在『需调整』分支仍须给出"],
    false_negative_disp=[("statistics.multiplicity.multi_confirmatory_endpoints", "提议新增显式 boolean：确证性家族>1 终点时才要求 family/ordering/alpha/dependencies/procedure；当前这些事实无条件 required 对单主要终点项目属过要求（src[803] 条件句）")],
    ov_facts=[("statistics.multiplicity.applicability_disposition", "remove_from_conditional_keep_unconditional")],
    ov_claims=[("multiplicity_procedure", "remove_from_conditional_keep_unconditional")],
    unresolved=["规则只覆盖 no-adjustment 分支；需调整分支义务目前藏在无条件事实里，建议以 multi_confirmatory_endpoints 重建对称条件结构（owner 决定）"],
)

A["conditional:v2-n-11-4-9:interim"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="statistics.interim.applicable value_type=json、rationale『必须显式声明期中分析是否适用』；提议 boolean 或 members=('applicable',) expected=true。",
    true_facts=[
        ("statistics.interim.timing", "already_unconditional", "source_required", "src[806] 分析时间点（入组<XX>例或发生<XX>事件后）"),
        ("statistics.interim.information_fraction", "already_unconditional", "source_required", "src[806] 时间点/信息量语义"),
        ("statistics.interim.purpose", "already_unconditional", "source_required", "src[806] 目的（有效性/无效性/安全性监查）"),
        ("statistics.interim.rules", "already_unconditional", "source_required", "src[806] 停止/调整规则语义"),
        ("statistics.interim.decision_responsibility", "already_unconditional", "source_required", "src[806] IDMC/DSMB 职责"),
        ("statistics.interim.final_analysis_impact", "already_unconditional", "source_required", "src[806] 期中→最终分析联动"),
        ("statistics.interim.efficacy_alpha_spending", "already_unconditional", "source_required_conditional_scope", "src[806] α消耗方法（O'Brien-Fleming/Lan-DeMets）仅当期中目的含有效性；纯安全性期中不适用——建议复合条件（未来 boolean：purpose_includes_efficacy）"),
        ("statistics.interim.safety_review_alpha_separation", "already_unconditional", "source_required_conditional_scope", "仅当有效性与安全性审查并存时才需α分离；同上建议复合条件"),
        ("statistics.interim.idmc_responsibilities", "already_unconditional", "source_required_conditional_scope", "src[806] IDMC/DSMB 职责仅当设立委员会；决策主体为其他时该事实应记录实际主体（处置式取值），不得虚构委员会"),
        ("statistics.interim.endpoint_irc_responsibilities", "required_when_active", "inherited_overrequirement", "IRC 未设立（irc.applicable=false）时不得要求 IRC 职责——建议拆分为 interim×IRC 复合规则（predicates=[interim.applicable, irc.applicable], mode=all），irc.applicable 已是可执行 boolean"),
        ("statistics.interim.canonical_reference", "not_in_rule_list", "source_required", "必须指向已解析规范目标（v2_n_14_7 安全性监督 或项目确认的现行 IDMC 章节身份）；不得指向过时『14.6』（现14.6=方案偏离）；字面『v2_n_13_x』为虚拟族ID（13.x=伦理族），不得视为已解析"),
    ],
    true_claims=[("interim_analysis_plan", "already_unconditional", "overlap_note", "claim 亦无条件 required"),
                  ("interim_final_analysis_impact", "already_unconditional", "keep_unconditional", "")],
    true_objects=[("table", "already_unconditional", "keep_at_true", "11个必需单元格：timing/information-fraction/purpose/rules/decision/final-impact/efficacy-alpha/safety-separation/idmc/irc/canonical-reference")],
    true_evidence=[],
    false_release_facts=["statistics.interim.timing", "statistics.interim.information_fraction", "statistics.interim.purpose", "statistics.interim.rules", "statistics.interim.decision_responsibility", "statistics.interim.final_analysis_impact", "statistics.interim.efficacy_alpha_spending", "statistics.interim.safety_review_alpha_separation", "statistics.interim.idmc_responsibilities", "statistics.interim.endpoint_irc_responsibilities", "statistics.interim.canonical_reference"],
    false_release_claims=["interim_analysis_plan", "interim_final_analysis_impact"],
    false_release_objects=["table（含全部11单元格义务一并释放，不能只释放10个交集事实字段）"],
    false_retain=["statistics.interim.applicable（记录 false 的显式判定）", "forbidden: statistics.interim.stale_reference_pointer / marketing_claim / interim_timing_alpha_inconsistent", "与 statistics.sample_size.interim_applicable 交叉一致（v2_n_11_1）"],
    false_negative_disp=[("statistics.interim.not_planned_disposition", "提议：false 时必须保留真实『不计划开展』处置与依据（含理由），canonical_reference 改为指向该处置记录身份；正文不得残留计划期中参数（残留即矛盾，须处理而非静默采入）")],
    ov_facts=[(p, "promote_to_conditional_drop_unconditional") for p in (
        "statistics.interim.timing", "statistics.interim.information_fraction", "statistics.interim.purpose",
        "statistics.interim.rules", "statistics.interim.decision_responsibility", "statistics.interim.final_analysis_impact",
        "statistics.interim.efficacy_alpha_spending", "statistics.interim.safety_review_alpha_separation",
        "statistics.interim.idmc_responsibilities", "statistics.interim.endpoint_irc_responsibilities")],
    ov_claims=[("interim_analysis_plan", "promote_to_conditional_drop_unconditional")],
    unresolved=[
        "合同 word_rule 以『v2_n_13_x 载体族』作为过时14.6引用的规范目标——13.x 实为伦理族（13_1伦理/13_2知情同意/13_3保密/13_4补偿），无IDMC载体；真实载体为 v2_n_14_7 安全性监督（计划3R.4B步骤5缺陷确认）",
        "efficacy_alpha_spending / safety_review_alpha_separation / idmc_responsibilities 的条件范围需要 owner 声明 purpose/decision-body 类型化事实后才能收窄",
        "endpoint_irc_responsibilities 拆分规则需新增 rule id 并绑定 source_rule_sha256",
    ],
)

A["applicability:v2-n-12-7:future-use"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="future_use.applicable value_type=json；提议 boolean 或 members 编码（如 samples_retained）。",
    true_facts=[(p, "already_unconditional", "source_required_conditional_scope", "src[830]『如研究结束后将保留预存或残余的样本，应说明…』——保留样本/数据时才成为义务") for p in (
        "future_use.purpose", "future_use.location", "future_use.duration", "future_use.genetic_testing",
        "future_use.consent", "future_use.review_plan", "future_use.current_study_assay_separation")],
    true_claims=[("future_use.separation", "already_unconditional", "overlap_note", "与本研究当前必需检测分离"),
                  ("future_use.review_required", "already_unconditional", "inherited_overrequirement", "src[830] EC是否审查未来研究属于保留样本时的披露项；不留存时不适用")],
    true_objects=[("table", "already_unconditional", "promote_to_conditional", "src[830]-[836] 示例为表格承载；不留存时应释放")],
    true_evidence=[],
    false_release_facts=["future_use.purpose", "future_use.location", "future_use.duration", "future_use.genetic_testing", "future_use.consent", "future_use.review_plan", "future_use.current_study_assay_separation"],
    false_retain=["forbidden: future_use.universal_withdrawal_conclusion / conflated_with_current_assay", "src[831] 禁止无EC批准的样品检测（GCP(2026修订)第三十七条）——保留为禁止性规则"],
    false_negative_disp=[("future_use.not_retained_disposition", "提议：不留存时显式记录不留存/销毁处置与依据")],
    ov_facts=[(p, "promote_to_conditional_drop_unconditional") for p in (
        "future_use.purpose", "future_use.location", "future_use.duration", "future_use.genetic_testing",
        "future_use.consent", "future_use.review_plan", "future_use.current_study_assay_separation")],
    ov_claims=[("future_use.separation", "promote_to_conditional_drop_unconditional")],
    unresolved=["『确实不留存』与『适用但材料缺失』须分开：not_retained_disposition 需 owner 确认事实路径与编码"],
)

A["applicability:n-14-1:risk-plan"] = dict(
    pred_status="executable_boolean_declared",
    pred_note="rationale『采用裸 true/false 编码』+ value_type=boolean。",
    true_facts=[("quality.risk_management_plan_identity", "promote_from_optional", "source_required", "src[885]『详见<质量风险管理计划/监查计划>（如适用）』——适用时须有实际计划身份"),
                 ("quality.plan_review_cadence", "promote_from_optional", "contract_derived_pending_owner_source_review", "复核节奏为合同派生良好实践，模板未直接给出")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["quality.risk_management_plan_identity", "quality.plan_review_cadence"],
    false_retain=["基础 CtQ 链义务不豁免（rationale + src[885] CtQ/RCA/CAPA 为无条件）", "forbidden: quality.template_example_plan_name"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:n-14-3:remote-monitoring"] = dict(
    pred_status="executable_boolean_declared",
    pred_note="rationale『采用裸 true/false 编码』+ value_type=boolean。",
    true_facts=[("quality.remote_monitoring_records", "promote_from_optional", "contract_derived_pending_owner_source_review", "远程监查记录方式与留存边界为合同派生；src[893]-[900] 仅给一般监查记录义务")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["quality.remote_monitoring_records"],
    false_retain=["基础监查义务（monitoring_scope/methods/records 等）不豁免", "forbidden: quality.copied_template_company_name"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:n-14-7:oversight-charter"] = dict(
    pred_status="executable_boolean_declared",
    pred_note="rationale『采用裸 true/false 编码』+ value_type=boolean。",
    true_facts=[("quality.oversight_charter_version", "promote_from_optional", "contract_derived_pending_owner_source_review", "src[918]『一份单独制定的DSMB章程将提供更详细的信息』；版本/批准记录为合同派生"),
                 ("quality.oversight_charter_approval_record", "promote_from_optional", "contract_derived_pending_owner_source_review", "同上；不适用不得写成已批准（rationale）")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["quality.oversight_charter_version", "quality.oversight_charter_approval_record"],
    false_retain=["监督义务本体不豁免（src[917]『如适用…否则注明不适用』→ 显式不适用声明）", "forbidden: fabricated_approved_charter / dsmb_smc_irc_interchangeable / fabricated_committee_membership"],
    false_negative_disp=[("quality.oversight_charter_not_applicable_statement", "提议：false 时显式『不适用』声明（src[917] 支持），替代章程版本义务")],
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:n-15:foreign-style"] = dict(
    pred_status="executable_boolean_declared",
    pred_note="rationale『采用裸 true/false 编码』+ value_type=boolean。",
    true_facts=[("references.foreign_format_style", "promote_from_optional", "source_required", "src[937]-[967] 模板为外文文献规定 JAMA/AMA 著录格式——存在外文来源时适用")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["references.foreign_format_style"],
    false_retain=["references.citation_style / used_source_register / bibliographic_metadata 无条件保留", "forbidden: references.template_example_reference_list"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:v2-n-16-x1:assessment"] = dict(
    pred_status="executable_boolean_declared",
    pred_note="rationale『采用裸 true/false 编码』+ value_type=boolean；不适用时不得自动收录。",
    true_facts=[("appendix.ecog_version", "promote_from_optional", "source_required", "核对版本"),
                 ("appendix.ecog_source_reference", "promote_from_optional", "source_required", "来源参考"),
                 ("appendix.ecog_scale_reproduced", "promote_from_optional", "source_required", "复现评分内容")],
    true_claims=[("appendix.ecog_version_and_contents_verified", "promote_from_allowed", "source_required", "版本与内容核对")],
    true_objects=[("table", "required_when_active", "source_required", "ECOG 评分表为附录本体")],
    true_evidence=[("regulatory_or_guideline|peer_reviewed", "评分表须有可追溯来源")],
    false_release_facts=["appendix.ecog_version", "appendix.ecog_source_reference", "appendix.ecog_scale_reproduced"],
    false_retain=["appendix.ecog_applicability_decision_record（无条件，记录不适用+理由）", "claim appendix.ecog_applicability_decided", "forbidden: appendix.ecog_template_example_table / ecog_appendix_without_actual_assessment"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:v2-n-16-x2:assessment"] = dict(
    pred_status="executable_boolean_declared",
    pred_note="同 ECOG：裸 true/false；不适用时不得自动收录。",
    true_facts=[("appendix.nyha_version", "promote_from_optional", "source_required", "核对版本"),
                 ("appendix.nyha_source_reference", "promote_from_optional", "source_required", "来源参考"),
                 ("appendix.nyha_classification_reproduced", "promote_from_optional", "source_required", "复现分级内容")],
    true_claims=[("appendix.nyha_version_and_contents_verified", "promote_from_allowed", "source_required", "版本与内容核对")],
    true_objects=[("table", "required_when_active", "source_required", "NYHA 分级表为附录本体")],
    true_evidence=[("regulatory_or_guideline|peer_reviewed", "分级表须有可追溯来源")],
    false_release_facts=["appendix.nyha_version", "appendix.nyha_source_reference", "appendix.nyha_classification_reproduced"],
    false_retain=["appendix.nyha_applicability_decision_record（无条件）", "claim appendix.nyha_applicability_decided", "forbidden: appendix.nyha_template_example_table"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:n-1-2:escalation"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="diagram.escalation_design value_type=json，rationale 未声明编码；提议显式 boolean（名义含 design 但未证布尔）。",
    true_facts=[("diagram.escalation_transition", "promote_from_optional", "source_required", "src[250]『除整个试验流程图外，还需有剂量递增图』")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["diagram.escalation_transition"],
    false_retain=["diagram.phase_arm_structure / visit_timepoints 无条件", "forbidden: diagram.template_example_timeline / source_example_values"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[],
    unresolved=["相邻：O[figure] 无条件 required vs src[246]『研究流程图为可选项目…可以删除』——图义务本身可能过要求（owner 决定，不在49条内）"],
)
A["applicability:n-1-2:allocation"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="diagram.randomized value_type=json；rationale『为真时触发』暗示布尔意图但未声明编码；提议显式 boolean。",
    true_facts=[("diagram.allocation_ratio", "promote_from_optional", "source_required", "src[246]『修改试验分组的分配方法』；单臂非随机设计必须能通过（rationale）")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["diagram.allocation_ratio"],
    false_retain=["design_description / diagram_transition claims"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:n-1-3:pk-sampling"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="soa.pk_sampling_present value_type=json；提议显式 boolean。",
    true_facts=[("soa.pk_timing_units", "promote_from_optional", "source_required", "src[262] PK 研究允许较小或无时间窗，时间点以分钟/小时计——窗口须带单位/参考事件")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["soa.pk_timing_units"],
    false_retain=["soa.visit_window_definitions / assessment_cells / early_exit_assessment 等无条件"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:n-3-1-1:rescue-strategy"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="design.rescue_treatment_planned value_type=json（『已确认设计事实』）；提议显式 boolean。",
    true_facts=[("design.discontinuation_rescue_strategy", "promote_from_optional", "source_required_conditional_scope", "src[312] 估计目标措辞含『不考虑…补救治疗』——设计含补救/停药策略时须给出该策略")],
    true_claims=[("rescue_strategy_statement", "promote_from_qualified", "source_required_conditional_scope", "C[qualified]→true 时 required；示例不得自动升级为项目要求（rationale）")],
    true_objects=[], true_evidence=[],
    false_release_facts=["design.discontinuation_rescue_strategy"],
    false_retain=["picos.primary_objectives / primary_clinical_question / primary_endpoint 无条件"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:n-3-1-2-3:background-rescue"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="estimand.primary.background_treatment value_type=json（『必须说明相关背景治疗』）；提议 members（如 ('present',)）或专用 boolean。",
    true_facts=[("estimand.primary.rescue_treatment_handling", "already_unconditional", "source_required", "节点标题即『伴有或不伴有补救治疗或背景治疗改变』——无论有无背景治疗都须说明处置；规则内要求属重复")],
    true_claims=[("estimand_cross_contract_consistency", "promote_from_absent", "contract_derived_pending_owner_source_review", "跨合同一致性声明")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["estimand.primary.rescue_treatment_handling 保持无条件（false 分支取值可为『无补救治疗允许』式显式处置）"],
    false_negative_disp=None,
    ov_facts=[("estimand.primary.rescue_treatment_handling", "remove_from_conditional_keep_unconditional")],
    ov_claims=[],
    unresolved=["触发事实本身为必填结构化属性，present/absent 子字段未声明——谓词无法落码直至 owner 声明 schema"],
)
A["applicability:n-3-1-2-4:strategy-crosscheck"] = dict(
    pred_status="unresolved_non_scalar_condition",
    pred_note="条件『汇总指标与伴发事件策略涉及补救治疗或背景治疗改变』不是触发事实（population_summary_measure）本身的取值；FactPredicate 无法表达。提议专用 boolean estimand.primary.ice_strategy_involves_treatment_change 作为显式触发。",
    true_facts=[("estimand.primary.ice_strategy_crosscheck", "promote_from_optional", "contract_derived_pending_owner_source_review", "策略须与随访/分析/缺失数据/敏感性分析合同交叉核对；rationale 自认 src[324] 措辞存在潜在冲突")],
    true_claims=[("estimand_cross_contract_consistency", "promote_from_absent", "contract_derived_pending_owner_source_review", "")],
    true_objects=[], true_evidence=[],
    false_release_facts=["estimand.primary.ice_strategy_crosscheck"],
    false_retain=["estimand.primary.intercurrent_events / ice_strategy / ice_rationale / population_summary_measure 无条件（src[323]）"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[],
    unresolved=["src[324] 五要素示例与四属性表述的潜在冲突需 owner 源核实后收口"],
)
A["applicability:n-3-3-1:injection-reaction"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="safety.injection_reaction_applicability value_type=json；rationale『必须显式给出给药途径是否适用及理由』→ 提议 members=('applicable',) expected=true（理由另立事实）。",
    true_facts=[("safety.injection_reaction_definitions", "promote_from_optional", "source_required_conditional_scope", "注射途径适用时才要求定义与观察方式")],
    true_claims=[("injection_reaction_statement", "promote_from_qualified", "source_required_conditional_scope", "C[qualified]→适用时 required")],
    true_objects=[], true_evidence=[],
    false_release_facts=["safety.injection_reaction_definitions"],
    false_retain=["safety.safety_objectives / picos.safety_endpoints / observation_period 无条件"],
    false_negative_disp=[("（适用性事实本身）", "applicability 事实须记录 false+理由（事实 rationale 为源义务：『必须显式给出…及理由』）——『确实不适用』与『材料缺失』由此分开")],
    ov_facts=[], ov_claims=[],
    unresolved=["本节点无正文文本（仅标题 src[333]）——义务颗粒度全部来自合同，源支持薄弱（source_thin 标记）"],
)
A["applicability:n-3-4-1:analysis-commitment"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="四个触发事实（population_pk/exposure_response/immunogenicity/biomarker）均 value_type=json；『任一适用』= mode=any，但每个都需要 owner 声明布尔/成员编码。",
    true_facts=[],
    true_claims=[("exploratory_commitment", "promote_from_qualified", "contract_derived_pending_owner_source_review", "C[qualified]→任一适用时 required；『示例不得整包继承』（rationale）")],
    true_objects=[("table", "required_when_active", "contract_derived_pending_owner_source_review", "节点无正文（仅标题 src[337]）；表格承载义务源支持薄弱")],
    true_evidence=[],
    false_release_facts=[],
    false_retain=["picos.exploratory_objectives / exploratory.disposition claim 无条件"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[],
    unresolved=["四个适用性事实与 v2_n_9_3 的 immunogenicity_applicable（boolean）编码不一致——建议统一（owner 决定）"],
)
A["applicability:n-3-4-2:non-confirmatory"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="exploratory.endpoint_disposition value_type=json；语义为『处置∈{不开展, 仅支持性}』——提议 members=('disposition',) 两条谓词 mode=any（expected 各取一枚举），schema 待 owner 声明。",
    true_facts=[],
    true_claims=[("exploratory_non_confirmatory", "promote_from_qualified", "source_required_conditional_scope", "src[339] 探索性表述；不开展/仅支持性时必须显式声明不构成确证性结论")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["picos.exploratory_endpoints / exploratory_endpoint_disposition claim 无条件", "forbidden: confirmatory_relabeling（11_4_6 同族）"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[],
    unresolved=["处置枚举值集合未声明（not_conducted/supportive_only/…）——谓词落码前需 owner 声明"],
)
A["applicability:v2_n_4_1:active"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="framing.structured_design 为必填结构化载体（恒存在）——以其为触发等于恒真，规则空洞。src[351]-[353]『如果有中期分析计划，需注明』等逐特征条件 → 提议逐特征显式 boolean（如 features.interim_analysis_applicable）。",
    true_facts=[],
    true_claims=[("design_description", "already_unconditional", "overlap_note", "claim 已无条件 required，规则激活不新增"),
                  ("design_feature_applicability", "already_unconditional", "keep_unconditional", "逐特征适用性声明已是源义务（src[345] 设计类型清单+src[351]-[353] 条件项）")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["structured_design 全载体事实无条件", "forbidden: framing.structured_design.template_example_values"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[("design_description", "remove_from_conditional_keep_unconditional")],
    unresolved=["逐特征 boolean schema 未声明；建议规则要么删除、要么改为特征级谓词（owner 决定）"],
)
A["applicability:v2_n_4_2:active"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="同 v2_n_4_1：载体触发恒真。src[355] 对照类型及选择理由为无条件义务；非劣效界值/安慰剂决策为条件项（F[optional] 已就位）。",
    true_facts=[],
    true_claims=[("design_rationale", "already_unconditional", "overlap_note", ""),
                  ("control_choice_decision", "already_unconditional", "overlap_note", ""),
                  ("noninferiority_margin_decision", "promote_from_qualified", "source_required_conditional_scope", "仅非劣效设计适用")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["comparator_type/comparator_rationale/hypothesis/evidence_floor 无条件"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[("design_rationale", "remove_from_conditional_keep_unconditional"), ("control_choice_decision", "remove_from_conditional_keep_unconditional")],
    unresolved=["非劣效/安慰剂特征 boolean 未声明；规则空洞化处理同 v2_n_4_1"],
)
A["applicability:v2_n_4_3:active"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="picos.intervention_dose_regimen 载体触发；条件『存在多剂量或剂量范围』→ 提议 members=('has_multiple_doses',) expected=true（schema 未声明）。",
    true_facts=[("picos.intervention_dose_regimen.maximum_dose", "promote_from_optional", "source_required", "src[357]『计划最大给药量和给药方案（包括起始剂量）的制定依据』——多剂量/范围时必须明确起始/最大+安全依据")],
    true_claims=[("dose_regimen_rationale", "already_unconditional", "overlap_note", "")],
    true_objects=[], true_evidence=[],
    false_release_facts=["picos.intervention_dose_regimen.maximum_dose"],
    false_retain=["起始剂量/途径/方案/人群链接无条件（src[357]）", "forbidden: picos.intervention_dose_regimen.template_example_values"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[("dose_regimen_rationale", "remove_from_conditional_keep_unconditional")],
    unresolved=["src[357] 未用条件句——最大剂量义务是否应无条件存在存在张力（owner 源核实）"],
)
A["applicability:v2_n_4_4:active"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="picos.study_epochs 载体触发；条件『包含治疗后评估或随访』→ 提议特征 boolean（has_post_treatment_followup）。",
    true_facts=[],
    true_claims=[("study_follow_up_definition", "already_unconditional", "overlap_note", ""),
                  ("overall_study_end_definition", "already_unconditional", "overlap_note", "")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["src[359] 研究结束定义无条件；完成/随访窗口细节按设计（src[361]『完成研究的所有阶段，包括末次访视或SoA所列最后一个计划程序』）"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[("study_follow_up_definition", "remove_from_conditional_keep_unconditional"), ("overall_study_end_definition", "remove_from_conditional_keep_unconditional")],
    unresolved=["规则空洞；完成/结束定义无条件与条件触发的张力需 owner 收口"],
)
A["applicability:v2_n_4_5:active"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="载体触发恒真。src[364]『本小节应对随机化和设盲程序进行描述（若研究设计适用）』——显式条件；开放标签项目不该被要求 masking_procedure。",
    true_facts=[],
    true_claims=[("allocation_procedure", "already_unconditional", "inherited_overrequirement", "非随机化设计不应要求——建议条件化（randomized 特征 boolean）"),
                  ("masking_procedure", "already_unconditional", "inherited_overrequirement", "开放标签设计不应要求——建议条件化（masking 特征 boolean）")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["盲法不适用时须解释（src[369]『若盲法被认为可取但不可行，则应讨论其原因和含义』→ 处置式义务）"],
    false_negative_disp=[("（适用性声明）", "src[369] 支持显式『不设盲/不可行』讨论作为 false 分支内容")],
    ov_facts=[], ov_claims=[("allocation_procedure", "promote_to_conditional_drop_unconditional"), ("masking_procedure", "promote_to_conditional_drop_unconditional")],
    unresolved=["randomization/masking 特征 boolean 未声明；unblinding 族事实随 masking 特征联动（owner 决定）"],
)
A["applicability:v2_n_5_1:active"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="picos.inclusion_modules 载体触发恒真；『all-applicable-criteria』即 src[381]/[384]『必须满足所有入选标准』——模块 logic 结构值，非适用性开关。",
    true_facts=[],
    true_claims=[("inclusion_predicate", "already_unconditional", "remove_from_conditional_keep_unconditional", "claim 已无条件 required——规则冗余")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["criteria/parameters/windows/exceptions/registry_identity 无条件"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[("inclusion_predicate", "remove_from_conditional_keep_unconditional")],
    unresolved=["规则当前空洞：建议删除或改为模块 logic 字段一致性核对（owner 决定）"],
)
A["applicability:v2_n_5_2:active"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="picos.exclusion_modules 载体触发恒真；『any-applicable-criterion』即 src[399]『符合以下任一标准…均将排除』——logic 结构值。",
    true_facts=[],
    true_claims=[("exclusion_predicate", "already_unconditional", "remove_from_conditional_keep_unconditional", "claim 已无条件 required——规则冗余")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["criteria/parameters/windows/exceptions/registry_identity 无条件", "src[395] 特殊人群排除须给理由（无条件义务）"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[("exclusion_predicate", "remove_from_conditional_keep_unconditional")],
    unresolved=["同 v2_n_5_1：建议删除或改为 logic 一致性核对"],
)
A["applicability:n-5-2:contraception-exclusion-reference"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="picos.risk.pregnancy_contraception value_type=json；提议显式 boolean/members（('applicable',)）。",
    true_facts=[("population.exclusion.contraception_criterion_ref", "required_when_active", "proposed_new_defect", "缺陷：该事实未在 v2_n_5_2 fact_requirements 声明（fact_bindings 仅指向规则自身）——true 时无处承载；须在合同声明（json 引用纳入载体标准身份，不复制逆命题、不设通用期限）")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["population.exclusion.contraception_criterion_ref"],
    false_retain=["exclusion_modules logic/criteria 无条件（不含避孕项即自然 omission）"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[],
    unresolved=["缺陷 D2：声明缺口须 owner 修复（合同增列该事实）后规则才可执行"],
)
A["applicability:v2_n_5_3:active"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="picos.risk.pregnancy_contraception json；同上提议。",
    true_facts=[],
    true_claims=[("lifestyle_restriction", "already_unconditional", "remove_from_conditional_keep_unconditional", "claim 已无条件 required（生活方式限制本身无条件：src[409]）"),
                  ("contraception_handling", "promote_from_qualified", "source_required_conditional_scope", "妊娠/避孕风险适用时才要求避孕处置")],
    true_objects=[], true_evidence=[],
    false_release_facts=["population.lifestyle.contraception_duration"],
    false_retain=["population.lifestyle.constraints/scope/timing/exceptions 无条件（src[409]）", "forbidden: population.lifestyle.template_example_values"],
    false_negative_disp=None,
    ov_facts=[],
    ov_claims=[("lifestyle_restriction", "remove_from_conditional_keep_unconditional")],
    unresolved=["population.lifestyle.contraception_duration 当前无条件 required——src[391]/[392]『对于有生育能力的女性/男性…』为条件措辞，建议 promote_to_conditional（未列入14项事实交集，但属同类过要求，owner 决定）"],
)
A["applicability:v2_n_5_4:active"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="population.screen_failure.definition 载体触发；条件『允许重新筛选时』→ 提议 members=('rescreening_allowed',)（schema 未声明）。",
    true_facts=[],
    true_claims=[("screen_failure_record", "already_unconditional", "keep_unconditional_as_negative_disposition_record", "src[411]『指明如何处理筛选失败，包括…复筛后是可接受的，何时可接受』——即使不允许复筛也要显式说明（处置式取值）"),
                  ("rescreening_eligibility", "already_unconditional", "keep_unconditional_as_negative_disposition_record", "同上；『不允许复筛』为合法显式负值，不属虚构")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["population.rescreening.* 无条件但取值可为显式否定（确实不适用≠材料缺失）", "forbidden: population.screen_failure.template_example_values"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[("screen_failure_record", "keep_unconditional_as_negative_disposition_record"), ("rescreening_eligibility", "keep_unconditional_as_negative_disposition_record")],
    unresolved=["规则空洞（载体恒真）+ 取值语义依赖处置式负值编码——owner 需确认事实 schema 允许显式负值"],
)
A["applicability:v2_n_5_5:active"] = dict(
    pred_status="unresolved_non_scalar_condition",
    pred_note="条件『当补偿或伦理审查适用时』与触发事实 picos.population_summary（载体）不符；真实开关 population.recruitment.compensation_applicable 已存在（F[optional]）→ 提议加入 triggering_fact_paths 并以 typed boolean 作谓词。",
    true_facts=[],
    true_claims=[("recruitment_plan", "already_unconditional", "remove_from_conditional_keep_unconditional", "src[416] 招募方式+材料EC批准为无条件义务"),
                  ("retention_plan", "already_unconditional", "remove_from_conditional_keep_unconditional", "src[418] 保留措施/补偿记录为无条件义务")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["population.recruitment.ethics_review_plan 无条件（src[416]/[418]）", "forbidden: completed_approval_receipt / fabricated_approval（条件文本『不得生成完成审批收据』）"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[("recruitment_plan", "remove_from_conditional_keep_unconditional"), ("retention_plan", "remove_from_conditional_keep_unconditional")],
    unresolved=["compensation_applicable 编码未声明（json）；触发路径增量需合同修订"],
)
A["applicability:n-6-1-2:dose-modification"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="intervention.dose_modification_required value_type=json；提议显式 boolean。",
    true_facts=[(p, "already_unconditional", "source_required_conditional_scope", "src[430]『如果适用，方案中应规定在何种情况下需要做出剂量调整』——设计含调整路径时才成为义务") for p in (
        "intervention.dose_hold_criteria", "intervention.dose_reduction_rules", "intervention.restart_criteria", "intervention.permanent_discontinuation_criteria")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["intervention.dose_hold_criteria", "intervention.dose_reduction_rules", "intervention.restart_criteria", "intervention.permanent_discontinuation_criteria"],
    false_retain=["intervention.dose_regimen / administration_instructions / missed_dose_instructions 无条件", "forbidden: intervention.template_example_hold_threshold"],
    false_negative_disp=[("intervention.dose_modification_disposition", "提议：false 时显式『固定剂量、无调整路径』处置（确实不适用≠材料缺失）")],
    ov_facts=[(p, "promote_to_conditional_drop_unconditional") for p in (
        "intervention.dose_hold_criteria", "intervention.dose_reduction_rules", "intervention.restart_criteria", "intervention.permanent_discontinuation_criteria")],
    ov_claims=[],
    unresolved=["四个事实当前无条件 required——对无调整路径设计属过要求；owner 需在『promote 条件化』与『处置式负值』间选择（本提案推荐前者+处置事实）"],
)
A["applicability:n-6-1-2:escalation"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="自触发规则：触发事实=intervention.dose_escalation_or_dlt_logic（study facts 适用性声明）与 required 事实（content facts 逻辑本体）同名异层。json 编码未声明。",
    true_facts=[("intervention.dose_escalation_or_dlt_logic", "already_unconditional", "inherited_overrequirement", "src[430]『如果适用，需描述剂量递增方案…方案必须明确规定预期的剂量限制性毒性』——条件语境；无递增/DLT 设计不应要求")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["intervention.dose_escalation_or_dlt_logic"],
    false_retain=["dose_consistency_with_design 无条件"],
    false_negative_disp=None,
    ov_facts=[("intervention.dose_escalation_or_dlt_logic", "promote_to_conditional_drop_unconditional")],
    ov_claims=[],
    unresolved=["自触发双层语义（声明 vs 内容）需 owner 在事实命名上区分（如 *_applicable 声明 + 逻辑本体事实）"],
)
A["applicability:n-6-2-2:label-text"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="intervention.regulatory_labeling_check value_type=json；rationale『为真时触发』暗示布尔意图（fresh-D3 已修复引用漂移）→ 提议显式 boolean。",
    true_facts=[("intervention.label_text", "promote_from_optional", "source_required_conditional_scope", "src[441]-[461] 标签必须包含内容清单——需核查时须登记实际标签文本")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["intervention.label_text"],
    false_retain=["intervention.packaging_and_labeling 无条件", "claim packaging_labeling_description / regulatory_labeling_review 无条件", "forbidden: intervention.template_example_label_text"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:n-6-4-2:background"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="intervention.background_therapy_applicable value_type=json；提议显式 boolean。",
    true_facts=[("intervention.background_therapy_rules", "already_unconditional", "source_required_conditional_scope", "src[479]『如适用，请在本节说明相关内容，否则注明不适用』")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["intervention.allowed_treatments / allowed_timing 无条件", "forbidden: intervention.template_example_concomitant_drug"],
    false_negative_disp=[("intervention.background_therapy_disposition", "提议：false 时显式『无必须背景治疗』处置（src[479]『否则注明不适用』）")],
    ov_facts=[("intervention.background_therapy_rules", "promote_to_conditional_drop_unconditional")],
    ov_claims=[],
    unresolved=["两种可行处置：promote 条件化（推荐）或保留无条件处置式负值——owner 决定"],
)
A["applicability:n-7-2:randomization"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="procedure.randomized_on_day1 value_type=json；提议显式 boolean。",
    true_facts=[("procedure.randomization_day_rules", "already_unconditional", "source_required_conditional_scope", "src[489] 示例『合格试验参与者于D1随机并接受首次给药』——随机化日规则仅随机化设计适用")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["procedure.randomization_day_rules"],
    false_retain=["procedure.treatment_period_definition / dosing_start_rules / blinded_treatment_handling 无条件", "forbidden: procedure.template_example_visit_schedule"],
    false_negative_disp=None,
    ov_facts=[("procedure.randomization_day_rules", "promote_to_conditional_drop_unconditional")],
    ov_claims=[],
    unresolved=["非随机化设计不得虚构随机化日规则（rationale）——条件化后由 applicability 事实承载否定"],
)
A["applicability:n-7-3:unscheduled-contact"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="procedure.followup_unscheduled_and_phone_visits value_type=json；提议显式 boolean。",
    true_facts=[("procedure.contact_visit_date", "promote_from_absent", "source_required", "src[492]『应记录访视日期、方式、内容及原因』"),
                 ("procedure.contact_visit_modality", "promote_from_absent", "source_required", "src[492] 方式"),
                 ("procedure.contact_visit_reason", "promote_from_absent", "source_required", "src[492] 原因"),
                 ("procedure.contact_visit_assessments", "promote_from_absent", "source_required", "src[492] 内容（含安全性信息按第10章记录）")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["procedure.contact_visit_date", "procedure.contact_visit_modality", "procedure.contact_visit_reason", "procedure.contact_visit_assessments"],
    false_retain=["procedure.followup_period_definition / followup_visit_windows 无条件"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[],
    unresolved=["procedure.phone_visit_linkage 无条件 required——无电话访视设计属潜在过要求（src[492] 条件句『如发生计划外访视（含电话随访）』；owner 决定）"],
)
A["applicability:n-8-1:individual-hold"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="discontinuation.individual_hold_applicable value_type=json；提议显式 boolean 并升为 required（设计必须记录是否存在个体暂停路径）。",
    true_facts=[("discontinuation.individual_hold_criteria", "already_unconditional", "contract_derived_pending_owner_source_review", "src[500]-[511] 个体『中止』概念存在（[511] 研究干预中止不意味着研究中止），但『暂时暂停路径』细则为合同派生；适用时必须完整"),
                 ("discontinuation.personal_hold", "already_unconditional", "contract_derived_pending_owner_source_review", "同上")],
    true_claims=[("individual_cessation_rules", "already_unconditional", "keep_unconditional", "")],
    true_objects=[], true_evidence=[],
    false_release_facts=["discontinuation.individual_hold_criteria", "discontinuation.personal_hold"],
    false_retain=["discontinuation.permanent_stop_criteria.participant / permanent_stop_recording 无条件（任何试验都可能有参试者永久停药）", "trial_suspension/termination 族无条件", "forbidden: discontinuation.template_example_stop_rule", "claim individual_cessation_rules / trial_level_stop_criteria；forbidden individual_equals_trial_stop"],
    false_negative_disp=[("（applicability 事实）", "individual_hold_applicable 升为 required 并记录 false——『确实无暂停路径』显式化，与『适用但材料缺失』分开")],
    ov_facts=[("discontinuation.individual_hold_criteria", "promote_to_conditional_drop_unconditional"), ("discontinuation.personal_hold", "promote_to_conditional_drop_unconditional")],
    ov_claims=[],
    unresolved=["暂停 vs 永久停药语义边界：src[500] 停药原因是研究级列举；个体级暂停细则源支持薄弱（source_thin 标记，owner 源核实）"],
)
A["applicability:n-8-1:hold-to-stop"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="discontinuation.individual_hold_requires_permanent_stop value_type=json；提议显式 boolean。",
    true_facts=[("discontinuation.permanent_stop_criteria.participant", "already_unconditional", "source_required", "src[500]/[511]——永久停药标准对任何试验均适用，规则内要求属重复"),
                 ("discontinuation.permanent_stop_recording", "already_unconditional", "source_required", "同上")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["permanent_stop 两事实保持无条件（不受本规则 false 影响）"],
    false_negative_disp=None,
    ov_facts=[("discontinuation.permanent_stop_criteria.participant", "remove_from_conditional_keep_unconditional"), ("discontinuation.permanent_stop_recording", "remove_from_conditional_keep_unconditional")],
    ov_claims=[],
    unresolved=["规则在移除重复后剩余值为『暂停→永久停药转换链』——若需保留建议专用事实 discontinuation.hold_to_stop_conversion（owner 决定是否新增）"],
)
A["applicability:n-9-2:central-lab"] = dict(
    pred_status="unresolved_json_encoding_proposed_member",
    pred_note="safety.central_lab_applicable value_type=json；提议显式 boolean。缺陷：该触发事实未在 v2_n_9_2 fact_requirements 声明——无人有义务记录中央实验室适用性判定（fact_bindings 仅指向规则）。",
    true_facts=[("safety.lab_units_and_reference_ranges", "already_unconditional", "source_required", "src[574] 单位/参考范围对本地与中央实验室同样必需——规则内要求属重复，应保留无条件"),
                 ("safety.special_assay_purposes", "already_unconditional", "source_required", "src[575] 特殊化验目的无条件；规则内要求属重复"),
                 ("（新增）safety.central_lab_qualification", "proposed_new", "source_required", "src[574]『如采用中心实验室，应说明其资质与承担的检测项目』"),
                 ("（新增）safety.assay_site_assignment", "proposed_new", "source_required", "src[574]『如果使用多个实验室，请指定每个实验室评估的项目』——中央/本地检测项目分配"),
                 ("（新增）safety.ecg_reading_location", "proposed_new", "source_required", "src[572] ECG 中心分析→收集/传输/归档；本地阅读→处理方法与格式——中央 vs 本地须显式二选一记录")],
    true_claims=[("safety_assessment_plan", "already_unconditional", "keep_unconditional", "")],
    true_objects=[], true_evidence=[],
    false_release_facts=[],
    false_retain=["lab_units_and_reference_ranges / special_assay_purposes / specimen_types_and_handling 无条件——『无中央实验室』不释放本地实验室义务（src[574] 实验室资质+室间质评）"],
    false_negative_disp=[("safety.lab_strategy", "提议：中央 vs 本地是必须显式记录的实验室策略（central|local|mixed）；false 时记录本地/混合策略及本地 ECG 阅读方法（src[572]）")],
    ov_facts=[("safety.lab_units_and_reference_ranges", "remove_from_conditional_keep_unconditional"), ("safety.special_assay_purposes", "remove_from_conditional_keep_unconditional")],
    ov_claims=[],
    unresolved=[
        "缺陷 D1：触发事实声明缺口须 owner 修复（合同增列 safety.central_lab_applicable 为 required 适用性判定）",
        "中央实验室专属义务目前缺位——规则现在的 required 列表是错配（通用事实），应替换为上述新增事实",
    ],
)
A["applicability:n-9-3:immunogenicity"] = dict(
    pred_status="executable_boolean_declared",
    pred_note="rationale『裸 true/false』+ value_type=boolean。",
    true_facts=[("exploratory.immunogenicity", "promote_from_optional", "source_required_conditional_scope", "src[584]『如果适用，请将该内容写在本节』+ src[339] 免疫原性（如适用）")],
    true_claims=[("immunogenicity_strategy", "promote_from_qualified", "source_required_conditional_scope", "检测策略适用时 required")],
    true_objects=[], true_evidence=[],
    false_release_facts=["exploratory.immunogenicity"],
    false_retain=["exploratory.population_pk / exposure_response / pk.* 无条件（见相邻发现）", "forbidden: pk.template_example_sampling"],
    false_negative_disp=[("（适用性事实本身）", "false 时按 src[584]『否则注明不适用』显式记录")],
    ov_facts=[], ov_claims=[],
    unresolved=["相邻（不在49条内）：v2_n_9_3 无条件 required exploratory.population_pk/exposure_response vs src[584]『如果适用…否则注明不适用』——疑 inherited overrequirement（owner 决定）"],
)
A["applicability:n-9-4:irc"] = dict(
    pred_status="executable_boolean_declared",
    pred_note="rationale『IRC 是否设立必须由项目事实条件判定（裸 true/false）』+ value_type=boolean。",
    true_facts=[("irc.review_scope_endpoints", "promote_from_optional", "source_required", "src[588]/[589] IRC 对主要疗效终点独立评估、RECIST1.1 评估流程"),
                 ("irc.adjudication_method_and_instrument", "promote_from_optional", "source_required", "src[589] 评估标准与数据流转（光盘存档/发送独立评估）"),
                 ("irc.charter_and_independence", "promote_from_optional", "contract_derived_pending_owner_source_review", "章程与独立性为合同派生良好实践（src[588]『独立评审委员会』）"),
                 ("irc.roles_and_conflict_management", "promote_from_optional", "contract_derived_pending_owner_source_review", "同上")],
    true_claims=[("irc_applicability_decision", "already_unconditional", "keep_unconditional", "")],
    true_objects=[], true_evidence=[],
    false_release_facts=["irc.charter_and_independence", "irc.review_scope_endpoints", "irc.adjudication_method_and_instrument", "irc.roles_and_conflict_management"],
    false_retain=["irc.applicable（记录 false）+ claim irc_applicability_decision", "forbidden: irc.template_example_adjudication / irc_equals_safety_committee / recist_universal_method"],
    false_negative_disp=[("（处置声明）", "src[587]『如不适用，删除本节，或对其他第三方独立评估进行描述』——保留本节时须描述替代性第三方独立评估（提议 conditional claim alternative_independent_assessment）")],
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:front-1:amendment"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="document_control.amendment_exists value_type=json；提议显式 boolean。",
    true_facts=[("document_control.change_rationale", "promote_from_optional", "source_required", "src[45]『包括修订内容描述及依据』——存在修订时依据逐行给出")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["document_control.change_rationale"],
    false_retain=["document_control.version_history / version_date / initial_version_treatment 无条件（初版本处置已覆盖）", "O[table] 保留（初版本行）", "forbidden: fabricated_approval"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:front-3:additional-signatory"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="signature.additional_signatory_applicable value_type=json；提议显式 boolean。",
    true_facts=[("signature.additional_signatory_identity", "promote_from_optional", "source_required", "src[77]『以下签字页如有需要可进行添加』——附加签署方身份")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["signature.additional_signatory_identity"],
    false_retain=["signature.sponsor.protocol_identity / representative 无条件", "forbidden: signature.completed_receipt；claim 级 forbidden synthetic_signature"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:front-4:service-parties"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="contact.service_parties_applicable value_type=json；提议显式 boolean（含中央实验室/IWRS 等服务方判定）。",
    true_facts=[("contact.service_parties", "promote_from_optional", "source_required", "src[87]『如适用，示例#1』+ src[92] 参与临床试验单位及相关部门——实际使用服务方时列出联系方式")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["contact.service_parties"],
    false_retain=["contact.sponsor_representative / principal_investigator 无条件（src[88]/[90]）", "O[table] 保留（申办者/研究者行）", "forbidden: contact.competitor_directory"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)
A["applicability:front-8:figures-present"] = dict(
    pred_status="unresolved_requires_owner_schema",
    pred_note="figure_index.has_figures value_type=json；rationale『由正文题注清单决定』→ 提议由题注清单派生的显式 boolean 或计数成员谓词（schema 未声明）。",
    true_facts=[("figure_index.caption_inventory", "promote_from_optional", "source_required", "存在图时必须给出实际图题注清单")],
    true_claims=[], true_objects=[], true_evidence=[],
    false_release_facts=["figure_index.caption_inventory"],
    false_retain=["forbidden: figure_index.stale_figure_refs（无条件）", "claim figure_index_record"],
    false_negative_disp=None,
    ov_facts=[], ov_claims=[], unresolved=[],
)

# ---------------------------------------------------------------------------
def main() -> None:
    matrix = json.loads(BASE.read_text())
    bindings = json.loads(BINDINGS.read_text())
    tree = json.loads(NODES.read_text())
    bt = {b["fact_path"]: b for b in bindings["bindings"]}
    nodes = {n["id"]: n for n in tree["outlined_tree"]["nodes"]}

    rows_out = []
    status_counts = {}
    for i, r in enumerate(matrix["rows"]):
        rule = r["rule"]
        rid = rule["conditional_applicability_rule_id"]
        adj = A[rid]
        nid = r["node_id"]
        node = nodes.get(nid, {})
        trig = []
        for p in rule["triggering_fact_paths"]:
            b = bt.get(p, {})
            trig.append({
                "fact_path": p,
                "fact_bindings_value_type": b.get("value_type"),
                "declared_bare_boolean": b.get("value_type") == "boolean",
            })
        # predicate proposal
        if adj["pred_status"] == "executable_boolean_declared":
            predicates = [{"fact_path": rule["triggering_fact_paths"][0], "members": [], "expected": True, "mode": "all"}]
        elif adj["pred_status"] == "unresolved_json_encoding_proposed_member":
            predicates = [{"fact_path": rule["triggering_fact_paths"][0], "members": ["applicable"], "expected": True, "mode": "all"}]
        else:
            predicates = []
        contract_sha = hashlib.sha256(Path(r["source"]).read_bytes()).hexdigest()

        def fr_items(items):
            out = []
            for it in items:
                if len(it) == 4:
                    out.append({"fact_path": it[0], "encoding": it[1], "origin": it[2], "note": it[3]})
                else:
                    out.append({"claim_or_object": it[0], "encoding": it[1], "origin": it[2], "note": it[3]})
            return out

        row = {
            "row_index": i,
            "node_id": nid,
            "node_title": node.get("title_zh"),
            "rule_id": rid,
            "rule_locator": r["rule_locator"],
            "contract_path": r["source"],
            "contract_sha256": contract_sha,
            "condition": rule.get("condition"),
            "rule_rationale": rule.get("rationale"),
            "trigger_analysis": trig,
            "predicate_proposal": {
                "status": adj["pred_status"],
                "note": adj["pred_note"],
                "predicates": predicates,
                "trigger_path_delta": [],
                "binding_requirement": "声明须以 RulePredicate.source_rule_sha256 == rule.material_sha256() 绑定现行规则（registries/applicability.py）；谓词 fact_path 必须⊆triggering_fact_paths，否则 conditional_predicate_trigger_mismatch",
            },
            "obligations": {
                "true": {
                    "facts": fr_items(adj["true_facts"]),
                    "claims": fr_items(adj["true_claims"]),
                    "objects": fr_items(adj["true_objects"]),
                    "evidence": [{"source_roles_or_note": it[0], "note": it[1]} for it in adj["true_evidence"]],
                },
                "false": {
                    "release_facts": adj["false_release_facts"],
                    "release_claims": adj.get("false_release_claims", []),
                    "release_objects": adj.get("false_release_objects", []),
                    "retain": adj["false_retain"],
                    "require_negative_disposition": [
                        {"proposed": p, "note": n} for p, n in (adj["false_negative_disp"] or [])
                    ],
                },
                "unknown": {
                    "behavior": "retain_dependency_do_not_treat_as_false_no_template_autofill",
                    "checker_semantics": "ApplicabilityStatus.CONDITIONAL → finding conditional_applicability_unresolved（现有 registries/applicability.py 行为，符合计划『unknown 等待事实』）",
                },
            },
            "overlap_disposition": {
                "in_14_fact_overlaps": bool(r.get("unconditional_required_overlap")),
                "reported_fact_overlap": r.get("unconditional_required_overlap", []),
                "fact_items": [
                    {"fact_path": p, "proposed_action": act} for p, act in adj["ov_facts"]
                ],
                "claim_items": [
                    {"claim_type": p, "proposed_action": act} for p, act in adj["ov_claims"]
                ],
            },
            "unresolved": adj["unresolved"],
        }
        status_counts[adj["pred_status"]] = status_counts.get(adj["pred_status"], 0) + 1
        rows_out.append(row)

    out = {
        "schema_version": "mw_protocol_v3_condition_proposal_v1",
        "created": "2026-09-13",
        "author": "worker_01 (zcode/GLM-5.3-Flash), bounded execution for mw_protocol_v3_3r4b_condition_matrix_20260913",
        "status": "worker_proposal_pending_codex_adjudication",
        "not_an_accepted_medical_conclusion": True,
        "inputs": {
            "plan": "plans/mw_protocol_v3_implementation_plan_v3_20260912.md#3R.4B",
            "base_matrix": "runs/mw_protocol_v3_3r4b_20260912/applicability_obligation_matrix.json (status=source_inventory_only_not_executable)",
            "contracts": "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/*.json",
            "fact_bindings": "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/fact_bindings.json",
            "node_tree": "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json",
            "source_docx": "TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx sha256=018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756 (readonly, stdlib zip/XML)",
            "registry": "services/api/app/protocol_workflow/registries/applicability.py (readonly context)",
        },
        "encoding_summary": {
            "rules_total": len(rows_out),
            "predicate_status_counts": status_counts,
            "declared_bare_boolean_triggers": sorted({
                t["fact_path"] for row in rows_out for t in row["trigger_analysis"] if t["declared_bare_boolean"]
            }),
            "json_typed_trigger_count": sum(
                1 for row in rows_out for t in row["trigger_analysis"] if t["fact_bindings_value_type"] == "json"
            ),
            "key_constraint": "FactPredicate 对 value_type=json 的事实做严格同型比较：expected=true 永远 CONDITIONAL，永不 APPLICABLE/NOT_APPLICABLE——36 个 json 触发路径在 owner 声明编码前不可落码",
        },
        "release_semantics_note": "false 分支的 release 属合同修订（promote/drop 义务），不是运行期对无条件义务的减法；registries/applicability.py evaluate_applicable_content 明确『释放遗留无条件要求须源裁定合同修订』。unknown 分支由现有 conditional_applicability_unresolved finding 承载。",
        "rows": rows_out,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("rows:", len(rows_out))
    print("statuses:", json.dumps(status_counts, ensure_ascii=False))
    print("overlaps flagged:", sum(1 for x in rows_out if x["overlap_disposition"]["in_14_fact_overlaps"]))
    print("wrote:", OUT)


if __name__ == "__main__":
    main()
