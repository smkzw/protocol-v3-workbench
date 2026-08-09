from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable


CORPUS_FUNCTIONS = {
    "synopsis",
    "company_style",
    "scientific_design",
    "reusable_clause",
    "table_soa",
}

CORPUS_PATTERN_KINDS = {
    "wording_convention",
    "clinical_design_requirement",
    "regulatory_common_structure",
}

_GENERALIZATION_LAYER_AXES = (
    "indication",
    "phase",
    "research_purpose",
    "mechanism",
    "technology_type",
    "dosage_form",
    "administration_route",
    "design_module",
)

_GENERALIZATION_LAYER_ALIASES: dict[str, tuple[str, ...]] = {
    "indication": ("indication", "indications", "condition", "conditions"),
    "phase": ("phase", "phases"),
    "research_purpose": ("research_purpose", "research_purposes"),
    "mechanism": ("mechanism", "mechanisms"),
    "technology_type": (
        "technology_type",
        "technology_types",
        "modality",
        "modalities",
    ),
    "dosage_form": ("dosage_form", "dosage_forms"),
    "administration_route": (
        "administration_route",
        "administration_routes",
        "route",
        "routes",
    ),
    "design_module": (
        "design_module",
        "design_modules",
        "design",
        "design_terms",
    ),
}

_PHASE_PART_BINDING_ALIASES = (
    "phase_part",
    "phase_stage",
    "part_phase",
    "stage_phase",
)
_PHASE_PART_BINDING_PREFIX = "__phase_part__:"


@dataclass(frozen=True)
class CorpusSourcePolicy:
    governance_status: str
    indication_terms: tuple[str, ...] = ()
    phase_terms: tuple[str, ...] = ()
    research_purpose_terms: tuple[str, ...] = ()
    modality_terms: tuple[str, ...] = ()
    mechanism_terms: tuple[str, ...] = ()
    route_terms: tuple[str, ...] = ()
    dosage_form_terms: tuple[str, ...] = ()
    design_terms: tuple[str, ...] = ()
    sponsor_name: str = ""
    authority_by_function: dict[str, float] = field(default_factory=dict)
    superseded: bool = False

    def authority(self, corpus_function: str) -> float:
        return self.authority_by_function.get(corpus_function, 0.4)


@dataclass(frozen=True)
class CorpusSupportAssessment:
    support_level: str
    source_count: int
    sponsor_count: int
    high_confidence_eligible: bool
    conflicting_values: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    pattern_kind: str = "unclassified"
    generalization_scope: str = "legacy_untyped"
    medical_confirmation_required: bool = False
    evidence_profiles: tuple[dict[str, Any], ...] = ()
    counterexamples: tuple[dict[str, Any], ...] = ()


CORPUS_GENERALIZATION_PROMPT_RULES: tuple[str, ...] = (
    "每条模式必须先归类为 wording_convention（表达措辞惯例）、clinical_design_requirement（临床设计要求）或 regulatory_common_structure（监管共性/章节结构）；三类不得混合汇总或互相替代。",
    "适应症特异的 wording_convention 必须逐条保留来源文件/来源ID、申办方、分期、研究目的、作用机制、技术类型、剂型、给药途径和设计模块标签；未知维度必须显式留空，不得推测补齐。",
    "同适应症来源不得一刀切视为可迁移；必须继续按研究分期、研究目的、作用机制/技术类型、剂型、给药途径和设计模块分层。",
    "跨适应症来源仅可用于章节结构和监管共性条款，不得迁移表达措辞惯例、临床设计要求、疾病活动度、疾病特异量表或阈值、终点、背景治疗、洗脱期、安全性风险、访视或时间窗逻辑。",
    "同适应症但分期、研究目的、机制、技术类型、剂型、途径或设计不一致时，只能作为低层级参考，不得逐字复用其项目事实。",
    "每条候选须保留来源、申办方、匹配维度、未匹配维度、反例和冲突；不得用多数表决或单一高权重来源掩盖差异。",
    "单一来源或单一申办方不得形成高置信结论；高置信支持至少需要两个独立来源且来自两个申办方，并且关键含义无冲突。",
    "小适应症或罕见病证据不足时，只能输出低置信候选或待医学确认，并列出缺失证据；不得为空白补写设计事实或表达规则。",
    "低证据结果的 unresolved_gaps 必须明确列出缺失的独立来源、申办方和分层证据；绑定证据不足时不得使用“多份方案”“均采用”“常用”“通常”或“普遍采用”等扩大证据范围的措辞。",
    "证据使用顺序为：同适应症且关键设计维度匹配优先；同疾病领域或相近研究设计仅作结构参照、备选假设和反例；其他适应症仅作监管共性和章节结构参照。",
    "输出必须明确区分结构模板、监管固定语、适应症特异措辞和项目事实参照；不得把单个项目事实包装成监管固定语或适应症常用措辞。",
    "不得从单个项目、单份方案或单一申办方归纳“常用”“通常”“普遍采用”等表达规律。",
    "骨架、corpus override、无证据预填或单一来源均不得作为高置信PASS。",
)


_SOURCE_POLICIES: dict[str, CorpusSourcePolicy] = {
    "CMS-D017-PNH-方案摘要_v0.2.docx": CorpusSourcePolicy(
        governance_status="user_designated_primary_with_version_warning",
        indication_terms=("阵发性睡眠性血红蛋白尿症", "PNH"),
        phase_terms=("II", "Ⅱ", "2期"),
        authority_by_function={
            "synopsis": 1.0,
            "company_style": 1.0,
            "table_soa": 1.0,
            "scientific_design": 0.45,
            "reusable_clause": 0.55,
        },
    ),
    "CMS-D005-减重II期临床试验方案概要-V0.3-KZYY0525-clean-DIP0526-KZYY0526 (2).docx": CorpusSourcePolicy(
        governance_status="clean_secondary_synopsis",
        indication_terms=("减重", "肥胖", "超重", "obesity"),
        phase_terms=("II", "Ⅱ", "2期"),
        authority_by_function={
            "synopsis": 0.92,
            "company_style": 0.92,
            "table_soa": 0.92,
            "scientific_design": 0.72,
            "reusable_clause": 0.68,
        },
    ),
    "CMS-D005-减重II期临床试验方案概要-V0.3-XY0525.docx": CorpusSourcePolicy(
        governance_status="superseded_synopsis",
        indication_terms=("减重", "肥胖", "超重", "obesity"),
        phase_terms=("II", "Ⅱ", "2期"),
        authority_by_function={
            "synopsis": 0.35,
            "company_style": 0.35,
            "table_soa": 0.3,
            "scientific_design": 0.3,
            "reusable_clause": 0.3,
        },
        superseded=True,
    ),
    "CMS-D017Ⅰ期方案-v1.1-20260209-clean.docx": CorpusSourcePolicy(
        governance_status="clean_full_protocol",
        indication_terms=("健康参与者", "健康受试者", "healthy participant", "healthy volunteer"),
        phase_terms=("I", "Ⅰ", "1期"),
        authority_by_function={
            "synopsis": 0.7,
            "company_style": 0.88,
            "table_soa": 0.86,
            "scientific_design": 0.78,
            "reusable_clause": 0.98,
        },
    ),
    "MG-K10-青少年AD-3期方案V1.0-20251105-clean.docx": CorpusSourcePolicy(
        governance_status="clean_full_protocol",
        indication_terms=("特应性皮炎", "AD", "atopic dermatitis"),
        phase_terms=("III", "Ⅲ", "3期"),
        authority_by_function={
            "synopsis": 0.74,
            "company_style": 0.82,
            "table_soa": 0.88,
            "scientific_design": 0.92,
            "reusable_clause": 0.9,
        },
    ),
    "CMD-D001-AD II期临床方案-V1.0-tracked-20251212(1).docx": CorpusSourcePolicy(
        governance_status="tracked_full_protocol_reference_only",
        indication_terms=("特应性皮炎", "AD", "atopic dermatitis"),
        phase_terms=("II", "Ⅱ", "2期"),
        authority_by_function={
            "synopsis": 0.58,
            "company_style": 0.58,
            "table_soa": 0.68,
            "scientific_design": 0.82,
            "reusable_clause": 0.62,
        },
    ),
    "1-3-4-1-2临床试验方案-V1.1→V1.2-clean(1).docx": CorpusSourcePolicy(
        governance_status="clean_full_protocol",
        indication_terms=("慢性自发性荨麻疹", "CSU", "chronic spontaneous urticaria"),
        phase_terms=("III", "Ⅲ", "3期"),
        authority_by_function={
            "synopsis": 0.72,
            "company_style": 0.82,
            "table_soa": 0.88,
            "scientific_design": 0.92,
            "reusable_clause": 0.9,
        },
    ),
    "MY004-RA-2b 研究方案摘要_V0.3-with Comments to ABBV.docx": CorpusSourcePolicy(
        governance_status="with_comments_reference_only",
        indication_terms=("类风湿关节炎", "RA", "rheumatoid arthritis"),
        phase_terms=("IIb", "2b"),
        authority_by_function={
            "synopsis": 0.82,
            "company_style": 0.7,
            "table_soa": 0.94,
            "scientific_design": 0.98,
            "reusable_clause": 0.52,
        },
    ),
    "MY004567片-炎症性皮肤病-方案摘要-V0.4-clean.docx": CorpusSourcePolicy(
        governance_status="clean_cross_project_synopsis_with_version_warning",
        indication_terms=("特应性皮炎", "慢性自发性荨麻疹", "结节性痒疹", "AD", "CSU", "PN"),
        authority_by_function={
            "synopsis": 0.82,
            "company_style": 0.76,
            "table_soa": 0.94,
            "scientific_design": 0.95,
            "reusable_clause": 0.55,
        },
    ),
}


_DOMAIN_PATTERNS: dict[str, str] = {
    "front_matter": r"首页|封面|签字页|保密声明|方案编号|版本日期|申办者",
    "synopsis": r"方案概要|方案摘要|研究概要|研究目的和终点|目的与估计目标|目的与终点",
    "study_schema": r"研究流程图|研究设计图|试验流程图|研究示意图",
    "soa": r"研究流程表|Schedule of Activities|SoA|研究阶段|试验阶段|研究周数|研究日|访视|附注",
    "rationale": r"研究依据|研究背景|获益风险|设计依据|设计理由",
    "eligibility": r"入选标准|排除标准|入排标准|筛选失败|再次筛选|受试者人群",
    "reproductive": r"妊娠|哺乳|避孕|育龄|生育|hCG|FSH",
    "dose_modification": r"剂量调整|剂量暂停|暂停给药|减量|重新给药|永久停药|给药中断",
    "intervention": r"试验药物|研究药物|试验干预|给药方案|给药剂量|药物管理|用法用量",
    "non_investigational": r"非试验用药|非研究性干预|背景治疗|救援治疗",
    "concomitant": r"合并用药|合并治疗|禁用药|限制用药|既往治疗|洗脱期",
    "disposition": r"EOT|EOS|治疗结束|研究结束|提前终止|退出研究|失访|停止治疗",
    "assessments": r"疗效评估|安全性评估|实验室检查|心电图|生命体征|体格检查|量表|问卷",
    "safety": r"不良事件|严重不良事件|AE|SAE|AESI|妊娠报告|过量|产品投诉",
    "statistics": r"统计分析|样本量|分析集|估计目标|estimand|多重性|缺失数据|敏感性分析",
    "ethics_governance": r"伦理|知情同意|GCP|隐私|保密|数据管理|质量管理|稽查|监查|发表政策",
    "laboratory": r"临床实验室|实验室检查|血常规|尿常规|生化|凝血|肝功能|肾功能",
    "references": r"参考文献|文献目录|bibliograph",
    "publication_policy": r"发表政策|研究发表|数据发布|出版物|作者资格|学术会议.{0,20}(?:发表|展示)",
    "quality_management": r"质量管理|质量保证|质量控制|风险管理|监查计划|稽查计划",
    "data_management": r"数据管理|EDC|eCRF|数据库锁定|数据冻结|数据更正|数据质疑|数据录入",
    "drug_accountability": r"试验药物管理|研究药物管理|药品管理|接收.{0,30}储存|发放.{0,30}回收|回收.{0,30}销毁",
    "eligibility_clause": r"入选标准|排除标准|纳入标准|符合.{0,30}(?:入选|纳入)标准|不得(?:入选|纳入)|筛选失败",
    "dose_modification_rule": r"剂量调整|给药调整|给药中断|暂停给药|恢复给药|减量|永久停药",
    "estimand_definition": r"估计目标|estimand|伴发事件策略|群体层面汇总",
    "rescreening_policy": r"再次筛选|重新筛选|重复筛选",
    "informed_consent": r"知情同意|法定代理人|监护人|同意书|assent",
    "ae_definition_clause": r"不良事件.{0,12}(?:定义|是指)|(?:定义|记录).{0,20}不良事件|治疗期出现的不良事件",
    "sae_reporting_clause": r"严重不良事件.{0,30}(?:记录|报告)|(?:记录|报告).{0,30}严重不良事件|SAE.{0,20}(?:记录|报告)",
    "pregnancy_reporting_clause": r"妊娠.{0,30}(?:报告|随访|结局)|(?:报告|随访).{0,20}妊娠",
    "overdose_management": r"药物过量|过量用药",
    "concomitant_rule": r"合并用药|合并治疗|禁用药|限制用药|洗脱",
    "randomization_blinding_rule": r"随机化|随机分配|盲法|设盲|揭盲|盲底",
    "analysis_set_definition": r"全分析集|符合方案集|安全性分析集|FAS|PPS|SS",
    "study_end_definition": r"研究结束|治疗结束|EOS|EOT",
    "adolescent_assent": r"青少年|未成年人|监护人|法定代理人|儿童知情同意",
    "dosing_instruction": r"服药剂量|服药频率|给药剂量|给药频率|用法用量|剂量及频率",
    "infection_screening_rule": r"HCV|丙型肝炎|HBV|乙型肝炎|HIV|活动性感染",
    "sae_seriousness_criteria": r"导致死亡|危及生命|住院|残疾|先天性异常|出生缺陷|重要医学事件",
    "contraception_complete_clause": r"避孕.{0,20}(?:方法|措施|要求|持续时间)|育龄.{0,20}(?:避孕|方法)",
    "ae_mh_boundary_clause": r"首次给药前|首次用药前|给药后.{0,20}(?:不良事件|AE)|病史.{0,20}(?:不良事件|AE)",
    "ae_general_definition": r"不良事件.{0,20}(?:是指|指)|AE.{0,20}(?:是指|指)|不一定.{0,20}因果关系",
    "consent_before_procedure_clause": r"签署.{0,20}知情同意.{0,20}(?:不得|不可|之前)|(?:不得|不可).{0,30}试验相关程序",
}


_SECTION_DOMAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1.1", ("synopsis",)),
    ("1.2", ("study_schema", "study_design")),
    ("1.3", ("soa",)),
    ("2", ("rationale",)),
    ("3.1", ("estimand_definition", "statistics")),
    ("3", ("synopsis", "statistics")),
    ("4.2", ("randomization_blinding_rule", "study_design")),
    ("4", ("study_design", "rationale")),
    ("5.4", ("reproductive",)),
    ("5.3", ("rescreening_policy", "eligibility")),
    ("5.1", ("eligibility_clause", "eligibility")),
    ("5.2", ("eligibility_clause", "eligibility")),
    ("5", ("eligibility",)),
    ("6.4", ("dose_modification_rule", "dose_modification")),
    ("6.6", ("drug_accountability", "intervention")),
    ("6.9", ("non_investigational",)),
    ("6.10", ("concomitant_rule", "concomitant")),
    ("6", ("intervention",)),
    ("7.1", ("dose_modification", "disposition")),
    ("7.3", ("study_end_definition", "disposition")),
    ("7", ("disposition",)),
    ("8", ("assessments", "laboratory")),
    ("9", ("safety",)),
    ("10.2", ("analysis_set_definition", "statistics")),
    ("10", ("statistics",)),
    ("11.2", ("informed_consent", "ethics_governance")),
    ("11.6", ("data_management", "ethics_governance")),
    ("11.7", ("quality_management", "ethics_governance")),
    ("11.9", ("publication_policy", "ethics_governance")),
    ("11", ("ethics_governance",)),
    ("12.1", ("laboratory",)),
    ("14", ("references",)),
)


HARD_TARGET_DOMAINS = {
    "publication_policy",
    "quality_management",
    "data_management",
    "drug_accountability",
    "eligibility_clause",
    "dose_modification_rule",
    "estimand_definition",
    "rescreening_policy",
    "informed_consent",
    "ae_definition_clause",
    "sae_reporting_clause",
    "pregnancy_reporting_clause",
    "overdose_management",
    "concomitant_rule",
    "randomization_blinding_rule",
    "analysis_set_definition",
    "study_end_definition",
    "adolescent_assent",
    "dosing_instruction",
    "infection_screening_rule",
    "sae_seriousness_criteria",
    "scale_eligibility_criterion",
    "contraception_complete_clause",
    "ae_mh_boundary_clause",
    "ae_general_definition",
    "consent_before_procedure_clause",
    "drug_accountability_lifecycle",
}

SPECIFIC_HARD_TARGET_DOMAINS = {
    "concomitant_rule",
    "randomization_blinding_rule",
    "analysis_set_definition",
    "study_end_definition",
    "adolescent_assent",
    "dosing_instruction",
    "infection_screening_rule",
    "sae_seriousness_criteria",
    "scale_eligibility_criterion",
    "contraception_complete_clause",
    "ae_mh_boundary_clause",
    "ae_general_definition",
    "consent_before_procedure_clause",
    "drug_accountability_lifecycle",
    "estimand_definition",
    "rescreening_policy",
    "quality_management",
    "data_management",
    "drug_accountability",
    "dose_modification_rule",
}


_PROJECT_FACT_PATTERNS: dict[str, str] = {
    "investigational_product": r"\b(?:CMS|CMD|MY|MG|RUX)[-–—]?[A-Z0-9]+\b|试验药物|研究药物",
    "dose_or_concentration": r"\b\d+(?:\.\d+)?\s*(?:mg|g|μg|ug|mg/kg|mg/mL|%)\b",
    "visit_or_timepoint": r"\b(?:D|W|V)\s*-?\d+\b|第\s*\d+\s*(?:天|周|月)|\d+\s*(?:天|周|月)",
    "threshold": r"[<>≤≥＝=]\s*\d|\d+(?:\.\d+)?\s*(?:倍|分|mmHg|U/L|IU/L)",
    "sample_size": r"样本量.{0,30}\d+|入组.{0,20}\d+\s*例",
    "endpoint_or_scale": r"主要终点|次要终点|探索性终点|EASI|IGA|UAS7|ACR20|DAS28|FACIT|LDH",
}


_CROSS_INDICATION_NON_TRANSFERABLE_PATTERNS: dict[str, str] = {
    "disease_activity_or_threshold": (
        r"EASI|IGA|UAS7|ISS7|HSS7|ACR20|ACR50|ACR70|DAS28|SLEDAI|PASI|"
        r"疾病活动度|严重程度.{0,20}(?:评分|分级)|基线.{0,30}(?:≥|≤|>|<|\d+\s*分)"
    ),
    "endpoint": r"主要终点|关键次要终点|次要终点|探索性终点|疗效终点|终点评估",
    "background_treatment": r"背景治疗|基础治疗|标准治疗.{0,20}(?:继续|维持)|稳定剂量",
    "washout": r"洗脱期|停药至少|停用.{0,30}(?:天|周|月)|末次使用.{0,30}(?:天|周|月)",
    "safety_risk": r"AESI|特别关注的不良事件|特殊关注不良事件|重要潜在风险|已识别风险|已知风险",
    "visit_logic": (
        r"访视窗|时间窗|第\s*\d+\s*(?:天|周|月)|\b(?:D|W|V)\s*-?\d+\b|"
        r"每\s*\d+\s*(?:天|周|月).{0,30}(?:评估|检查|访视)"
    ),
}

_CROSS_INDICATION_COMMON_PATTERNS: tuple[str, ...] = (
    r"知情同意|GCP|伦理委员会|受试者隐私|保密",
    r"数据管理|EDC|eCRF|数据库锁定|质量管理|质量保证|质量控制",
    r"发表政策|研究发表|作者资格",
    r"不良事件.{0,20}(?:是指|定义)|严重不良事件.{0,30}(?:记录|报告)",
    r"试验药物.{0,30}(?:接收|储存|发放|回收|销毁)",
)

_FACET_CONCEPT_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "research_purpose": {
        "fih": ("fih", "first-in-human", "首次人体"),
        "first_in_patient": ("first-in-patient", "首次患者"),
        "poc": ("poc", "proof-of-concept", "概念验证"),
        "pom": ("pom", "proof-of-mechanism", "机制验证"),
        "dose_exploration": ("剂量探索", "剂量递增", "dose escalation"),
        "confirmatory": ("确证性", "验证性", "confirmatory"),
        "ole": ("长期延展", "开放标签延展", "open-label extension", "ole"),
        "food_effect": ("食物影响", "food effect"),
        "mass_balance": ("物质平衡", "mass balance"),
        "hepatic_impairment": ("肝损伤", "hepatic impairment"),
        "renal_impairment": ("肾损伤", "renal impairment"),
    },
    "modality": {
        "antibody": ("单克隆抗体", "单抗", "monoclonal antibody"),
        "adc": ("adc", "antibody-drug conjugate", "antibody drug conjugate", "抗体偶联药物"),
        "small_molecule": ("小分子", "small molecule"),
        "sirna": ("sirna", "small interfering rna", "小干扰rna"),
        "mrna": ("mrna", "messenger rna"),
        "oligonucleotide": ("寡核苷酸", "oligonucleotide", "antisense oligonucleotide", "aso"),
        "cell_therapy": ("细胞治疗", "cell therapy", "car-t", "car t"),
        "gene_therapy": ("基因治疗", "gene therapy"),
    },
    "route": {
        "oral": ("口服", "oral"),
        "subcutaneous": ("皮下注射", "皮下给药", "皮下", "subcutaneous", "sc"),
        "intravenous": ("静脉注射", "静脉给药", "静脉", "静脉滴注", "intravenous", "iv"),
        "intramuscular": ("肌内注射", "肌肉注射", "肌内", "intramuscular", "im"),
        "injection_generic": ("注射", "injection", "注射液"),
        "topical": ("外用", "局部涂抹", "乳膏", "软膏", "topical"),
        "intranasal": ("鼻喷", "鼻内", "intranasal", "nasal spray"),
        "inhaled": ("吸入", "inhaled", "inhalation"),
        "ocular": ("滴眼", "眼用", "ophthalmic", "ocular"),
    },
    "dosage_form": {
        "tablet": ("片剂", "tablet", "分散片"),
        "capsule": ("胶囊", "capsule"),
        "injection": ("注射液", "预充式注射器", "injection"),
        "cream": ("乳膏", "cream"),
        "ointment": ("软膏", "ointment"),
        "spray": ("喷雾", "鼻喷", "spray"),
        "inhalation": ("吸入制剂", "吸入粉雾剂", "inhalation"),
    },
    "phase1_part": {
        "sad": ("sad", "单次给药剂量递增"),
        "mad": ("mad", "多次给药剂量递增"),
        "food_effect": ("食物影响", "food effect"),
        "mass_balance": ("物质平衡", "mass balance"),
        "first_in_patient": ("首次患者", "first-in-patient"),
        "hepatic_impairment": ("肝损伤", "hepatic impairment"),
        "renal_impairment": ("肾损伤", "renal impairment"),
    },
    "control": {
        "placebo": ("安慰剂", "placebo"),
        "active": ("阳性对照", "active comparator"),
        "uncontrolled": ("无对照", "uncontrolled"),
    },
    "allocation": {
        "parallel": ("平行", "parallel"),
        "crossover": ("交叉", "crossover"),
        "sequential": ("序贯", "sequential"),
    },
}

# Short ASCII aliases that require word-boundary-aware matching to avoid
# cross-activation (e.g. "RNA" must not prove siRNA; "IV" must not prove
# intravenous unless it appears as a standalone token).
_SHORT_TOKEN_AXES: dict[str, frozenset[str]] = {
    "modality": frozenset({
        "adc", "aso", "sirna", "mrna", "rna", "mab",
    }),
    "route": frozenset({
        "sc", "iv", "im",
    }),
}


def corpus_generalization_prompt_contract() -> list[str]:
    return list(CORPUS_GENERALIZATION_PROMPT_RULES)


def _compact_term(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def _normalized_context(*values: str) -> str:
    return re.sub(r"\s+", " ", " ".join(value for value in values if value)).casefold()


def _term_matches_context(term: str, context: str) -> bool:
    normalized_term = re.sub(r"\s+", "", term).casefold()
    compact_context = re.sub(r"\s+", "", context).casefold()
    if not normalized_term:
        return False
    if len(normalized_term) <= 3 and normalized_term.isascii():
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])",
                context.casefold(),
            )
        )
    return normalized_term in compact_context


def _policy_indication_match(policy: CorpusSourcePolicy, indication: str) -> bool | None:
    if not policy.indication_terms or not indication.strip():
        return None
    return any(_term_matches_context(term, indication) for term in policy.indication_terms)


def cross_indication_transfer_scope(text: str) -> tuple[str, tuple[str, ...]]:
    blocked = tuple(
        name
        for name, pattern in _CROSS_INDICATION_NON_TRANSFERABLE_PATTERNS.items()
        if re.search(pattern, text, re.I)
    )
    if blocked:
        return "non_transferable_clinical_logic", blocked
    if any(re.search(pattern, text, re.I) for pattern in _CROSS_INDICATION_COMMON_PATTERNS):
        return "structure_or_regulatory_common_only", ()
    return "reference_only_unclassified", ()


def _facet_concepts(axis: str, value: str) -> set[str]:
    normalized = _normalized_context(value)
    if not normalized:
        return set()
    if axis == "randomization":
        if re.search(r"非随机|non[- ]?random", normalized):
            return {"nonrandomized"}
        if re.search(r"随机|randomi[sz]", normalized):
            return {"randomized"}
        return set()
    if axis == "blinding":
        if re.search(r"开放标签|开放性|open[- ]?label", normalized):
            return {"open_label"}
        if re.search(r"双盲|double[- ]?blind", normalized):
            return {"double_blind"}
        if re.search(r"单盲|single[- ]?blind", normalized):
            return {"single_blind"}
        return set()
    if axis == "background_treatment":
        if re.search(r"无背景治疗|不要求背景治疗|without background", normalized):
            return {"absent"}
        if re.search(r"背景治疗|基础治疗|background treatment", normalized):
            return {"present"}
        return set()
    concepts: set[str] = set()
    short_tokens = _SHORT_TOKEN_AXES.get(axis, frozenset())
    for concept, aliases in _FACET_CONCEPT_GROUPS.get(axis, {}).items():
        for alias in aliases:
            alias_cf = alias.casefold()
            if alias_cf in short_tokens:
                # Token-aware: match only as a standalone word to avoid
                # cross-activation (e.g. "iv" inside "olive" or "delivery").
                if re.search(
                    rf"(?<![a-z0-9]){re.escape(alias_cf)}(?![a-z0-9])",
                    normalized,
                ):
                    concepts.add(concept)
                    break
            elif alias_cf in normalized:
                concepts.add(concept)
                break
    # When a specific injection route is detected, drop the generic
    # injection_generic marker so that SC/IV/IM remain distinct.
    specific_routes = {"subcutaneous", "intravenous", "intramuscular"}
    if axis == "route" and (concepts & specific_routes):
        concepts.discard("injection_generic")
    return concepts


def _layer_values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    raw_values = value if isinstance(value, (list, tuple, set)) else (value,)
    normalized: list[str] = []
    for item in raw_values:
        cleaned = re.sub(r"\s+", " ", str(item or "").strip())
        if cleaned and cleaned.casefold() not in {
            candidate.casefold() for candidate in normalized
        }:
            normalized.append(cleaned)
    return tuple(normalized)


def _record_layer(record: dict[str, Any]) -> tuple[dict[str, tuple[str, ...]], set[str]]:
    layer: dict[str, tuple[str, ...]] = {}
    declared_axes: set[str] = set()
    nested = record.get("layer")
    nested_layer = nested if isinstance(nested, dict) else {}
    for axis, aliases in _GENERALIZATION_LAYER_ALIASES.items():
        value: Any = None
        found = False
        for alias in aliases:
            if alias in record:
                value = record.get(alias)
                found = True
                break
            if alias in nested_layer:
                value = nested_layer.get(alias)
                found = True
                break
        if found:
            declared_axes.add(axis)
        layer_values = _layer_values(value)
        if axis == "phase":
            phase_binding: Any = None
            for alias in _PHASE_PART_BINDING_ALIASES:
                if alias in record:
                    phase_binding = record.get(alias)
                    break
                if alias in nested_layer:
                    phase_binding = nested_layer.get(alias)
                    break
            bound_values = _layer_values(phase_binding)
            if bound_values:
                layer_values = (
                    *layer_values,
                    *(
                        f"{_PHASE_PART_BINDING_PREFIX}{bound_value}"
                        for bound_value in bound_values
                    ),
                )
        layer[axis] = layer_values
    return layer, declared_axes


def _evidence_profile(
    record: dict[str, Any],
    *,
    value_key: str,
    pattern_kind: str,
) -> dict[str, Any]:
    layer, declared_axes = _record_layer(record)
    source_file = str(record.get("source_file") or "").strip()
    source_id = str(record.get("source_id") or source_file).strip()
    sponsor = str(
        record.get("lead_sponsor")
        or record.get("sponsor")
        or record.get("source_sponsor")
        or ""
    ).strip()
    return {
        "source_id": source_id,
        "source_file": source_file,
        "document_sha256": str(record.get("document_sha256") or "").strip(),
        "sponsor": sponsor,
        "pattern_kind": pattern_kind,
        "claim_value": re.sub(
            r"\s+", " ", str(record.get(value_key) or "").strip()
        ),
        "layer": layer,
        "declared_axes": tuple(
            axis for axis in _GENERALIZATION_LAYER_AXES if axis in declared_axes
        ),
    }


def _layer_mismatches(
    profile_layer: dict[str, tuple[str, ...]],
    target_layer: dict[str, tuple[str, ...]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    mismatches: list[str] = []
    missing: list[str] = []
    for axis, target_values in target_layer.items():
        if not target_values:
            continue
        source_values = profile_layer.get(axis, ())
        if not source_values:
            missing.append(axis)
            continue
        if axis == "indication" and any(
            _compact_term(source_value) == _compact_term(target_value)
            for source_value in source_values
            for target_value in target_values
        ):
            continue
        source_normalized = _layer_match_tokens(axis, source_values)
        target_normalized = _layer_match_tokens(axis, target_values)
        if source_normalized.isdisjoint(target_normalized):
            mismatches.append(axis)
    return tuple(mismatches), tuple(missing)


def _layer_match_tokens(axis: str, values: tuple[str, ...]) -> set[str]:
    normalized = {_normalized_context(value) for value in values if value}
    if axis == "phase":
        canonical = _phase_match_tokens(values)
        return canonical or normalized
    concept_axis = {
        "research_purpose": "research_purpose",
        "technology_type": "modality",
        "dosage_form": "dosage_form",
        "administration_route": "route",
    }.get(axis)
    if concept_axis:
        concepts = set().union(
            *(_facet_concepts(concept_axis, value) for value in values)
        )
        return concepts or normalized
    if axis == "design_module":
        concepts = set().union(
            *(
                _facet_concepts(design_axis, " ".join(values))
                for design_axis in (
                    "randomization",
                    "blinding",
                    "control",
                    "allocation",
                )
            )
        )
        return concepts or normalized
    return normalized


def assess_corpus_support(
    records: Iterable[dict[str, Any]],
    *,
    value_key: str = "claim_value",
    pattern_kind: str = "",
    target_layer: dict[str, Any] | None = None,
) -> CorpusSupportAssessment:
    material = [dict(record) for record in records]
    record_kinds = {
        str(record.get("pattern_kind") or "").strip()
        for record in material
        if str(record.get("pattern_kind") or "").strip()
    }
    requested_kind = pattern_kind.strip()
    if requested_kind and requested_kind not in CORPUS_PATTERN_KINDS:
        raise ValueError(f"unsupported corpus pattern kind: {requested_kind}")
    invalid_kinds = record_kinds - CORPUS_PATTERN_KINDS
    if invalid_kinds:
        raise ValueError(
            "unsupported corpus pattern kind(s): "
            + ", ".join(sorted(invalid_kinds))
        )
    effective_kind = requested_kind
    if not effective_kind and len(record_kinds) == 1:
        effective_kind = next(iter(record_kinds))
    mixed_kinds = len(record_kinds) > 1 or (
        effective_kind
        and record_kinds
        and any(kind != effective_kind for kind in record_kinds)
    )
    if not effective_kind:
        effective_kind = "unclassified"

    normalized_target, target_declared_axes = _record_layer(target_layer or {})
    profiles = tuple(
        _evidence_profile(
            record,
            value_key=value_key,
            pattern_kind=str(record.get("pattern_kind") or effective_kind),
        )
        for record in material
    )
    eligible_profiles: list[dict[str, Any]] = []
    counterexamples: list[dict[str, Any]] = []
    layer_missing_axes: set[str] = set()
    cross_indication_clinical_logic = False
    for profile in profiles:
        comparison_target = normalized_target
        if effective_kind == "regulatory_common_structure":
            # Regulatory common structure (GCP, ethics, data management)
            # is independent of ALL design axes, not just indication.
            # The content-level cross_indication_transfer_scope check
            # below already guards against clinical logic transfer.
            comparison_target = {}
        mismatches, missing = _layer_mismatches(
            profile["layer"], comparison_target
        )
        layer_missing_axes.update(missing)
        if mismatches:
            counterexamples.append(
                {
                    **profile,
                    "reason": "layer_mismatch:" + ",".join(mismatches),
                }
            )
            continue
        if (
            effective_kind == "regulatory_common_structure"
            and profile["claim_value"]
        ):
            transfer_scope, blocked = cross_indication_transfer_scope(
                profile["claim_value"]
            )
            indications = profile["layer"].get("indication", ())
            target_indications = normalized_target.get("indication", ())
            cross_indication = bool(
                indications
                and target_indications
                and {
                    _normalized_context(value) for value in indications
                }.isdisjoint(
                    {_normalized_context(value) for value in target_indications}
                )
            )
            if transfer_scope == "non_transferable_clinical_logic" or (
                cross_indication
                and transfer_scope != "structure_or_regulatory_common_only"
            ):
                cross_indication_clinical_logic = True
                counterexamples.append(
                    {
                        **profile,
                        "reason": "regulatory_common_structure_contains_clinical_logic:"
                        + ",".join(blocked or ("unclassified",)),
                    }
                )
                continue
        eligible_profiles.append(profile)

    sources = {
        profile["document_sha256"] or profile["source_id"]
        for profile in eligible_profiles
        if profile["document_sha256"] or profile["source_id"]
    }
    sponsors = {
        profile["sponsor"]
        for profile in eligible_profiles
        if profile["sponsor"]
    }
    values = {
        profile["claim_value"].casefold()
        for profile in eligible_profiles
        if profile["claim_value"]
    }
    conflicts = tuple(sorted(values)) if len(values) > 1 else ()
    reasons: list[str] = []
    if mixed_kinds:
        reasons.append("mixed_pattern_types_require_separation")
    if len(sources) < 2:
        reasons.append("fewer_than_two_independent_sources")
    if len(sponsors) < 2:
        reasons.append("fewer_than_two_sponsors")
    if conflicts:
        reasons.append("conflicting_claim_values_preserved")
    if counterexamples:
        reasons.append("counterexamples_preserved")
    if layer_missing_axes:
        reasons.append(
            "target_layer_metadata_missing:" + ",".join(
                axis
                for axis in _GENERALIZATION_LAYER_AXES
                if axis in layer_missing_axes
            )
        )
    if cross_indication_clinical_logic:
        reasons.append("cross_indication_clinical_logic_not_transferable")
    if effective_kind in {
        "wording_convention",
        "clinical_design_requirement",
    } and not normalized_target.get("indication"):
        reasons.append("same_indication_target_required")
    if effective_kind in {
        "wording_convention",
        "clinical_design_requirement",
    }:
        incomplete_target_axes = [
            axis
            for axis in _GENERALIZATION_LAYER_AXES
            if axis not in target_declared_axes or not normalized_target.get(axis)
        ]
        if incomplete_target_axes:
            reasons.append(
                "target_layer_incomplete:" + ",".join(incomplete_target_axes)
            )
    if effective_kind == "wording_convention":
        for profile in eligible_profiles:
            undeclared = set(_GENERALIZATION_LAYER_AXES) - set(
                profile["declared_axes"]
            )
            if undeclared:
                reasons.append(
                    "wording_provenance_axes_not_declared:"
                    + ",".join(
                        axis
                        for axis in _GENERALIZATION_LAYER_AXES
                        if axis in undeclared
                    )
                )
                break

    typed_gate_passes = not any(
        reason.startswith(
            (
                "mixed_pattern_types",
                "target_layer_metadata_missing",
                "cross_indication_clinical_logic",
                "same_indication_target_required",
                "target_layer_incomplete",
                "wording_provenance_axes_not_declared",
            )
        )
        for reason in reasons
    )
    high_confidence = (
        len(sources) >= 2
        and len(sponsors) >= 2
        and not conflicts
        and not mixed_kinds
        and (
            effective_kind == "unclassified"
            or typed_gate_passes
        )
    )
    if high_confidence:
        level = "multi_source_multi_sponsor_consistent"
    elif mixed_kinds:
        level = "mixed_pattern_types_require_separation"
    elif conflicts:
        level = "conflicting_requires_medical_review"
    elif len(sources) >= 2:
        level = "multi_source_limited_sponsor_support"
    elif sources:
        level = "single_source_low_strength"
    else:
        level = "no_traceable_source"
    if effective_kind == "regulatory_common_structure":
        scope = "cross_indication_structure_or_regulatory_common_only"
    elif effective_kind in {
        "wording_convention",
        "clinical_design_requirement",
    }:
        scope = "same_indication_layered_only"
    else:
        scope = "legacy_untyped"
    return CorpusSupportAssessment(
        support_level=level,
        source_count=len(sources),
        sponsor_count=len(sponsors),
        high_confidence_eligible=high_confidence,
        conflicting_values=conflicts,
        reasons=tuple(reasons),
        pattern_kind=effective_kind,
        generalization_scope=scope,
        medical_confirmation_required=not high_confidence,
        evidence_profiles=profiles,
        counterexamples=tuple(counterexamples),
    )


def source_policy(source_file: str) -> CorpusSourcePolicy:
    return _SOURCE_POLICIES.get(
        source_file,
        CorpusSourcePolicy(
            governance_status="legacy_reference",
            authority_by_function={name: 0.35 for name in CORPUS_FUNCTIONS},
        ),
    )


def infer_corpus_function(
    explicit: str = "",
    *,
    section_number: str = "",
    template_node_id: str = "",
    section_heading: str = "",
    interaction_types: Iterable[str] = (),
) -> str:
    if explicit:
        if explicit not in CORPUS_FUNCTIONS:
            raise ValueError(f"unsupported company corpus function: {explicit}")
        return explicit
    context = f"{section_number} {template_node_id} {section_heading}".casefold()
    if section_number.startswith("1.3") or re.search(r"研究流程表|schedule.of.activities|\bsoa\b", context, re.I):
        return "table_soa"
    if section_number.startswith("1.1") or re.search(r"方案概要|方案摘要|synopsis", context, re.I):
        return "synopsis"
    if re.search(r"封面|首页|签字页|页眉|页脚|目录|front", context, re.I):
        return "company_style"
    if section_number.startswith(("9", "11", "14")):
        return "reusable_clause"
    if "T" in set(interaction_types) and re.search(r"流程|访视|schedule", context, re.I):
        return "table_soa"
    return "scientific_design"


def target_domain_tags(
    *,
    section_number: str = "",
    template_node_id: str = "",
    section_heading: str = "",
) -> set[str]:
    tags: set[str] = set()
    for prefix, domains in _SECTION_DOMAINS:
        if section_number.startswith(prefix):
            tags.update(domains)
            break
    context = f"{template_node_id} {section_heading}"
    for domain, pattern in _DOMAIN_PATTERNS.items():
        if re.search(pattern, context, re.I):
            tags.add(domain)
    if section_number.startswith("5") and re.search(
        r"EASI|IGA|UAS7|ISS7|HSS7|ACR20|DAS28|BMI",
        context,
        re.I,
    ):
        tags.add("scale_eligibility_criterion")
    if len(set(re.findall(
        r"接收|收到|储存|贮存|保存|发放|分发|回收|返还|销毁|统一处理",
        context,
    ))) >= 4:
        tags.add("drug_accountability_lifecycle")
    return tags


def row_domain_tags(row: dict[str, Any]) -> set[str]:
    context = f"{row.get('section', '')} {row.get('text', '')}"
    tags = {
        domain
        for domain, pattern in _DOMAIN_PATTERNS.items()
        if re.search(pattern, context, re.I)
    }
    category_map = {
        "ethics_consent_privacy": "ethics_governance",
        "reproductive_pregnancy_contraception": "reproductive",
        "infection_screening": "eligibility",
        "general_medical_exclusion": "eligibility",
        "prior_concomitant_treatment": "concomitant",
        "study_design_structure": "study_design",
        "visit_eos_eot_withdrawal": "disposition",
        "soa_procedure_framework": "soa",
        "safety_reporting": "safety",
        "endpoint_objective_stats": "statistics",
        "eligibility_disease_specific": "eligibility",
    }
    tags.update(
        category_map[category]
        for category in row.get("categories") or []
        if category in category_map
    )
    return tags


def row_text_domain_tags(row: dict[str, Any]) -> set[str]:
    text = str(row.get("text") or "")
    tags = {
        domain
        for domain, pattern in _DOMAIN_PATTERNS.items()
        if re.search(pattern, text, re.I)
    }
    if not (
        all(re.search(pattern, text, re.I) for pattern in (
            r"目标人群",
            r"治疗|处理",
            r"变量|终点",
            r"伴发事件",
            r"群体层面汇总|总体效应度量",
        ))
    ):
        tags.discard("estimand_definition")
    if not all(re.search(pattern, text, re.I) for pattern in (
        r"全分析集|FAS|意向性治疗|ITT",
        r"符合方案集|PPS",
        r"安全性分析集|安全性集|SS",
    )):
        tags.discard("analysis_set_definition")
    if len(re.findall(r"随机化|随机分配|盲法|设盲|揭盲|盲底", text, re.I)) < 2:
        tags.discard("randomization_blinding_rule")
    if not (
        re.search(r"研究结束|EOS", text, re.I)
        and re.search(r"治疗结束|EOT", text, re.I)
    ):
        tags.discard("study_end_definition")
    if not (
        re.search(r"青少年|未成年人", text)
        and re.search(r"监护人|法定代理人", text)
        and re.search(r"知情同意|同意书|ICF", text, re.I)
    ):
        tags.discard("adolescent_assent")
    if not (
        re.search(r"(?:禁止|限制|允许|不得|洗脱|可继续).{0,50}(?:合并用药|合并治疗|药物|治疗)", text)
        or re.search(r"(?:合并用药|合并治疗|禁用药|限制用药).{0,50}(?:禁止|限制|允许|包括|如下|洗脱)", text)
    ):
        tags.discard("concomitant_rule")
    if re.search(r"总结|发生率|例数|百分比", text) and not re.search(r"若|如|应当|应予|可以|不得", text):
        tags.discard("dose_modification_rule")
    if not (
        re.search(r"质量保证|质量控制|质量管理(?!规范)|基于风险.{0,20}质量|监查计划|稽查计划", text)
    ):
        tags.discard("quality_management")
    data_process_terms = re.findall(
        r"EDC|eCRF|数据采集|数据录入|数据核查|数据质疑|数据更正|数据清理|数据库冻结|数据库锁定|数据库修改|数据导出",
        text,
        re.I,
    )
    if len(set(term.casefold() for term in data_process_terms)) < 2:
        tags.discard("data_management")
    if not (
        re.search(
            r"(?:\d+(?:\.\d+)?\s*(?:mg|μg|ug|mg/kg|mg/mL)).{0,100}(?:QD|BID|TID|Q\d+W|每日|每周|每\s*\d+\s*周|给药频率|服药频率)",
            text,
            re.I,
        )
        or re.search(
            r"(?:QD|BID|TID|Q\d+W|每日|每周|每\s*\d+\s*周|给药频率|服药频率).{0,100}(?:\d+(?:\.\d+)?\s*(?:mg|μg|ug|mg/kg|mg/mL))",
            text,
            re.I,
        )
    ):
        tags.discard("dosing_instruction")
    if not (
        re.search(r"HCV|丙型肝炎", text, re.I)
        and re.search(r"抗体", text)
        and re.search(r"RNA|活动性感染", text, re.I)
    ):
        tags.discard("infection_screening_rule")
    if not (
        re.search(r"育龄|生育能力|生育潜能|有潜在生育能力", text)
        and re.search(r"末次.{0,12}给药后\s*\d+\s*个?月|研究期间.{0,30}末次.{0,12}给药", text)
        and len(set(re.findall(
            r"激素避孕|口服避孕|宫内节育|输精管结扎|禁欲|避孕套|注射|植入",
            text,
        ))) >= 2
    ):
        tags.discard("contraception_complete_clause")
    if not (
        re.search(r"首次(?:给药|用药)前|首次试验用药品给药前", text)
        and re.search(r"病史|伴随疾病", text)
        and re.search(r"不良事件|AE", text, re.I)
        and re.search(r"不作为\s*AE|作为病史|记录并报告|AE记录", text, re.I)
    ):
        tags.discard("ae_mh_boundary_clause")
    if not (
        re.search(r"不良事件|Adverse Event|\bAE\b", text, re.I)
        and re.search(r"是指|指", text)
        and re.search(r"不利.{0,10}医学事件|不良医学事件", text)
        and re.search(r"不一定.{0,30}因果关系|无论.{0,30}因果关系", text)
    ):
        tags.discard("ae_general_definition")
    if not (
        re.search(r"签署.{0,20}知情同意|知情同意.{0,20}签署", text)
        and re.search(r"不得|不可", text)
        and re.search(r"试验相关程序|研究相关程序|试验程序|研究程序", text)
    ):
        tags.discard("consent_before_procedure_clause")
    if all(re.search(pattern, text, re.I) for pattern in (
        r"接收|收到",
        r"储存|贮存|保存",
        r"发放|分发",
        r"回收|返还",
        r"销毁|统一处理",
    )):
        tags.add("drug_accountability_lifecycle")
    else:
        tags.discard("drug_accountability_lifecycle")
    if len(set(re.findall(
        r"导致死亡|危及生命|住院|残疾|先天性异常|出生缺陷|重要医学事件",
        text,
    ))) < 2:
        tags.discard("sae_seriousness_criteria")
    if (
        re.search(r"EASI|IGA|UAS7|ISS7|HSS7|ACR20|DAS28|BMI", text, re.I)
        and re.search(r"≥|≤|>|<|不少于|不低于|不超过|\d+\s*分|\d+(?:\.\d+)?\s*kg/m", text, re.I)
        and re.search(r"筛选|入选|纳入|排除|合格", text)
    ):
        tags.add("scale_eligibility_criterion")
    else:
        tags.discard("scale_eligibility_criterion")
    return tags


def project_fact_slots(text: str) -> list[str]:
    return [
        name
        for name, pattern in _PROJECT_FACT_PATTERNS.items()
        if re.search(pattern, text, re.I)
    ]


_PHASE_ORDER = {
    "1": 10,
    "1a": 11,
    "1b": 12,
    "2": 20,
    "2a": 21,
    "2b": 22,
    "3": 30,
    "3a": 31,
    "3b": 32,
}


def _canonical_phase_components(value: str) -> tuple[str, ...]:
    compact = re.sub(r"\s+", "", str(value or "").casefold())
    for token in ("clinicaltrial", "clinical", "trial", "phase", "阶段", "期"):
        compact = compact.replace(token, "")
    compact = (
        compact.replace("ⅰ", "i")
        .replace("ⅱ", "ii")
        .replace("ⅲ", "iii")
    )
    parts = re.split(r"[/+,&、，;；和及至~～-]+", compact)
    canonical: list[str] = []
    for part in parts:
        match = re.fullmatch(r"(iii|ii|i|3|2|1)([ab]?)", part)
        if not match:
            continue
        base = {"i": "1", "ii": "2", "iii": "3"}.get(
            match.group(1),
            match.group(1),
        )
        token = f"{base}{match.group(2)}"
        if token not in canonical:
            canonical.append(token)
    return tuple(sorted(canonical, key=lambda item: _PHASE_ORDER[item]))


def _phase_match_tokens(values: tuple[str, ...]) -> set[str]:
    bound_components: set[str] = set()
    for value in values:
        if str(value).startswith(_PHASE_PART_BINDING_PREFIX):
            bound_components.update(
                _canonical_phase_components(
                    str(value)[len(_PHASE_PART_BINDING_PREFIX) :]
                )
            )
    if bound_components:
        return bound_components

    combined_tokens: set[str] = set()
    single_components: set[str] = set()
    for value in values:
        components = _canonical_phase_components(value)
        if len(components) == 1:
            single_components.add(components[0])
        elif len(components) > 1:
            combined_tokens.add("combined:" + "+".join(components))
    if combined_tokens:
        return combined_tokens
    if len(single_components) > 1:
        return {
            "combined:"
            + "+".join(
                sorted(
                    single_components,
                    key=lambda item: _PHASE_ORDER[item],
                )
            )
        }
    return single_components


def _phase_tokens_explicit_in_text(text: str) -> set[str]:
    normalized = (
        str(text or "")
        .casefold()
        .replace("ⅰ", "i")
        .replace("ⅱ", "ii")
        .replace("ⅲ", "iii")
    )
    tokens: set[str] = set()
    atom = r"(?:iii|ii|i|3|2|1)(?:a|b)?"
    expression = rf"{atom}(?:\s*[/+]\s*{atom})*"
    patterns = (
        rf"(?<![a-z0-9])phase\s*({expression})(?![a-z0-9])",
        rf"(?<![a-z0-9])({expression})\s*期",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            tokens.update(_phase_match_tokens((match.group(1),)))
    return tokens


def _canonical_phase(value: str) -> str:
    tokens = _phase_match_tokens((value,))
    if len(tokens) == 1:
        return next(iter(tokens))
    return ""


def project_match_score(
    policy: CorpusSourcePolicy,
    project_indication: str,
    project_phase: str = "",
) -> tuple[float, str]:
    context = re.sub(r"\s+", "", project_indication).casefold()
    if not policy.indication_terms:
        return 0.6, "source_has_no_indication_scope"
    if not context:
        return 0.5, "project_indication_not_provided"
    matched_term = ""
    for term in policy.indication_terms:
        normalized_term = re.sub(r"\s+", "", term).casefold()
        if len(normalized_term) <= 2 and normalized_term.isascii():
            if re.search(rf"(?<![a-z]){re.escape(normalized_term)}(?![a-z])", project_indication.casefold()):
                matched_term = term
                break
        elif normalized_term in context:
            matched_term = term
            break
    if not matched_term:
        return 0.0, "indication_mismatch"
    target_phases = _phase_match_tokens((project_phase,))
    source_phases = _phase_match_tokens(policy.phase_terms)
    if target_phases and source_phases and target_phases.isdisjoint(source_phases):
        return (
            0.65,
            f"matched_indication:{matched_term};phase_mismatch:"
            + ",".join(sorted(target_phases)),
        )
    if target_phases and source_phases:
        return (
            1.0,
            f"matched_indication:{matched_term};matched_phase:"
            + ",".join(sorted(target_phases)),
        )
    return 1.0, f"matched_indication:{matched_term};phase_not_constrained"


def section_fit_score(target_tags: set[str], candidate_tags: set[str]) -> float:
    if not target_tags:
        return 0.5
    if not candidate_tags:
        return 0.1
    overlap = target_tags & candidate_tags
    if overlap:
        return min(1.0, 0.65 + 0.15 * len(overlap))
    return 0.0


def text_quality(row: dict[str, Any]) -> tuple[float, list[str]]:
    text = str(row.get("text") or "").strip()
    flags: list[str] = []
    if re.search(r"(?:电话|传真|邮箱|E-?mail)\s*[:：]", text, re.I):
        return 0.0, ["contact_detail_not_reusable"]
    if "意见消除的同样" in text:
        return 0.0, ["confirmed_source_text_error"]
    if "USA7" in text:
        return 0.0, ["confirmed_scale_abbreviation_error"]
    if re.search(
        r"伴发事件及处理策略\s*[:：]\s*(?:[（(]?5[）)]?|群体层面汇总|$)",
        text,
    ):
        return 0.0, ["empty_estimand_attribute_not_reusable"]
    if re.search(r"\+\+\s*\d", text):
        return 0.0, ["confirmed_numeric_transcription_error"]
    if re.search(r"(?:待.{0,30}(?:明确|确定|补充|规定)|\bTBD\b|\bTODO\b|\b待定\b)", text, re.I):
        return 0.0, ["unresolved_placeholder_not_reusable"]
    if len(text) < 40 and (text.endswith(("：", ":")) or re.search(r"(?:定义|标准|原则)$", text)):
        return 0.0, ["bare_clause_heading_not_reusable"]
    if len(text) < 80 and re.fullmatch(r"表\s*\d+(?:\.\d+)*[.．、\s].*研究流程表", text):
        return 0.0, ["bare_soa_title_not_reusable"]
    if len(text) < 40 and re.search(r"是否|是、否|有、无|请选择", text):
        return 0.0, ["form_field_not_reusable_clause"]
    if re.fullmatch(r"(?:目\s*录|目录|table of contents)", text, re.I):
        return 0.0, ["navigation_label_not_clause"]
    if row.get("block_type") == "paragraph" and re.match(
        r"^\d+(?:\.\d+){1,5}\s+[^。；：:，,]{1,60}$",
        text,
    ):
        return 0.0, ["bare_numbered_heading_not_clause"]
    if len(text) <= 90 and re.match(
        r"^(?:表\s*)?\d+(?:\.\d+)*(?:[.．、\s]|\s*[:：]).*\s\d+$",
        text,
    ):
        return 0.0, ["navigation_entry_not_clause"]
    score = 1.0
    if len(text) < 24:
        score -= 0.35
        flags.append("short_fragment")
    if len(text) < 80 and not re.search(r"[。；：:，,]", text):
        score -= 0.2
        flags.append("heading_like")
    if re.match(r"^(?:\d+(?:\.\d+){0,4}\s*)?(?:研究目的|研究设计|统计分析|入选标准|排除标准|严重不良事件)$", text):
        score -= 0.35
        flags.append("bare_heading")
    if row.get("block_type") in {"table", "table_row"}:
        flags.append("structured_table_content")
    return max(0.0, score), flags


def governance_quality(policy: CorpusSourcePolicy) -> float:
    if policy.superseded:
        return 0.2
    status = policy.governance_status
    if status.startswith("clean_"):
        return 1.0
    if status.startswith("user_designated"):
        return 0.85
    if "with_comments" in status:
        return 0.55
    if "tracked" in status:
        return 0.45
    return 0.35


def reuse_policy(
    row: dict[str, Any],
    policy: CorpusSourcePolicy,
    *,
    project_match: float,
    fact_slots: list[str],
) -> str:
    if policy.superseded or "tracked" in policy.governance_status or "with_comments" in policy.governance_status:
        return "reference_only"
    if project_match == 0.0:
        transfer_scope, _ = cross_indication_transfer_scope(str(row.get("text") or ""))
        if transfer_scope != "structure_or_regulatory_common_only":
            return "reference_only"
        return "adapt_required"
    if row.get("reuse_level") == "disease_specific_reference" and project_match < 1.0:
        return "reference_only"
    if project_match < 1.0:
        return "adapt_required"
    if fact_slots:
        return "adapt_required"
    if row.get("reuse_level") == "common_candidate":
        return "verbatim_candidate_after_review"
    return "adapt_required"


def quality_flags(text: str) -> list[str]:
    flags: list[str] = []
    if re.search(r"试验参与者|参与者", text) and re.search(r"受试者", text):
        flags.append("mixed_participant_terminology")
    if re.search(r"MedDRA|CTCAE|ICH\s*E6|GCP", text, re.I):
        flags.append("version_sensitive_terminology")
    if re.search(r"首剂前|首次给药前", text) and re.search(r"病史|不良事件|AE", text, re.I):
        flags.append("ae_mh_boundary_requires_pv_review")
    if re.search(r"估计目标|estimand", text, re.I):
        flags.append("estimand_five_attribute_review")
    if re.search(r"FAS|ITT|PPS|EAS|分析集", text, re.I):
        flags.append("analysis_set_definition_requires_statistics_review")
    if re.search(r"(?:NCT\d+|APPOINT|HRS-|竞品).{0,80}\d", text, re.I):
        flags.append("external_numeric_claim_requires_source_binding")
    if re.search(r"\+\+\s*\d", text):
        flags.append("suspected_numeric_transcription_error")
    return flags


# ---------------------------------------------------------------------------
# Plan-driven corpus facets
# ---------------------------------------------------------------------------

# Maps driver_kind → corpus search term equivalents.  When the plan confirms
# a design driver, its value_summary is used as a hard facet to filter or
# boost corpus candidates whose source policy or text matches the same facet.
_PLAN_DRIVER_CORPUS_FACETS: dict[str, tuple[str, ...]] = {
    "drug_modality": ("modality",),
    "drug_route": ("route",),
    "dosage_form": ("dosage_form",),
    "phase": ("phase",),
    "indication": ("indication",),
    "research_purpose": ("research_purpose",),
    "study_purpose": ("research_purpose",),
    "mechanism": ("mechanism",),
    "target_mechanism": ("mechanism",),
    "phase1_part": ("phase1_part", "research_purpose"),
    "randomization": ("randomization",),
    "blinding": ("blinding",),
    "control": ("control",),
    "allocation": ("allocation",),
    "exposure_scope": ("exposure_scope",),
    "interim_analysis": ("interim", "期中分析"),
    "active_comparator": ("active_comparator", "阳性对照"),
    "placebo": ("placebo", "安慰剂"),
    "background_treatment": ("background_treatment", "背景治疗"),
    "pk_pd": ("pk_pd",),
    "aesi": ("aesi",),
}


def plan_corpus_facets(
    design_drivers: list[dict[str, Any]],
) -> dict[str, str]:
    """Extract hard corpus facets from plan design drivers.

    Returns a dict mapping facet name → confirmed value.  Only drivers with
    decision_state in {required, design_driven} and a non-empty value_summary
    contribute facets.  Drivers with decision_state=not_applicable produce
    a facet value of ``"not_applicable"`` so callers can exclude matching
    corpus entries.
    """
    facets: dict[str, str] = {}
    for driver in design_drivers:
        kind = driver.get("driver_kind", "")
        state = driver.get("decision_state", "unknown")
        value = str(driver.get("value_summary", "")).strip()
        if kind not in _PLAN_DRIVER_CORPUS_FACETS:
            continue
        if state == "not_applicable":
            for facet_name in _PLAN_DRIVER_CORPUS_FACETS[kind]:
                facets[facet_name] = "not_applicable"
        elif state in ("required", "design_driven") and value:
            for facet_name in _PLAN_DRIVER_CORPUS_FACETS[kind]:
                facets[facet_name] = value
    return facets


def corpus_text_facet_match(
    text: str,
    source_file: str,
    policy: CorpusSourcePolicy,
    plan_facets: dict[str, str],
) -> tuple[float, list[str]]:
    """Score how well a corpus candidate matches plan-driven facets.

    Returns (score_adjustment, mismatch_reasons).  A negative adjustment
    means the candidate conflicts with a confirmed plan facet and should be
    penalized or excluded.
    """
    if not plan_facets:
        return 0.0, []
    policy_context = _normalized_context(
        text,
        source_file,
        *policy.research_purpose_terms,
        *policy.modality_terms,
        *policy.mechanism_terms,
        *policy.route_terms,
        *policy.dosage_form_terms,
        *policy.design_terms,
    )
    text_lower = text.casefold()
    file_lower = source_file.casefold()
    adjustment = 0.0
    reasons: list[str] = []
    plan_indication = plan_facets.get("indication", "")
    indication_match = _policy_indication_match(policy, plan_indication)
    if indication_match is False:
        transfer_scope, blocked_dimensions = cross_indication_transfer_scope(text)
        if transfer_scope == "non_transferable_clinical_logic":
            adjustment -= 0.45
            reasons.append(
                "cross_indication_non_transferable:"
                + ",".join(blocked_dimensions)
            )
        elif transfer_scope == "structure_or_regulatory_common_only":
            adjustment -= 0.02
            reasons.append("cross_indication_structure_regulatory_only")
        else:
            adjustment -= 0.12
            reasons.append("cross_indication_reference_only")

    target_phases = _phase_match_tokens((plan_facets.get("phase", ""),))
    source_phases = _phase_match_tokens(policy.phase_terms)
    if target_phases and source_phases and target_phases.isdisjoint(source_phases):
        adjustment -= 0.14
        reasons.append(
            "same_or_known_indication_phase_mismatch:"
            + ",".join(sorted(target_phases))
            + ":"
            + ",".join(sorted(source_phases))
        )

    mismatch_weights = {
        "research_purpose": 0.14,
        "modality": 0.16,
        "route": 0.20,
        "dosage_form": 0.14,
        "phase1_part": 0.16,
        "randomization": 0.12,
        "blinding": 0.12,
        "control": 0.14,
        "allocation": 0.12,
        "background_treatment": 0.18,
    }
    for axis, weight in mismatch_weights.items():
        target_concepts = _facet_concepts(axis, plan_facets.get(axis, ""))
        source_concepts = _facet_concepts(axis, policy_context)
        if target_concepts and source_concepts and target_concepts.isdisjoint(source_concepts):
            adjustment -= weight
            reasons.append(
                f"facet_mismatch:{axis}:target={','.join(sorted(target_concepts))};"
                f"source={','.join(sorted(source_concepts))}"
            )

    mechanism = plan_facets.get("mechanism", "").strip()
    if mechanism and policy.mechanism_terms:
        if not any(_term_matches_context(term, mechanism) for term in policy.mechanism_terms):
            adjustment -= 0.14
            reasons.append("facet_mismatch:mechanism")

    # Modality/route: if plan confirms a non-oral route (e.g. nasal, topical,
    # inhaled), penalize corpus entries that only describe oral systemic PK
    # or safety defaults.
    for facet_key in ("modality", "route"):
        plan_value = plan_facets.get(facet_key)
        if not plan_value or plan_value == "not_applicable":
            continue
        plan_lower = plan_value.casefold()
        if any(term in plan_lower for term in ("鼻", "nose", "nasal", "吸入", "inhale", "外用", "topical", "皮肤")):
            if not any(
                term in text_lower or term in file_lower
                for term in ("鼻", "nose", "nasal", "吸入", "inhale", "外用", "topical", "皮肤", "局部")
            ):
                # If the text discusses oral systemic PK/safety defaults,
                # apply a stronger penalty.
                if any(term in text_lower for term in ("口服", "oral", "全身", "systemic")):
                    adjustment -= 0.05
                    reasons.append(f"plan_route={plan_value};text_is_oral_systemic")
                else:
                    adjustment -= 0.03
                    reasons.append(f"plan_route={plan_value};text_route_mismatch")
        else:
            # For oral/systemic, no penalty — the corpus already skews oral.
            pass
    # Interim analysis: if plan marks interim as not_applicable, penalize
    # corpus entries about interim analysis.
    if plan_facets.get("interim") == "not_applicable":
        if re.search(r"期中分析|interim\s*analysis", text_lower):
            adjustment -= 0.20
            reasons.append("plan_interim=not_applicable;text_contains_interim")
    # Active comparator: if plan confirms active comparator, boost entries
    # from sources that mention active comparator.
    plan_comparator = plan_facets.get("active_comparator")
    if plan_comparator and plan_comparator != "not_applicable":
        if re.search(r"阳性对照|active\s*comparator", text_lower):
            adjustment += 0.05
            reasons.append("plan_active_comparator;text_matches")
    return max(-0.85, min(0.20, adjustment)), reasons


def plan_not_applicable_module_filter(
    text: str,
    not_applicable_module_ids: list[str],
) -> bool:
    """Return True if the text should be excluded because it describes a
    module the plan has marked not_applicable.

    This is a hard filter, not a score adjustment.
    """
    if not not_applicable_module_ids:
        return False
    text_lower = text.casefold()
    module_patterns: dict[str, tuple[str, ...]] = {
        "design.interim_analysis": ("期中分析", "interim analysis"),
        "design.adaptive_design": ("适应性设计", "adaptive design"),
        "design.crossover": ("交叉设计", "crossover"),
        "design.open_label_extension": ("开放延展", "open label extension", "ole扩展"),
    }
    for module_id in not_applicable_module_ids:
        patterns = module_patterns.get(module_id)
        if patterns and any(p in text_lower for p in patterns):
            return True
    return False
