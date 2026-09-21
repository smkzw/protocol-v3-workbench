import { cloneElement, isValidElement, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, FileText, PenLine, Plus, RefreshCw, Save, Search, ShieldAlert, Sparkles, Trash2, Upload, XCircle } from "lucide-react";
import { WritingReferencePanel } from "../writing-reference/WritingReferencePanel";
import { InterventionRulesEditor } from "./InterventionRulesEditor";
import { AuthoringCompetitorDrawer } from "./AuthoringCompetitorDrawer";
import { InstrumentAppendixPreview } from "./InstrumentAppendixPreview";
import {
  AuthoringCandidatePackagePanel,
  collectCompositePrefillGroups,
  compositeCandidateBlockedCode,
  isPendingCompositeCandidate,
  packageFieldLabel,
  receiptSummaryMessage,
} from "./AuthoringCandidatePackagePanel";
import "./MedicalWritingAuthoringJourneySetup.css";

// Mirrors services/api/app/medical_writing_research_pipeline.py::TERMINAL_STAGES.
const PIPELINE_TERMINAL_STAGES = new Set(["corpus_ready", "round2_ready", "failed", "cancelled"]);
const PIPELINE_STABLE_WAITING_STAGES = new Set([
  "awaiting_triage_confirm",
  "awaiting_preparation_admission",
  "awaiting_document_validation",
  "awaiting_translation_scope",
  "awaiting_corpus_analysis",
  "awaiting_corpus_admission",
]);
const PIPELINE_STAGE_LABELS = {
  queued: "排队中",
  searching: "检索公开研究",
  triaging: "AI竞品分诊",
  awaiting_triage_confirm: "等待确认分诊",
  preparing: "下载并提取原文",
  awaiting_preparation_admission: "等待下一批原文准入",
  awaiting_document_validation: "等待处理文件核验",
  awaiting_translation_scope: "等待修复翻译范围",
  translating: "翻译关键锚点",
  analyzing_round1: "第一轮深度分析",
  awaiting_corpus_analysis: "等待重试语料分析",
  awaiting_corpus_admission: "等待语料准入",
  corpus_ready: "语料已准备完毕",
  analyzing_round2: "第二轮精细化分析",
  round2_ready: "第二轮分析已完成",
  failed: "研究流水线失败",
  cancelled: "已取消研究流水线",
};
// Keep the formal-stage wording available to the UI contract even when the
// lightweight minimum-intake hint explains that unknown product facts do not
// block the initial registry search.
const COMPLETE_FRAMING_SUBMIT_LABEL = "完整第一步仍需单独提交";
const CORPUS_EXCEPTION_AUDIT_LABEL = "未就绪状态和医学理由会持续保留";

const PURPOSE_OPTIONS = ["首次人体试验（FIH）", "首次患者试验（first-in-patient）", "药理/药效探索", "机制验证（PoM）", "概念验证（PoC）", "剂量探索", "确证性研究", "长期延展性研究（OLE）"];
const PHASE_OPTIONS = ["I期", "I/II期", "II期", "II/III期", "III期"];
const PHASE1_PART_OPTIONS = Object.freeze([
  { code: "SAD", label: "单次递增剂量（SAD）" },
  { code: "MAD", label: "多次递增剂量（MAD）" },
  { code: "食物影响", label: "食物影响" },
  { code: "物质平衡", label: "物质平衡" },
  { code: "肝损伤", label: "肝损伤" },
  { code: "肾损伤", label: "肾损伤" },
  { code: "DDI", label: "药物相互作用（DDI）" },
  { code: "首次患者", label: "首次患者" },
]);
const PHASE1_PART_DETAIL_FIELDS = Object.freeze([
  { key: "population", label: "研究人群", required: true, rows: 3, placeholder: "如健康受试者、目标患者及关键分层条件" },
  { key: "cohort_dose", label: "队列/剂量方案、给药方式与频次", required: true, rows: 4, placeholder: "可逐步补充队列、剂量、给药途径、频次与观察窗" },
  { key: "pk_pd", label: "PK/PD设计", rows: 3, placeholder: "采样窗口、参数、PD指标及探索性分析" },
  { key: "safety", label: "安全监测", rows: 3, placeholder: "安全指标、监测窗口、委员会或复核安排" },
  { key: "stopping_rules", label: "停止/递增规则", rows: 3, placeholder: "停止、暂停、递增或降阶规则；未知处可暂留待补" },
  { key: "soa_summary", label: "SoA/访视相关说明", rows: 3, placeholder: "关键访视、给药、采样及随访安排" },
  { key: "transition_dependencies", label: "转段依赖/序列", rows: 3, placeholder: "与其他Part的先后、并行、数据审阅或放行依赖" },
]);
const PRODUCT_TECHNOLOGY_OPTIONS = Object.freeze([
  { value: "unknown", label: "未知/待定" },
  { value: "monoclonal_antibody", label: "单克隆抗体" },
  { value: "other_biologic", label: "其他生物制品" },
  { value: "small_molecule", label: "小分子" },
  { value: "rna_therapy", label: "RNA疗法" },
  { value: "cell_therapy", label: "细胞治疗" },
  { value: "gene_therapy", label: "基因治疗" },
  { value: "vaccine", label: "疫苗" },
  { value: "other", label: "其他" },
]);
const PRODUCT_ADMINISTRATION_ROUTES = Object.freeze(["口服", "静脉注射", "皮下注射", "外用", "吸入", "其他"]);
const PRODUCT_EXPOSURE_SCOPE_OPTIONS = Object.freeze([
  { value: "unknown", label: "未知/待定" },
  { value: "systemic", label: "全身暴露" },
  { value: "local", label: "局部暴露" },
  { value: "mixed", label: "混合暴露" },
]);
const PRODUCT_DOSAGE_FORM_OPTIONS = Object.freeze([
  { value: "", label: "未知/待定" },
  { value: "注射剂", label: "注射剂" },
  { value: "口服固体制剂", label: "口服固体制剂" },
  { value: "口服液体制剂", label: "口服液体制剂" },
  { value: "外用制剂", label: "外用制剂" },
  { value: "其他", label: "其他（请在产品资料中说明）" },
]);
const POPULATION_AGE_BAND_OPTIONS = Object.freeze(["成人", "儿童", "青少年"]);
const POPULATION_DISEASE_STATE_OPTIONS = Object.freeze(["轻中度", "中重度", "重度"]);
const POPULATION_TREATMENT_STATUS_OPTIONS = Object.freeze(["初治", "经治疗效不佳", "未经某类治疗"]);
const DESIGN_EXPLICIT_DECISION_FIELDS = new Set([
  "design.adaptive_design",
  "design.src_dmc",
  "design.interim_analysis",
]);

function isPhaseOneStudy(studyPhase) {
  const value = String(studyPhase || "").trim();
  if (!value || /first-in-human\s*=\s*false/i.test(value)) return false;
  if (/\b(?:first[\s-]?in[\s-]?human|FIH)\b/i.test(value)) return true;
  const compact = value.toUpperCase()
    .replace(/\s+/g, "")
    .replaceAll("Ⅰ", "I")
    .replaceAll("Ⅱ", "II")
    .replaceAll("Ⅲ", "III")
    .replaceAll("Ⅳ", "IV")
    .replaceAll("／", "/");
  if (/PHASE(?:I|1)(?=$|[/+\-])/.test(compact) || compact.includes("一期")) return true;
  return compact.split(/[/+\-]/).some((token) => ["I", "1"].includes(token.replace("期", "")));
}

function phase1PartsFromFraming(framing) {
  const parts = framing?.structured_design?.phase1_parts;
  return Array.isArray(parts) ? parts.filter((part) => part && typeof part === "object") : [];
}

function phase1PartsReady(framing) {
  if (!isPhaseOneStudy(framing?.study_phase)) return true;
  return phase1PartsFromFraming(framing).every(
    (part) => String(part.population || "").trim() && String(part.cohort_dose || "").trim(),
  );
}

function StudyPhaseInput({ value, onChange, listId }) {
  return <>
    <input
      list={listId}
      value={value || ""}
      onChange={(event) => onChange(event.target.value)}
      placeholder="选择常用分期或直接输入"
    />
    <datalist id={listId}>
      {PHASE_OPTIONS.map((item) => <option key={item} value={item} />)}
    </datalist>
  </>;
}
const FRAMING_GROUPS = [{ key: "identity", label: "项目与产品" }, { key: "purpose", label: "研究目的" }, { key: "competition", label: "竞品范围" }, { key: "design", label: "总体设计" }];
const PICOS_GROUPS = [{ key: "applicability", label: "设计适用性" }, { key: "population", label: "研究人群" }, { key: "intervention", label: "干预措施" }, { key: "comparator", label: "对照" }, { key: "outcomes", label: "结局指标" }, { key: "execution", label: "执行与统计" }];
const DESIGN_ARCHETYPES = [
  { value: "randomized_confirmatory", label: "随机对照确证性研究", detail: "对照和估计目标为必填设计事实。" },
  { value: "randomized_exploratory", label: "随机探索性研究", detail: "适用于随机、开放标签或盲法的剂量/概念探索；对照必填，估计目标可说明后标记不适用。" },
  { value: "single_arm_early_phase", label: "单臂早期探索", detail: "适用于FIH、first-in-patient、PoM或剂量探索。" },
  { value: "open_label_extension", label: "开放标签延展研究", detail: "适用于无同期对照的OLE研究。" },
  { value: "other", label: "其他研究设计", detail: "由医学经理逐项确认适用性并说明依据。" },
];
const DESIGN_ARCHETYPE_LABELS = Object.fromEntries(DESIGN_ARCHETYPES.map((item) => [item.value, item.label]));
const DESIGN_PREFILL_FIELD_LABELS = {
  "design.randomization": "随机化",
  "design.blinding": "盲法",
  "design.comparator_type": "对照类型",
  "design.assignment_model": "分组方式",
  "design.center_model": "中心设置",
  "design.adaptive_design": "适应性设计",
  "design.src_dmc": "SRC/DMC设置",
  "design.interim_analysis": "期中分析",
  "design.phase1_parts": "I期研究模块",
  "design.arms_or_cohorts": "研究臂/队列",
};
const PREFILL_GROUP_FIELDS = {
  "framing:identity": ["framing.protocol_id", "framing.document_title", "framing.clinicaltrials_condition_term"],
  "framing:purpose": ["framing.population_intent"],
  "framing:competition": [],
  "framing:design": ["framing.design_pattern"],
  "picos:applicability": [
    "picos.design_archetype",
    "design.randomization",
    "design.blinding",
    "design.comparator_type",
    "design.assignment_model",
    "design.center_model",
    "design.adaptive_design",
    "design.src_dmc",
    "design.interim_analysis",
    "design.phase1_parts",
    "design.arms_or_cohorts",
  ],
  "picos:population": ["picos.population_summary"],
  "picos:intervention": ["picos.intervention_summary"],
  "picos:comparator": ["picos.comparator_summary"],
  "picos:outcomes": [],
  "picos:execution": ["picos.study_epochs"],
};
const PREFILL_OVERVIEW_SECTIONS = [
  {
    key: "identity",
    label: "项目身份",
    fields: [
      "framing.protocol_id",
      "framing.document_title",
      "framing.clinicaltrials_condition_term",
      "framing.population_intent",
      "framing.product_profile.technology_type",
      "framing.product_profile.administration_routes",
      "framing.product_profile.exposure_scope",
    ],
  },
  {
    key: "design",
    label: "总体设计",
    fields: [
      "framing.design_pattern",
      "picos.design_archetype",
      "design.randomization",
      "design.blinding",
      "design.comparator_type",
      "design.assignment_model",
      "design.center_model",
      "design.adaptive_design",
      "design.src_dmc",
      "design.interim_analysis",
      "design.phase1_parts",
      "design.arms_or_cohorts",
    ],
  },
  {
    key: "picos",
    label: "PICOS",
    fields: [
      "picos.population_summary",
      "picos.intervention_summary",
      "picos.comparator_summary",
      "picos.study_epochs",
    ],
  },
];
const AUTOMATIC_RESEARCH_TIMEOUT_MS = 120000;
const STRING_PREFILL_FIELDS = new Set([
  "framing.protocol_id",
  "framing.document_title",
  "framing.clinicaltrials_condition_term",
  "framing.population_intent",
  "framing.design_pattern",
  "picos.population_summary",
  "picos.intervention_summary",
  "picos.comparator_summary",
  "picos.visit_strategy",
]);
const CONDITIONAL_PICOS_FIELDS = [
  { key: "comparator_summary", label: "对照组设计" },
  { key: "estimand_strategy", label: "估计目标策略" },
];
const DEPENDENT_LABELS = {
  competitor_search_plan: "竞品检索计划", corpus_coverage: "项目语料覆盖", picos_recommendations: "PICOS推荐", m11_section_applicability: "M11章节适用性", front_matter: "方案首页信息", document_identity: "文档身份", protocol_synopsis: "研究摘要", objectives_endpoints: "研究目的与终点", intervention_sections: "试验干预章节", trial_rationale: "研究依据", eligibility_sections: "入选/排除标准", schedule_of_activities: "研究流程表", study_schema: "研究流程图", estimands: "估计目标", statistical_design: "统计设计", statistical_analysis: "统计分析", sample_size: "样本量", screening_activities: "筛选期活动", dose_modification_rules: "试验药物剂量调整规则", concomitant_therapy_rules: "合并用药规则", non_investigational_interventions: "非试验用药/治疗", safety_assessments: "安全性评价", safety_reporting: "安全性事件规则", multiplicity: "多重性控制", regional_requirements: "区域监管要求", instrument_appendices: "量表与评估工具附录",
};
const SYNOPSIS_FIELD_LABELS = {
  "framing.protocol_id": "方案号", "framing.version": "版本", "framing.document_title": "方案标题", "framing.indication": "适应症", "framing.clinicaltrials_condition_term": "ClinicalTrials.gov疾病检索词", "framing.study_phase": "研究分期", "framing.intrinsic_objectives": "内在研究目的", "framing.investigational_product": "试验药物", "framing.target_mechanism": "靶点/作用机制", "framing.competitor_target_scope": "竞品靶点与机制范围", "framing.development_regions": "开发区域", "framing.design_pattern": "总体设计模式", "framing.population_intent": "目标研究人群", "framing.key_uncertainties": "关键科学与开发不确定性", "framing.manual_source_ids": "已准备的Protocol资料", "framing.terminology_policy": "受试者术语规范",
  "picos.design_archetype": "研究设计类型", "picos.field_applicability": "设计字段适用性", "picos.population_summary": "研究人群概述", "picos.inclusion_modules": "入选标准", "picos.exclusion_modules": "排除标准", "picos.washout_rules": "药物/治疗洗脱规则", "picos.intervention_summary": "干预措施概述", "picos.intervention_dose_regimen": "试验药物用法用量", "picos.allowed_concomitant_rules": "允许的合并用药/治疗", "picos.required_background_rules": "必须使用的背景用药/治疗", "picos.prohibited_concomitant_rules": "限制或禁止的合并用药/治疗", "picos.assessment_timing_restrictions": "访视/评价前用药限制", "picos.comparator_summary": "对照组设计", "picos.primary_endpoint": "主要终点及评价时间", "picos.key_secondary_endpoints": "关键次要终点及评价时间", "picos.other_secondary_endpoints": "其他次要终点及评价时间", "picos.exploratory_endpoints": "探索性终点及评价时间", "picos.safety_endpoints": "安全性终点", "picos.aesi_definitions": "特别关注的不良事件（AESI）", "picos.assessment_instruments": "量表与评估工具", "picos.study_epochs": "研究阶段", "picos.visit_strategy": "访视与评价安排", "picos.estimand_strategy": "估计目标策略", "picos.sample_size_strategy": "样本量策略", "picos.statistical_strategy": "统计分析策略",
};
const FACT_FIELD_LABELS = {
  ...SYNOPSIS_FIELD_LABELS,
  "framing.product_profile.technology_type": "药物技术类型",
  "framing.product_profile.technology_description": "药物类型说明",
  "framing.product_profile.administration_routes": "给药途径",
  "framing.product_profile.dosage_forms": "剂型",
  "framing.product_profile.exposure_scope": "暴露范围",
  "framing.product_profile.device_dependency": "给药装置依赖",
  "framing.product_profile.immunogenicity_relevance": "免疫原性相关性",
  "framing.product_profile.safety_considerations": "已知安全性关注",
  "framing.product_profile.pk_pd_considerations": "PK/PD关注",
  "framing.product_profile.historical_study_summaries": "既往人体研究概况",
  "framing.product_profile.historical_dose_regimens": "既往测试剂量与给药方案",
  "framing.product_profile.historical_population_designs": "既往研究人群与设计",
  "framing.product_profile.confirmed_facts.first_in_human_starting_dose": "首次人体起始剂量",
  "framing.product_profile.confirmed_facts.nonclinical_safety_margin": "非临床安全窗",
  "framing.product_profile.confirmed_facts.recommended_phase2_dose": "推荐II期剂量（RP2D）",
  "framing.product_profile.confirmed_facts.dose_escalation_step": "剂量递增步长",
  "framing.product_profile.confirmed_facts.treatment_interval": "给药间隔",
  "framing.product_profile.confirmed_facts.exposure_margin": "暴露安全边际",
  "framing.product_profile.confirmed_facts.safety_threshold": "安全性阈值",
  "framing.product_profile.confirmed_facts.monitoring_window": "安全监测窗口",
};
const FACT_GAP_LABELS = {
  "product_profile.technology_type": "药物技术类型",
  "product_profile.administration_routes": "给药途径",
  target_mechanism: "靶点/作用机制",
  "high_impact_missing.first_in_human_starting_dose": "首次人体起始剂量依据",
  "high_impact_missing.nonclinical_safety_margin": "非临床安全窗",
  "high_impact_missing.recommended_phase2_dose": "推荐II期剂量（RP2D）",
  "high_impact_missing.dose_escalation_step": "剂量递增步长",
  "high_impact_missing.treatment_interval": "给药间隔",
  "high_impact_missing.exposure_margin": "暴露安全边际",
  "high_impact_missing.safety_threshold": "安全性阈值",
  "high_impact_missing.monitoring_window": "安全监测窗口",
};
const emptyPicos = {
  design_archetype: "", field_applicability: {}, population_summary: "", inclusion_modules: [], exclusion_modules: [], washout_rules: [], intervention_summary: "", intervention_dose_regimen: "", allowed_concomitant_rules: [], required_background_rules: [], prohibited_concomitant_rules: [], assessment_timing_restrictions: [], intervention_rules: null, comparator_summary: "", primary_endpoint: "", key_secondary_endpoints: [], other_secondary_endpoints: [], exploratory_endpoints: [], safety_endpoints: [], aesi_definitions: [], assessment_instruments: [], study_epochs: [], visit_strategy: "", estimand_strategy: "", sample_size_strategy: "", statistical_strategy: "",
};
const PICOS_TEXT_LIST_FIELDS = [
  "inclusion_modules", "exclusion_modules", "washout_rules", "allowed_concomitant_rules",
  "required_background_rules", "prohibited_concomitant_rules", "assessment_timing_restrictions",
  "key_secondary_endpoints", "other_secondary_endpoints", "exploratory_endpoints", "safety_endpoints",
  "aesi_definitions", "study_epochs",
];

const synopsisFieldLabel = (fieldPath) => SYNOPSIS_FIELD_LABELS[fieldPath] || "其他待补充项";
const prefillFieldLabel = (fieldPath) => DESIGN_PREFILL_FIELD_LABELS[fieldPath] || SYNOPSIS_FIELD_LABELS[fieldPath] || FACT_FIELD_LABELS[fieldPath] || fieldPath;
const prefillCandidateDisplay = (fieldPath, candidate) => {
  const rawValue = candidate?.preview || (typeof candidate?.structured_value === "string" ? candidate.structured_value : "");
  if (fieldPath === "picos.design_archetype") return DESIGN_ARCHETYPE_LABELS[rawValue] || "其他研究设计";
  return rawValue || "候选内容待生成";
};
const prefillFieldsForSection = (prefillPackage, sectionKey) => {
  const section = PREFILL_OVERVIEW_SECTIONS.find((item) => item.key === sectionKey) || PREFILL_OVERVIEW_SECTIONS[0];
  return section.fields.map((fieldPath) => prefillPackage?.field_candidates?.[fieldPath]).filter(Boolean);
};
// Single-path adoption fails closed for pending-like candidates
// (pending_decision / manual_only / insufficient / unsupported gap), mirroring
// the server gates in adopt_prefill_candidate.  The classification is shared
// with the composite panel; only the user-facing copy differs here.
const SINGLE_PATH_BLOCK_REASON_LABELS = {
  unavailable: "该候选不可用",
  pending_decision: "该候选含「待确认」项，不可单字段直接采用；请在组合推荐中逐字段确认，或打开高级微调填写",
  manual_only: "该候选标注为需逐项确认（manual_only），不可单字段直接采用；请在组合推荐中逐字段确认或跳过",
  insufficient: "该候选证据不足，不可单字段直接采用；请在组合推荐中逐字段确认或跳过",
  unsupported_gap: "该候选存在未被来源原文支持的实质声明，不可单字段直接采用；请在组合推荐中逐字段确认或跳过",
};
const prefillCandidateBlockedReason = (candidate) => (
  SINGLE_PATH_BLOCK_REASON_LABELS[compositeCandidateBlockedCode(candidate)] || ""
);
const recommendedPrefillCandidate = (group) => {
  const candidates = group?.candidates || [];
  const byId = candidates.find((item) => item.candidate_id === group?.recommended_candidate_id);
  // Empty or pending-like recommendation stays no recommendation: never
  // promote the first non-pending alternative into the slot.
  if (byId && !isPendingCompositeCandidate(byId)) return byId;
  return null;
};
const recommendedClinicalTrialsSearchCandidate = (journey) => {
  const group = journey?.prefill_package?.field_candidates?.["framing.clinicaltrials_condition_term"];
  const candidate = recommendedPrefillCandidate(group);
  if (
    !candidate?.candidate_id
    || candidate.field_path !== "framing.clinicaltrials_condition_term"
    || candidate.recommendation_role === "pending_decision"
    || candidate.state === "superseded"
    || typeof candidate.structured_value !== "string"
    || !candidate.structured_value.trim()
  ) return null;
  return candidate;
};
const prefillDestination = (fieldPath) => {
  const entry = Object.entries(PREFILL_GROUP_FIELDS).find(([, fields]) => fields.includes(fieldPath));
  if (!entry) return null;
  const [stage, group] = entry[0].split(":");
  return { stage, group };
};
const factFieldLabel = (fieldPath) => FACT_FIELD_LABELS[fieldPath] || "其他产品事实";
const factGapLabel = (fieldPath) => FACT_GAP_LABELS[fieldPath] || "其他高影响缺口";
const IB_STATUS_LABELS = {
  not_provided: "暂未形成·稍后补充",
  not_available: "尚无IB·不阻断调研",
  uploaded: "已上传IB",
  parsed: "IB已解析",
};
const IB_STATUS_TONE = {
  not_provided: "optional",
  not_available: "optional",
  uploaded: "available",
  parsed: "available",
};
const FACT_PACKET_STATUS_LABELS = {
  not_started: "尚未开始",
  assembling: "正在汇总公开与项目资料",
  sufficient_for_research: "可进入调研与建议包",
  needs_user_input: "有高影响缺口·需补充",
};
const EVIDENCE_STATUS_LABELS = {
  user_provided: "用户提供",
  user_stated: "用户明述",
  source_extracted: "来源提取",
  public_evidence: "公开证据",
  ai_inferred: "AI推断",
  unknown: "未知",
  conflict: "存在冲突",
};
const CONFIDENCE_LABELS = {
  unknown: "未知",
  low: "低",
  medium: "中",
  high: "高",
};
const lines = (value) => String(value || "").split(/\n+/).map((item) => item.trim()).filter(Boolean);
const lineText = (value) => (value || []).join("\n");
const hasPopulatedList = (value) => Array.isArray(value) && value.some((item) => String(item || "").trim());
const normalizePicosForWrite = (value) => ({
  ...value,
  ...Object.fromEntries(PICOS_TEXT_LIST_FIELDS.map((field) => [
    field,
    (value?.[field] || []).map((item) => String(item || "").trim()).filter(Boolean),
  ])),
});
const persistedStagePayload = (journey, targetStage) => journey?.[`${targetStage}_draft`]?.[targetStage] || journey?.[targetStage] || (targetStage === "picos" ? emptyPicos : null);
const synopsisReviewPending = (journey) => journey?.entry_mode === "synopsis_import" && journey?.synopsis_import?.status !== "confirmed";

async function stableSynopsisUploadKey(projectId, file) {
  const contentDigest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  const contentHash = Array.from(new Uint8Array(contentDigest), (value) => value.toString(16).padStart(2, "0")).join("");
  const requestIdentity = new TextEncoder().encode(`${file.name}|${file.type}|${file.size}|${contentHash}`);
  const requestDigest = await crypto.subtle.digest("SHA-256", requestIdentity);
  const requestHash = Array.from(new Uint8Array(requestDigest), (value) => value.toString(16).padStart(2, "0")).join("");
  return {
    contentSha256: contentHash,
    uploadKey: `authoring-synopsis-import-${projectId}-${requestHash}`.slice(0, 200),
  };
}

async function stableInstrumentAppendixUploadKey(projectId, sectionId, instrumentId, workingCopyRevision, file) {
  const contentDigest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  const contentHash = Array.from(new Uint8Array(contentDigest), (value) => value.toString(16).padStart(2, "0")).join("");
  const identity = `${projectId}|${sectionId}|${instrumentId}|${workingCopyRevision}|${file.name}|${contentHash}`;
  const requestDigest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(identity));
  const requestHash = Array.from(new Uint8Array(requestDigest), (value) => value.toString(16).padStart(2, "0")).join("");
  return `authoring-instrument-appendix-${requestHash}`.slice(0, 200);
}

function canonicalWriteValue(value) {
  if (Array.isArray(value)) return value.map((item) => canonicalWriteValue(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().filter((key) => value[key] !== undefined).map((key) => [key, canonicalWriteValue(value[key])]),
    );
  }
  return value;
}

function canonicalWriteJson(value) {
  return JSON.stringify(canonicalWriteValue(value));
}

function projectValueAtFieldPath(journey, fieldPath) {
  return String(fieldPath || "").split(".").reduce((current, key) => current?.[key], journey);
}

function confirmedProjectCandidate(journey, candidateGroup) {
  if (!candidateGroup?.field_path) return null;
  const fieldState = journey?.study_definition?.field_states?.[candidateGroup.field_path];
  if (fieldState?.status !== "confirmed") return null;
  const currentValue = projectValueAtFieldPath(journey, candidateGroup.field_path);
  return candidateGroup.candidates?.find(
    (candidate) => canonicalWriteJson(candidate.structured_value) === canonicalWriteJson(currentValue),
  ) || null;
}

function isPrefillFieldConfirmed(journey, candidateGroup) {
  return Boolean(
    candidateGroup?.candidates?.some((candidate) => candidate.state === "user_confirmed")
    || confirmedProjectCandidate(journey, candidateGroup),
  );
}

async function stableAuthoringWriteKey(projectId, operation, sourceRevision, payload, previewId = "") {
  const identity = canonicalWriteJson({ operation, payload, preview_id: previewId, project_id: projectId, source_revision: sourceRevision });
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(identity));
  const hash = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
  return `authoring-${operation}-${hash}`.slice(0, 200);
}

function writePayloadMatches(left, right) {
  return canonicalWriteJson(left) === canonicalWriteJson(right);
}

function shouldReconcileWrite(error) {
  return error?.status === 409 || !Number.isInteger(error?.status);
}

// --- structured policy rejection mapping ---------------------------------
// Backend contract (worker_01): composite policy rejections arrive as
// HTTP 422 with detail.code == "POLICY_REJECTED" and a stable detail.reason;
// revision/state conflicts remain plain-string 409.  The single-path endpoint
// keeps plain-string 409 for its fail-closed gates (asserted by the API
// contract tests), so its policy rejections are recognised by stable message
// patterns instead.  Policy rejection is attribute-based and deterministic:
// it must never be presented as a concurrency conflict, must not trigger a
// reload, and must never auto-resubmit.
const POLICY_REJECTED_CODE = "POLICY_REJECTED";
const SINGLE_PATH_POLICY_REJECTION_PATTERNS = [
  "single-candidate adoption is blocked",
  "evidence-bound candidate requires server evidence verification",
  "server evidence verification rejected candidate",
];
const POLICY_REASON_LABELS = {
  candidate_pending_decision: "该候选含待确认项：请在组合采用中逐字段确认或跳过后再提交，不会自动重试。",
  candidate_manual_only: "该候选标注为需逐项确认（manual_only）：组合采用前必须对每个字段明确确认或跳过。",
  candidate_insufficient_evidence: "该候选证据不足：组合采用前必须对每个字段明确确认或跳过。",
  candidate_unsupported_evidence_gap: "该候选存在未被来源原文支持的实质声明：组合采用前必须对每个字段明确确认或跳过。",
  no_applicable_paths: "该候选没有可应用的目标字段，无法整包采用。",
};
const isPolicyRejection = (error) => (
  error?.status === 422 && error?.code === POLICY_REJECTED_CODE
);
const isSinglePathPolicyRejection = (error) => (
  error?.status === 409
  && SINGLE_PATH_POLICY_REJECTION_PATTERNS.some(
    (pattern) => String(error?.message || "").includes(pattern),
  )
);
const policyRejectionMessage = (error) => (
  POLICY_REASON_LABELS[error?.reason]
  || (error?.message ? `该候选不符合直接采用条件：${error.message}` : "该候选不符合直接采用条件，请在组合采用中逐字段确认或跳过。")
);

function formatFileSize(size) {
  if (!Number.isFinite(size) || size <= 0) return "-";
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function validationStatus(status) {
  return ({ matched: "一致", warning: "需确认", mismatch: "不一致", not_assessed: "未评估" })[status] || "未评估";
}

function isConditionalPicosFieldComplete(picos, fieldName) {
  if (String(picos?.[fieldName] || "").trim()) return true;
  const decision = picos?.field_applicability?.[fieldName];
  const designAllowsNotApplicable = ["randomized_exploratory", "single_arm_early_phase", "open_label_extension", "other"].includes(picos?.design_archetype)
    && !(picos?.design_archetype === "randomized_exploratory" && fieldName === "comparator_summary");
  return Boolean(designAllowsNotApplicable && decision?.status === "not_applicable" && decision?.confirmed_by_medical_manager);
}

async function readJson(response) {
  let payload;
  try {
    payload = await response.json();
  } catch (cause) {
    if (response.ok) {
      const error = new Error("服务器已响应，但结果未完整返回；正在按原请求核对服务器状态");
      error.cause = cause;
      throw error;
    }
    payload = {};
  }
  if (!response.ok) {
    const detail = payload?.detail;
    const error = new Error(typeof detail === "string" ? detail : `HTTP ${response.status}`);
    error.status = response.status;
    if (detail && typeof detail === "object") {
      // Preserve the structured policy contract (code/reason/message) so
      // callers can distinguish policy rejection from revision conflicts.
      error.code = detail.code;
      error.reason = detail.reason;
      if (typeof detail.message === "string") error.message = detail.message;
    }
    throw error;
  }
  return payload;
}

function statusLabel(journey) {
  if (!journey) return "尚未建立";
  if (journey.entry_mode === "synopsis_import" && journey.synopsis_import?.status !== "confirmed") {
    return ({ not_started: "待导入方案摘要", extraction_pending: "摘要解析中", review_pending: "摘要待用户确认", failed: "摘要导入失败" })[journey.synopsis_import?.status] || "摘要导入中";
  }
  if (journey.status === "document_created") return "已建立工作稿";
  if (journey.status === "writing_allowed") return journey.corpus_gate?.readiness_status === "ready" ? "语料准入完成" : "例外允许写作";
  if (journey.picos_complete || journey.status === "corpus_not_ready") return "语料准备中";
  if (journey.framing_complete || journey.picos_draft || journey.status === "stage2_in_progress") return "PICOS设计进行中";
  if (journey.framing_draft) return "研究框架待确认";
  return ({ stage1_in_progress: "研究框架准备中", stage1_complete: "PICOS设计进行中" })[journey.status] || "研究设计准备中";
}

function initialFramingFor(projectHeader) {
  const product = String(projectHeader?.product_name || "").trim();
  const indication = String(projectHeader?.indication || "").trim();
  return {
    protocol_id: projectHeader?.protocol_id || "",
    version: projectHeader?.protocol_version && projectHeader.protocol_version !== "-" ? projectHeader.protocol_version : "V0.1",
    document_title: product && indication ? `${product}治疗${indication}的临床研究方案` : "",
    indication, clinicaltrials_condition_term: /^[\x00-\x7F]+$/.test(indication) ? indication : "", study_phase: projectHeader?.study_phase || "", intrinsic_objectives: [], investigational_product: product, target_mechanism: "", competitor_target_scope: "", development_regions: ["中国"], design_pattern: "", population_intent: "", key_uncertainties: [], manual_source_ids: [], terminology_policy: "cde_participant",
  };
}

const emptyFactConversation = {
  available: false,
  conversation: null,
  pendingInput: "",
  turns: [],
};

function factConversationFromBackend(payload, pendingInput = "") {
  const conversation = payload?.conversation || (payload?.available === false ? null : payload);
  if (!conversation?.conversation_id) return { ...emptyFactConversation, pendingInput };
  const messages = conversation.messages || [];
  const currentProposalById = new Map(
    (conversation.open_proposals || []).map((proposal) => [proposal.proposal_id, proposal]),
  );
  const turns = [];
  let latestUserMessage = null;
  for (const message of messages) {
    if (message.turn_kind === "user_message") {
      latestUserMessage = message;
      continue;
    }
    if (message.turn_kind !== "ai_response") continue;
    const proposals = (message.proposals || []).map(
      (proposal) => currentProposalById.get(proposal.proposal_id) || proposal,
    );
    turns.push({
      turn_id: message.message_id,
      user_message: latestUserMessage?.text || "",
      ai_response: {
        response_text: message.text,
        proposals,
        questions: message.questions || [],
        high_impact_gaps: conversation.unresolved_high_impact_fields || [],
      },
      decisions: Object.fromEntries(
        proposals
          .filter((proposal) => proposal.decision && proposal.decision !== "pending")
          .map((proposal) => [proposal.proposal_id, proposal.decision]),
      ),
      created_at: message.created_at,
    });
    latestUserMessage = null;
  }
  return {
    available: true,
    conversation,
    pendingInput,
    turns,
  };
}

function listFactValue(value) {
  return String(value || "").split(/[\n,，、;；]+/).map((item) => item.trim()).filter(Boolean);
}

function applyConfirmedFactsToFraming(current, confirmedValues = {}, conversation = null) {
  const factPacket = { ...(current.minimum_product_fact_packet || {}) };
  const conversationHasFactState = Boolean(
    conversation
      && (
        (conversation.messages || []).length
        || Object.keys(conversation.confirmed_field_values || {}).length
        || (conversation.unresolved_high_impact_fields || []).length
      )
  );
  const conversationStatus = conversation?.status || "collecting";
  const conversationGaps = [...(conversation?.unresolved_high_impact_fields || [])];
  const next = {
    ...current,
    product_profile: { ...(current.product_profile || {}) },
    minimum_product_fact_packet: factPacket,
  };
  for (const [fieldPath, rawValue] of Object.entries(confirmedValues)) {
    if (!fieldPath.startsWith("framing.")) continue;
    const relativePath = fieldPath.slice("framing.".length);
    if (relativePath.startsWith("product_profile.confirmed_facts.")) {
      const factKey = relativePath.slice("product_profile.confirmed_facts.".length);
      const proposal = [...(conversation?.open_proposals || [])].reverse().find(
        (item) => item.field_path === fieldPath && ["adopted", "edited"].includes(item.decision),
      );
      const evidenceStatus = ({
        user_stated: "user_provided",
        source_extracted: "source_extracted",
        ai_inferred: "ai_inferred",
      })[proposal?.fact_kind] || "user_provided";
      const evidenceFacts = (next.product_profile.evidence_facts || []).filter(
        (item) => item.field_path !== fieldPath,
      );
      evidenceFacts.push({
        fact_id: `fact_intake_${factKey}`,
        field_path: fieldPath,
        value: String(rawValue || "").trim(),
        evidence_status: evidenceStatus,
        source_ids: proposal?.source_ids || [],
        confidence: proposal?.confidence || "high",
        user_confirmed: true,
      });
      next.product_profile.evidence_facts = evidenceFacts;
      continue;
    }
    if (relativePath.startsWith("product_profile.")) {
      const profileField = relativePath.slice("product_profile.".length);
      next.product_profile[profileField] = [
        "administration_routes",
        "dosage_forms",
        "safety_considerations",
        "pk_pd_considerations",
        "historical_study_summaries",
        "historical_dose_regimens",
        "historical_population_designs",
      ].includes(profileField) ? listFactValue(rawValue) : rawValue;
      continue;
    }
    next[relativePath] = [
      "intrinsic_objectives",
      "development_regions",
      "key_uncertainties",
    ].includes(relativePath) ? listFactValue(rawValue) : rawValue;
  }
  if (conversationHasFactState) {
    const existingPacketGaps = (current.minimum_product_fact_packet?.unresolved_high_impact_fields || [])
      .filter((item) => !String(item).startsWith("high_impact_missing."));
    const unresolvedPacketGaps = existingPacketGaps.filter((item) => {
      if (item === "product_profile.technology_type") {
        return !next.product_profile?.technology_type
          || next.product_profile.technology_type === "unknown";
      }
      if (item === "product_profile.administration_routes") {
        return !(next.product_profile?.administration_routes || []).length;
      }
      if (item === "target_mechanism") return !next.target_mechanism;
      return true;
    });
    const allGaps = [...new Set([...unresolvedPacketGaps, ...conversationGaps])];
    factPacket.unresolved_high_impact_fields = allGaps;
    factPacket.status = conversationStatus === "collecting"
      ? (allGaps.length ? "needs_user_input" : "assembling")
      : "sufficient_for_research";
    factPacket.safe_to_start_competitor_research = conversationStatus !== "collecting";
    factPacket.safe_to_generate_protocol_candidates = (
      conversationStatus === "sufficient_for_writing_candidates"
      && allGaps.length === 0
    );
  }
  return next;
}

function authoringEntryModeForSourceMode(sourceMode) {
  return ({
    user_created_from_zero: "guided_greenfield",
    user_created_synopsis_import: "synopsis_import",
  })[sourceMode] || "";
}

export function MedicalWritingAuthoringJourneySetup({
  projectId,
  projectHeader,
  projectSourceMode = "",
  onCreated,
  onJourneyChanged,
  readOnly = false,
  existingDocument = false,
  initialStage = "",
  initialGroup = "",
  initialInterventionPanel = "",
  focusLabel = "",
}) {
  const activeProjectRef = useRef(projectId);
  const synopsisSelectionGenerationRef = useRef(0);
  const autoJourneyAttemptRef = useRef("");
  const autoPrefillAttemptRef = useRef("");
  const prefillAdoptionLockRef = useRef("");
  const automaticResearchTokenRef = useRef("");
  const automaticResearchAttemptRef = useRef("");
  const automaticResearchGenerationRef = useRef(0);
  const automaticMinimumSearchLockRef = useRef("");
  const [journey, setJourney] = useState(null);
  const [entryMode, setEntryMode] = useState("");
  const [framing, setFraming] = useState(() => initialFramingFor(projectHeader));
  const [picos, setPicos] = useState(emptyPicos);
  const [synopsisFile, setSynopsisFile] = useState(null);
  const [synopsisFileIdentity, setSynopsisFileIdentity] = useState(null);
  const [synopsisUploadKey, setSynopsisUploadKey] = useState("");
  const [synopsisReplacementPending, setSynopsisReplacementPending] = useState(false);
  const [synopsisText, setSynopsisText] = useState("");
  const [synopsisAcknowledged, setSynopsisAcknowledged] = useState([]);
  const [synopsisOverrideReason, setSynopsisOverrideReason] = useState("");
  const [synopsisJob, setSynopsisJob] = useState(null);
  const synopsisJobRef = useRef(null);
  const [stage, setStage] = useState("framing");
  const [group, setGroup] = useState("identity");
  const [prefillSection, setPrefillSection] = useState("identity");
  const [advancedRefinementOpen, setAdvancedRefinementOpen] = useState(Boolean(readOnly));
  const [deferredPrefillFields, setDeferredPrefillFields] = useState([]);
  const [compositeAdoptReceipt, setCompositeAdoptReceipt] = useState(null);
  const [researchRecovery, setResearchRecovery] = useState(null);
  const [interventionPanel, setInterventionPanel] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [searchMessage, setSearchMessage] = useState("");
  const [impact, setImpact] = useState(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [acknowledged, setAcknowledged] = useState([]);
  const [selectedCorpusBriefIds, setSelectedCorpusBriefIds] = useState([]);
  const [competitorDrawerOpen, setCompetitorDrawerOpen] = useState(false);
  const [referencePanelRequest, setReferencePanelRequest] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [loadNonce, setLoadNonce] = useState(0);
  const [factConversation, setFactConversation] = useState(emptyFactConversation);
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [pipelinePollNonce, setPipelinePollNonce] = useState(0);
  const [researchProgressOpen, setResearchProgressOpen] = useState(false);
  const pipelinePollRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    activeProjectRef.current = projectId;
    synopsisSelectionGenerationRef.current += 1;
    autoJourneyAttemptRef.current = "";
    autoPrefillAttemptRef.current = "";
    prefillAdoptionLockRef.current = "";
    automaticResearchTokenRef.current = "";
    automaticResearchAttemptRef.current = "";
    automaticResearchGenerationRef.current += 1;
    automaticMinimumSearchLockRef.current = "";
    setJourney(null); setEntryMode("");
    setFraming(initialFramingFor(projectHeader)); setPicos(emptyPicos);
    setStage("framing"); setGroup("identity"); setPrefillSection("identity");
    setAdvancedRefinementOpen(Boolean(readOnly)); setDeferredPrefillFields([]); setCompositeAdoptReceipt(null);
    setResearchRecovery(null);
    setInterventionPanel(initialInterventionPanel || "");
    setSynopsisFile(null); setSynopsisFileIdentity(null); setSynopsisUploadKey(""); setSynopsisReplacementPending(false); setSynopsisText("");
    setSynopsisAcknowledged([]); setSynopsisOverrideReason("");
    setBusy(""); setMessage(""); setSearchMessage(""); setImpact(null);
    setCompetitorDrawerOpen(false);
    setReferencePanelRequest(null);
    setSelectedCorpusBriefIds([]);
    setLoading(true); setLoadError("");
    setFactConversation(emptyFactConversation);
    setPipelineStatus(null);
    setResearchProgressOpen(false);
    (async () => {
      try {
        const payload = await fetch(
          `/api/projects/${projectId}/medical-writing/authoring-journey`,
          { signal: controller.signal },
        ).then(readJson);
        let loadedFraming = synopsisReviewPending(payload)
          ? payload.synopsis_import.proposed_framing
          : persistedStagePayload(payload, "framing");
        try {
          const factPayload = await fetch(
            `/api/projects/${projectId}/medical-writing/fact-intake/study_framing?allow_missing=true`,
            { signal: controller.signal },
          ).then(readJson);
          if (factPayload.available !== false) {
            setFactConversation(factConversationFromBackend(factPayload));
            loadedFraming = applyConfirmedFactsToFraming(
              loadedFraming,
              factPayload.confirmed_field_values,
              factPayload.conversation || factPayload,
            );
          }
        } catch (error) {
          if (!controller.signal.aborted && error.status !== 404) {
            setMessage(`读取产品事实对话失败：${error.message}`);
          }
        }
        if (controller.signal.aborted) return;
        setJourney(payload); setEntryMode(payload.entry_mode || "guided_greenfield");
        setFraming(loadedFraming);
        setPicos(synopsisReviewPending(payload) ? payload.synopsis_import.proposed_picos : persistedStagePayload(payload, "picos"));
        setSynopsisText(payload.synopsis_import?.proposed_synopsis_text || payload.study_definition?.synopsis_text || "");
        const restoredStage = payload.framing_draft ? "framing" : payload.picos_draft ? "picos" : payload.current_stage === "writing" ? "corpus" : payload.current_stage;
        const requestedStageAllowed = initialStage === "framing"
          || (initialStage === "picos" && payload.framing_complete)
          || (initialStage === "corpus" && payload.picos_complete);
        const nextStage = requestedStageAllowed ? initialStage : restoredStage;
        const requestedGroups = nextStage === "framing" ? FRAMING_GROUPS : nextStage === "picos" ? PICOS_GROUPS : [];
        const nextGroup = requestedGroups.some((item) => item.key === initialGroup)
          ? initialGroup
          : nextStage === "picos" ? "applicability" : nextStage === "framing" ? "identity" : "corpus";
        setStage(nextStage);
        setGroup(nextGroup);
      } catch (error) {
        if (!controller.signal.aborted && error.status !== 404) {
          setLoadError(error.message);
          setMessage(`读取建项进度失败：${error.message}`);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [projectId, loadNonce]);

  useEffect(() => { setAcknowledged([]); setOverrideReason(""); }, [journey?.revision, journey?.corpus_gate?.missing_requirements?.length]);

  useEffect(() => {
    if (!journey || readOnly) return undefined;
    const requestProjectId = projectId;
    let cancelled = false;
    const poll = async () => {
      try {
        const payload = await fetch(
          `/api/projects/${requestProjectId}/medical-writing/research-pipeline/status`,
        ).then(readJson);
        if (cancelled || activeProjectRef.current !== requestProjectId) return;
        setPipelineStatus(payload);
        const stage = payload?.pipeline?.stage || "";
        if (
          stage
          && !PIPELINE_TERMINAL_STAGES.has(stage)
          && !PIPELINE_STABLE_WAITING_STAGES.has(stage)
        ) {
          pipelinePollRef.current = globalThis.setTimeout(poll, 3000);
        }
      } catch (error) {
        if (cancelled || activeProjectRef.current !== requestProjectId) return;
        if (error.status !== 404) {
          pipelinePollRef.current = globalThis.setTimeout(poll, 3000);
        }
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (pipelinePollRef.current) {
        globalThis.clearTimeout(pipelinePollRef.current);
        pipelinePollRef.current = null;
      }
    };
  }, [projectId, journey?.revision, readOnly, pipelinePollNonce]);

  const cancelResearchPipeline = async () => {
    const requestProjectId = projectId;
    setBusy("pipeline-cancel");
    try {
      const result = await fetch(`/api/projects/${requestProjectId}/medical-writing/research-pipeline/cancel`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: "medical_manager" }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return;
      setPipelineStatus((current) => ({ ...(current || {}), pipeline: result.pipeline }));
      setPipelinePollNonce((current) => current + 1);
    } catch (error) {
      if (activeProjectRef.current === requestProjectId) setMessage(`取消研究流水线失败：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };

  const continueResearchPipelineAfterTriage = async () => {
    const requestProjectId = projectId;
    setBusy("pipeline-continue");
    try {
      const result = await fetch(`/api/projects/${requestProjectId}/medical-writing/research-pipeline/continue-after-triage`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: "medical_manager" }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return;
      setPipelineStatus((current) => ({ ...(current || {}), pipeline: result.pipeline }));
      setPipelinePollNonce((current) => current + 1);
    } catch (error) {
      if (activeProjectRef.current === requestProjectId) setMessage(`确认分诊后继续研究流水线失败：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };

  const openResearchPipelineFileIssues = () => {
    const pipeline = pipelineStatus?.pipeline || {};
    const firstBlocker = (pipeline.document_admission_blockers || [])[0] || {};
    setReferencePanelRequest({
      view: "translations",
      artifactId: firstBlocker.artifact_id || "",
      requestKey: `${pipeline.pipeline_id || "pipeline"}-${pipeline.stage || "waiting"}-${Date.now()}`,
    });
    setCompetitorDrawerOpen(true);
  };

  const resumeResearchPipeline = async () => {
    const requestProjectId = projectId;
    const pipeline = pipelineStatus?.pipeline || {};
    const randomPart = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setBusy("pipeline-resume");
    setMessage("");
    setPipelineStatus((current) => current ? {
      ...current,
      pipeline: {
        ...(current.pipeline || {}),
        stage: "preparing",
        detail: "正在复核既有原文、解析、OCR与准入状态后继续翻译。",
      },
    } : current);
    setPipelinePollNonce((current) => current + 1);
    try {
      const result = await fetch(`/api/projects/${requestProjectId}/medical-writing/research-pipeline/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          actor: "medical_manager",
          idempotency_key: `research-resume-${pipeline.pipeline_id || requestProjectId}-${randomPart}`,
          expected_pipeline_id: pipeline.pipeline_id || "",
          expected_stage: pipeline.stage || "",
        }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return;
      setPipelineStatus((current) => ({ ...(current || {}), pipeline: result.pipeline }));
      setPipelinePollNonce((current) => current + 1);
      setMessage(
        PIPELINE_STABLE_WAITING_STAGES.has(result.pipeline?.stage)
          ? "流水线仍在等待用户处理；已完成的下载和结构提取保持复用。"
          : "已从文件处理节点继续研究流水线。",
      );
    } catch (error) {
      if (activeProjectRef.current === requestProjectId) {
        setMessage(`继续研究流水线未完成：${error.message}`);
      }
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };

  const retryResearchPipelineTriage = async () => {
    const requestProjectId = projectId;
    const pipeline = pipelineStatus?.pipeline || {};
    const randomPart = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setBusy("pipeline-retry-triage");
    setMessage("");
    try {
      const result = await fetch(`/api/projects/${requestProjectId}/medical-writing/research-pipeline/retry-triage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          actor: "medical_manager",
          idempotency_key: `triage-retry-${pipeline.pipeline_id || requestProjectId}-${randomPart}`,
          expected_pipeline_id: pipeline.pipeline_id || "",
          expected_triage_run_id: pipeline.triage_run_id || "",
        }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return;
      setPipelineStatus((current) => ({ ...(current || {}), pipeline: result.pipeline, triage_retryable: false }));
      setPipelinePollNonce((current) => current + 1);
      setMessage("已保留完成结果，继续处理未完成的竞品分诊。");
    } catch (error) {
      if (activeProjectRef.current === requestProjectId) {
        setMessage(`继续竞品分诊未完成：${error.message}`);
      }
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };

  const startResearchPipelineRound2 = async () => {
    const requestProjectId = projectId;
    const sourceRevision = journey?.revision || 0;
    setBusy("pipeline-round2");
    setMessage("");
    try {
      const result = await fetch(`/api/projects/${requestProjectId}/medical-writing/research-pipeline/round2`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          actor: "medical_manager",
          idempotency_key: `research-round2-${requestProjectId}-${sourceRevision}`,
        }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return;
      setPipelineStatus((current) => ({ ...(current || {}), pipeline: result.pipeline }));
      setPipelinePollNonce((current) => current + 1);
      setMessage(result.started === false ? "第二轮竞品分析已完成，无需重复启动。" : "第二轮竞品分析已完成；可对照已确认设计复核竞品差异。");
    } catch (error) {
      if (activeProjectRef.current === requestProjectId) setMessage(`第二轮竞品分析未完成：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };

  const updateFraming = (field, value) => setFraming((current) => ({ ...current, [field]: value }));
  const updatePicos = (field, value) => setPicos((current) => {
    const next = { ...current, [field]: value };
    if (field === "design_archetype" && value !== current.design_archetype) {
      next.field_applicability = Object.fromEntries(Object.entries(current.field_applicability || {}).map(([key, decision]) => [key, { ...decision, status: "applicable", reason: "", confirmed_by_medical_manager: false }]));
    }
    return next;
  });
  const updatePicosApplicability = (fieldName, patch) => setPicos((current) => {
    const previous = current.field_applicability?.[fieldName] || { status: "applicable", reason: "", confirmed_by_medical_manager: false };
    const nextDecision = { ...previous, ...patch };
    if (Object.prototype.hasOwnProperty.call(patch, "reason") && patch.reason !== previous.reason) nextDecision.confirmed_by_medical_manager = false;
    if (nextDecision.status === "applicable") Object.assign(nextDecision, { reason: "", confirmed_by_medical_manager: false });
    return { ...current, ...(nextDecision.status === "not_applicable" ? { [fieldName]: "" } : {}), field_applicability: { ...(current.field_applicability || {}), [fieldName]: nextDecision } };
  });
  const selectedPhase1Parts = phase1PartsFromFraming(framing);
  const unresolvedPhase1PartCount = selectedPhase1Parts.filter(
    (part) => !String(part.population || "").trim() || !String(part.cohort_dose || "").trim(),
  ).length;
  const typedPhase1PartsReady = phase1PartsReady(framing);
  // The backend's framing contract intentionally starts from the smallest
  // reliable fact packet (product, indication, phase, title/design intent).
  // Technology class and route are high-impact product facts, but they may be
  // unavailable at greenfield intake.  Keeping them as ``unknown`` must not
  // strand a user before the evidence/IB intake can propose a sourced value;
  // downstream writing still keeps the unresolved fact visible and guarded.
  const technologyTypeReady = Boolean(framing.product_profile?.technology_type)
    && framing.product_profile.technology_type !== "unknown";
  const administrationRouteReady = Boolean(framing.product_profile?.administration_routes?.length);
  const framingReady = Boolean(framing.protocol_id?.trim() && framing.document_title?.trim() && framing.indication?.trim() && framing.study_phase?.trim() && framing.intrinsic_objectives?.length && framing.investigational_product?.trim() && framing.design_pattern?.trim() && framing.population_intent?.trim() && typedPhase1PartsReady);
  const framingSearchReady = Boolean(framing.investigational_product?.trim() && framing.indication?.trim() && framing.study_phase?.trim());
  const picosReady = Boolean(picos.design_archetype && picos.population_summary?.trim() && hasPopulatedList(picos.inclusion_modules) && hasPopulatedList(picos.exclusion_modules) && picos.intervention_summary?.trim() && picos.intervention_dose_regimen?.trim() && isConditionalPicosFieldComplete(picos, "comparator_summary") && picos.primary_endpoint?.trim() && hasPopulatedList(picos.safety_endpoints) && hasPopulatedList(picos.study_epochs) && picos.visit_strategy?.trim() && isConditionalPicosFieldComplete(picos, "estimand_strategy") && picos.sample_size_strategy?.trim() && picos.statistical_strategy?.trim());
  const framingDirty = journey ? JSON.stringify(framing) !== JSON.stringify(persistedStagePayload(journey, "framing")) : true;
  const picosDirty = Boolean(journey && JSON.stringify(picos) !== JSON.stringify(persistedStagePayload(journey, "picos")));
  const framingPendingDraft = Boolean(journey?.framing_draft);
  const picosPendingDraft = Boolean(journey?.picos_draft);
  const hasUnsavedChanges = framingDirty || picosDirty;
  const hasUncommittedChanges = hasUnsavedChanges || framingPendingDraft || picosPendingDraft;
  const pipelineStage = pipelineStatus?.pipeline?.stage || "";
  const authoringWriteBlocked = Boolean(
    pipelineStage
      && !PIPELINE_TERMINAL_STAGES.has(pipelineStage)
      && !PIPELINE_STABLE_WAITING_STAGES.has(pipelineStage),
  );
  const authoringWriteBlockedMessage = authoringWriteBlocked
    ? `研究流水线正在${PIPELINE_STAGE_LABELS[pipelineStage] || pipelineStage}；为保持检索/分诊快照冻结，暂不能保存研究框架。`
    : "";

  const requestPrefillPackage = async (nextJourney, force = false, requestProjectId = projectId) => {
    const effectiveFraming = persistedStagePayload(nextJourney, "framing");
    if (!nextJourney?.revision || !effectiveFraming?.investigational_product?.trim() || !effectiveFraming?.indication?.trim() || !effectiveFraming?.study_phase?.trim()) return nextJourney;
    const requestPayload = { expected_revision: nextJourney.revision, force };
    const idempotencyKey = await stableAuthoringWriteKey(
      requestProjectId,
      force ? "prefill-regenerate" : "prefill-generate",
      nextJourney.revision,
      requestPayload,
    );
    return fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey/prefill-package/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...requestPayload,
        actor: "medical_manager",
        idempotency_key: idempotencyKey,
      }),
    }).then(readJson);
  };

  const generatePrefill = async (nextJourney = journey, force = false) => {
    if (!nextJourney) return;
    const requestProjectId = projectId;
    setBusy("prefill-generate");
    setMessage(force ? "正在根据最新研究事实和调研结果更新建议..." : "正在准备研究设计建议...");
    try {
      // A settled reference batch can recalculate the corpus gate without
      // changing the prefill package.  That system projection may advance
      // the journey revision while this component still holds the previous
      // prop.  Always refresh the authoritative journey before the single
      // external prefill call so the request cannot spend a model call on a
      // stale revision and then fail closed as an unknown-outcome lease.
      const latestResponse = await fetch(
        `/api/projects/${requestProjectId}/medical-writing/authoring-journey?allow_missing=true`,
      ).then(readJson);
      const effectiveJourney = latestResponse?.available === false ? nextJourney : latestResponse;
      if (effectiveJourney !== nextJourney) {
        applyJourneyResponse(effectiveJourney);
        onJourneyChanged?.(effectiveJourney);
      }
      const prepared = await requestPrefillPackage(effectiveJourney, force, requestProjectId);
      if (activeProjectRef.current !== requestProjectId) return;
      applyJourneyResponse(prepared);
      const progress = prepared.prefill_package?.progress;
      setMessage(
        progress
          ? "研究设计建议已更新，可直接审阅推荐方案。"
          : "研究设计建议已更新。",
      );
    } catch (error) {
      if (activeProjectRef.current === requestProjectId) setMessage(`研究设计建议生成失败：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };

  const requestPrefillAdoption = async (baseJourney, fieldPath, candidate, operation, editedValue = undefined) => {
    const prefillPackage = baseJourney?.prefill_package;
    if (!baseJourney || !prefillPackage || !candidate?.candidate_id) throw new Error("当前建议已更新，请重新读取后再采用");
    const adoptionPayload = {
      expected_package_revision: prefillPackage.package_revision,
      field_path: fieldPath,
      candidate_id: candidate.candidate_id,
      ...(editedValue !== undefined ? { edited_value: editedValue } : {}),
    };
    const idempotencyKey = await stableAuthoringWriteKey(
      projectId,
      operation,
      baseJourney.revision,
      adoptionPayload,
    );
    return fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/prefill-package/adopt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_revision: baseJourney.revision,
        ...adoptionPayload,
        actor: "medical_manager",
        idempotency_key: idempotencyKey,
      }),
    }).then(readJson);
  };

  const reloadJourneyAfterPrefillConflict = async (requestProjectId) => {
    const refreshed = await fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey`).then(readJson);
    if (activeProjectRef.current === requestProjectId) applyJourneyResponse(refreshed);
    return refreshed;
  };

  const adoptPrefillCandidate = async (fieldPath, candidate, editedValue = undefined) => {
    const prefillPackage = journey?.prefill_package;
    if (!journey || !prefillPackage || !candidate?.candidate_id || prefillAdoptionLockRef.current) return;
    const requestProjectId = projectId;
    const lockToken = `${requestProjectId}:${journey.revision}:${fieldPath}:${candidate.candidate_id}`;
    prefillAdoptionLockRef.current = lockToken;
    setBusy(`prefill-adopt-${fieldPath}`);
    setMessage("");
    try {
      const response = await requestPrefillAdoption(journey, fieldPath, candidate, "prefill-adopt", editedValue);
      if (activeProjectRef.current !== requestProjectId || prefillAdoptionLockRef.current !== lockToken) return;
      applyJourneyResponse(response);
      onJourneyChanged?.(response);
      setDeferredPrefillFields((current) => current.filter((item) => item !== fieldPath));
      if (fieldPath === "framing.clinicaltrials_condition_term") {
        setMessage("ClinicalTrials.gov疾病检索词已采用，正在按新检索计划自动调研...");
        await runPublicSearch(response, {
          adoptionConfirmed: true,
          requestProjectId,
        });
      } else {
        setMessage(`${prefillFieldLabel(fieldPath)}已采用并写入当前研究事实，可继续在下方微调。`);
      }
    } catch (error) {
      if (activeProjectRef.current !== requestProjectId || prefillAdoptionLockRef.current !== lockToken) return;
      if (isSinglePathPolicyRejection(error)) {
        // Fail-closed policy rejection: attribute-based and deterministic.
        // No reload, no concurrency wording, no auto-resubmit.
        setMessage(policyRejectionMessage(error));
      } else if (error.status === 409) {
        try {
          const refreshed = await reloadJourneyAfterPrefillConflict(requestProjectId);
          const refreshedCandidate = refreshed.prefill_package?.field_candidates?.[fieldPath]?.candidates
            ?.find((item) => item.candidate_id === candidate.candidate_id);
          if (
            fieldPath === "framing.clinicaltrials_condition_term"
            && refreshedCandidate?.state === "user_confirmed"
          ) {
            setMessage("ClinicalTrials.gov疾病检索词已采用，正在恢复自动调研...");
            await runPublicSearch(refreshed, {
              adoptionConfirmed: true,
              requestProjectId,
            });
          } else {
            setMessage("建议包已被其他操作更新，已重新读取最新版本；请核对后再次采用。");
          }
        } catch (reloadError) {
          setMessage(`建议已更新，但重新读取失败：${reloadError.message}`);
        }
      } else {
        setMessage(`建议采用失败：${error.message}`);
      }
    } finally {
      if (activeProjectRef.current === requestProjectId && prefillAdoptionLockRef.current === lockToken) {
        prefillAdoptionLockRef.current = "";
        setBusy("");
      }
    }
  };

  const adoptPrefillComposite = async (
    packageFieldPath,
    candidate,
    pathOverrides = {},
    skippedPaths = [],
  ) => {
    const prefillPackage = journey?.prefill_package;
    if (!journey || !prefillPackage || !candidate?.candidate_id || !packageFieldPath || prefillAdoptionLockRef.current) return;
    if (!["module", "design_package"].includes(candidate.candidate_scope)) {
      setMessage("该候选不是组合方案，请使用单字段采用。");
      return;
    }
    const requestProjectId = projectId;
    const lockToken = `${requestProjectId}:${journey.revision}:${packageFieldPath}:${candidate.candidate_id}:composite`;
    prefillAdoptionLockRef.current = lockToken;
    setBusy(`prefill-composite-adopt-${packageFieldPath}`);
    setMessage("");
    try {
      const adoptionPayload = {
        expected_package_revision: prefillPackage.package_revision,
        package_field_path: packageFieldPath,
        candidate_id: candidate.candidate_id,
        path_overrides: pathOverrides || {},
        skipped_paths: skippedPaths || [],
      };
      const idempotencyKey = await stableAuthoringWriteKey(
        requestProjectId,
        "prefill-composite-adopt",
        journey.revision,
        adoptionPayload,
      );
      const response = await fetch(
        `/api/projects/${requestProjectId}/medical-writing/authoring-journey/prefill-package/adopt-composite`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision: journey.revision,
            ...adoptionPayload,
            actor: "medical_manager",
            idempotency_key: idempotencyKey,
          }),
        },
      ).then(readJson);
      if (activeProjectRef.current !== requestProjectId || prefillAdoptionLockRef.current !== lockToken) return;
      const nextJourney = response?.journey || response;
      const receipt = response?.receipt || null;
      applyJourneyResponse(nextJourney);
      onJourneyChanged?.(nextJourney);
      setCompositeAdoptReceipt(receipt);
      if (receipt?.package_marked_stale) {
        setMessage("组合采用已写入，但建议包已标记为需更新；请重新生成后再继续采用其他方案。");
      } else {
        setMessage(receiptSummaryMessage(receipt) || `${packageFieldLabel(packageFieldPath)}已整包写入当前研究事实。`);
      }
    } catch (error) {
      if (activeProjectRef.current !== requestProjectId || prefillAdoptionLockRef.current !== lockToken) return;
      if (isPolicyRejection(error)) {
        setCompositeAdoptReceipt(null);
        // Structured policy rejection: attribute-based and deterministic —
        // no reload, no concurrency wording, never an auto-resubmit.
        setMessage(policyRejectionMessage(error));
      } else if (error.status === 409) {
        try {
          await reloadJourneyAfterPrefillConflict(requestProjectId);
          setCompositeAdoptReceipt(null);
          // 409: reload once and inform; never silently resubmit the adoption.
          setMessage("建议包或研究定义已被其他操作更新，已重新读取最新版本；请核对组合方案后再次采用，不会自动重试提交。");
        } catch (reloadError) {
          setMessage(`组合采用冲突；重新读取失败：${reloadError.message}`);
        }
      } else {
        setMessage(`组合采用失败：${error.message}`);
      }
    } finally {
      if (activeProjectRef.current === requestProjectId && prefillAdoptionLockRef.current === lockToken) {
        prefillAdoptionLockRef.current = "";
        setBusy("");
      }
    }
  };

  const runPublicSearch = async (
    nextJourney = journey,
    {
      adoptionConfirmed = false,
      conflictRetried = false,
      requestProjectId = projectId,
    } = {},
  ) => {
    if (activeProjectRef.current !== requestProjectId) return { status: "stale_project" };
    const searchPlan = nextJourney?.search_plan;
    const conditionTerm = searchPlan?.registry_filter?.condition_term
      || nextJourney?.framing?.clinicaltrials_condition_term
      || nextJourney?.framing?.indication;
    if (!searchPlan?.plan_id) {
      const detail = adoptionConfirmed
        ? "检索词已采用，但新的检索计划尚未生成，自动调研未完成，可重试。"
        : "竞品检索计划尚未生成，请先确认最小项目信息。";
      setSearchMessage(detail);
      if (adoptionConfirmed) {
        setMessage(detail);
        setResearchRecovery({ projectId: requestProjectId, adoptionConfirmed: true });
      }
      return { status: "missing_search_plan" };
    }
    automaticResearchGenerationRef.current += 1;
    const researchToken = `${requestProjectId}:${searchPlan.plan_id}:${automaticResearchGenerationRef.current}`;
    automaticResearchTokenRef.current = researchToken;
    const controller = new AbortController();
    const timeoutId = globalThis.setTimeout(
      () => controller.abort(),
      AUTOMATIC_RESEARCH_TIMEOUT_MS,
    );
    setResearchRecovery(null);
    setBusy("search");
    setSearchMessage("正在自动检索公开竞品研究并准备可用原文...");
    let searched = null;
    try {
      searched = await fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey/competitor-search`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({ search_plan_id: searchPlan.plan_id, actor: "medical_manager", idempotency_key: `authoring-search-${requestProjectId}-${searchPlan.plan_id}` }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return { status: "stale_project" };
      // Start the parent research pipeline BEFORE applying journey state or
      // notifying the parent.  Applying journey state + onJourneyChanged
      // triggers React re-render / parent callback that can unmount or
      // navigate away from this component before the pipeline-start fetch
      // reaches the server (proven by release-r9: competitor-search 200 but
      // research-pipeline/start never arrived).  Firing start first makes the
      // search → start transition survive re-render, remount and navigation.
      //
      // Do not gate this request on automaticResearchTokenRef.  A same-project
      // remount or a second effect can rotate that UI token after the search
      // response has committed, but the server-side start is still the
      // required idempotent continuation for this immutable search snapshot.
      // The request itself is keyed by project + search-plan and must be sent;
      // only a project switch is allowed to suppress it.
      // The backend start() is idempotent: it reuses the existing search
      // snapshot when one is already bound, so a late/duplicate start is safe.
      let pipelineStartError = null;
      let startedPipeline = null;
      try {
        const started = await fetch(`/api/projects/${requestProjectId}/medical-writing/research-pipeline/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            actor: "medical_manager",
            idempotency_key: `research-pipe-${requestProjectId}-${searchPlan.plan_id}`,
            auto_confirm_triage: false,
            force: false,
          }),
        }).then(readJson);
        startedPipeline = started.pipeline;
      } catch (pipeError) {
        pipelineStartError = pipeError;
      }
      // The server-side start is intentionally allowed to finish, but an old
      // response must not write into a component that has since switched to a
      // different project or automatic-research generation.
      if (
        activeProjectRef.current !== requestProjectId
        || automaticResearchTokenRef.current !== researchToken
      ) return { status: "stale_project" };
      if (startedPipeline) {
        setPipelineStatus((current) => ({ ...(current || {}), pipeline: startedPipeline }));
        setPipelinePollNonce((current) => current + 1);
      }
      // Apply the successful search snapshot to local state and notify the
      // parent AFTER the pipeline-start request has completed (success or
      // failure).  This preserves the valid search snapshot regardless of
      // whether the pipeline started, keeping the failure visible/retryable.
      applyJourneyResponse(searched);
      onJourneyChanged?.(searched);
      const returnedCount = searched.search_plan?.returned_count || 0;
      const documentCount = searched.search_plan?.public_document_count || 0;
      if (pipelineStartError) {
        const detail = `竞品研究已检索，但后续资料准备未启动：${pipelineStartError.message}`;
        setSearchMessage(detail);
        setMessage(detail);
        setResearchRecovery({ projectId: requestProjectId, adoptionConfirmed });
        return { status: "pipeline_start_failed", journey: searched, error: pipelineStartError.message };
      }
      const detail = returnedCount
        ? `已找到${returnedCount}项公开研究${documentCount ? `和${documentCount}份Protocol` : ""}，正在准备研究设计建议。`
        : "暂未找到匹配的公开研究，可调整检索词后重试。";
      setSearchMessage(detail);
      if (adoptionConfirmed) setMessage(`检索词已采用；${detail}`);
      return { status: returnedCount ? "pipeline_started" : "no_results", journey: searched };
    } catch (error) {
      if (
        activeProjectRef.current !== requestProjectId
        || automaticResearchTokenRef.current !== researchToken
      ) return { status: "stale_project" };
      if (error.status === 409 && !conflictRetried) {
        try {
          const refreshed = await reloadJourneyAfterPrefillConflict(requestProjectId);
          if (activeProjectRef.current !== requestProjectId) return { status: "stale_project" };
          return runPublicSearch(refreshed, {
            adoptionConfirmed,
            conflictRetried: true,
            requestProjectId,
          });
        } catch (reloadError) {
          error = reloadError;
        }
      }
      const failureDetail = error.name === "AbortError"
        ? "请求超时"
        : error.message;
      const detail = adoptionConfirmed
        ? searched
          ? `公开研究已检索，后续准备未完成：${failureDetail}`
          : `自动调研未完成：${failureDetail}`
        : `自动调研未完成：${failureDetail}`;
      setResearchRecovery({ projectId: requestProjectId, adoptionConfirmed });
      setSearchMessage(detail);
      if (adoptionConfirmed) setMessage(detail);
      return { status: "failed", error };
    } finally {
      globalThis.clearTimeout(timeoutId);
      if (
        activeProjectRef.current === requestProjectId
        && automaticResearchTokenRef.current === researchToken
      ) setBusy("");
    }
  };

  const retryAutomaticResearch = async () => {
    const requestProjectId = projectId;
    if (
      busy
      || researchRecovery?.projectId !== requestProjectId
      || activeProjectRef.current !== requestProjectId
    ) return;
    setMessage("正在读取最新检索计划并重试自动调研...");
    try {
      const refreshed = await fetch(
        `/api/projects/${requestProjectId}/medical-writing/authoring-journey`,
      ).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return;
      applyJourneyResponse(refreshed);
      await runPublicSearch(refreshed, {
        adoptionConfirmed: Boolean(researchRecovery.adoptionConfirmed),
        requestProjectId,
      });
    } catch (error) {
      if (activeProjectRef.current !== requestProjectId) return;
      const detail = researchRecovery.adoptionConfirmed
        ? `检索词已采用，自动调研未完成，可重试：${error.message}`
        : `公开研究检索未完成，可重试：${error.message}`;
      setMessage(detail);
      setSearchMessage(detail);
    }
  };

  const applyJourneyResponse = (response) => {
    setJourney(response);
    setEntryMode(response.entry_mode || "guided_greenfield");
    setFraming(synopsisReviewPending(response) ? response.synopsis_import.proposed_framing : persistedStagePayload(response, "framing"));
    setPicos(synopsisReviewPending(response) ? response.synopsis_import.proposed_picos : persistedStagePayload(response, "picos"));
    setSynopsisText(response.synopsis_import?.proposed_synopsis_text || response.study_definition?.synopsis_text || "");
  };

  const submitFactIntakeTurn = async (
    messageOverride = "",
    sourceIdsOverride = null,
    ibStatusOverride = "",
  ) => {
    if (!journey) return;
    const userInput = (
      typeof messageOverride === "string" && messageOverride.trim()
        ? messageOverride
        : factConversation.pendingInput
    ).trim();
    if (!userInput) return;
    const requestProjectId = projectId;
    const ibSourceIds = sourceIdsOverride || framing.minimum_product_fact_packet?.ib_source_ids || [];
    const ibStatus = ibStatusOverride || framing.minimum_product_fact_packet?.ib_status || "not_provided";
    setBusy("fact-turn");
    try {
      let conversation = factConversation.conversation;
      if (!conversation) {
        conversation = await fetch(`/api/projects/${requestProjectId}/medical-writing/fact-intake/study_framing`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            scope: "study_framing",
            actor: "medical_manager",
            idempotency_key: `fact-intake-create-${requestProjectId}-study-framing`,
          }),
        }).then(readJson);
      }
      const idempotencyKey = await stableAuthoringWriteKey(
        requestProjectId,
        "fact-turn",
        conversation.revision,
        { message_text: userInput, ib_status: ibStatus, ib_source_ids: ibSourceIds },
      );
      const response = await fetch(`/api/projects/${requestProjectId}/medical-writing/fact-intake/study_framing/turns`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: conversation.revision,
          message_text: userInput,
          ib_status: ibStatus,
          ib_source_ids: ibSourceIds,
          actor: "medical_manager",
          idempotency_key: idempotencyKey,
        }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return;
      setFactConversation(factConversationFromBackend(response, ""));
      setMessage(response.ai_message?.text || "产品事实已拆解，请采用、修订或拒绝候选。");
    } catch (error) {
      setMessage(`事实采集未完成：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };

  const applyFactIntakeProposal = async (turnId, proposalId, decision, editedValue = null) => {
    if (!journey || !factConversation.conversation) return;
    const requestProjectId = projectId;
    const action = ({ adopted: "adopt", edited: "edit", rejected: "reject" })[decision];
    const decisionPayload = { proposal_id: proposalId, action, edited_value: editedValue || "" };
    const idempotencyKey = await stableAuthoringWriteKey(
      requestProjectId,
      "fact-apply",
      factConversation.conversation.revision,
      decisionPayload,
    );
    setBusy(`fact-apply-${proposalId}`);
    try {
      const response = await fetch(`/api/projects/${requestProjectId}/medical-writing/fact-intake/study_framing/apply`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: factConversation.conversation.revision,
          decisions: [decisionPayload],
          actor: "medical_manager",
          idempotency_key: idempotencyKey,
        }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return;
      setFactConversation(factConversationFromBackend(response, ""));
      setFraming((current) => applyConfirmedFactsToFraming(
        current,
        response.confirmed_field_values,
        response.conversation,
      ));
      const label = decision === "adopted" ? "已采用" : decision === "rejected" ? "已拒绝" : "已修订";
      setMessage(`事实${label}${decision === "rejected" ? "" : "并已回填研究框架"}。`);
    } catch (error) {
      setMessage(`事实应用失败：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };

  const persistIbPacket = async ({
    ibStatus,
    sourceEntryId = "",
    validation = null,
    overrideReason = "",
  }) => {
    if (!journey) return null;
    const requestProjectId = projectId;
    const warnings = validation?.warnings || [];
    const nextPacket = {
      ...(framing.minimum_product_fact_packet || {}),
      ib_status: ibStatus,
      ib_source_ids: sourceEntryId ? [sourceEntryId] : [],
      ib_validation_status: warnings.length
        ? "confirmed_after_warning"
        : sourceEntryId ? "matched" : "not_assessed",
      ib_warning_codes: warnings.map((item) => item.code),
      ib_override_reason: warnings.length ? overrideReason.trim() : "",
      supporting_source_ids: [
        ...new Set([
          ...(framing.minimum_product_fact_packet?.supporting_source_ids || []).filter(
            (item) => !(framing.minimum_product_fact_packet?.ib_source_ids || []).includes(item),
          ),
          ...(sourceEntryId ? [sourceEntryId] : []),
        ]),
      ],
    };
    const payload = {
      ...framing,
      minimum_product_fact_packet: nextPacket,
    };
    const sourceRevision = journey.revision;
    const idempotencyKey = await stableAuthoringWriteKey(
      requestProjectId,
      "ib-packet",
      sourceRevision,
      payload,
    );
    setBusy("ib-attach");
    try {
      const response = await fetch(
        `/api/projects/${requestProjectId}/medical-writing/authoring-journey/stages/framing/draft`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision: sourceRevision,
            stage: "framing",
            framing: payload,
            actor: "medical_manager",
            idempotency_key: idempotencyKey,
          }),
        },
      ).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return response;
      applyJourneyResponse(response);
      setMessage(
        sourceEntryId
          ? "研究者手册已登记为项目来源，可提取关键产品事实并逐项确认。"
          : "已记录当前不提供研究者手册；可继续使用最小事实对话和公开竞品调研。",
      );
      return response;
    } catch (error) {
      setMessage(`研究者手册状态保存失败：${error.message}`);
      throw error;
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };

  const attachInvestigatorBrochure = async (registration, overrideReason = "") => {
    const validation = registration?.entry?.metadata?.content_validation || {};
    return persistIbPacket({
      ibStatus: "parsed",
      sourceEntryId: registration?.entry?.entry_id || "",
      validation,
      overrideReason,
    });
  };

  const analyzeInvestigatorBrochure = async () => {
    const sourceIds = framing.minimum_product_fact_packet?.ib_source_ids || [];
    if (!sourceIds.length) return;
    await submitFactIntakeTurn(
      "请仅依据已上传研究者手册的原文片段，提取当前方案设计需要的产品类型、给药途径、作用机制、已知安全性关注、PK/PD关注和有明确原文支持的高影响定量事实；没有原文支持的精确值保持未知。",
      sourceIds,
      "parsed",
    );
  };

  const reconcileJourneyWrite = async (requestProjectId, matches) => {
    if (activeProjectRef.current !== requestProjectId) return null;
    try {
      const current = await fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey`).then(readJson);
      if (activeProjectRef.current !== requestProjectId || !matches(current)) return null;
      return current;
    } catch {
      return null;
    }
  };

  const createJourney = async (mode) => {
    const requestProjectId = projectId;
    setBusy(`create-${mode}`); setMessage("");
    try {
      const created = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entry_mode: mode, framing: mode === "guided_greenfield" ? initialFramingFor(projectHeader) : {}, actor: "medical_manager", idempotency_key: `authoring-create-${projectId}-${mode}` }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return null;
      let prepared = created;
      if (mode === "guided_greenfield") {
        try {
          prepared = await requestPrefillPackage(created);
        } catch (error) {
          setMessage(`写作任务已建立；研究设计建议稍后重试：${error.message}`);
        }
      }
      if (activeProjectRef.current !== requestProjectId) return null;
      applyJourneyResponse(prepared);
      setStage("framing"); setGroup("identity");
      return prepared;
    } catch (error) {
      if (activeProjectRef.current === requestProjectId) setMessage(`建立写作任务失败：${error.message}`);
      return null;
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };

  const preferredEntryMode = authoringEntryModeForSourceMode(projectSourceMode);
  useEffect(() => {
    if (loading || loadError || journey || busy || !preferredEntryMode) return;
    const attemptKey = `${projectId}:${preferredEntryMode}`;
    if (autoJourneyAttemptRef.current === attemptKey) return;
    autoJourneyAttemptRef.current = attemptKey;
    createJourney(preferredEntryMode).then((created) => {
      if (!created && activeProjectRef.current === projectId) autoJourneyAttemptRef.current = "";
    });
  }, [busy, journey, loadError, loading, preferredEntryMode, projectId]);

  useEffect(() => {
    if (
      loading
      || loadError
      || !journey
      || journey.prefill_package
      // A greenfield candidate already in the writing workspace must not
      // re-enter the setup prefill loop on editor mount/refresh.  New guided
      // projects still use the AI-first prefill path before writing begins.
      || journey.current_stage === "writing"
      || journey.status === "document_created"
      || busy
      || automaticMinimumSearchLockRef.current
      || !journey.search_plan?.latest_snapshot_id
    ) return;
    const minimumReady = Boolean(
      journey.framing?.investigational_product?.trim()
      && journey.framing?.indication?.trim()
      && journey.framing?.study_phase?.trim(),
    );
    if (!minimumReady) return;
    const attemptKey = `${projectId}:${journey.revision}`;
    if (autoPrefillAttemptRef.current === attemptKey) return;
    autoPrefillAttemptRef.current = attemptKey;
    generatePrefill(journey).catch(() => {
      if (activeProjectRef.current === projectId) autoPrefillAttemptRef.current = "";
    });
  }, [
    busy,
    journey?.prefill_package,
    journey?.current_stage,
    journey?.project_id,
    journey?.revision,
    journey?.status,
    journey?.search_plan?.latest_snapshot_id,
    loadError,
    loading,
    projectId,
  ]);

  const selectSynopsisFile = async (file) => {
    const requestProjectId = projectId;
    const selectionGeneration = synopsisSelectionGenerationRef.current + 1;
    synopsisSelectionGenerationRef.current = selectionGeneration;
    setSynopsisFile(file || null);
    setSynopsisFileIdentity(null);
    setSynopsisUploadKey("");
    setSynopsisReplacementPending(Boolean(file));
    setSynopsisAcknowledged([]);
    setSynopsisOverrideReason("");
    setMessage("");
    if (!file) return;
    try {
      const identity = await stableSynopsisUploadKey(projectId, file);
      if (activeProjectRef.current === requestProjectId && synopsisSelectionGenerationRef.current === selectionGeneration) {
        setSynopsisFileIdentity(identity);
        setSynopsisUploadKey(identity.uploadKey);
      }
    } catch (error) {
      if (activeProjectRef.current === requestProjectId && synopsisSelectionGenerationRef.current === selectionGeneration) {
        setSynopsisFile(null);
        setMessage(`无法读取方案摘要文件：${error.message}`);
      }
    }
  };

  const uploadSynopsis = async () => {
    if (!journey || !synopsisFile || !synopsisFileIdentity || !synopsisUploadKey) return;
    const requestProjectId = projectId;
    const requestGeneration = synopsisSelectionGenerationRef.current;
    const requestFileIdentity = synopsisFileIdentity;
    const requestUploadKey = synopsisUploadKey;
    const form = new FormData();
    form.append("file", synopsisFile);
    form.append("expected_revision", String(journey.revision));
    form.append("actor", "medical_manager");
    form.append("idempotency_key", requestUploadKey);
    setBusy("synopsis-upload"); setMessage("正在读取方案摘要并启动结构化任务...");
    synopsisJobRef.current = requestUploadKey;
    try {
      const startResponse = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/synopsis-import`, { method: "POST", body: form }).then(readJson);
      if (activeProjectRef.current !== requestProjectId || synopsisSelectionGenerationRef.current !== requestGeneration) return;
      if (startResponse.status !== 202 && startResponse.status_code !== 202 && !startResponse.job_id) {
        throw new Error(startResponse.detail || "启动结构化任务失败");
      }
      const jobId = startResponse.idempotency_key || startResponse.job_id;
      if (startResponse.content_sha256 && requestFileIdentity.contentSha256 && startResponse.content_sha256 !== requestFileIdentity.contentSha256) {
        throw new Error("解析结果与当前选择的文件不一致，请重新导入");
      }
      setSynopsisJob({ idempotency_key: jobId, status: startResponse.phase || "chunking", chunk_index: 0, chunk_total: 0 });
      // Persist active task identity for refresh/tab-close reconnection.
      try { localStorage.setItem(`mw_synopsis_job_${requestProjectId}`, JSON.stringify({ idempotency_key: jobId, content_sha256: requestFileIdentity.contentSha256, started_at: performance.now() })); } catch (e) { /* localStorage may be unavailable */ }
      setMessage("方案摘要已上传，正在后台执行AI结构化提取...");
      // Poll for completion. No hard timeout — the job is persisted server-side
      // and the user can reconnect via localStorage after refresh.
      const pollInterval = 3000;
      let lastPhase = "";
      while (true) {
        if (synopsisJobRef.current !== requestUploadKey) return; // cancelled or superseded
        await new Promise((resolve) => setTimeout(resolve, pollInterval));
        if (synopsisJobRef.current !== requestUploadKey) return;
        const status = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/synopsis-import/jobs/${jobId}`).then(readJson);
        if (activeProjectRef.current !== requestProjectId || synopsisSelectionGenerationRef.current !== requestGeneration) return;
        const phase = status.phase || status.status;
        if (phase !== lastPhase) {
          lastPhase = phase;
          const phaseLabel = {
            uploaded: "已上传", parsing: "正在解析", chunking: "正在分块",
            ai_synthesis: `AI结构化提取中${status.chunk_total > 0 ? ` (${status.chunk_index}/${status.chunk_total})` : ""}`,
            validating: "正在校验来源忠实度", review_ready: "提取完成",
            cancelled: "已取消", failed: "失败", recoverable: "可恢复",
          }[phase] || phase;
          setMessage(`${phaseLabel}${status.error_message ? `：${status.error_message}` : ""}`);
        }
        setSynopsisJob(status);
        if (status.status === "review_ready") {
          break;
        }
        if (status.status === "cancelled") {
          setMessage("方案摘要导入已取消。");
          setBusy("");
          return;
        }
        if (status.status === "failed") {
          throw new Error(status.error_message || "AI结构化提取失败");
        }
      }
      // Fetch result and attach.
      const imported = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/synopsis-import/jobs/${jobId}/result`).then(readJson);
      if (activeProjectRef.current !== requestProjectId || synopsisSelectionGenerationRef.current !== requestGeneration) return;
      if (imported.synopsis_import?.source?.content_sha256 !== requestFileIdentity.contentSha256) {
        throw new Error("解析结果与当前选择的文件不一致，请重新导入");
      }
      applyJourneyResponse(imported);
      setSynopsisReplacementPending(false);
      setSynopsisAcknowledged([]); setSynopsisOverrideReason("");
      setSynopsisJob(null);
      try { localStorage.removeItem(`mw_synopsis_job_${requestProjectId}`); } catch (e) { /* ignore */ }
      setMessage("摘要解析完成，请核对文件角色、适应症和提取候选。确认后仍需完成两阶段医学确认。");
    } catch (error) {
      if (activeProjectRef.current === requestProjectId && synopsisSelectionGenerationRef.current === requestGeneration) setMessage(`摘要导入失败：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestProjectId && synopsisSelectionGenerationRef.current === requestGeneration) setBusy("");
    }
  };

  const cancelSynopsisImport = async () => {
    if (!synopsisJob?.idempotency_key) return;
    const cancelKey = synopsisJob.idempotency_key;
    synopsisJobRef.current = null;
    setMessage("正在取消方案摘要导入...");
    try {
      await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/synopsis-import/jobs/${cancelKey}/cancel`, { method: "POST" }).then(readJson);
      setSynopsisJob(null);
      setBusy("");
      try { localStorage.removeItem(`mw_synopsis_job_${projectId}`); } catch (e) { /* ignore */ }
      setMessage("方案摘要导入已取消。");
    } catch (error) {
      setMessage(`取消失败：${error.message}`);
    }
  };

  const retrySynopsisImport = async () => {
    const jobKey = synopsisJob?.idempotency_key;
    if (!jobKey) return;
    setMessage("正在恢复方案摘要导入...");
    setBusy("synopsis-upload");
    try {
      await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/synopsis-import/jobs/${jobKey}/resume`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "actor=medical_manager" }).then(readJson);
      setMessage("方案摘要导入已恢复，继续轮询进度...");
    } catch (error) {
      setMessage(`恢复失败：${error.message}`);
      setBusy("");
    }
  };

  const confirmSynopsisImport = async () => {
    const source = journey?.synopsis_import?.source;
    const sourceMatchesSelection = !synopsisFileIdentity || source?.content_sha256 === synopsisFileIdentity.contentSha256;
    if (!source || synopsisReplacementPending || !sourceMatchesSelection) return;
    const requestProjectId = projectId;
    const requestGeneration = synopsisSelectionGenerationRef.current;
    const requestSourceId = source.source_id;
    setBusy("synopsis-confirm"); setMessage("");
    try {
      const confirmed = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/synopsis-import/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: journey.revision, source_id: source.source_id, framing, picos, synopsis_text: synopsisText,
          acknowledged_validation_warnings: synopsisAcknowledged, validation_override_reason: synopsisOverrideReason,
          actor: "medical_manager", idempotency_key: `authoring-synopsis-confirm-${projectId}-${source.source_id}-${journey.revision}`.slice(0, 200),
        }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId || synopsisSelectionGenerationRef.current !== requestGeneration) return;
      if (confirmed.synopsis_import?.source?.source_id !== requestSourceId) throw new Error("确认结果与当前方案摘要来源不一致，请重新读取");
      applyJourneyResponse(confirmed);
      setStage("framing"); setGroup("identity");
      setMessage("摘要候选已写入统一研究定义草稿。请从第一步开始逐项补全并完成医学确认。");
    } catch (error) {
      if (activeProjectRef.current === requestProjectId && synopsisSelectionGenerationRef.current === requestGeneration) setMessage(`摘要确认失败：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestProjectId && synopsisSelectionGenerationRef.current === requestGeneration) setBusy("");
    }
  };

  // Reconnect to a persisted active synopsis-import job on mount/refresh.
  useEffect(() => {
    if (!projectId) return;
    let stored;
    try { stored = JSON.parse(localStorage.getItem(`mw_synopsis_job_${projectId}`) || "null"); } catch (e) { stored = null; }
    if (!stored || !stored.idempotency_key) return;
    let cancelled = false;
    const controller = new AbortController();
    const checkJob = async () => {
      try {
        const status = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/synopsis-import/jobs/${stored.idempotency_key}`, { signal: controller.signal }).then(readJson);
        if (cancelled) return;
        if (status.status === "review_ready" || status.status === "cancelled" || status.status === "failed") {
          try { localStorage.removeItem(`mw_synopsis_job_${projectId}`); } catch (e) { /* ignore */ }
          return;
        }
        setSynopsisJob(status);
        setBusy("synopsis-upload");
        setMessage(`已重连到正在进行的方案摘要导入（${status.phase || status.status}）...`);
        synopsisJobRef.current = stored.idempotency_key;
        const poll = async () => {
          while (!cancelled && synopsisJobRef.current === stored.idempotency_key) {
            await new Promise((r) => setTimeout(r, 3000));
            if (cancelled || synopsisJobRef.current !== stored.idempotency_key) return;
            try {
              const st = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/synopsis-import/jobs/${stored.idempotency_key}`).then(readJson);
              if (cancelled) return;
              setSynopsisJob(st);
              if (st.status === "review_ready") {
                const result = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/synopsis-import/jobs/${stored.idempotency_key}/result`).then(readJson);
                if (cancelled) return;
                applyJourneyResponse(result);
                setSynopsisJob(null);
                try { localStorage.removeItem(`mw_synopsis_job_${projectId}`); } catch (e) { /* ignore */ }
                setBusy("");
                setMessage("摘要解析完成，请核对文件角色、适应症和提取候选。");
                return;
              }
              if (st.status === "cancelled" || st.status === "failed") {
                setSynopsisJob(null);
                try { localStorage.removeItem(`mw_synopsis_job_${projectId}`); } catch (e) { /* ignore */ }
                setBusy("");
                setMessage(st.status === "cancelled" ? "方案摘要导入已取消。" : `导入失败：${st.error_message || ""}`);
                return;
              }
            } catch (e) {
              if (!cancelled) setMessage(`轮询失败：${e.message}`);
              return;
            }
          }
        };
        poll();
      } catch (e) {
        try { localStorage.removeItem(`mw_synopsis_job_${projectId}`); } catch (err) { /* ignore */ }
      }
    };
    checkJob();
    return () => { cancelled = true; controller.abort(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const commitPayload = async (targetStage, payload, previewId = "") => {
    const requestProjectId = projectId;
    const sourceRevision = journey.revision;
    const idempotencyKey = await stableAuthoringWriteKey(requestProjectId, `commit-${targetStage}`, sourceRevision, payload, previewId);
    let response;
    try {
      response = await fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey/stages/${targetStage}/commit`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: sourceRevision, stage: targetStage, [targetStage]: payload, impact_preview_id: previewId, actor: "medical_manager", idempotency_key: idempotencyKey }),
      }).then(readJson);
    } catch (error) {
      if (!shouldReconcileWrite(error)) throw error;
      response = await reconcileJourneyWrite(requestProjectId, (current) => current.revision > sourceRevision && writePayloadMatches(persistedStagePayload(current, targetStage), payload) && !current?.[`${targetStage}_draft`]);
      if (!response) throw error;
    }
    if (activeProjectRef.current !== requestProjectId) return response;
    applyJourneyResponse(response); setImpact(null);
    onJourneyChanged?.(response);
    if (targetStage === "framing" && response.framing_complete) {
      if (!existingDocument) { setStage("picos"); setGroup("applicability"); }
      await runPublicSearch(response);
    }
    if (targetStage === "picos" && response.picos_complete && !existingDocument) { setStage("corpus"); setGroup("corpus"); }
    return response;
  };

  const saveStage = async (targetStage) => {
    if (authoringWriteBlocked) {
      setMessage(authoringWriteBlockedMessage);
      return;
    }
    const payload = targetStage === "framing" ? framing : normalizePicosForWrite(picos);
    setBusy(`save-${targetStage}`); setMessage("");
    try {
      if (!journey) {
        const requestProjectId = projectId;
        const sourceRevision = 0;
        const idempotencyKey = await stableAuthoringWriteKey(requestProjectId, "create-with-framing", sourceRevision, payload);
        let created;
        try {
          created = await fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ framing: payload, actor: "medical_manager", idempotency_key: idempotencyKey }) }).then(readJson);
        } catch (error) {
          if (!shouldReconcileWrite(error)) throw error;
          created = await reconcileJourneyWrite(requestProjectId, (current) => current.revision > sourceRevision && current.entry_mode === "guided_greenfield" && writePayloadMatches(current.framing, payload));
          if (!created) throw error;
        }
        if (activeProjectRef.current !== requestProjectId) return;
        applyJourneyResponse(created);
        if (created.framing_complete) { setStage("picos"); setGroup("applicability"); await runPublicSearch(created); }
        return;
      }
      const preview = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: journey.revision, stage: targetStage, [targetStage]: payload }) }).then(readJson);
      if (preview.requires_confirmation) { setImpact({ preview, targetStage, payload }); return; }
      await commitPayload(targetStage, payload);
    } catch (error) { setMessage(`保存未完成：${error.message}`); }
    finally { setBusy(""); }
  };

  const saveDraft = async (targetStage, baseJourneyOverride = null) => {
    if (authoringWriteBlocked) {
      setMessage(authoringWriteBlockedMessage);
      return null;
    }
    const payload = targetStage === "framing" ? framing : normalizePicosForWrite(picos);
    const requestProjectId = projectId;
    setBusy(`draft-${targetStage}`); setMessage("");
    try {
      let baseJourney = baseJourneyOverride || journey;
      if (!baseJourney) {
        baseJourney = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ framing: {}, actor: "medical_manager", idempotency_key: `authoring-create-draft-shell-${projectId}` }),
        }).then(readJson);
      }
      const sourceRevision = baseJourney.revision;
      const idempotencyKey = await stableAuthoringWriteKey(requestProjectId, `draft-${targetStage}`, sourceRevision, payload);
      let response;
      try {
        response = await fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey/stages/${targetStage}/draft`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_revision: sourceRevision, stage: targetStage, [targetStage]: payload, actor: "medical_manager", idempotency_key: idempotencyKey }),
        }).then(readJson);
      } catch (error) {
        if (!shouldReconcileWrite(error)) throw error;
        response = await reconcileJourneyWrite(requestProjectId, (current) => current.revision > sourceRevision && writePayloadMatches(current?.[`${targetStage}_draft`]?.[targetStage], payload));
        if (!response) {
          const isStaleRevision = error?.status === 409
            && String(error?.message || "").includes("stale authoring journey revision");
          if (!isStaleRevision) throw error;

          // A background projection may advance the journey while the user is
          // editing. Refresh the revision and retry this explicit draft save
          // once; transport failures and unknown outcomes are never replayed.
          const latest = await fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey`).then(readJson);
          if (activeProjectRef.current !== requestProjectId || latest.revision <= sourceRevision) throw error;
          const retryKey = await stableAuthoringWriteKey(
            requestProjectId,
            `draft-${targetStage}`,
            latest.revision,
            payload,
          );
          response = await fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey/stages/${targetStage}/draft`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ expected_revision: latest.revision, stage: targetStage, [targetStage]: payload, actor: "medical_manager", idempotency_key: retryKey }),
          }).then(readJson);
        }
      }
      if (activeProjectRef.current !== requestProjectId) return;
      applyJourneyResponse(response);
      const missingCount = response?.[`${targetStage}_draft`]?.missing_required_fields?.length || 0;
      setMessage(`草稿已保存，未完成本阶段${missingCount ? `；仍有${missingCount}项必填内容待确认` : "；内容完整后仍需点击完成本阶段"}。`);
      return response;
    } catch (error) { setMessage(`草稿保存失败：${error.message}`); }
    finally { setBusy(""); }
  };

  const saveCurrentDrafts = async () => {
    let baseJourney = journey;
    if (framingDirty) {
      baseJourney = await saveDraft("framing", baseJourney);
      if (!baseJourney) return;
    }
    if (stage === "picos" && picosDirty) {
      await saveDraft("picos", baseJourney);
    }
  };

  const saveMinimumAndSearch = async ({
    conflictRetried = false,
    lockToken = "",
    baseJourneyOverride = null,
  } = {}) => {
    if (!framingSearchReady) return;
    const requestProjectId = projectId;
    const ownsLock = !lockToken;
    const activeLockToken = lockToken
      || `${requestProjectId}:${Date.now()}:${Math.random().toString(16).slice(2)}`;
    if (
      automaticMinimumSearchLockRef.current
      && automaticMinimumSearchLockRef.current !== activeLockToken
    ) return { status: "already_running" };
    if (ownsLock && busy) return;
    automaticMinimumSearchLockRef.current = activeLockToken;
    setMessage("");
    try {
      let searchableJourney = baseJourneyOverride || journey;
      if (framingDirty || !searchableJourney?.search_plan) {
        searchableJourney = await saveDraft("framing", searchableJourney);
      }
      if (!searchableJourney) return;

      if (!searchableJourney.framing?.clinicaltrials_condition_term?.trim()) {
        if (
          !searchableJourney.prefill_package
          || searchableJourney.prefill_package.journey_revision !== searchableJourney.revision
        ) {
          searchableJourney = await requestPrefillPackage(searchableJourney, true, requestProjectId);
          if (activeProjectRef.current !== requestProjectId) return;
          applyJourneyResponse(searchableJourney);
        }
        const recommendedTerm = recommendedClinicalTrialsSearchCandidate(searchableJourney);
        if (recommendedTerm) {
          searchableJourney = await requestPrefillAdoption(
            searchableJourney,
            "framing.clinicaltrials_condition_term",
            recommendedTerm,
            "prefill-adopt-minimum-search",
          );
          if (activeProjectRef.current !== requestProjectId) return;
          applyJourneyResponse(searchableJourney);
          onJourneyChanged?.(searchableJourney);
        }
      }

      if (searchableJourney.search_plan) {
        return runPublicSearch(searchableJourney, {
          adoptionConfirmed: Boolean(searchableJourney.framing?.clinicaltrials_condition_term?.trim()),
          requestProjectId,
        });
      }
      setResearchRecovery({ projectId: requestProjectId, adoptionConfirmed: false });
      return { status: "missing_search_plan" };
    } catch (error) {
      if (error.status === 409 && !conflictRetried) {
        try {
          const refreshed = await reloadJourneyAfterPrefillConflict(requestProjectId);
          if (activeProjectRef.current !== requestProjectId) return { status: "stale_project" };
          return await saveMinimumAndSearch({
            conflictRetried: true,
            lockToken: activeLockToken,
            baseJourneyOverride: refreshed,
          });
        } catch (reloadError) {
          error = reloadError;
        }
      }
      if (activeProjectRef.current === requestProjectId) {
        const technicalConflict = /stale journey revision|expected revision|actual revision/i.test(
          String(error?.message || ""),
        );
        setMessage(
          technicalConflict
            ? "最小信息已保留，公开研究调研暂未完成，可直接重试。"
            : `最小信息已保留，但自动检索未完成：${error.message}`,
        );
        setResearchRecovery({ projectId: requestProjectId, adoptionConfirmed: false });
      }
      return { status: "failed", error };
    } finally {
      if (
        activeProjectRef.current === requestProjectId
        && automaticMinimumSearchLockRef.current === activeLockToken
      ) {
        automaticMinimumSearchLockRef.current = "";
      }
    }
  };

  useEffect(() => {
    if (
      readOnly
      || loading
      || loadError
      || !journey
      // Do not launch public search or the parent research pipeline when a
      // greenfield candidate is being reopened from the writing workspace.
      // Search remains an explicit action for this already-created document.
      || journey.current_stage === "writing"
      || journey.status === "document_created"
      || busy
      || automaticMinimumSearchLockRef.current
      || !framingSearchReady
      || journey.search_plan?.latest_snapshot_id
      || journey.discovery_basket_projection?.snapshot_id
    ) return;
    const minimumFactKey = [
      projectId,
      framing.investigational_product?.trim(),
      framing.indication?.trim(),
      framing.study_phase?.trim(),
    ].join(":");
    if (automaticResearchAttemptRef.current === minimumFactKey) return;
    automaticResearchAttemptRef.current = minimumFactKey;
    saveMinimumAndSearch();
  }, [
    busy,
    framing.indication,
    framing.investigational_product,
    framing.study_phase,
    framingSearchReady,
    journey?.current_stage,
    journey?.project_id,
    journey?.status,
    journey?.search_plan?.latest_snapshot_id,
    journey?.discovery_basket_projection?.snapshot_id,
    loadError,
    loading,
    projectId,
    readOnly,
  ]);

  const confirmImpact = async () => {
    if (!impact) return;
    setBusy("confirm-impact"); setMessage("");
    try { await commitPayload(impact.targetStage, impact.payload, impact.preview.preview_id); }
    catch (error) { setMessage(`变更未提交：${error.message}`); }
    finally { setBusy(""); }
  };

  const overrideCorpusGate = async () => {
    const requestProjectId = projectId;
    const sourceRevision = journey.revision;
    const missingLabels = Array.isArray((journey?.corpus_gate || {}).missing_requirements)
      ? [...((journey?.corpus_gate || {}).missing_requirements || [])]
      : [];
    const ack = [...new Set(acknowledged || [])].sort();
    const reasonText = (overrideReason || "").trim();
    if (!missingLabels.every((label) => ack.includes(label))) {
      setMessage("例外放行前请逐项确认全部未满足条件。");
      return;
    }
    const overridePayload = { reason: reasonText, acknowledged_missing_requirements: ack };
    setBusy("override"); setMessage("");
    try {
      const idempotencyKey = await stableAuthoringWriteKey(requestProjectId, "corpus-override", sourceRevision, overridePayload);
      let response;
      try {
        response = await fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey/corpus-gate/override`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: sourceRevision, ...overridePayload, actor: "medical_manager", idempotency_key: idempotencyKey }) }).then(readJson);
      } catch (error) {
        if (!shouldReconcileWrite(error)) throw error;
        response = await reconcileJourneyWrite(requestProjectId, (current) => current.revision > sourceRevision && current.corpus_gate?.override?.active && current.corpus_gate.override.reason === overridePayload.reason && writePayloadMatches([...(current.corpus_gate.override.acknowledged_missing_requirements || [])].sort(), overridePayload.acknowledged_missing_requirements));
        if (!response) throw error;
      }
      if (activeProjectRef.current !== requestProjectId) return;
      setJourney(response); setMessage("已记录医学例外放行；语料状态仍保持“未就绪”，缺口不会被隐藏。");
    } catch (error) { setMessage(`例外放行未完成：${error.message}`); }
    finally { setBusy(""); }
  };

  const createDocument = async () => {
    setBusy("create-document"); setMessage("");
    try {
      if (hasUncommittedChanges) throw new Error("存在未完成提交的研究框架或PICOS草稿，请先完成对应阶段并重新核验影响");
      const approvedFraming = journey.framing;
      const approvedPicos = journey.picos;
      const studyDefinition = journey.study_definition;
      if (!studyDefinition?.definition_id || !studyDefinition?.revision || !studyDefinition?.state_sha256) throw new Error("统一研究定义尚未完成版本绑定，请返回两阶段设计并重新提交");
      const defaultTemplate = await fetch("/api/medical-writing/protocol-templates/default").then(readJson);
      if (!defaultTemplate?.template_id || !defaultTemplate?.template_version) throw new Error("默认方案模板身份不可用，请刷新后重试");
      // 作者确认装配计划（P0#1修复）：进入写作平台即作者对装配计划的确认动作；
      // 先读取当前计划版本与哈希，再按CAS契约确认，避免PlanUnconfirmedError阻断建稿。
      const planState = await fetch(`/api/projects/${projectId}/medical-writing/protocol-assembly-plan`, { signal: undefined }).then(readJson);
      const plan = planState?.plan;
      if (!plan?.revision || !plan?.state_sha256) throw new Error("装配计划尚未就绪，请先完成研究框架与PICOS设计并重新核验");
      await fetch(`/api/projects/${projectId}/medical-writing/protocol-assembly-plan/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_plan_revision: plan.revision,
          expected_plan_sha256: plan.state_sha256,
          actor: "medical_manager",
          idempotency_key: `assembly-plan-confirm-${projectId}-${plan.revision}-${plan.state_sha256.slice(0, 16)}`.slice(0, 200),
        }),
      }).then(readJson);
      const response = await fetch(`/api/projects/${projectId}/medical-writing/greenfield-document`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ protocol_id: approvedFraming.protocol_id, version: approvedFraming.version, document_title: approvedFraming.document_title, indication: approvedFraming.indication, study_phase: approvedFraming.study_phase, source_study_definition_id: studyDefinition.definition_id, source_study_definition_revision: studyDefinition.revision, source_study_definition_sha256: studyDefinition.state_sha256, template_id: defaultTemplate.template_id, template_version: defaultTemplate.template_version, actor: "medical_manager", idempotency_key: `greenfield-from-definition-${projectId}-${studyDefinition.definition_id}-${studyDefinition.revision}-${defaultTemplate.template_version}`.slice(0, 200) }) }).then(readJson);
      onCreated(response);
    } catch (error) { setMessage(`建立工作稿失败：${error.message}`); }
    finally { setBusy(""); }
  };

  if (loading) return <div className="authoring-journey-loading"><RefreshCw size={16} /> 正在恢复建项进度...</div>;
  if (loadError) return <div className="authoring-journey-load-failure"><ShieldAlert size={20} /><div><strong>无法确认当前建项状态</strong><span>{loadError}</span></div><button type="button" onClick={() => setLoadNonce((value) => value + 1)}><RefreshCw size={14} /> 重新读取</button></div>;
  const header = <header className="authoring-journey-header"><div><span>{readOnly ? "当前方案的研究设计基线" : existingDocument ? "调整当前方案研究设计" : "新建中国临床试验方案"}</span><h2>{readOnly ? "研究框架、PICOS与语料依据" : existingDocument ? "研究设计受控变更" : journey ? "研究设计引导" : "建立研究方案"}</h2>{focusLabel && <small className="authoring-focus-context">当前定位：{focusLabel}</small>}</div><div className="authoring-journey-state"><span>项目状态</span><strong>{journey ? statusLabel(journey) : preferredEntryMode ? "正在恢复已选写作路径" : "选择开始方式"}</strong>{journey && <small>{entryMode === "synopsis_import" ? "来源：导入已有方案/方案摘要" : "来源：从零开始"} · 版本 {journey.revision}</small>}</div></header>;
  if (!journey && preferredEntryMode) return <div className="authoring-journey-shell">{header}<main className="authoring-journey-body"><section className="authoring-entry-mode"><header><div><strong>{preferredEntryMode === "synopsis_import" ? "准备导入已有方案/方案摘要" : "准备两阶段研究设计引导"}</strong><span>系统正在按新建项目时确认的路径建立写作任务，无需再次选择。</span></div></header><p><RefreshCw size={14} /> {busy ? "正在建立写作任务..." : "写作任务尚未建立"}</p>{message && <button type="button" onClick={() => createJourney(preferredEntryMode)} disabled={Boolean(busy)}><RefreshCw size={14} /> 重新建立写作任务</button>}</section></main>{message && <p className="authoring-journey-message danger">{message}</p>}</div>;
  if (!journey) return <div className="authoring-journey-shell">{header}<main className="authoring-journey-body"><EntryModeChooser busy={busy} onSelect={createJourney} /></main>{message && <p className="authoring-journey-message danger">{message}</p>}</div>;
  if (synopsisReviewPending(journey)) {
    const validationWarnings = journey.synopsis_import?.source?.validation_warnings || [];
    const allWarningsAcknowledged = validationWarnings.every((item) => synopsisAcknowledged.includes(item));
    const sourceMatchesSelection = Boolean(journey.synopsis_import?.source && (!synopsisFileIdentity || journey.synopsis_import.source.content_sha256 === synopsisFileIdentity.contentSha256));
    const canConfirm = Boolean(sourceMatchesSelection && !synopsisReplacementPending && synopsisText.trim() && allWarningsAcknowledged);
    const synopsisInteractionLocked = ["synopsis-upload", "synopsis-confirm"].includes(busy);
    return <div className="authoring-journey-shell">{header}<main className="authoring-journey-body"><SynopsisImportPanel journey={journey} file={synopsisFile} uploadKey={synopsisUploadKey} replacementPending={synopsisReplacementPending} framing={framing} picos={picos} synopsisText={synopsisText} acknowledged={synopsisAcknowledged} overrideReason={synopsisOverrideReason} busy={busy} interactionLocked={synopsisInteractionLocked} onFile={selectSynopsisFile} onUpload={uploadSynopsis} onFraming={updateFraming} onPicos={updatePicos} onSynopsisText={setSynopsisText} onAcknowledged={setSynopsisAcknowledged} onOverrideReason={setSynopsisOverrideReason} /></main>{message && <p className={`authoring-journey-message ${message.includes("失败") ? "danger" : ""}`}>{message}</p>}{journey.synopsis_import?.source && <footer className="authoring-journey-footer synopsis-import-footer"><span>{synopsisReplacementPending ? "已选择替换文件；重新解析完成前，当前候选不可确认。" : "导入候选不会直接成为正式研究事实；确认后仍需完成研究框架和PICOS两阶段医学审核。"}</span><button className="primary-button" type="button" onClick={confirmSynopsisImport} disabled={Boolean(busy) || !canConfirm}><CheckCircle2 size={15} /> {busy === "synopsis-confirm" ? "确认中" : "确认并进入两阶段补全"}</button></footer>}</div>;
  }
  const corpusReady = journey?.corpus_gate?.readiness_status === "ready";
  const corpusException = Boolean(journey?.corpus_gate?.access_permitted && !corpusReady);
  const stageItems = [{ key: "framing", index: "01", label: "研究框架", done: Boolean(journey?.framing_complete) }, { key: "picos", index: "02", label: "PICOS设计", done: Boolean(journey?.picos_complete) }, { key: "corpus", index: "03", label: "语料准备", done: corpusReady, exception: corpusException }];
  const groups = stage === "framing" ? FRAMING_GROUPS : stage === "picos" ? PICOS_GROUPS : [];
  const missing = journey?.corpus_gate?.missing_requirements || [];
  const allAcknowledged = missing.length > 0 && missing.every((item) => acknowledged.includes(item));
  const interactionLocked = Boolean(busy || impact);
  const openAdvancedRefinementForPrefill = (fieldPath) => {
    const destination = prefillDestination(fieldPath);
    const seedFromPrefill = () => {
      const group = journey?.prefill_package?.field_candidates?.[fieldPath];
      const recommended = recommendedPrefillCandidate(group);
      if (!recommended || !STRING_PREFILL_FIELDS.has(fieldPath)) return;
      const preview = typeof recommended.structured_value === "string"
        ? recommended.structured_value
        : (recommended.preview || "");
      const nextValue = String(preview || "").trim();
      if (!nextValue || nextValue.includes("待确认")) return;
      if (fieldPath.startsWith("framing.")) {
        const key = fieldPath.slice("framing.".length);
        setFraming((current) => (String(current[key] || "").trim() ? current : { ...current, [key]: nextValue }));
      } else if (fieldPath.startsWith("picos.")) {
        const key = fieldPath.slice("picos.".length);
        setPicos((current) => (String(current[key] || "").trim() ? current : { ...current, [key]: nextValue }));
      }
    };
    seedFromPrefill();
    if (!destination) {
      setAdvancedRefinementOpen(true);
      return;
    }
    if (destination.stage === "picos" && (!journey.framing_complete || framingDirty || framingPendingDraft)) {
      setMessage("该项属于PICOS高级微调；请先完成研究框架确认。已打开高级微调面板，当前AI建议仍会保留。");
      setStage("framing");
      setGroup(destination.group === "applicability" ? "design" : "identity");
      setPrefillSection("design");
      setAdvancedRefinementOpen(true);
      return;
    }
    setStage(destination.stage);
    setGroup(destination.group);
    setPrefillSection(destination.stage === "picos" ? (destination.group === "applicability" ? "design" : "picos") : destination.group === "design" ? "design" : "identity");
    setAdvancedRefinementOpen(true);
  };
  const competitorSnapshotId = journey?.search_plan?.latest_snapshot_id
    || journey?.discovery_basket_projection?.snapshot_id
    || "";
  const competitorSearchCount = journey?.search_plan?.returned_count || 0;
  const compactResearchPipeline = pipelineStatus?.pipeline || {};
  const compactResearchPercent = Math.max(
    0,
    Math.min(100, Number(compactResearchPipeline.percent || 0)),
  );
  const compactResearchChildTotal = Number(
    compactResearchPipeline.child_total || 0,
  );
  const compactResearchChildCompleted = Number(
    compactResearchPipeline.child_completed || 0,
  );
  const compactResearchChildPercent = Number.isFinite(
    Number(compactResearchPipeline.child_percent),
  )
    ? Number(compactResearchPipeline.child_percent)
    : compactResearchPercent;
  const compactResearchLabel = compactResearchPipeline.child_label
    || PIPELINE_STAGE_LABELS[compactResearchPipeline.stage]
    || "正在启动公开研究检索";
  const preparationHasChildIssue = compactResearchPipeline.stage === "awaiting_preparation_admission"
    && String(compactResearchPipeline.child_label || "").includes("失败");
  const compactResearchActive = Boolean(compactResearchPipeline.stage)
    && !PIPELINE_TERMINAL_STAGES.has(compactResearchPipeline.stage)
    && !PIPELINE_STABLE_WAITING_STAGES.has(compactResearchPipeline.stage);
  const showCompactResearchProgress = !competitorSnapshotId
    || (Boolean(compactResearchPipeline.stage)
      && !PIPELINE_TERMINAL_STAGES.has(compactResearchPipeline.stage));
  const competitorToolbarSummary = competitorSnapshotId
    ? (compactResearchPipeline.stage === "awaiting_corpus_admission"
      && [
        "no_retainable_candidates_after_confirm",
        "no_retainable_candidates",
        "no_public_protocol_results",
      ].includes(String(compactResearchPipeline.error_summary || ""))
      ? "公开检索未发现可保留Protocol；未启动下载、OCR或翻译，请在语料准入处选择共享语料、手动上传或记录例外。"
      : compactResearchPipeline.stage === "failed"
      ? pipelineStatus?.pipeline_retryable
        ? `公开研究检索已保留${competitorSearchCount ? ` · ${competitorSearchCount} 项研究` : ""}；后续语料分析未完成，已完成原文、OCR和翻译可复用。`
        : `公开研究检索已保留${competitorSearchCount ? ` · ${competitorSearchCount} 项研究` : ""}；后续处理未完成，请查看原因并重试。`
      : compactResearchPipeline.stage === "awaiting_preparation_admission"
        ? `公开Protocol已完成第一批处理；仍有资料待下一阶段准入，已完成项不会重复下载或OCR。${preparationHasChildIssue ? "另有文件原文/OCR未通过，请先查看竞品资料中的处理结果。" : ""}`
      : compactResearchPipeline.stage === "cancelled"
        ? "公开研究检索已保留；后续处理已取消，可查看现有资料后重试。"
        : showCompactResearchProgress
          ? `已锁定${competitorSearchCount ? ` ${competitorSearchCount} 项` : ""}候选研究；${compactResearchLabel}，可同时查看已准备资料。`
          : `公开研究处理已完成${competitorSearchCount ? ` · ${competitorSearchCount} 项研究` : ""}；可随时查看分诊结果与原文。`)
    : "项目已建立；系统将自动检索并处理竞品研究，当前草稿会持续保留。";
  const openCompetitorDrawer = () => setCompetitorDrawerOpen(true);
  const closeCompetitorDrawer = () => setCompetitorDrawerOpen(false);

  // When the drawer recovers the latest triage run it also re-reads the parent
  // research-pipeline status.  Propagate that payload into our own pipelineStatus
  // so the compact toolbar and banner converge to the same terminal state the
  // drawer already observes — but only if the pipeline still belongs to the
  // currently mounted project, and without clobbering the existing stale guards.
  const handleTriagePipelineChange = (pipeline) => {
    if (activeProjectRef.current !== projectId) return;
    setPipelineStatus((current) => {
      if (!pipeline) return current;
      // Preserve any fields the parent owns (e.g. triage_retryable,
      // design_recommendations_unlocked) that the drawer-side payload may omit.
      return { ...(current || {}), pipeline };
    });
    // If the drawer reports a non-terminal/non-waiting stage, resume polling so
    // subsequent stage transitions continue to flow without manual re-entry.
    const stage = pipeline?.stage || "";
    if (
      stage
      && !PIPELINE_TERMINAL_STAGES.has(stage)
      && !PIPELINE_STABLE_WAITING_STAGES.has(stage)
    ) {
      setPipelinePollNonce((current) => current + 1);
    }
  };
  return (
    <div className="authoring-journey-shell">
      {header}
      {!readOnly && pipelineStatus?.pipeline?.stage && (
        <details
          className="authoring-research-progress-details"
          open={researchProgressOpen}
          onToggle={(event) => setResearchProgressOpen(event.currentTarget.open)}
        >
          <summary>
            <span>
              <Search size={14} />
              <strong>竞品调研进度</strong>
            </span>
            <small>{PIPELINE_STAGE_LABELS[pipelineStatus.pipeline.stage] || "处理中"}</small>
          </summary>
          <ResearchPipelineBanner
            status={pipelineStatus}
            busy={busy}
            onCancel={cancelResearchPipeline}
            onContinueAfterTriage={continueResearchPipelineAfterTriage}
          onOpenFileIssues={openResearchPipelineFileIssues}
          onOpenCorpusAdmission={() => {
            setStage("corpus");
            setGroup("corpus");
            setAdvancedRefinementOpen(false);
          }}
          onResume={resumeResearchPipeline}
            onRetryTriage={retryResearchPipelineTriage}
            onStartRound2={startResearchPipelineRound2}
          />
        </details>
      )}
      <nav className="authoring-stage-strip" aria-label="医学写作建项步骤">{stageItems.map((item) => { const disabled = interactionLocked || (item.key === "picos" && (!journey?.framing_complete || framingDirty || framingPendingDraft)) || (item.key === "corpus" && (!journey?.picos_complete || hasUncommittedChanges)); return <button key={item.key} type="button" className={`${stage === item.key ? "active" : ""} ${item.done ? "done" : ""} ${item.exception ? "exception" : ""}`} onClick={() => { if (disabled) return; setStage(item.key); setGroup(item.key === "framing" ? "identity" : item.key === "picos" ? "applicability" : "corpus"); setPrefillSection(item.key === "picos" ? "design" : "identity"); setAdvancedRefinementOpen(Boolean(readOnly)); }} disabled={disabled}><span>{item.done ? <CheckCircle2 size={15} /> : item.exception ? <ShieldAlert size={14} /> : item.index}</span><strong>{item.label}</strong></button>; })}</nav>
      {stage !== "corpus" && (
        <div className="authoring-competitor-toolbar" data-testid="authoring-competitor-toolbar">
          <div>
            <Search size={15} />
            <span>
              <strong>竞品方案处理</strong>
              <small>{competitorToolbarSummary}</small>
            </span>
          </div>
          <div className="authoring-competitor-toolbar-actions">
            {showCompactResearchProgress && (
              <span
                className="authoring-automatic-research-state"
                data-testid="authoring-automatic-research-progress"
              >
                <RefreshCw className={compactResearchActive || busy ? "spin" : ""} size={14} />
                <span>
                  <strong>{compactResearchLabel}</strong>
                  <small>
                    {compactResearchChildTotal > 0
                      ? `已完成 ${compactResearchChildCompleted}/${compactResearchChildTotal} · ${compactResearchChildPercent}%`
                      : `${compactResearchPercent}%`}
                  </small>
                  <span
                    className="authoring-automatic-research-track"
                    role="progressbar"
                    aria-label="竞品调研进度"
                    aria-valuemin="0"
                    aria-valuemax="100"
                    aria-valuenow={compactResearchPercent}
                  >
                    <span style={{ width: `${compactResearchPercent}%` }} />
                  </span>
                </span>
              </span>
            )}
            {competitorSnapshotId ? (
              <button
                type="button"
                className="authoring-open-competitor-drawer"
                data-action="open-competitor-drawer"
                data-testid="open-competitor-drawer"
                onClick={openCompetitorDrawer}
                disabled={interactionLocked}
                title="打开竞品处理抽屉"
              >
                <Search size={14} /> 查看竞品资料
              </button>
            ) : researchRecovery?.projectId === projectId ? (
              <button
                type="button"
                className="authoring-light-retry"
                onClick={retryAutomaticResearch}
                disabled={Boolean(busy)}
              >
                <RefreshCw size={14} /> 重试
              </button>
            ) : null}
            {compactResearchPipeline.stage === "failed"
              && pipelineStatus?.pipeline_retryable
              && (
                <button
                  type="button"
                  className="authoring-light-retry"
                  onClick={resumeResearchPipeline}
                  disabled={Boolean(busy)}
                  title={busy ? "正在复核已完成资料，请稍候" : "复用已完成原文、OCR和翻译，仅重试后续语料分析"}
                >
                  <RefreshCw size={14} /> {busy === "pipeline-resume" ? "重试中" : "重试后续语料分析"}
                </button>
              )}
            {compactResearchPipeline.stage === "awaiting_preparation_admission"
              && (
                <button
                  type="button"
                  className="authoring-light-retry"
                  onClick={resumeResearchPipeline}
                  disabled={Boolean(busy)}
                  title={busy ? "正在准入下一批原文，请稍候" : "复用已完成原文和OCR结果，准入下一批公开Protocol"}
                >
                  <RefreshCw size={14} /> {busy === "pipeline-resume" ? "准入中" : "准入下一阶段原文"}
                </button>
              )}
            {["awaiting_translation_scope", "awaiting_corpus_analysis"].includes(
              compactResearchPipeline.stage,
            ) && (
              <button
                type="button"
                className="authoring-light-retry"
                onClick={resumeResearchPipeline}
                disabled={Boolean(busy)}
                title={busy ? "正在复用已完成资料并继续，请稍候" : "复用已完成原文、OCR和翻译，从当前等待节点继续"}
              >
                <RefreshCw size={14} /> {busy === "pipeline-resume"
                  ? "继续中"
                  : compactResearchPipeline.stage === "awaiting_corpus_analysis"
                    ? "重试后续语料分析"
                    : "继续翻译与分析"}
              </button>
            )}
          </div>
        </div>
      )}
      <main className="authoring-journey-body"><fieldset className="authoring-journey-fieldset" disabled={interactionLocked || (readOnly && stage !== "corpus")}>
        {stage !== "corpus" && <PrefillRecommendations
          journey={journey}
          prefillPackage={journey.prefill_package}
          searchPlan={journey.search_plan}
          busy={busy}
          readOnly={readOnly}
          activeSection={prefillSection}
          onSectionChange={setPrefillSection}
          onAdopt={adoptPrefillCandidate}
          onAdoptComposite={adoptPrefillComposite}
          onDefer={(fieldPath) => setDeferredPrefillFields((current) => current.includes(fieldPath) ? current.filter((item) => item !== fieldPath) : [...current, fieldPath])}
          onRefine={openAdvancedRefinementForPrefill}
          onRegenerate={() => generatePrefill(journey, true)}
          deferredFields={deferredPrefillFields}
          compositeReceipt={compositeAdoptReceipt}
          onOpenCompetitorDrawer={openCompetitorDrawer}
        />}
        {stage !== "corpus" && <details className="authoring-advanced-refinement" open={advancedRefinementOpen} onToggle={(event) => setAdvancedRefinementOpen(event.currentTarget.open)}>
          <summary><span><strong>高级微调</strong><small>仅在需要逐字段改写、补充精确规则或处理“其他”设计时展开</small></span><em>{groups.find((item) => item.key === group)?.label || "选择字段组"}</em></summary>
          <div className="authoring-group-tabs" role="tablist">{groups.map((item) => <button key={item.key} type="button" role="tab" aria-selected={group === item.key} className={group === item.key ? "active" : ""} onClick={() => setGroup(item.key)} disabled={interactionLocked}>{item.label}</button>)}</div>
          <div className="authoring-advanced-refinement-body">
            {stage === "framing" && <FramingFields projectId={projectId} framing={framing} group={group} update={updateFraming} factConversation={factConversation} setFactConversation={setFactConversation} onSubmitFactIntake={submitFactIntakeTurn} onApplyFactProposal={applyFactIntakeProposal} onAttachIb={attachInvestigatorBrochure} onMarkIbUnavailable={persistIbPacket} onAnalyzeIb={analyzeInvestigatorBrochure} busy={busy} interactionLocked={interactionLocked} />}
            {stage === "picos" && <PicosFields projectId={projectId} framing={framing} picos={picos} group={group} updateFraming={updateFraming} update={updatePicos} updateApplicability={updatePicosApplicability} interventionPanel={interventionPanel} setInterventionPanel={setInterventionPanel} hasPrefillRecommendations={Boolean(journey.prefill_package)} existingDocument={existingDocument} readOnly={readOnly} appendixReady={Boolean(journey.picos_complete && !picosDirty && !picosPendingDraft)} onSaveDesignDraft={saveCurrentDrafts} framingDirty={framingDirty} busy={busy} />}
          </div>
        </details>}
        {stage === "corpus" && <CorpusGate projectId={projectId} journey={journey} setJourney={setJourney} selectedBriefIds={selectedCorpusBriefIds} setSelectedBriefIds={setSelectedCorpusBriefIds} searchMessage={searchMessage} busy={busy} onSearch={() => runPublicSearch(journey)} acknowledged={acknowledged} setAcknowledged={setAcknowledged} overrideReason={overrideReason} setOverrideReason={setOverrideReason} allAcknowledged={allAcknowledged} onOverride={overrideCorpusGate} onCreateDocument={createDocument} onReviewAssemblyPlan={() => { setStage("picos"); setGroup("intervention"); }} readOnly={readOnly} existingDocument={existingDocument} />}
      </fieldset></main>
      {impact && <section className="authoring-impact-panel" aria-live="polite"><div><ShieldAlert size={18} /><span><strong>该变更会使下游内容失效</strong><small>确认后系统保留旧版本，并把以下对象标记为需要重新核验。</small></span></div><ul>{impact.preview.affected_dependents.map((item) => <li key={item}>{DEPENDENT_LABELS[item] || item}</li>)}</ul><div className="authoring-impact-actions"><button type="button" onClick={() => setImpact(null)}>返回修改</button><button className="primary-button" type="button" onClick={confirmImpact} disabled={busy === "confirm-impact"}>确认变更并重新核验</button></div></section>}
      {(message || hasUncommittedChanges) && <p className={`authoring-journey-message ${message.includes("失败") ? "danger" : ""}`} role="status"><span>{message || (hasUnsavedChanges ? "当前有尚未保存的修改。" : "草稿已保存，尚未提交当前阶段。")}</span>{researchRecovery?.projectId === projectId && <button type="button" onClick={retryAutomaticResearch} disabled={Boolean(busy)}><RefreshCw size={13} /> 重试</button>}</p>}
      {stage !== "corpus" && !impact && !readOnly && <footer className="authoring-journey-footer"><span>{authoringWriteBlockedMessage || (unresolvedPhase1PartCount > 0 ? `还有 ${unresolvedPhase1PartCount} 个I期Part缺少研究人群或队列/剂量方案；可先保存草稿，但投影与阶段完成继续阻断。` : stage === "framing" ? "研究药物、适应症和研究分期足以启动竞品检索；产品技术类型或给药途径未知时可先保留待确认，由IB/语料证据提出建议。" : framingPendingDraft ? "研究设计已写入第一步草稿；请返回第一步完成变更后再提交PICOS。" : "先采用或微调调研建议；精确剂量、阈值和终点仍需项目证据支持。")}</span><div>{stage === "picos" && <button type="button" onClick={() => { setStage("framing"); setGroup(isPhaseOneStudy(framing.study_phase) ? "design" : "identity"); setPrefillSection("identity"); setAdvancedRefinementOpen(true); }} disabled={authoringWriteBlocked}><ArrowLeft size={14} /> 返回第一步</button>}<button type="button" onClick={saveCurrentDrafts} disabled={authoringWriteBlocked || Boolean(busy) || (journey && !(stage === "framing" ? framingDirty : framingDirty || picosDirty))} title={authoringWriteBlocked ? authoringWriteBlockedMessage : busy ? "正在处理中，请稍候" : (journey && !(stage === "framing" ? framingDirty : framingDirty || picosDirty)) ? "当前没有需要保存的修改" : "保存当前草稿"}><Save size={14} /> {String(busy).startsWith("draft-") ? "保存中" : "保存草稿"}</button><button className="primary-button" type="button" onClick={() => saveStage(stage)} disabled={authoringWriteBlocked || Boolean(busy) || (stage === "framing" ? !framingReady : !picosReady || framingDirty || framingPendingDraft || !typedPhase1PartsReady)} title={authoringWriteBlockedMessage ? authoringWriteBlockedMessage : busy ? "正在处理中，请稍候" : stage === "framing" ? (!framingReady ? "请先补齐第一步必填项；未知产品技术类型不会阻断此步骤" : "提交并完成第一步") : framingDirty || framingPendingDraft ? "请先保存并完成第一步变更后再提交PICOS" : !typedPhase1PartsReady ? "请先补齐I期Part必填项" : !picosReady ? "请先补齐第二步必填项后再完成" : "提交并完成第二步"}>{busy === `save-${stage}` ? "提交中" : stage === "framing" ? "完成第一步" : "完成第二步"}<ArrowRight size={14} /></button></div></footer>}
      <AuthoringCompetitorDrawer
        open={competitorDrawerOpen}
        onClose={closeCompetitorDrawer}
        projectId={projectId}
        snapshotId={competitorSnapshotId}
        lockedIndication={journey.search_plan?.registry_filter?.condition_term || journey.framing?.clinicaltrials_condition_term || journey.framing?.indication || ""}
        lockedPhase={journey.framing?.study_phase || ""}
        journey={journey}
        onJourneyChange={setJourney}
        onTriagePipelineChange={handleTriagePipelineChange}
        selectedBriefIds={selectedCorpusBriefIds}
        onSelectedBriefIdsChange={setSelectedCorpusBriefIds}
        requestedView={referencePanelRequest?.view || ""}
        requestedArtifactId={referencePanelRequest?.artifactId || ""}
        focusRequestKey={referencePanelRequest?.requestKey || ""}
        keepPanelMounted
        onExecuteSearch={() => runPublicSearch(journey)}
        searchBusy={busy === "search"}
      />

    </div>
  );
}

function ResearchPipelineBanner({
  status,
  busy,
  onCancel,
  onContinueAfterTriage,
  onOpenFileIssues,
  onOpenCorpusAdmission,
  onResume,
  onRetryTriage,
  onStartRound2,
}) {
  const pipeline = status?.pipeline;
  if (!pipeline || !pipeline.stage) return null;
  const stage = pipeline.stage;
  const triageProgress = status?.triage_progress || {};
  const percent = Number.isFinite(Number(pipeline.percent))
    ? Number(pipeline.percent)
    : stage === "triaging" && Number.isFinite(triageProgress.percent)
      ? triageProgress.percent
      : 0;
  const childCompleted = Number.isFinite(Number(pipeline.child_completed))
    ? Number(pipeline.child_completed)
    : stage === "triaging" ? Number(triageProgress.completed_chunks || 0) : 0;
  const childTotal = Number.isFinite(Number(pipeline.child_total))
    ? Number(pipeline.child_total)
    : stage === "triaging" ? Number(triageProgress.total_chunks || 0) : 0;
  const childPercent = Number.isFinite(Number(pipeline.child_percent))
    ? Number(pipeline.child_percent)
    : stage === "triaging" ? Number(triageProgress.percent || 0) : 0;
  const childSubstepPercent = Number.isFinite(
    Number(pipeline.child_context?.current_substep_percent),
  )
    ? Math.max(0, Math.min(100, Number(pipeline.child_context.current_substep_percent)))
    : null;
  const childLabel = pipeline.child_label
    || (stage === "triaging" ? triageProgress.label : "")
    || "";
  const stageLabel = PIPELINE_STAGE_LABELS[stage] || stage;
  const isFailed = stage === "failed";
  const isCancelled = stage === "cancelled";
  const isCorpusReady = stage === "corpus_ready";
  const isRound2Ready = stage === "round2_ready";
  const isTerminal = PIPELINE_TERMINAL_STAGES.has(stage);
  const isWaitingForUser = PIPELINE_STABLE_WAITING_STAGES.has(stage);
  const isSourceIssueWaiting = isWaitingForUser
    && stage !== "awaiting_corpus_admission"
    && stage !== "awaiting_triage_confirm"
    && stage !== "awaiting_preparation_admission";
  const isPreparationStageWaiting = stage === "awaiting_preparation_admission";
  const emptyBasketFallback = stage === "awaiting_corpus_admission"
    && [
      "no_retainable_candidates_after_confirm",
      "no_retainable_candidates",
      "no_public_protocol_results",
    ].includes(
      String(pipeline.error_summary || ""),
    );
  const downstreamRetryable = isFailed && Boolean(status?.pipeline_retryable);
  const failedTaskMessage = String(pipeline.error_summary || "").includes(
    "HTTP 401",
  )
    ? "产品模型连接未通过鉴权；公开检索结果已保留。请修复模型连接后仅重试分诊，不会重复检索。"
    : String(pipeline.error_summary || "").includes(
    "CorpusAnalysisAiError",
  )
    ? "独立AI返回的语料分析结构未符合系统合同；已完成的原文、OCR和翻译仍保留，可直接重试后续语料分析。"
    : String(pipeline.error_summary || "").includes(
      "AI provider response is not valid JSON",
    )
      ? "独立AI接口未返回可解析的结构化结果；已完成的原文、OCR和翻译仍保留，可直接重试后续语料分析。"
      : "研究流水线未完成；可按页面提示重试。";
  const taskMessage = isFailed
    ? failedTaskMessage
    : isCancelled
      ? "研究流水线已取消，已保留已完成步骤。"
      : isCorpusReady
        ? "研究语料已准备完毕，可进入研究设计推荐。"
        : isRound2Ready
          ? "第二轮竞品分析已完成。"
          : isWaitingForUser
            ? (stage === "awaiting_triage_confirm"
              ? "竞品分诊已完成，等待确认后继续。"
              : stage === "awaiting_preparation_admission"
                ? "本阶段公开Protocol已完成；下一批原文需明确准入后继续，已完成项不会重复下载或OCR。"
              : stage === "awaiting_corpus_admission"
                ? emptyBasketFallback
                  ? "公开检索没有可保留Protocol；可使用已审核共享语料或手动上传，并在语料准入处记录项目特异理由后继续。"
                  : "第一轮竞品语料分析已完成；可继续研究设计，完整医学准入与PICOS对齐将在后续补齐。"
                : stage === "awaiting_corpus_analysis"
                  ? "独立AI未返回可解析的最终语料分析JSON；已完成的下载、OCR和翻译仍保留，可直接重试后续语料分析。"
                : stage === "awaiting_translation_scope"
                  ? "翻译范围仍需处理；已完成的原文和解析结果仍保留，可继续翻译与分析。"
                : "当前步骤需要处理后才能继续。")
            : childLabel || stageLabel;
  const blockers = Array.isArray(pipeline.document_admission_blockers)
    ? pipeline.document_admission_blockers
    : [];
  const exclusions = Array.isArray(pipeline.document_admission_exclusions)
    ? pipeline.document_admission_exclusions
    : [];
  const triageRetryable = Boolean(status?.triage_retryable);
  const unlocked = Boolean(status?.design_recommendations_unlocked);
  const busyReason = busy
    ? (busy === "pipeline-cancel"
      ? "正在取消研究流水线，请稍候"
      : busy === "pipeline-continue"
        ? "正在确认分诊并继续，请稍候"
        : busy === "pipeline-resume"
          ? "正在复核已处理文件并继续，请稍候"
        : busy === "pipeline-retry-triage"
          ? "正在继续未完成的竞品分诊，请稍候"
        : "当前有其他操作进行中，请稍候")
    : "";
  const cancelDisabled = Boolean(busy) || isTerminal;
  const continueDisabled = Boolean(busy);
  return (
    <section
      className={`research-pipeline-banner ${isFailed ? "danger" : isTerminal ? "success" : isWaitingForUser ? "waiting" : "active"}`}
      role="status"
      data-testid="research-pipeline-banner"
    >
      <div className="research-pipeline-banner-head">
        <span className="research-pipeline-banner-stage">
          {!isTerminal && !isWaitingForUser && <RefreshCw size={13} className="research-pipeline-banner-spin" />}
          {isWaitingForUser && <ShieldAlert size={13} />}
          研究流水线 · {stageLabel}
        </span>
        <span className="research-pipeline-banner-percent">
          {percent}%
        </span>
      </div>
      <div
        className="research-pipeline-banner-track"
        role="progressbar"
        aria-label="研究流水线进度"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={percent}
      ><div style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} /></div>
      {childLabel && (
        <p className="research-pipeline-banner-substep" data-testid="research-pipeline-current-substep">
          <strong>{childLabel}</strong>
          {childTotal > 0 && (
            <small>
              {childCompleted}/{childTotal} · {childPercent}%
              {childSubstepPercent !== null && ` · 子步骤 ${childSubstepPercent}%`}
            </small>
          )}
        </p>
      )}
      {isCorpusReady && (
        <p className="research-pipeline-banner-ready" role="status">
          <strong>语料已准备完毕，可进入研究设计推荐</strong>
        </p>
      )}
      {isRound2Ready && (
        <p className="research-pipeline-banner-ready" role="status">
          <strong>第二轮竞品分析已完成，可对照已确认设计复核差异</strong>
        </p>
      )}
      {emptyBasketFallback && (
        <p className="research-pipeline-banner-fallback" role="alert">
          <strong>未发现可下载的公开方案</strong>
          <span>系统没有启动下载、OCR或翻译；请打开语料准入查看可用来源和缺口。当前没有候选研究时，不会伪造上传或公开来源。</span>
        </p>
      )}
      <p>
        {taskMessage}
        {!unlocked && !isFailed && !isCancelled && !isCorpusReady ? " 语料就绪前不会开放证据化设计推荐。" : ""}
        {unlocked && !isCorpusReady ? " 证据化设计推荐已开放。" : ""}
      </p>
      {isWaitingForUser && blockers.length > 0 && (
        <div className="research-pipeline-blockers" role="alert">
          {blockers.map((blocker) => (
            <article key={blocker.artifact_id || blocker.filename}>
              <header>
                <strong>{blocker.filename || blocker.nct_id || "待处理文档"}</strong>
                <span>{[blocker.nct_id, blocker.document_type].filter(Boolean).join(" · ")}</span>
              </header>
              {(blocker.checks || []).map((check) => (
                <div key={check.check_code || check.label}>
                  <b>{check.label || "内容核验"}</b>
                  <span>{check.observed_value || "原文中未识别到可核对信息"}</span>
                  {check.expected_value && <small>当前项目预期：{check.expected_value}</small>}
                </div>
              ))}
              {!(blocker.checks || []).length && <p>{blocker.detail || blocker.required_action}</p>}
            </article>
          ))}
        </div>
      )}
      {exclusions.length > 0 && (
        <details className="research-pipeline-exclusions">
          <summary>
            已自动排除 {exclusions.length} 份不适合作为本轮章节语料的原文，不影响其余资料继续
          </summary>
          <ul>
            {exclusions.map((item) => (
              <li key={item.artifact_id || item.filename}>
                <strong>{item.nct_id || item.filename || "例外文件"}</strong>
                <span>{item.detail || item.reason_code || "未通过本轮语料准入"}</span>
                {Array.isArray(item.checks) && item.checks.length > 0 && (
                  <dl>
                    {item.checks.map((check) => (
                      <div key={check.check_code || check.label}>
                        <dt>{check.label || "内容核验"}</dt>
                        <dd>
                          <span>识别：{check.observed_value || "未识别到可核对信息"}</span>
                          {check.expected_value && <small>预期：{check.expected_value}</small>}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="research-pipeline-banner-actions">
        {emptyBasketFallback && onOpenCorpusAdmission && (
          <button
            type="button"
            className="primary-button"
            onClick={onOpenCorpusAdmission}
            disabled={Boolean(busy)}
            title={busy ? busyReason : "打开语料准入，查看共享语料、项目资料和例外放行条件"}
          >
            <FileText size={13} /> 查看语料准入
          </button>
        )}
        {downstreamRetryable && (
          <button
            type="button"
            className="primary-button"
            onClick={onResume}
            disabled={Boolean(busy)}
            title={busy ? busyReason : "复用既有原文、解析和OCR结果，仅重试翻译与后续语料分析"}
          >
            <RefreshCw size={13} /> {busy === "pipeline-resume" ? "重试中" : "从已完成原文继续"}
          </button>
        )}
        {isFailed && triageRetryable && (
          <button
            type="button"
            className="primary-button"
            onClick={onRetryTriage}
            disabled={Boolean(busy)}
            title={busy ? busyReason : "保留已完成分块，仅继续处理未完成的竞品分诊"}
          >
            <RefreshCw size={13} /> {busy === "pipeline-retry-triage" ? "继续中" : "继续未完成分诊"}
          </button>
        )}
        {isCorpusReady && (
          <button
            type="button"
            className="primary-button"
            onClick={onStartRound2}
            disabled={Boolean(busy)}
            title={busy ? busyReason : "以当前已确认研究设计启动第二轮精细化竞品分析"}
          >
            <RefreshCw size={13} /> {busy === "pipeline-round2" ? "分析中" : "启动第二轮精细化分析"}
          </button>
        )}
        {stage === "awaiting_triage_confirm" && (
          <button
            type="button"
            className="primary-button"
            onClick={onContinueAfterTriage}
            disabled={continueDisabled}
            title={continueDisabled ? busyReason : "确认分诊结果后继续研究流水线"}
          >
            <CheckCircle2 size={13} /> {busy === "pipeline-continue" ? "处理中" : "确认分诊后继续"}
          </button>
        )}
        {isSourceIssueWaiting && (
          <>
            <button
              type="button"
              onClick={onOpenFileIssues}
              disabled={Boolean(busy)}
              title={busy ? busyReason : "打开现有竞品方案处理面板，核对文件内容、结构与翻译范围"}
            >
              <FileText size={13} /> 处理文件问题
            </button>
            <button
              type="button"
              className="primary-button"
              onClick={onResume}
              disabled={continueDisabled}
              title={continueDisabled ? busyReason : "仅复核既有原文准备批次，并从当前等待节点继续"}
            >
              <CheckCircle2 size={13} /> {busy === "pipeline-resume" ? "复核中" : "已处理，继续流水线"}
            </button>
          </>
        )}
        {isPreparationStageWaiting && (
          <button
            type="button"
            className="primary-button"
            onClick={onResume}
            disabled={continueDisabled}
            title={continueDisabled ? busyReason : "准入并处理下一批延后公开Protocol；已完成项不会重跑"}
          >
            <CheckCircle2 size={13} /> {busy === "pipeline-resume" ? "准入中" : "准入下一批原文"}
          </button>
        )}
        {!isTerminal && (
          <button
            type="button"
            onClick={onCancel}
            disabled={cancelDisabled}
            title={cancelDisabled ? (isTerminal ? "流水线已结束，无需取消" : busyReason) : "取消当前研究流水线（已完成步骤会保留审计）"}
          >
            <XCircle size={13} /> {busy === "pipeline-cancel" ? "取消中" : "取消研究流水线"}
          </button>
        )}
        {isCancelled && (
          <span className="research-pipeline-banner-clear-stage" title="流水线已取消，阶段已清空为终态">
            阶段已清除：已取消研究流水线
          </span>
        )}
      </div>
    </section>
  );
}

function EntryModeChooser({ busy, onSelect }) {
  return <section className="authoring-entry-mode"><header><div><strong>选择开始方式</strong><span>两种方式最终汇入同一研究定义、两阶段医学确认和完整方案编辑器。</span></div></header><div className="authoring-entry-mode-options"><button type="button" onClick={() => onSelect("synopsis_import")} disabled={Boolean(busy)}><FileText size={19} /><span><strong>导入已有方案/方案摘要</strong><small>上传PDF或DOCX，核对提取的研究框架、PICOS和量表候选后继续补全。</small></span><ArrowRight size={16} /></button><button type="button" onClick={() => onSelect("guided_greenfield")} disabled={Boolean(busy)}><PenLine size={19} /><span><strong>从零开始</strong><small>通过两阶段反问确定方案摘要和研究框架，再进入完整方案撰写。</small></span><ArrowRight size={16} /></button></div>{busy && <p><RefreshCw size={14} /> 正在建立写作任务...</p>}</section>;
}

function InstrumentCandidateEvidence({ item, evidenceSpans }) {
  const evidenceById = new Map((evidenceSpans || []).map((evidence) => [evidence.span_id, evidence]));
  const evidence = (item.evidence_span_ids || []).map((spanId) => evidenceById.get(spanId)).filter(Boolean);
  const renderEvidence = (entry) => <div key={entry.span_id}><span>原文</span><blockquote>{entry.source_text}</blockquote><small title={entry.locator}>{entry.locator}</small></div>;
  if (!evidence.length) return <div className="synopsis-instrument-evidence missing"><span>原文</span><p>未找到该候选的直接原文，暂不可确认。</p></div>;
  return <div className="synopsis-instrument-evidence">{renderEvidence(evidence[0])}{evidence.length > 1 && <details><summary>查看其余 {evidence.length - 1} 条直接原文</summary>{evidence.slice(1).map(renderEvidence)}</details>}</div>;
}

function SynopsisImportPanel({ journey, file, uploadKey, replacementPending, framing, picos, synopsisText, acknowledged, overrideReason, busy, interactionLocked, onFile, onUpload, onFraming, onPicos, onSynopsisText, onAcknowledged, onOverrideReason }) {
  const imported = journey.synopsis_import || {};
  const source = imported.source;
  const validationWarnings = source?.validation_warnings || [];
  const toggleWarning = (warning) => onAcknowledged(acknowledged.includes(warning) ? acknowledged.filter((item) => item !== warning) : [...acknowledged, warning]);
  return <section className="synopsis-import-stage"><header><div><strong>导入已有方案/方案摘要</strong><span>先校验文件基本信息、内容角色和项目适应症，再审核AI提取候选。</span></div><span className={`synopsis-import-status ${source && !replacementPending ? "review" : "pending"}`}>{replacementPending ? (source ? "替换待解析" : "文件待解析") : source ? "AI建议·待确认" : "待导入"}</span></header><fieldset className="authoring-journey-fieldset" disabled={interactionLocked}><div className="synopsis-upload-bar"><label className="synopsis-file-picker"><input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => onFile(event.target.files?.[0] || null)} /><Upload size={16} /><span><strong>{file?.name || (source ? "选择新的PDF或DOCX以替换当前文件" : "选择PDF或DOCX方案/方案摘要")}</strong><small>{file ? `${formatFileSize(file.size)} · 重试将沿用同一导入请求` : "文件需可正常读取；内容校验结果由医学经理确认。"}</small></span></label><button type="button" onClick={onUpload} disabled={!file || !uploadKey || Boolean(busy)}><Upload size={14} /> {busy === "synopsis-upload" ? "解析中" : source ? "替换并重新解析" : "导入并解析"}</button></div>{source && <><section className="synopsis-source-review"><header><strong>文件与内容校验</strong><small>原始判断会持续保留；确认沿用不会把“需确认/不一致”改写为“一致”。</small></header><dl><div><dt>文件</dt><dd title={source.original_filename}>{source.original_filename}</dd></div><div><dt>格式 / 大小</dt><dd>{source.media_type === "application/pdf" ? "PDF" : "DOCX"} · {formatFileSize(source.actual_size)}</dd></div><div><dt>文件角色</dt><dd><span className={`synopsis-validation ${source.source_role_status}`}>{validationStatus(source.source_role_status)}</span> 临床试验方案/方案摘要</dd></div><div><dt>适应症</dt><dd><span className={`synopsis-validation ${source.indication_status}`}>{validationStatus(source.indication_status)}</span> 当前项目</dd></div><div><dt>解析器</dt><dd>{source.parser_name}</dd></div><div><dt>提取版本</dt><dd title={source.extraction_revision}>{source.extraction_revision}</dd></div></dl></section><div className="synopsis-findings-grid"><section><header><strong>待补充字段</strong><span>{imported.missing_fields?.length || 0}项</span></header>{imported.missing_fields?.length ? <ul>{imported.missing_fields.map((item) => <li key={item} title={item}>{synopsisFieldLabel(item)}</li>)}</ul> : <p>未发现结构性缺失。</p>}</section><section><header><strong>提取冲突</strong><span>{imported.conflict_notes?.length || 0}项</span></header>{imported.conflict_notes?.length ? <ul>{imported.conflict_notes.map((item) => <li key={item}>{item}</li>)}</ul> : <p>未发现相互冲突的表述。</p>}</section></div>{picos.assessment_instruments?.length > 0 && <section className="synopsis-instrument-candidates"><header><div><strong>量表与评估工具候选</strong><span>仅为原文提取候选；进入PICOS后仍需逐项核对用途、访视、中文版本与使用许可。</span></div><small>{picos.assessment_instruments.length}项待确认</small></header><div>{picos.assessment_instruments.map((item) => <article key={item.instrument_id}><span>{item.acronym || "工具"}</span><div className="synopsis-instrument-summary"><strong>{item.canonical_name_zh}</strong><small>{[item.study_purpose, item.visit_labels?.join("、")].filter(Boolean).join(" · ") || "用途与访视待补充"}</small></div><em>候选·待确认</em><InstrumentCandidateEvidence item={item} evidenceSpans={imported.evidence_spans} /></article>)}</div></section>}{validationWarnings.length > 0 && <section className="synopsis-validation-review"><header><div><ShieldAlert size={17} /><span><strong>逐项确认内容提示</strong><small>以下提示必须逐项确认，并记录不少于10个字符的沿用理由。</small></span></div><span>{acknowledged.length}/{validationWarnings.length}</span></header><div>{validationWarnings.map((warning, index) => <label key={`${index}-${warning}`}><input type="checkbox" checked={acknowledged.includes(warning)} onChange={() => toggleWarning(warning)} /><span><strong>{warning}</strong><small>{acknowledged.includes(warning) ? "医学经理已确认沿用" : "尚未确认"}</small></span></label>)}</div><label className="synopsis-override-reason"><span>确认沿用理由</span><textarea rows={2} value={overrideReason} onChange={(event) => onOverrideReason(event.target.value)} placeholder="说明为何该文件仍属于当前项目并可继续使用；不少于10个字符。" /></label></section>}<section className="synopsis-extraction-review"><header><div><strong>提取结果摘要</strong><span>可直接修订候选；确认后会写入统一研究定义草稿，并继续两阶段补全。</span></div><small>AI提取 · 待用户确认</small></header><div className="authoring-field-grid four"><Field label="方案号"><input value={framing.protocol_id || ""} onChange={(event) => onFraming("protocol_id", event.target.value)} /></Field><Field label="版本"><input value={framing.version || ""} onChange={(event) => onFraming("version", event.target.value)} /></Field><Field label="研究分期"><StudyPhaseInput value={framing.study_phase} onChange={(value) => onFraming("study_phase", value)} listId="medical-writing-synopsis-phase-options" /></Field><Field label="适应症"><input value={framing.indication || ""} onChange={(event) => onFraming("indication", event.target.value)} /></Field><Field className="span-2" label="方案标题"><input value={framing.document_title || ""} onChange={(event) => onFraming("document_title", event.target.value)} /></Field><Field label="试验药物"><input value={framing.investigational_product || ""} onChange={(event) => onFraming("investigational_product", event.target.value)} /></Field><Field label="靶点/作用机制"><input value={framing.target_mechanism || ""} onChange={(event) => onFraming("target_mechanism", event.target.value)} /></Field><Field className="span-2" label="总体设计意图"><textarea rows={3} value={framing.design_pattern || ""} onChange={(event) => onFraming("design_pattern", event.target.value)} /></Field><Field className="span-2" label="目标研究人群"><textarea rows={3} value={framing.population_intent || picos.population_summary || ""} onChange={(event) => { onFraming("population_intent", event.target.value); onPicos("population_summary", event.target.value); }} /></Field><Field className="span-2" label="干预措施"><textarea rows={3} value={picos.intervention_summary || ""} onChange={(event) => onPicos("intervention_summary", event.target.value)} /></Field><Field className="span-2" label="对照"><textarea rows={3} value={picos.comparator_summary || ""} onChange={(event) => onPicos("comparator_summary", event.target.value)} /></Field><Field className="span-4" label="主要终点及评价时间"><textarea rows={3} value={picos.primary_endpoint || ""} onChange={(event) => onPicos("primary_endpoint", event.target.value)} /></Field><Field className="span-4" label="研究摘要文本"><textarea rows={8} value={synopsisText} onChange={(event) => onSynopsisText(event.target.value)} /></Field></div></section></>}</fieldset></section>;
}

function PrefillRecommendations({
  journey,
  prefillPackage,
  searchPlan,
  busy,
  readOnly,
  activeSection,
  onSectionChange,
  onAdopt,
  onAdoptComposite,
  onDefer,
  onRefine,
  onRegenerate,
  deferredFields,
  compositeReceipt,
  onOpenCompetitorDrawer,
}) {
  const searchCount = searchPlan?.returned_count || 0;
  const documentCount = searchPlan?.public_document_count || 0;
  if (!prefillPackage) {
    return <section className="authoring-prefill-panel preparing" aria-live="polite">
      <header><div><Sparkles size={16} /><span><strong>{busy === "prefill-generate" ? "正在准备研究设计建议" : "研究设计建议尚未准备完成"}</strong><small>系统只使用已确认的试验药物、适应症和分期启动准备，不会要求重复填写。</small></span></div>{busy === "prefill-generate" ? <RefreshCw className="spin" size={16} /> : !readOnly && <button type="button" onClick={onRegenerate} disabled={Boolean(busy)}><RefreshCw size={14} /> 重新准备</button>}</header>
      <div className="authoring-prefill-preparation" aria-label="建议准备进程">
        <span className="done"><CheckCircle2 size={13} /> 项目最小信息已确认</span>
        <span className={busy === "prefill-generate" ? "running" : "pending"}><RefreshCw size={13} /> 汇总公开研究与项目资料</span>
        <span className="pending"><Sparkles size={13} /> 生成研究框架与PICOS建议</span>
      </div>
    </section>;
  }
  const compositeGroups = collectCompositePrefillGroups(prefillPackage);
  const groups = prefillFieldsForSection(prefillPackage, activeSection);
  const statusLabel = ({ ready: "建议已就绪", partial: "部分建议已就绪", stale: "建议需更新", failed: "建议生成失败" })[prefillPackage.status] || "建议准备中";
  const pathLabels = {
    ...SYNOPSIS_FIELD_LABELS,
    ...FACT_FIELD_LABELS,
    ...DESIGN_PREFILL_FIELD_LABELS,
  };
  return <section className={`authoring-prefill-panel ${prefillPackage.status}`} aria-label="研究设计推荐包">
    <header>
      <div><Sparkles size={16} /><span><strong>{statusLabel}</strong><small>{searchCount || documentCount ? `已结合 ${searchCount} 项公开研究${documentCount ? `及 ${documentCount} 份Protocol` : ""}` : "AI正在结合项目事实与公开研究形成整套建议"}</small></span></div>
      {!readOnly && <div className="authoring-prefill-header-actions">
        {searchPlan?.latest_snapshot_id && typeof onOpenCompetitorDrawer === "function" && (
          <button type="button" data-action="open-competitor-drawer-from-prefill" onClick={onOpenCompetitorDrawer} disabled={Boolean(busy)} title="打开竞品处理抽屉">
            <Search size={14} /> 打开竞品处理
          </button>
        )}
        <button type="button" onClick={onRegenerate} disabled={Boolean(busy)} title="按最新项目事实和调研结果重新生成建议"><RefreshCw size={14} /> 更新建议</button>
      </div>}
    </header>
    <AuthoringCandidatePackagePanel
      groups={compositeGroups}
      packageRevision={prefillPackage.package_revision}
      pathLabels={pathLabels}
      busy={busy}
      readOnly={readOnly}
      receipt={compositeReceipt}
      onAdoptComposite={onAdoptComposite}
    />
    <details className="authoring-prefill-field-details">
      <summary>
        <span><strong>展开单字段修改与依据</strong><small>仅在整包建议需要局部调整时使用</small></span>
      </summary>
      <div className="authoring-prefill-workspace">
        <div className="authoring-prefill-main">
        <nav className="authoring-prefill-section-tabs" aria-label="AI推荐分组">
          {PREFILL_OVERVIEW_SECTIONS.map((section) => {
            const sectionGroups = prefillFieldsForSection(prefillPackage, section.key);
            return <button key={section.key} type="button" className={activeSection === section.key ? "active" : ""} aria-pressed={activeSection === section.key} onClick={() => onSectionChange(section.key)}><span>{section.label}</span><small>{sectionGroups.length}项</small></button>;
          })}
        </nav>
        {activeSection === "design" && (
          <p className="authoring-prefill-design-helper" role="note">
            总体设计须给出明确采用/不采用（如不启用适应性设计、不设置SRC或DMC、不计划期中分析）；禁止以「待确认」作为推荐或默认选项。
          </p>
        )}
        {groups.length > 0 ? <div className="authoring-prefill-fields">{groups.map((candidateGroup) => <PrefillFieldCard key={candidateGroup.field_path} group={candidateGroup} projectConfirmedCandidate={confirmedProjectCandidate(journey, candidateGroup)} busy={busy} readOnly={readOnly} onAdopt={onAdopt} onDefer={onDefer} onRefine={onRefine} deferred={deferredFields.includes(candidateGroup.field_path)} />)}</div> : <div className="authoring-prefill-empty"><ShieldAlert size={15} /><span>该分组尚无证据充分的预填建议。系统不会为精确剂量、频率或终点虚构内容；完成Protocol解析后可更新。</span></div>}
        </div>
        <aside className="authoring-prefill-impact" aria-label="整包建议说明">
          <strong>修改原则</strong>
          <p>优先采用整包方案。仅在项目事实与推荐不一致时修改单字段；精确剂量、终点与AESI仍受现有证据门约束。</p>
        </aside>
      </div>
      {prefillPackage.partial_source_failures?.length > 0 && <details className="authoring-prefill-limitations"><summary>来源限制</summary><ul>{prefillPackage.partial_source_failures.map((item) => <li key={item}>{item}</li>)}</ul></details>}
    </details>
  </section>;
}

function PrefillFieldCard({ group, projectConfirmedCandidate, busy, readOnly, onAdopt, onDefer, onRefine, deferred }) {
  const recommended = recommendedPrefillCandidate(group);
  const confirmed = group.candidates.find((item) => item.state === "user_confirmed") || projectConfirmedCandidate;
  const [editingCandidateId, setEditingCandidateId] = useState("");
  const [editedValue, setEditedValue] = useState("");
  const candidates = [...group.candidates].sort((left, right) => {
    const leftPending = isPendingCompositeCandidate(left);
    const rightPending = isPendingCompositeCandidate(right);
    if (!leftPending && rightPending) return -1;
    if (leftPending && !rightPending) return 1;
    if (left.candidate_id === group.recommended_candidate_id) return -1;
    if (right.candidate_id === group.recommended_candidate_id) return 1;
    return 0;
  });
  const startEdit = (candidate) => {
    setEditingCandidateId(candidate.candidate_id);
    setEditedValue(typeof candidate.structured_value === "string" ? candidate.structured_value : candidate.preview || "");
  };
  const currentCandidate = confirmed || recommended;
  const currentDisplay = prefillCandidateDisplay(group.field_path, currentCandidate);
  const rawCurrentDisplay = currentCandidate?.preview || (typeof currentCandidate?.structured_value === "string" ? currentCandidate.structured_value : "");
  const evidenceCount = currentCandidate?.evidence_refs?.length || 0;
  const editingCandidate = candidates.find((candidate) => candidate.candidate_id === editingCandidateId);
  const editingCandidatePending = isPendingCompositeCandidate(editingCandidate);
  const needsExplicitDecision = DESIGN_EXPLICIT_DECISION_FIELDS.has(group.field_path);
  const refineDisabled = Boolean(busy);
  const bothCandidate = candidates.find((c) => {
    const v = c.structured_value || {};
    return v.src === true && v.dmc === true;
  }) || candidates.find((c) => String(c.preview || "").includes("同时设"));
  const noneCandidate = candidates.find((c) => {
    const v = c.structured_value || {};
    return v.src === false && v.dmc === false;
  }) || candidates.find((c) => String(c.preview || "").includes("不设"));
  return <article className={`authoring-prefill-field ${confirmed ? "confirmed" : ""} ${deferred ? "deferred" : ""}`} data-prefill-field={group.field_path}>
    <div className="authoring-prefill-field-head">
      <span><strong>{prefillFieldLabel(group.field_path)}</strong><small>{confirmed ? "已成为当前项目事实" : deferred ? "本次暂缓，不写入项目事实" : `AI推荐 · ${evidenceCount}条主要依据`}</small></span>
      <em>{confirmed ? "已采用" : deferred ? "暂未确定" : "AI建议"}</em>
    </div>
    {needsExplicitDecision && (
      <p className="authoring-prefill-explicit-helper">
        请选择明确采用或不采用选项（如不启用适应性设计 / 同时设置SRC与DMC / 不设置SRC或DMC / 不计划期中分析）；勿采用含「待确认」的表述。
      </p>
    )}
    {group.field_path === "design.src_dmc" && !readOnly && !confirmed && (
      <div className="authoring-prefill-src-dmc-bulk" role="group" aria-label="SRC/DMC快捷选择">
        <button
          type="button"
          className="primary-button"
          disabled={Boolean(busy) || Boolean(bothCandidate && isPendingCompositeCandidate(bothCandidate))}
          title={bothCandidate && isPendingCompositeCandidate(bothCandidate) ? prefillCandidateBlockedReason(bothCandidate) : "同时设置SRC与DMC"}
          onClick={() => { if (bothCandidate) onAdopt(group.field_path, bothCandidate); }}
        >
          SRC/DMC 全选
        </button>
        <button
          type="button"
          disabled={Boolean(busy) || Boolean(noneCandidate && isPendingCompositeCandidate(noneCandidate))}
          title={noneCandidate && isPendingCompositeCandidate(noneCandidate) ? prefillCandidateBlockedReason(noneCandidate) : "不设置SRC或DMC"}
          onClick={() => { if (noneCandidate) onAdopt(group.field_path, noneCandidate); }}
        >
          SRC/DMC 全不选
        </button>
      </div>
    )}
    <div className="authoring-prefill-current">
      <strong title={rawCurrentDisplay && rawCurrentDisplay !== currentDisplay ? rawCurrentDisplay : undefined}>{currentDisplay || (candidates.length ? "当前无推荐方案；请从下方候选中选择或使用组合推荐" : needsExplicitDecision ? "请从下方候选中明确选择" : "候选内容待生成")}</strong>
      {currentCandidate?.rationale && <p>{currentCandidate.rationale}</p>}
    </div>
    {!readOnly && <div className="authoring-prefill-primary-actions">
      {!confirmed && recommended && <button type="button" className="primary-button" data-prefill-action="adopt-recommended" onClick={() => onAdopt(group.field_path, recommended)} disabled={Boolean(busy) || isPendingCompositeCandidate(recommended)} title={isPendingCompositeCandidate(recommended) ? prefillCandidateBlockedReason(recommended) : "采用当前推荐方案"}>{busy === `prefill-adopt-${group.field_path}` ? "写入中" : "采用推荐"}</button>}
      {!confirmed && STRING_PREFILL_FIELDS.has(group.field_path) && recommended && <button type="button" onClick={() => startEdit(recommended)} disabled={Boolean(busy) || isPendingCompositeCandidate(recommended)} title={isPendingCompositeCandidate(recommended) ? prefillCandidateBlockedReason(recommended) : "修改后采用，写入您的表述"}>修改后采用</button>}
      {!confirmed && <button type="button" className={deferred ? "selected" : ""} onClick={() => onDefer(group.field_path)} disabled={Boolean(busy)} title="仅暂缓本次处理，不写入项目事实；下次读取仍会保留该建议">{deferred ? "继续处理" : "暂不确定"}</button>}
      <button type="button" onClick={() => onRefine(group.field_path)} disabled={refineDisabled} title={refineDisabled ? "正在处理中，请稍候" : "打开高级微调面板；已有内容会保留，空字段可从推荐预填"}>{STRING_PREFILL_FIELDS.has(group.field_path) ? "其他表述" : "其他/高级微调"}</button>
    </div>}
    {editingCandidateId === recommended?.candidate_id && <div className="authoring-prefill-edit"><textarea rows={3} value={editedValue} onChange={(event) => setEditedValue(event.target.value)} aria-label={`${prefillFieldLabel(group.field_path)}修改稿`} /><div><button type="button" onClick={() => setEditingCandidateId("")}>取消</button><button className="primary-button" type="button" onClick={() => onAdopt(group.field_path, recommended, editedValue.trim())} disabled={!editedValue.trim() || Boolean(busy) || editingCandidatePending} title={editingCandidatePending ? prefillCandidateBlockedReason(editingCandidate) : "采用修改后的候选"}>采用修改稿</button></div></div>}
    <details className="authoring-prefill-candidate-drawer" open={needsExplicitDecision && !confirmed}>
      <summary>查看{candidates.length}个候选、依据与局限</summary>
      <div className="authoring-prefill-candidates">
      {candidates.map((candidate) => {
        const isRecommended = candidate.candidate_id === recommended?.candidate_id;
        const isConfirmed = candidate.state === "user_confirmed" || candidate.candidate_id === confirmed?.candidate_id;
        const isBusy = busy === `prefill-adopt-${group.field_path}`;
        const display = prefillCandidateDisplay(group.field_path, candidate);
        const rawDisplay = candidate.preview || (typeof candidate.structured_value === "string" ? candidate.structured_value : "");
        const pendingCandidate = isPendingCompositeCandidate(candidate);
        return <section key={candidate.candidate_id} className={`${isRecommended ? "recommended" : ""} ${isConfirmed ? "selected" : ""} ${pendingCandidate ? "pending" : ""}`}>
          <div className="authoring-prefill-candidate-copy">
            <div><span>{isConfirmed ? <CheckCircle2 size={13} /> : isRecommended ? <Sparkles size={13} /> : null}{isConfirmed ? "已采用" : pendingCandidate ? "待决定（非推荐）" : isRecommended ? "推荐" : "备选"}</span><small>{({ high: "高", medium: "中", low: "低", none: "无" })[candidate.confidence] || "未知"}置信</small></div>
            <strong title={rawDisplay && rawDisplay !== display ? rawDisplay : undefined}>{display}</strong>
            {candidate.rationale && <p>{candidate.rationale}</p>}
          </div>
          {!readOnly && !isConfirmed && <div className="authoring-prefill-candidate-actions">
            <button type="button" className={isRecommended ? "primary-button" : ""} onClick={() => onAdopt(group.field_path, candidate)} disabled={Boolean(busy) || pendingCandidate} title={pendingCandidate ? prefillCandidateBlockedReason(candidate) : "采用该候选"}>{isBusy ? "写入中" : "采用"}</button>
            {STRING_PREFILL_FIELDS.has(group.field_path) && <button type="button" onClick={() => startEdit(candidate)} disabled={Boolean(busy) || pendingCandidate} title={pendingCandidate ? prefillCandidateBlockedReason(candidate) : "修改后采用，写入您的表述"}>修改后采用</button>}
          </div>}
          {editingCandidateId === candidate.candidate_id && <div className="authoring-prefill-edit"><textarea rows={3} value={editedValue} onChange={(event) => setEditedValue(event.target.value)} /><div><button type="button" onClick={() => setEditingCandidateId("")}>取消</button><button className="primary-button" type="button" onClick={() => onAdopt(group.field_path, candidate, editedValue.trim())} disabled={!editedValue.trim() || Boolean(busy) || editingCandidatePending} title={editingCandidatePending ? prefillCandidateBlockedReason(editingCandidate) : "采用修改后的候选"}>采用修改稿</button></div></div>}
          {(candidate.evidence_refs?.length > 0 || candidate.limitations?.length > 0) && <details className="authoring-prefill-evidence"><summary>依据与局限</summary>{candidate.evidence_refs?.map((evidence, index) => <div key={`${evidence.source_id}-${index}`}><strong>{evidence.source_text || evidence.source_id}</strong><small title={evidence.locator}>{evidence.source_kind} · {evidence.locator || evidence.source_id}</small></div>)}{candidate.limitations?.length > 0 && <ul>{candidate.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}</details>}
        </section>;
      })}
      </div>
    </details>
  </article>;
}

function InvestigatorBrochureIntake({
  projectId,
  packet,
  busy,
  interactionLocked,
  onAttach,
  onMarkUnavailable,
  onAnalyze,
}) {
  const [file, setFile] = useState(null);
  const [registration, setRegistration] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [acknowledged, setAcknowledged] = useState([]);
  const [overrideReason, setOverrideReason] = useState("");
  const [localMessage, setLocalMessage] = useState("");
  useEffect(() => {
    setFile(null);
    setRegistration(null);
    setAcknowledged([]);
    setOverrideReason("");
    setLocalMessage("");
  }, [projectId]);
  const currentSourceId = packet.ib_source_ids?.[0] || "";
  const upload = async () => {
    if (!file || uploading || interactionLocked) return;
    setUploading(true);
    setLocalMessage("正在解析研究者手册并核对文件角色与适应症...");
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      const response = await fetch(
        `/api/projects/${projectId}/medical-writing/sources/investigator-brochure`,
        { method: "POST", body: form },
      ).then(readJson);
      const validation = response?.entry?.metadata?.content_validation || {};
      setRegistration(response);
      setAcknowledged([]);
      setOverrideReason("");
      if (!(validation.warnings || []).length) {
        await onAttach(response, "");
        setLocalMessage("文件角色与项目内容已核对，研究者手册已进入项目事实来源。");
      } else {
        setLocalMessage("文件已读取；请核对下方内容提示后决定是否沿用。");
      }
    } catch (error) {
      setLocalMessage(`研究者手册导入失败：${error.message}`);
    } finally {
      setUploading(false);
    }
  };
  const validation = registration?.entry?.metadata?.content_validation || {};
  const warnings = validation.warnings || [];
  const allAcknowledged = warnings.length > 0
    && warnings.every((item) => acknowledged.includes(item.code));
  const confirm = async () => {
    if (!allAcknowledged) return;
    await onAttach(registration, overrideReason);
    setLocalMessage("已按医学经理确认沿用该研究者手册；原提示仍保留在来源记录中。");
  };
  return <section className="authoring-ib-intake">
    <div className="authoring-ib-actions">
      <label className="authoring-ib-file-picker">
        <input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => {
          setFile(event.target.files?.[0] || null);
          setRegistration(null);
          setAcknowledged([]);
          setOverrideReason("");
          setLocalMessage("");
        }} disabled={interactionLocked || uploading} />
        <Upload size={14} />
        <span>{file?.name || (currentSourceId ? "替换研究者手册" : "上传研究者手册")}</span>
      </label>
      {file && <button type="button" onClick={upload} disabled={interactionLocked || uploading}>{uploading ? <RefreshCw size={14} /> : <FileText size={14} />}{uploading ? "解析中" : "导入并解析"}</button>}
      {!currentSourceId && <button type="button" onClick={onMarkUnavailable} disabled={interactionLocked || uploading}>暂不提供IB</button>}
      {currentSourceId && <button type="button" className="primary-button" onClick={onAnalyze} disabled={interactionLocked || busy === "fact-turn"}><Sparkles size={14} /> {busy === "fact-turn" ? "提取中" : "提取关键事实"}</button>}
    </div>
    {warnings.length > 0 && currentSourceId !== registration?.entry?.entry_id && <div className="authoring-ib-validation">
      <header><ShieldAlert size={15} /><span><strong>内容提示</strong><small>仅核对是否误传文件或项目资料，不执行额外安全检查。</small></span></header>
      {warnings.map((warning) => <label key={warning.code}>
        <input type="checkbox" checked={acknowledged.includes(warning.code)} onChange={() => setAcknowledged((current) => current.includes(warning.code) ? current.filter((item) => item !== warning.code) : [...current, warning.code])} />
        <span><strong>{warning.label}</strong><small>{warning.message}</small></span>
      </label>)}
      <textarea rows={2} value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} placeholder="可选：补充说明为何该文件可用于当前项目" />
      <button type="button" className="primary-button" onClick={confirm} disabled={!allAcknowledged || interactionLocked}><CheckCircle2 size={14} /> 确认沿用</button>
    </div>}
    {currentSourceId && <div className="authoring-ib-current"><CheckCircle2 size={14} /><span><strong>已接入项目事实来源</strong><small title={currentSourceId}>{currentSourceId}</small></span></div>}
    {localMessage && <p>{localMessage}</p>}
  </section>;
}

function FramingFields({ projectId, framing, group, update, factConversation, setFactConversation, onSubmitFactIntake, onApplyFactProposal, onAttachIb, onMarkIbUnavailable, onAnalyzeIb, busy, interactionLocked }) {
  if (group === "identity") {
    const factPacket = framing.minimum_product_fact_packet || {};
    const ibStatus = factPacket.ib_status || "not_provided";
    const ibTone = IB_STATUS_TONE[ibStatus] || "optional";
    const ibLabel = IB_STATUS_LABELS[ibStatus] || IB_STATUS_LABELS.not_provided;
    const packetStatusLabel = FACT_PACKET_STATUS_LABELS[factPacket.status] || FACT_PACKET_STATUS_LABELS.not_started;
    const highImpactGaps = factPacket.unresolved_high_impact_fields || [];
    const productProfile = framing.product_profile || {};
    const updateProductProfile = (patch) => update("product_profile", { ...productProfile, ...patch });
    const toggleAdministrationRoute = (route) => {
      const current = productProfile.administration_routes || [];
      updateProductProfile({
        administration_routes: current.includes(route)
          ? current.filter((item) => item !== route)
          : [...current, route],
      });
    };
    const updateDosageForm = (value) => updateProductProfile({ dosage_forms: value ? [value] : [] });
    return <section className="authoring-field-section"><header><strong>项目与产品</strong><span>研究药物、适应症和研究分期是启动竞品检索的最小三项；其他内容可由系统预填后再确认</span></header><div className="authoring-ib-banner"><div className={`authoring-ib-status ${ibTone}`}><FileText size={16} /><div><strong>可选：研究者手册（IB）</strong><span>{ibLabel}</span></div></div><div className="authoring-ib-fact-packet"><span>最小产品事实包</span><strong>{packetStatusLabel}</strong>{highImpactGaps.length > 0 && <small>高影响缺口 {highImpactGaps.length} 项：{highImpactGaps.slice(0, 3).map(factGapLabel).join("、")}{highImpactGaps.length > 3 ? " 等" : ""}</small>}</div></div><InvestigatorBrochureIntake projectId={projectId} packet={factPacket} busy={busy} interactionLocked={interactionLocked} onAttach={onAttachIb} onMarkUnavailable={() => onMarkIbUnavailable({ ibStatus: "not_available" })} onAnalyze={onAnalyzeIb} /><div className="authoring-field-grid four"><Field label="方案号"><input value={framing.protocol_id} onChange={(event) => update("protocol_id", event.target.value)} /></Field><Field label="版本"><input value={framing.version} onChange={(event) => update("version", event.target.value)} /></Field><Field label="研究分期" required><StudyPhaseInput value={framing.study_phase} onChange={(value) => update("study_phase", value)} listId="medical-writing-study-phase-options" /></Field><Field label="开发区域"><input value={lineText(framing.development_regions)} onChange={(event) => update("development_regions", lines(event.target.value))} /></Field><Field className="span-4" label="方案标题"><input value={framing.document_title} onChange={(event) => update("document_title", event.target.value)} /></Field><Field className="span-2" label="适应症" required><input value={framing.indication} onChange={(event) => update("indication", event.target.value)} /></Field><Field className="span-2" label="试验药物" required><input value={framing.investigational_product} onChange={(event) => update("investigational_product", event.target.value)} /></Field><Field className="span-2" label="药物技术类型" required><select value={productProfile.technology_type || "unknown"} onChange={(event) => updateProductProfile({ technology_type: event.target.value })} aria-label="药物技术类型" aria-required="true">{PRODUCT_TECHNOLOGY_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field><Field className="span-2" label="暴露范围"><select value={productProfile.exposure_scope || "unknown"} onChange={(event) => updateProductProfile({ exposure_scope: event.target.value })} aria-label="暴露范围">{PRODUCT_EXPOSURE_SCOPE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field><Field className="span-2" label="剂型"><select value={(productProfile.dosage_forms || [])[0] || ""} onChange={(event) => updateDosageForm(event.target.value)} aria-label="剂型">{PRODUCT_DOSAGE_FORM_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field><Field className="span-2" label="给药途径"><div className="authoring-choice-grid" role="group" aria-label="给药途径">{PRODUCT_ADMINISTRATION_ROUTES.map((route) => <label key={route} className={(productProfile.administration_routes || []).includes(route) ? "selected" : ""}><input type="checkbox" checked={(productProfile.administration_routes || []).includes(route)} onChange={() => toggleAdministrationRoute(route)} /><span>{route}</span></label>)}</div></Field><Field className="span-4" label="ClinicalTrials.gov疾病检索词（系统建议，可修改）"><input value={framing.clinicaltrials_condition_term || ""} onChange={(event) => update("clinicaltrials_condition_term", event.target.value)} placeholder="可留空；系统先按适应症形成检索计划，并可在调研后建议规范英文词" /><small>该字段用于优化注册库检索，不是启动检索的硬门；留空时使用适应症。</small></Field></div><ConversationalFactIntake factConversation={factConversation} setFactConversation={setFactConversation} onSubmit={onSubmitFactIntake} onApplyProposal={onApplyFactProposal} busy={busy} interactionLocked={interactionLocked} /></section>;
  }
  if (group === "purpose") return <section className="authoring-field-section"><header><strong>内在研究目的</strong><span>不是正文中的“研究目的”，用于决定设计路径和证据检索范围</span></header><div className="authoring-choice-grid">{PURPOSE_OPTIONS.map((item) => <label key={item} className={framing.intrinsic_objectives.includes(item) ? "selected" : ""}><input type="checkbox" checked={framing.intrinsic_objectives.includes(item)} onChange={() => update("intrinsic_objectives", framing.intrinsic_objectives.includes(item) ? framing.intrinsic_objectives.filter((value) => value !== item) : [...framing.intrinsic_objectives, item])} /><span>{item}</span></label>)}</div><Field label="其他研究目的（自然语言，每行一项）"><textarea rows={3} value={lineText(framing.intrinsic_objectives.filter((item) => !PURPOSE_OPTIONS.includes(item)))} onChange={(event) => update("intrinsic_objectives", [...framing.intrinsic_objectives.filter((item) => PURPOSE_OPTIONS.includes(item)), ...lines(event.target.value)])} placeholder="可填写组合研究目的或列表中没有的其他目的" /></Field><Field label="关键科学与开发不确定性（每行一项）"><textarea rows={4} value={lineText(framing.key_uncertainties)} onChange={(event) => update("key_uncertainties", lines(event.target.value))} /></Field></section>;
  if (group === "competition") return <section className="authoring-field-section"><header><strong>靶点与竞品范围</strong><span>第一步完成后据此形成宽检索和人工分诊篮子；未知时可留空，由IB或后续证据补充</span></header><div className="authoring-field-grid two"><Field label="靶点/作用机制"><textarea rows={4} value={framing.target_mechanism} onChange={(event) => update("target_mechanism", event.target.value)} /></Field><Field label="竞品靶点与机制范围"><textarea rows={4} value={framing.competitor_target_scope} onChange={(event) => update("competitor_target_scope", event.target.value)} placeholder="可扩展到同靶点、同机制或同治疗线竞品" /></Field><Field label="已准备的Protocol文件名称或资料编号（每行一项）" className="span-2"><textarea rows={4} value={lineText(framing.manual_source_ids)} onChange={(event) => update("manual_source_ids", lines(event.target.value))} placeholder="此处登记资料；原文将在语料准备步骤导入并校验文件角色" /></Field></div></section>;
  return <DesignIntentFields framing={framing} update={update} />;
}

function parsePopulationIntentStructure(text) {
  const source = String(text || "");
  const extract = (label, options) => {
    const match = source.match(new RegExp(`${label}：([^；;]+)`));
    if (!match) return [];
    return options.filter((item) => match[1].includes(item));
  };
  let freeText = source;
  for (const label of ["年龄段", "疾病状态", "经治情况"]) {
    freeText = freeText.replace(new RegExp(`${label}：[^；;]*[；;]?`, "g"), "");
  }
  return {
    ageBands: extract("年龄段", POPULATION_AGE_BAND_OPTIONS),
    diseaseStates: extract("疾病状态", POPULATION_DISEASE_STATE_OPTIONS),
    treatmentStatuses: extract("经治情况", POPULATION_TREATMENT_STATUS_OPTIONS),
    freeText: freeText.replace(/^[；;\s]+|[；;\s]+$/g, "").trim(),
  };
}

function composePopulationIntent({ ageBands, diseaseStates, treatmentStatuses, freeText }) {
  const parts = [];
  if (ageBands.length) parts.push(`年龄段：${ageBands.join("、")}`);
  if (diseaseStates.length) parts.push(`疾病状态：${diseaseStates.join("、")}`);
  if (treatmentStatuses.length) parts.push(`经治情况：${treatmentStatuses.join("、")}`);
  if (String(freeText || "").trim()) parts.push(String(freeText).trim());
  return parts.join("；");
}

function DesignIntentFields({ framing, update }) {
  const parsed = parsePopulationIntentStructure(framing.population_intent);
  const [ageBands, setAgeBands] = useState(parsed.ageBands);
  const [diseaseStates, setDiseaseStates] = useState(parsed.diseaseStates);
  const [treatmentStatuses, setTreatmentStatuses] = useState(parsed.treatmentStatuses);
  const [freeText, setFreeText] = useState(parsed.freeText);
  const lastComposedRef = useRef(framing.population_intent || "");

  useEffect(() => {
    if ((framing.population_intent || "") === lastComposedRef.current) return;
    const next = parsePopulationIntentStructure(framing.population_intent);
    setAgeBands(next.ageBands);
    setDiseaseStates(next.diseaseStates);
    setTreatmentStatuses(next.treatmentStatuses);
    setFreeText(next.freeText);
    lastComposedRef.current = framing.population_intent || "";
  }, [framing.population_intent]);

  const writePopulationIntent = (nextAge, nextDisease, nextTreatment, nextFree) => {
    const composed = composePopulationIntent({
      ageBands: nextAge,
      diseaseStates: nextDisease,
      treatmentStatuses: nextTreatment,
      freeText: nextFree,
    });
    lastComposedRef.current = composed;
    update("population_intent", composed);
  };

  const toggleMulti = (current, value, setter, writer) => {
    const next = current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value];
    setter(next);
    writer(next);
  };

  return (
    <section className="authoring-field-section">
      <header>
        <strong>总体设计意图</strong>
        <span>回答“准备做什么研究”，暂不要求写成方案正文；总体设计须明确采用/不采用，禁止待确认</span>
      </header>
      <div className="authoring-field-grid two">
        <Field label="总体设计模式" required>
          <textarea
            rows={5}
            value={framing.design_pattern}
            onChange={(event) => update("design_pattern", event.target.value)}
            placeholder="如随机、双盲、安慰剂对照、平行组、多中心"
          />
        </Field>
        <Field label="目标研究人群意图" required>
          <div className="authoring-population-structure" data-testid="population-structure-fields">
            <div className="authoring-choice-grid" role="group" aria-label="年龄段">
              <span className="authoring-population-structure-label">年龄段</span>
              {POPULATION_AGE_BAND_OPTIONS.map((item) => (
                <label key={item} className={ageBands.includes(item) ? "selected" : ""}>
                  <input
                    type="checkbox"
                    checked={ageBands.includes(item)}
                    onChange={() => toggleMulti(ageBands, item, setAgeBands, (next) => writePopulationIntent(next, diseaseStates, treatmentStatuses, freeText))}
                  />
                  <span>{item}</span>
                </label>
              ))}
            </div>
            <div className="authoring-choice-grid" role="group" aria-label="疾病状态">
              <span className="authoring-population-structure-label">疾病状态</span>
              {POPULATION_DISEASE_STATE_OPTIONS.map((item) => (
                <label key={item} className={diseaseStates.includes(item) ? "selected" : ""}>
                  <input
                    type="checkbox"
                    checked={diseaseStates.includes(item)}
                    onChange={() => toggleMulti(diseaseStates, item, setDiseaseStates, (next) => writePopulationIntent(ageBands, next, treatmentStatuses, freeText))}
                  />
                  <span>{item}</span>
                </label>
              ))}
            </div>
            <div className="authoring-choice-grid" role="group" aria-label="经治情况">
              <span className="authoring-population-structure-label">经治情况</span>
              {POPULATION_TREATMENT_STATUS_OPTIONS.map((item) => (
                <label key={item} className={treatmentStatuses.includes(item) ? "selected" : ""}>
                  <input
                    type="checkbox"
                    checked={treatmentStatuses.includes(item)}
                    onChange={() => toggleMulti(treatmentStatuses, item, setTreatmentStatuses, (next) => writePopulationIntent(ageBands, diseaseStates, next, freeText))}
                  />
                  <span>{item}</span>
                </label>
              ))}
            </div>
            <textarea
              rows={3}
              value={freeText}
              onChange={(event) => {
                const next = event.target.value;
                setFreeText(next);
                writePopulationIntent(ageBands, diseaseStates, treatmentStatuses, next);
              }}
              placeholder="补充疾病定义、治疗线、既往治疗与严重程度等自然语言意图"
              aria-label="目标研究人群补充说明"
            />
            <small>上述选项会自动写入「目标研究人群意图」摘要；可继续补充自然语言细节。</small>
          </div>
        </Field>
      </div>
      <Phase1PartsEditor framing={framing} update={update} />
    </section>
  );
}

function Phase1PartsEditor({ framing, update, onSave = null, dirty = false, busy = "" }) {
  const parts = phase1PartsFromFraming(framing);
  const selectedCodesKey = parts.map((part) => part.part_code).join("|");
  const [expandedCodes, setExpandedCodes] = useState([]);
  useEffect(() => {
    const currentCodes = parts.map((part) => part.part_code).filter(Boolean);
    setExpandedCodes((current) => {
      const retained = current.filter((code) => currentCodes.includes(code));
      if (retained.length || !currentCodes.length) return retained;
      const firstUnresolved = parts.find(
        (part) => !String(part.population || "").trim() || !String(part.cohort_dose || "").trim(),
      );
      return [firstUnresolved?.part_code || currentCodes[0]];
    });
  // Part codes are the stable accordion identity; field edits must not reset expansion.
  }, [selectedCodesKey]);

  if (!isPhaseOneStudy(framing?.study_phase)) return null;

  const structuredDesign = framing.structured_design || {};
  const writeDesign = (patch) => update("structured_design", { ...structuredDesign, ...patch });
  const availableOptions = [
    ...PHASE1_PART_OPTIONS,
    ...parts
      .filter((part) => !PHASE1_PART_OPTIONS.some((option) => option.code === part.part_code))
      .map((part) => ({ code: part.part_code, label: part.part_label || part.part_code })),
  ];
  const togglePart = (option, selected) => {
    const nextParts = selected
      ? [...parts, {
        part_code: option.code,
        part_label: option.label,
        population: "",
        cohort_dose: "",
        pk_pd: "",
        safety: "",
        stopping_rules: "",
        soa_summary: "",
        transition_dependencies: "",
        unresolved: true,
      }]
      : parts.filter((part) => part.part_code !== option.code);
    writeDesign({ phase1_parts: nextParts });
    setExpandedCodes((current) => selected
      ? [...new Set([...current, option.code])]
      : current.filter((code) => code !== option.code));
  };
  const updatePart = (partCode, field, value) => {
    writeDesign({
      phase1_parts: parts.map((part) => (
        part.part_code === partCode ? { ...part, [field]: value } : part
      )),
    });
  };

  return <section className="phase1-parts-editor" aria-label="I期复合研究Part编辑器">
    <header>
      <div>
        <strong>I期复合研究 Parts</strong>
        <span>已采用或已保存的内容直接载入；可分次补充。研究人群与队列/剂量方案缺失时，确定性投影继续阻断。</span>
      </div>
      {onSave && <button type="button" onClick={onSave} disabled={!dirty || Boolean(busy)}><Save size={14} /> {String(busy).startsWith("draft-") ? "保存中" : "保存研究设计草稿"}</button>}
    </header>
    <div className="phase1-part-selector" aria-label="选择I期研究Part">
      {availableOptions.filter((option) => option.code).map((option) => {
        const selected = parts.some((part) => part.part_code === option.code);
        return <label key={option.code} className={selected ? "selected" : ""}>
          <input type="checkbox" checked={selected} onChange={(event) => togglePart(option, event.target.checked)} />
          <span>{option.label}</span>
        </label>;
      })}
    </div>
    {parts.length > 1 && <Field className="phase1-part-sequence" label="Part总体序列/并行关系"><textarea rows={2} value={structuredDesign.phase1_sequence || ""} onChange={(event) => writeDesign({ phase1_sequence: event.target.value })} placeholder="说明各Part的先后、并行、数据审阅或转段关系" /></Field>}
    {parts.length ? <div className="phase1-part-list">
      {parts.map((part) => {
        const resolved = Boolean(String(part.population || "").trim() && String(part.cohort_dose || "").trim());
        const populatedCount = PHASE1_PART_DETAIL_FIELDS.filter((field) => String(part[field.key] || "").trim()).length;
        return <details key={part.part_code} className="phase1-part-item" open={expandedCodes.includes(part.part_code)} onToggle={(event) => setExpandedCodes((current) => event.currentTarget.open ? [...new Set([...current, part.part_code])] : current.filter((code) => code !== part.part_code))}>
          <summary>
            <span><strong>{part.part_code}</strong><small>{part.part_label || "名称待补"} · {populatedCount}/{PHASE1_PART_DETAIL_FIELDS.length}项已有内容</small></span>
            <em className={resolved ? "ready" : ""}>{resolved ? "投影必填已齐" : "缺投影必填"}</em>
          </summary>
          <div className="phase1-part-fields">
            <Field className="phase1-part-label" label="Part显示名称"><input value={part.part_label || ""} onChange={(event) => updatePart(part.part_code, "part_label", event.target.value)} /></Field>
            {PHASE1_PART_DETAIL_FIELDS.map((field) => <Field key={field.key} className={field.key === "transition_dependencies" ? "phase1-part-wide" : ""} label={field.label} required={field.required}><textarea rows={field.rows} value={part[field.key] || ""} onChange={(event) => updatePart(part.part_code, field.key, event.target.value)} placeholder={field.placeholder} /></Field>)}
          </div>
        </details>;
      })}
    </div> : <p className="phase1-part-empty">尚未选择Part。可先保留为空，后续根据研究目的和证据逐项选择。</p>}
  </section>;
}

const STRUCTURED_DESIGN_MODE_OPTIONS = Object.freeze({
  randomization_mode: [
    ["undecided", "待确认"],
    ["randomized", "随机"],
    ["non_randomized", "非随机"],
    ["other", "其他（需说明）"],
  ],
  blinding_mode: [
    ["undecided", "待确认"],
    ["open_label", "开放标签"],
    ["single_blind", "单盲"],
    ["double_blind", "双盲"],
    ["triple_blind", "三盲"],
    ["other", "其他（需说明）"],
  ],
  comparator_type: [
    ["undecided", "待确认"],
    ["placebo", "安慰剂对照"],
    ["active", "阳性/活性对照"],
    ["none_or_dose_escalation", "无对照/剂量递增"],
    ["other", "其他（需说明）"],
  ],
});

const STRUCTURED_DESIGN_PLANNED_FIELDS = Object.freeze([
  ["adaptive_design", "适应性设计"],
  ["crossover", "交叉设计"],
  ["open_label_extension", "开放标签延伸"],
  ["treatment_switch", "治疗转换"],
  ["sample_size_reestimation", "样本量重估"],
  ["interim_analysis", "期中分析"],
]);

function plannedValue(value) {
  if (value === true) return "true";
  if (value === false) return "false";
  return "";
}

function StructuredDesignFactEditor({ framing, picos, update }) {
  const design = framing.structured_design || {};
  const updateDesign = (patch) => update("structured_design", { ...design, ...patch });
  const updatePlanned = (key, value) => updateDesign({
    [key]: { ...(design[key] || {}), planned: value === "" ? null : value === "true" },
  });
  const text = `${framing.design_pattern || ""} ${picos?.comparator_summary || ""}`;
  const currentTextSuggestion = {
    randomization_mode: /随机/.test(text) ? "randomized" : "undecided",
    blinding_mode: /三盲/.test(text) ? "triple_blind" : /双盲/.test(text) ? "double_blind" : /单盲/.test(text) ? "single_blind" : /开放标签/.test(text) ? "open_label" : "undecided",
    comparator_type: /安慰剂/.test(text) ? "placebo" : /活性对照|阳性对照/.test(text) ? "active" : /剂量递增|无对照/.test(text) ? "none_or_dose_escalation" : "undecided",
    assignment_model: /平行/.test(text) ? "平行组" : /交叉/.test(text) ? "交叉设计" : "",
    center_model: /多中心/.test(text) ? "多中心" : /单中心/.test(text) ? "单中心" : "",
  };
  const applyTextSuggestion = () => updateDesign({
    ...currentTextSuggestion,
    adaptive_design: { ...(design.adaptive_design || {}), planned: false },
    crossover: { ...(design.crossover || {}), planned: currentTextSuggestion.assignment_model === "交叉设计" },
    open_label_extension: { ...(design.open_label_extension || {}), planned: false },
    treatment_switch: { ...(design.treatment_switch || {}), planned: false },
    sample_size_reestimation: { ...(design.sample_size_reestimation || {}), planned: false },
    interim_analysis: { ...(design.interim_analysis || {}), planned: false },
    src_planned: false,
    dmc_planned: false,
  });
  return <section className="authoring-structured-design-facts" data-testid="structured-design-fact-editor">
    <header><div><strong>结构化研究设计确认</strong><span>AI/当前方案文字已给出建议；确认后才会投影到方案摘要、流程图和正文。未确认的维度继续阻断，不会被系统猜测。</span></div><button type="button" className="secondary-button" data-action="apply-structured-design-suggestion" onClick={applyTextSuggestion}>采用当前方案文字建议</button></header>
    <div className="authoring-field-grid three">
      {[["randomization_mode", "随机化"], ["blinding_mode", "盲法"], ["comparator_type", "对照类型"]].map(([key, label]) => <Field key={key} label={label} required><select aria-label={label} value={design[key] || "undecided"} onChange={(event) => updateDesign({ [key]: event.target.value })}>{STRUCTURED_DESIGN_MODE_OPTIONS[key].map(([value, option]) => <option key={value} value={value}>{option}</option>)}</select></Field>)}
      <Field label="分组/分配方式" required><select aria-label="分组/分配方式" value={design.assignment_model || ""} onChange={(event) => updateDesign({ assignment_model: event.target.value })}><option value="">待确认</option><option value="平行组">平行组</option><option value="交叉设计">交叉设计</option><option value="序贯设计">序贯设计</option><option value="其他">其他（需说明）</option></select></Field>
      <Field label="中心模式" required><select aria-label="中心模式" value={design.center_model || ""} onChange={(event) => updateDesign({ center_model: event.target.value })}><option value="">待确认</option><option value="多中心">多中心</option><option value="单中心">单中心</option><option value="有限中心">有限中心</option><option value="其他">其他（需说明）</option></select></Field>
      <Field label="随机化/盲法补充说明"><input aria-label="随机化盲法补充说明" value={design.randomization_details || ""} onChange={(event) => updateDesign({ randomization_details: event.target.value })} placeholder="可保留分层因素、盲态角色等具体说明" /></Field>
    </div>
    <div className="authoring-structured-planned-grid" aria-label="复杂设计计划状态">
      {STRUCTURED_DESIGN_PLANNED_FIELDS.map(([key, label]) => <label key={key}><span>{label}</span><select aria-label={`${label}计划状态`} value={plannedValue(design[key]?.planned)} onChange={(event) => updatePlanned(key, event.target.value)}><option value="">待确认</option><option value="false">不计划</option><option value="true">计划</option></select></label>)}
      <label><span>SRC</span><select aria-label="SRC计划状态" value={design.src_planned == null ? "" : String(Boolean(design.src_planned))} onChange={(event) => updateDesign({ src_planned: event.target.value === "" ? null : event.target.value === "true" })}><option value="">待确认</option><option value="false">不计划</option><option value="true">计划</option></select></label>
      <label><span>DMC</span><select aria-label="DMC计划状态" value={design.dmc_planned == null ? "" : String(Boolean(design.dmc_planned))} onChange={(event) => updateDesign({ dmc_planned: event.target.value === "" ? null : event.target.value === "true" })}><option value="">待确认</option><option value="false">不计划</option><option value="true">计划</option></select></label>
    </div>
  </section>;
}

function PicosFields({ projectId, framing, picos, group, updateFraming, update, updateApplicability, interventionPanel, setInterventionPanel, hasPrefillRecommendations = false, existingDocument = false, readOnly = false, appendixReady = false, onSaveDesignDraft = null, framingDirty = false, busy = "" }) {
  if (group === "applicability") return <section className="authoring-field-section"><header><strong>研究设计适用性</strong><span>优先采用上方调研建议；随机化、盲法、对照、分组和期中分析等维度分别确认，系统再组合成研究设计。</span></header>{picos.design_archetype && <div className="authoring-current-design"><CheckCircle2 size={15} /><span>当前兼容设计类型：<strong>{DESIGN_ARCHETYPES.find((item) => item.value === picos.design_archetype)?.label || picos.design_archetype}</strong></span></div>}<details className="authoring-manual-design-options" open={!hasPrefillRecommendations}><summary>{hasPrefillRecommendations ? "手动选择兼容设计类型" : "选择兼容设计类型"}</summary><div className="authoring-design-archetypes">{DESIGN_ARCHETYPES.map((item) => <label key={item.value} className={picos.design_archetype === item.value ? "selected" : ""}><input type="radio" name="picos-design-archetype" value={item.value} checked={picos.design_archetype === item.value} onChange={() => update("design_archetype", item.value)} /><span><strong>{item.label}</strong><small>{item.detail}</small></span></label>)}</div></details>{picos.design_archetype && <div className="authoring-applicability-list"><div className="authoring-applicability-head"><strong>条件字段</strong><span>标记为“不适用”时，必须填写理由并由医学经理确认。</span></div>{CONDITIONAL_PICOS_FIELDS.map((item) => { const decision = picos.field_applicability?.[item.key] || { status: "applicable", reason: "", confirmed_by_medical_manager: false }; const lockedRequired = picos.design_archetype === "randomized_confirmatory" || (picos.design_archetype === "randomized_exploratory" && item.key === "comparator_summary"); const notApplicable = decision.status === "not_applicable"; return <div className="authoring-applicability-row" key={item.key}><div><strong>{item.label}</strong><small>{lockedRequired ? "当前随机设计中必须填写" : "可根据已确认的研究设计判断是否适用"}</small></div><select aria-label={`${item.label}适用性`} value={lockedRequired ? "applicable" : decision.status} onChange={(event) => updateApplicability(item.key, { status: event.target.value })} disabled={lockedRequired}><option value="applicable">适用，需填写</option><option value="not_applicable">不适用</option></select>{notApplicable && !lockedRequired && <><textarea aria-label={`${item.label}不适用理由`} rows={2} value={decision.reason || ""} onChange={(event) => updateApplicability(item.key, { reason: event.target.value })} placeholder="说明本研究为何无需该设计项；不少于10个字符" /><label className="authoring-applicability-confirm"><input type="checkbox" checked={Boolean(decision.confirmed_by_medical_manager)} onChange={(event) => updateApplicability(item.key, { confirmed_by_medical_manager: event.target.checked })} /><span>医学经理确认该项不适用</span></label></>}</div>; })}</div>}<StructuredDesignFactEditor framing={framing} picos={picos} update={updateFraming} /><Phase1PartsEditor framing={framing} update={updateFraming} onSave={onSaveDesignDraft} dirty={framingDirty} busy={busy} /></section>;
  if (group === "population") return <section className="authoring-field-section"><header><strong>研究人群</strong><span>模块化确定人群、入排、洗脱与重筛边界</span></header><div className="authoring-field-grid two"><Field label="目标人群概述" required className="span-2"><textarea rows={3} value={picos.population_summary} onChange={(event) => update("population_summary", event.target.value)} /></Field><StructuredListField label="入选标准" prefix="IN" required value={picos.inclusion_modules} onChange={(value) => update("inclusion_modules", value)} /><StructuredListField label="排除标准" prefix="EX" required value={picos.exclusion_modules} onChange={(value) => update("exclusion_modules", value)} /><StructuredListField className="span-2" label="药物/治疗洗脱规则" prefix="WO" value={picos.washout_rules} onChange={(value) => update("washout_rules", value)} /></div></section>;
  if (group === "intervention") return <section className="authoring-field-section"><header><strong>干预措施</strong><span>试验药物、非试验用药和普通CM保持清晰边界</span></header><div className="authoring-field-grid two"><Field label="试验药物干预概述" required><textarea rows={4} value={picos.intervention_summary} onChange={(event) => update("intervention_summary", event.target.value)} /></Field><Field label="试验药物常规用法用量" required><textarea rows={4} value={picos.intervention_dose_regimen} onChange={(event) => update("intervention_dose_regimen", event.target.value)} /></Field><StructuredListField label="必须使用/背景治疗" prefix="BG" value={picos.required_background_rules} onChange={(value) => update("required_background_rules", value)} /><StructuredListField label="允许使用的合并用药/治疗" prefix="CM-A" value={picos.allowed_concomitant_rules} onChange={(value) => update("allowed_concomitant_rules", value)} /><StructuredListField label="限制/禁止使用的合并用药/治疗" prefix="CM-P" value={picos.prohibited_concomitant_rules} onChange={(value) => update("prohibited_concomitant_rules", value)} /><StructuredListField label="访视/评价前用药与治疗限制" prefix="TIME" value={picos.assessment_timing_restrictions} onChange={(value) => update("assessment_timing_restrictions", value)} /></div><InterventionRulesEditor value={picos.intervention_rules || null} onChange={(value) => update("intervention_rules", value)} panel={interventionPanel} onPanelChange={setInterventionPanel} /></section>;
  if (group === "comparator") { const notApplicable = picos.field_applicability?.comparator_summary?.status === "not_applicable" && !["randomized_confirmatory", "randomized_exploratory"].includes(picos.design_archetype); return <section className="authoring-field-section"><header><strong>对照</strong><span>{notApplicable ? "已在设计适用性中标记为不适用；理由仍保留在正式研究事实中" : "明确安慰剂、阳性对照或随机组间比较及其用法用量"}</span></header>{notApplicable ? <ApplicabilitySummary label="对照/组间比较设计" decision={picos.field_applicability.comparator_summary} onEdit={() => {}} /> : <Field label="对照/组间比较设计" required><textarea rows={7} value={picos.comparator_summary} onChange={(event) => update("comparator_summary", event.target.value)} /></Field>}</section>; }
  if (group === "outcomes") return <section className="authoring-field-section"><header><strong>结局指标</strong><span>终点定义必须包含评价变量、时间点和必要的应答规则</span></header><div className="authoring-field-grid two"><Field label="主要终点及评价时间" required className="span-2"><textarea rows={3} value={picos.primary_endpoint} onChange={(event) => update("primary_endpoint", event.target.value)} /></Field><ListField label="关键次要终点" value={picos.key_secondary_endpoints} onChange={(value) => update("key_secondary_endpoints", value)} /><ListField label="其他次要终点" value={picos.other_secondary_endpoints} onChange={(value) => update("other_secondary_endpoints", value)} /><ListField label="探索性终点" value={picos.exploratory_endpoints} onChange={(value) => update("exploratory_endpoints", value)} /><ListField label="安全性终点" required value={picos.safety_endpoints} onChange={(value) => update("safety_endpoints", value)} /><ListField label="AESI定义" value={picos.aesi_definitions} onChange={(value) => update("aesi_definitions", value)} /></div><AssessmentInstrumentEditor projectId={projectId} value={picos.assessment_instruments || []} onChange={(value) => update("assessment_instruments", value)} existingDocument={existingDocument} readOnly={readOnly} appendixReady={appendixReady} /></section>;
  const estimandNotApplicable = picos.field_applicability?.estimand_strategy?.status === "not_applicable" && picos.design_archetype !== "randomized_confirmatory";
  return <section className="authoring-field-section"><header><strong>研究执行与统计</strong><span>补齐生成流程表、估计目标和统计章节所需结构事实</span></header><div className="authoring-field-grid two"><ListField label="研究时期/阶段" required value={picos.study_epochs} onChange={(value) => update("study_epochs", value)} /><Field label="访视策略" required><textarea rows={4} value={picos.visit_strategy} onChange={(event) => update("visit_strategy", event.target.value)} placeholder="概述筛选、基线、治疗、关键评价和随访访视；具体活动可在SoA表格设计器中完善" /></Field>{estimandNotApplicable ? <ApplicabilitySummary label="估计目标策略" decision={picos.field_applicability.estimand_strategy} /> : <Field label="估计目标策略" required><textarea rows={4} value={picos.estimand_strategy} onChange={(event) => update("estimand_strategy", event.target.value)} /></Field>}<Field label="样本量策略" required><textarea rows={4} value={picos.sample_size_strategy} onChange={(event) => update("sample_size_strategy", event.target.value)} /></Field><Field label="统计分析策略" required className="span-2"><textarea rows={4} value={picos.statistical_strategy} onChange={(event) => update("statistical_strategy", event.target.value)} /></Field></div></section>;
}

const INSTRUMENT_KIND_OPTIONS = [
  ["clinician_reported", "研究者/临床医生评估"],
  ["patient_reported", "患者报告结局（PRO）"],
  ["observer_reported", "观察者报告结局"],
  ["performance_outcome", "操作/表现结局"],
  ["diagnostic_criterion", "诊断/入排判定工具"],
  ["safety_grading", "安全性分级标准"],
  ["other", "其他评估工具"],
];
const TRANSLATION_STATUS_OPTIONS = [
  ["unknown", "中文版本待核实"], ["not_needed", "无需翻译"], ["official_available", "已有官方中文版本"],
  ["validated_available", "已有验证中文版本"], ["permission_required", "翻译/使用需许可"],
  ["translation_candidate", "中文候选待医学审阅"], ["medical_reviewed", "医学已审阅"], ["unavailable", "未找到可用中文版本"],
];
const RIGHTS_STATUS_OPTIONS = [
  ["unknown", "权利状态待核实"], ["permission_required", "使用前需许可"], ["license_pending", "许可申请中"],
  ["licensed", "当前项目已获许可"], ["public_domain", "公共领域"], ["permission_not_required", "已确认无需许可"],
];
const ENDPOINT_BINDINGS = [
  ["picos.primary_endpoint", "主要终点"], ["picos.key_secondary_endpoints", "关键次要终点"],
  ["picos.other_secondary_endpoints", "其他次要终点"], ["picos.exploratory_endpoints", "探索性终点"],
  ["picos.safety_endpoints", "安全性终点"], ["picos.inclusion_modules", "入选标准"], ["picos.exclusion_modules", "排除标准"],
];

function newInstrument() {
  const identity = typeof globalThis.crypto?.randomUUID === "function" ? globalThis.crypto.randomUUID() : `${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
  return {
    instrument_id: `mwinstrument_${identity}`, canonical_name_zh: "待命名评估工具", canonical_name_en: "", acronym: "", version_label: "",
    instrument_kind: "other", administration_mode: "", respondent: "", recall_period: "", scoring_range: "", scoring_direction: "", scoring_summary: "", study_purpose: "",
    endpoint_paths: [], visit_labels: [], soa_activity_ids: [], appendix_locator: "", protocol_modified: false, source_synopsis_only: false, evidence_span_ids: [], source_bindings: [],
    rights: { status: "unknown", full_text_policy: "metadata_only", owner: "", license_reference: "", evidence_url: "", checked_at: null, confirmed_by: "", confirmed_at: null },
    translation: { source_language: "", target_language: "简体中文", status: "unknown", version_label: "", source_url: "", artifact_id: "", reviewed_by: "", reviewed_at: null },
    confirmation_status: "candidate", confirmed_by: "", confirmed_at: null, notes: "",
  };
}

function AssessmentInstrumentEditor({ projectId, value, onChange, existingDocument = false, readOnly = false, appendixReady = false }) {
  const [selectedId, setSelectedId] = useState(value[0]?.instrument_id || "");
  const [appendixFile, setAppendixFile] = useState(null);
  const [appendixTarget, setAppendixTarget] = useState(null);
  const [appendixResult, setAppendixResult] = useState(null);
  const [appendixPages, setAppendixPages] = useState([]);
  const [appendixBusy, setAppendixBusy] = useState(false);
  const [appendixMessage, setAppendixMessage] = useState("");
  useEffect(() => {
    if (!value.length) {
      if (selectedId) setSelectedId("");
      return;
    }
    if (!value.some((item) => item.instrument_id === selectedId)) {
      setSelectedId(value[0].instrument_id);
    }
  }, [selectedId, value]);
  useEffect(() => {
    const controller = new AbortController();
    setAppendixFile(null);
    setAppendixTarget(null);
    setAppendixResult(null);
    setAppendixPages([]);
    setAppendixMessage("");
    if (!projectId || !existingDocument || !selectedId) return () => controller.abort();
    (async () => {
      try {
        const document = await fetch(
          `/api/projects/${projectId}/medical-writing/document-session`,
          { signal: controller.signal },
        ).then(readJson);
        const sections = document.sections || [];
        const section = (
          sections.find((item) => item.node_kind === "assessment_instrument_appendix")
          || sections.find((item) => /instrument/i.test(item.template_node_id || ""))
          || sections.find((item) => /量表|评价工具/.test(item.heading || ""))
          || sections.find((item) => (item.interaction_types || []).includes("assessment_instrument_builder"))
          || sections.find((item) => item.section_number === "14.2" && /量表|评价工具/.test(item.heading || ""))
        );
        if (!section) {
          setAppendixMessage("当前方案未启用“研究量表和评价工具”章节。");
          return;
        }
        const workingCopy = await fetch(
          `/api/projects/${projectId}/medical-writing/working-copies/${section.section_id}`,
          { signal: controller.signal },
        ).then(readJson);
        if (controller.signal.aborted) return;
        const pages = (workingCopy.content_blocks || []).filter((block) => (
          block.block_type === "appendix_image"
          && block.attachment_kind === "assessment_instrument_page"
          && block.instrument_id === selectedId
        ));
        setAppendixTarget({ section, workingCopy });
        // Keep block references only; preview reads image_base64 from these objects.
        setAppendixPages(pages);
        if (pages.length) {
          const first = pages[0];
          setAppendixResult({
            source_filename: first.source_filename,
            page_count: first.page_count || pages.length,
            render_dpi: first.render_dpi,
            projection_action: "existing",
            updated_at: workingCopy.updated_at,
          });
        }
      } catch (error) {
        if (error.name !== "AbortError" && !controller.signal.aborted) {
          setAppendixMessage(error.status === 404 ? "方案正文尚未生成，生成后可上传原始量表。" : `量表附件状态读取失败：${error.message}`);
        }
      }
    })();
    return () => controller.abort();
  }, [existingDocument, projectId, selectedId]);
  const selected = value.find((item) => item.instrument_id === selectedId) || null;
  const updateItem = (patch) => onChange(value.map((item) => item.instrument_id === selectedId ? { ...item, ...patch } : item));
  const updateNested = (field, patch) => updateItem({ [field]: { ...(selected?.[field] || {}), ...patch } });
  const add = () => { const next = newInstrument(); onChange([...value, next]); setSelectedId(next.instrument_id); };
  const remove = () => {
    const next = value.filter((item) => item.instrument_id !== selectedId);
    onChange(next);
    setSelectedId(next[0]?.instrument_id || "");
  };
  const toggleEndpoint = (path) => updateItem({ endpoint_paths: selected.endpoint_paths.includes(path) ? selected.endpoint_paths.filter((item) => item !== path) : [...selected.endpoint_paths, path] });
  const uploadAppendix = async () => {
    if (!appendixFile || !appendixTarget || !selected || appendixBusy) return;
    setAppendixBusy(true);
    setAppendixMessage("正在上传并按 220 DPI 转换原始页面...");
    try {
      const form = new FormData();
      form.append("file", appendixFile);
      form.append("instrument_id", selected.instrument_id);
      form.append("expected_working_copy_revision", String(appendixTarget.workingCopy.revision));
      form.append("actor", "medical_manager");
      form.append("dpi", "220");
      form.append(
        "idempotency_key",
        await stableInstrumentAppendixUploadKey(
          projectId,
          appendixTarget.section.section_id,
          selected.instrument_id,
          appendixTarget.workingCopy.revision,
          appendixFile,
        ),
      );
      const payload = await fetch(
        `/api/projects/${projectId}/medical-writing/working-copies/${appendixTarget.section.section_id}/assessment-instrument-appendix`,
        { method: "POST", body: form },
      ).then(readJson);
      setAppendixTarget((current) => ({ ...current, workingCopy: payload.working_copy }));
      setAppendixResult(payload);
      const refreshedPages = (payload.working_copy?.content_blocks || []).filter((block) => (
        block.block_type === "appendix_image"
        && block.attachment_kind === "assessment_instrument_page"
        && block.instrument_id === selected.instrument_id
      ));
      setAppendixPages(refreshedPages);
      const sectionLabel = [payload.target_section_number, payload.target_section_heading].filter(Boolean).join(" ");
      setAppendixMessage(payload.projection_action === "replaced" ? `已替换“${sectionLabel}”中的原始量表页面。` : `已写入“${sectionLabel}”。`);
      setAppendixFile(null);
    } catch (error) {
      setAppendixMessage(
        error.status === 409
          ? "目标章节已被更新，请重新选择文件后再试。"
          : error.status === 422
            ? `暂不能写入：${error.message}`
            : `量表附件上传失败：${error.message}`,
      );
    } finally {
      setAppendixBusy(false);
    }
  };
  return <section className="authoring-instrument-registry">
    <header><div><strong>量表与评估工具</strong><span>统一维护版本、项目用法、评价时点、中文版本及全文使用边界；未知状态不会被系统自动视为已获许可。</span></div><button type="button" onClick={add}><Plus size={14} /> 新增工具</button></header>
    {!value.length ? <div className="authoring-instrument-empty"><p>尚未登记量表或评分工具。可根据主要/次要终点添加；竞品方案提取的候选也将在此处待用户确认。</p><button type="button" onClick={add}><Plus size={14} /> 登记第一个工具</button></div> : <div className="authoring-instrument-layout">
      <div className="authoring-instrument-list" role="listbox" aria-label="量表与评估工具列表">{value.map((item) => <button type="button" role="option" aria-selected={item.instrument_id === selectedId} className={item.instrument_id === selectedId ? "selected" : ""} key={item.instrument_id} onClick={() => setSelectedId(item.instrument_id)}><span><strong>{item.acronym || item.canonical_name_zh}</strong><small>{item.acronym ? item.canonical_name_zh : item.canonical_name_en || "英文名称待补充"}</small></span><em className={`instrument-state ${item.confirmation_status}`}>{item.confirmation_status === "confirmed" ? "已确认" : item.confirmation_status === "needs_review" ? "需复核" : "候选"}</em></button>)}</div>
      {selected && <div className="authoring-instrument-editor">
        <div className="authoring-instrument-editor-head"><div><strong>{selected.acronym || selected.canonical_name_zh}</strong><span>{selected.version_label || "版本待确认"}</span></div><button type="button" className="danger-quiet" onClick={remove} title="删除当前工具"><Trash2 size={14} /> 删除</button></div>
        <div className="authoring-field-grid four"><Field label="中文规范名称" required><input value={selected.canonical_name_zh} onChange={(event) => updateItem({ canonical_name_zh: event.target.value })} /></Field><Field label="英文规范名称"><input value={selected.canonical_name_en} onChange={(event) => updateItem({ canonical_name_en: event.target.value })} /></Field><Field label="缩写"><input value={selected.acronym} onChange={(event) => updateItem({ acronym: event.target.value })} /></Field><Field label="版本/变体"><input value={selected.version_label} onChange={(event) => updateItem({ version_label: event.target.value })} placeholder="如 8a、v4、0-4分制" /></Field><Field label="工具类型"><select value={selected.instrument_kind} onChange={(event) => updateItem({ instrument_kind: event.target.value })}>{INSTRUMENT_KIND_OPTIONS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field><Field label="填写/评估者"><input value={selected.respondent} onChange={(event) => updateItem({ respondent: event.target.value })} placeholder="参与者、研究者、照护者" /></Field><Field label="回忆期"><input value={selected.recall_period} onChange={(event) => updateItem({ recall_period: event.target.value })} placeholder="如过去24小时、过去7天" /></Field><Field label="实施方式"><input value={selected.administration_mode} onChange={(event) => updateItem({ administration_mode: event.target.value })} placeholder="纸质、ePRO、访视现场" /></Field><Field label="评分范围"><input value={selected.scoring_range} onChange={(event) => updateItem({ scoring_range: event.target.value })} placeholder="如 0-52" /></Field><Field className="span-2" label="评分方向"><input value={selected.scoring_direction} onChange={(event) => updateItem({ scoring_direction: event.target.value })} placeholder="分值越高表示……" /></Field><Field label="附录/来源定位"><input value={selected.appendix_locator} onChange={(event) => updateItem({ appendix_locator: event.target.value })} placeholder="如 附录1、表6" /></Field><Field className="span-2" label="本研究用途"><textarea rows={3} value={selected.study_purpose} onChange={(event) => updateItem({ study_purpose: event.target.value })} /></Field><Field className="span-2" label="评分与应答规则摘要"><textarea rows={3} value={selected.scoring_summary} onChange={(event) => updateItem({ scoring_summary: event.target.value })} /></Field></div>
        <fieldset className="authoring-instrument-bindings"><legend>关联研究事实</legend><div>{ENDPOINT_BINDINGS.map(([path, label]) => <label key={path}><input type="checkbox" checked={selected.endpoint_paths.includes(path)} onChange={() => toggleEndpoint(path)} /><span>{label}</span></label>)}</div><Field label="评价访视/时点（每行一项）"><textarea rows={3} value={lineText(selected.visit_labels)} onChange={(event) => updateItem({ visit_labels: lines(event.target.value) })} placeholder="基线（D1）&#10;第12周（D85±7天）" /></Field></fieldset>
        <div className="authoring-instrument-governance"><section><header><strong>中文版本</strong><span>{selected.translation.status === "medical_reviewed" ? "医学已审阅" : "待按来源确认"}</span></header><label><span>状态</span><select value={selected.translation.status} onChange={(event) => updateNested("translation", { status: event.target.value, reviewed_by: event.target.value === "medical_reviewed" ? "medical_manager" : "", reviewed_at: event.target.value === "medical_reviewed" ? new Date().toISOString() : null })}>{TRANSLATION_STATUS_OPTIONS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label><span>版本/语言</span><input value={selected.translation.version_label} onChange={(event) => updateNested("translation", { version_label: event.target.value })} /></label><label><span>权威来源</span><input type="url" value={selected.translation.source_url} onChange={(event) => updateNested("translation", { source_url: event.target.value })} placeholder="量表所有者或验证研究链接" /></label></section><section><header><strong>权利与全文边界</strong><span>{selected.rights.full_text_policy === "metadata_only" ? "仅保存元数据" : "按已确认范围使用"}</span></header><label><span>状态</span><select value={selected.rights.status} onChange={(event) => updateNested("rights", { status: event.target.value })}>{RIGHTS_STATUS_OPTIONS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label><span>权利人/管理方</span><input value={selected.rights.owner} onChange={(event) => updateNested("rights", { owner: event.target.value })} /></label><label><span>许可编号或证据链接</span><input value={selected.rights.license_reference || selected.rights.evidence_url} onChange={(event) => updateNested("rights", { license_reference: event.target.value, evidence_url: /^https?:/i.test(event.target.value) ? event.target.value : selected.rights.evidence_url })} /></label></section></div>
        <section className="authoring-instrument-appendix">
          <header><div><strong>原始量表附件</strong><span>PDF原页将按 220 DPI 写入方案中的量表工具章节，保持题项、选框和版权标识的可读性。</span></div><em className={appendixResult || appendixPages.length ? "ready" : ""}>{appendixResult || appendixPages.length ? "已写入方案" : "尚未写入"}</em></header>
          {(appendixResult || appendixPages.length > 0) && <div className="authoring-instrument-appendix-result"><FileText size={16} /><span><strong title={appendixResult?.source_filename || selected.canonical_name_zh}>{appendixResult?.source_filename || selected.canonical_name_zh}</strong><small>{appendixPages.length || appendixResult?.page_count || 0} 页 · {appendixResult?.render_dpi || 220} DPI{appendixResult?.projection_action === "replaced" ? " · 已替换" : ""}</small></span></div>}
          {appendixPages.length > 0 ? (
            <InstrumentAppendixPreview
              pages={appendixPages}
              declaredPageCount={appendixResult?.page_count || appendixPages[0]?.page_count || appendixPages.length}
              instrumentLabel={selected.acronym || selected.canonical_name_zh || "量表附件"}
            />
          ) : existingDocument && selected.confirmation_status === "confirmed" && appendixReady ? (
            <InstrumentAppendixPreview pages={[]} emptyMessage="当前工作副本尚无该量表的原始页面；上传 PDF 后可在此逐页审阅。" />
          ) : null}
          {!existingDocument ? <p>完成PICOS并生成方案正文后，可在此上传原始量表PDF。</p> : selected.confirmation_status !== "confirmed" ? <p>先确认该量表在本项目中的用法，再上传原始量表PDF。</p> : !appendixReady ? <p>当前量表信息尚未保存。完成第二步后即可写入方案中的量表工具章节。</p> : !readOnly && <div className="authoring-instrument-appendix-actions"><label><input type="file" accept=".pdf,application/pdf" onChange={(event) => { setAppendixFile(event.target.files?.[0] || null); setAppendixMessage(""); }} /><Upload size={15} /><span><strong>{appendixFile?.name || (appendixResult || appendixPages.length ? "选择新PDF以替换" : "选择原始量表PDF")}</strong><small>{appendixFile ? formatFileSize(appendixFile.size) : "最多50 MB；支持1–100页"}</small></span></label><button type="button" onClick={uploadAppendix} disabled={!appendixFile || !appendixTarget || appendixBusy}>{appendixBusy ? <RefreshCw size={14} /> : <Upload size={14} />}{appendixBusy ? "处理中" : appendixResult || appendixPages.length ? "替换附件" : "写入方案"}</button></div>}
          {readOnly && appendixPages.length > 0 && <p className="success">只读模式可审阅原始页面，不可上传或删除附件。</p>}
          {appendixMessage && <p className={/失败|暂不能|未启用|尚未生成|更新/.test(appendixMessage) ? "warning" : "success"}>{appendixMessage}</p>}
        </section>
        <div className="authoring-instrument-confirm"><label><input type="checkbox" checked={selected.protocol_modified} onChange={(event) => updateItem({ protocol_modified: event.target.checked })} /><span>本方案对原量表回忆期、填写频率、措辞或版式有修改，需单独核实</span></label><label><input type="checkbox" checked={selected.source_synopsis_only} onChange={(event) => updateItem({ source_synopsis_only: event.target.checked })} /><span>当前仅有方案摘要信息，完整版本/题项待后续方案核对</span></label><button type="button" className={selected.confirmation_status === "confirmed" ? "confirmed" : ""} onClick={() => updateItem({ confirmation_status: selected.confirmation_status === "confirmed" ? "needs_review" : "confirmed", confirmed_by: selected.confirmation_status === "confirmed" ? "" : "medical_manager", confirmed_at: selected.confirmation_status === "confirmed" ? null : new Date().toISOString() })}>{selected.confirmation_status === "confirmed" ? <CheckCircle2 size={14} /> : <ShieldAlert size={14} />}{selected.confirmation_status === "confirmed" ? "医学经理已确认本项目用法" : "确认本项目用法"}</button></div>
      </div>}
    </div>}
  </section>;
}

const ASSEMBLY_PLAN_BLOCKER_LABELS = Object.freeze({
  "intervention.active_comparator_regimen": "活动对照的具体方案",
  "intervention.background_treatment": "背景治疗规则",
  "intervention.investigational_product_dose_actions": "试验药物剂量调整规则",
  "intervention.investigational_product_regimen": "试验药物给药方案",
  "intervention.permitted_concomitant_treatment": "允许的合并治疗",
  "intervention.placebo_regimen": "安慰剂给药方案",
  "intervention.prohibited_concomitant_treatment": "禁止的合并治疗",
  "intervention.rescue_treatment": "救援治疗规则",
});

function CorpusGate({ projectId, journey, setJourney, selectedBriefIds, setSelectedBriefIds, searchMessage, busy, onSearch, acknowledged, setAcknowledged, overrideReason, setOverrideReason, allAcknowledged, onOverride, onCreateDocument, onReviewAssemblyPlan, readOnly = false, existingDocument = false }) {
  const [assemblyPlanState, setAssemblyPlanState] = useState({ status: "loading", payload: null, error: "" });
  const assemblyPlanRefreshAttemptRef = useRef("");
  const gate = journey?.corpus_gate; const searchPlan = journey?.search_plan; const missing = gate?.missing_requirements || []; const allowed = Boolean(gate?.access_permitted);
  const ready = gate?.readiness_status === "ready";
  const gateStatusClass = ready ? "allowed" : allowed ? "exception" : "blocked";
  const assemblyPayload = assemblyPlanState.payload || {};
  const assemblyPlan = assemblyPayload.plan || null;
  const assemblyPlanReady = Boolean(
    assemblyPayload.available
      && assemblyPayload.source_current
      && assemblyPayload.confirmation_current
      && assemblyPayload.deterministic_projection_allowed,
  );
  const studyDefinitionBound = Boolean(
    journey?.study_definition?.definition_id
      && journey?.study_definition?.revision
      && journey?.study_definition?.state_sha256,
  );
  const assemblyPlanBlockers = (assemblyPlan?.modules || []).flatMap((module) => (module.unresolved_questions || []).map((question) => ({
    code: question.code || module.module_id,
    label: ASSEMBLY_PLAN_BLOCKER_LABELS[module.module_id] || ASSEMBLY_PLAN_BLOCKER_LABELS[question.code] || question.prompt || module.module_id,
  })));
  const gateStatusText = ready && assemblyPlanReady
    ? "语料与方案结构均已核对"
    : ready
      ? "语料已就绪 · 仍需核对方案结构"
      : allowed
        ? "例外放行 · 语料未就绪"
        : "当前阻断写作";

  useEffect(() => {
    const definition = journey?.study_definition;
    if (!definition?.definition_id || !definition.revision || !definition.state_sha256) {
      setAssemblyPlanState({ status: "missing-definition", payload: null, error: "研究定义尚未完成版本绑定" });
      return undefined;
    }
    const controller = new AbortController();
    let cancelled = false;
    const definitionKey = `${definition.definition_id}:${definition.revision}:${definition.state_sha256}`;
    const readPlan = async () => {
      try {
        const payload = await fetch(`/api/projects/${projectId}/medical-writing/protocol-assembly-plan`, { signal: controller.signal }).then(readJson);
        if (cancelled) return;
        if (payload.available && payload.source_current) {
          setAssemblyPlanState({ status: "ready", payload, error: "" });
          return;
        }
        const planRevision = payload.plan?.revision || 0;
        const refreshKey = `${projectId}:${definitionKey}:${planRevision}`;
        if (readOnly || assemblyPlanRefreshAttemptRef.current === refreshKey) {
          setAssemblyPlanState({ status: payload.available ? "stale" : "missing", payload, error: payload.stale_reason || "方案组装计划尚未生成" });
          return;
        }
        assemblyPlanRefreshAttemptRef.current = refreshKey;
        setAssemblyPlanState({ status: "refreshing", payload, error: "正在自动核对方案结构完整性" });
        await fetch(`/api/projects/${projectId}/medical-writing/protocol-assembly-plan/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            expected_plan_revision: planRevision,
            expected_source_definition_id: definition.definition_id,
            expected_source_definition_revision: definition.revision,
            expected_source_definition_sha256: definition.state_sha256,
            actor: "medical_manager",
            idempotency_key: `authoring-assembly-plan-refresh-${projectId}-${definitionKey}`.slice(0, 200),
          }),
        }).then(readJson);
        const refreshed = await fetch(`/api/projects/${projectId}/medical-writing/protocol-assembly-plan`, { signal: controller.signal }).then(readJson);
        if (!cancelled) setAssemblyPlanState({ status: refreshed.available ? "ready" : "missing", payload: refreshed, error: refreshed.stale_reason || "" });
      } catch (error) {
        if (cancelled || error.name === "AbortError") return;
        if (error.status === 404) {
          setAssemblyPlanState({ status: "missing", payload: { available: false }, error: "方案组装计划尚未生成" });
        } else {
          setAssemblyPlanState({ status: "error", payload: null, error: "暂时无法核对方案结构，请稍后重试" });
        }
      }
    };
    readPlan();
    return () => { cancelled = true; controller.abort(); };
  }, [projectId, journey?.revision, journey?.study_definition?.definition_id, journey?.study_definition?.revision, journey?.study_definition?.state_sha256, readOnly]);

  // A documented corpus exception is an explicit, auditable writing route;
  // it must not be rendered as permanently disabled merely because the full
  // evidence gate is not ready.  The backend still requires a complete,
  // version-bound StudyDefinition, so keep that binding as the only local
  // prerequisite for this exception path.  The normal ready path retains the
  // stricter assembly-plan check.
  const writeEntryReady = allowed
    && (ready ? assemblyPlanReady : studyDefinitionBound);
  const assemblyPlanMessage = assemblyPlanState.status === "loading" || assemblyPlanState.status === "refreshing"
    ? "系统正在自动核对方案结构完整性，您无需填写技术表单。"
    : assemblyPlanReady
      ? "方案结构已完成版本绑定，可建立版本化方案工作稿。"
      : assemblyPlanBlockers.length
        ? `还需确认：${assemblyPlanBlockers.slice(0, 3).map((item) => item.label).join("、")}${assemblyPlanBlockers.length > 3 ? `等${assemblyPlanBlockers.length}项` : ""}。`
        : assemblyPlanState.error || "方案结构尚未完成核对，暂不能建立工作稿。";
  const persistedSearchMessage = searchPlan?.latest_snapshot_id ? `最近一次公开检索已记录：${searchPlan.returned_count}项公开研究，${searchPlan.public_document_count}份公开Protocol；结果编号 ${searchPlan.latest_snapshot_id}。` : "";
  const reusableSnapshotId = searchPlan?.latest_snapshot_id
    || journey?.discovery_basket_projection?.snapshot_id
    || "";
  const reusingPriorSnapshot = Boolean(
    reusableSnapshotId && !searchPlan?.latest_snapshot_id,
  );
  const visibleSearchMessage = searchMessage
    || (reusingPriorSnapshot
      ? "既有公开检索结果已保留；请按当前研究信息复核预选分类，无需重复检索。"
      : persistedSearchMessage);
  const searchContractIncomplete = Boolean(searchPlan && !searchPlan.registry_filter);
  const registryFilter = searchPlan?.registry_filter || {};
  const triageCriteria = searchPlan?.triage_criteria || [];
  const registryFilterRows = [
    ["疾病/适应症", registryFilter.condition_term],
    ["研究分期", (registryFilter.phases || []).join("、")],
    ["研究类型", registryFilter.study_type],
    ["干预名称", (registryFilter.intervention_terms || []).join("、") || "不限"],
    ["研究地区", (registryFilter.regions || []).join("、") || "不限"],
  ];
  return (
    <section className="authoring-corpus-stage">
      <header><div><strong>语料准备与写作准入</strong><span>公开竞品原文、监管中文语料和项目设计事实共同决定章节可写性</span></div><span className={`authoring-gate-status ${gateStatusClass}`}>{gateStatusText}</span></header>
      <div className="authoring-search-plan">
        <div><Search size={17} /><span><strong>ClinicalTrials.gov竞品检索计划</strong><small>先按注册库条件宽检索，再由医学经理按项目设计线索分诊相关研究。</small></span></div>
        <button
          type="button"
          onClick={onSearch}
          disabled={readOnly || busy === "search" || searchContractIncomplete}
          title={
            searchContractIncomplete
              ? "检索条件不完整，请刷新页面后重试"
              : reusingPriorSnapshot
                ? "既有结果可直接复核；仅在需要更新公开信息时重新检索"
                : searchPlan?.latest_snapshot_id && (searchPlan?.returned_count || 0) > 0
                ? "已有检索结果；再次点击将按当前条件重新检索并覆盖上一批结果"
                : searchPlan?.latest_snapshot_id && (searchPlan?.returned_count || 0) === 0
                  ? "上次检索未找到公开研究；可修正适应症英文检索词后重新检索"
                  : "向 ClinicalTrials.gov 发起公开竞品检索"
          }
        >
          <RefreshCw size={14} />
          {" "}
          {busy === "search"
            ? "检索中…"
            : reusingPriorSnapshot
              ? "按需重新检索"
              : searchPlan?.latest_snapshot_id
              ? ((searchPlan?.returned_count || 0) > 0 ? "重新检索竞品" : "未找到结果，重新检索")
              : "执行公开竞品检索"}
        </button>
        <div className="authoring-search-contract">
          <section aria-label="实际注册库过滤条件">
            <strong>实际发送到注册库的条件</strong>
            <dl>{registryFilterRows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "待确认"}</dd></div>)}</dl>
          </section>
          <section aria-label="检索后医学分诊条件">
            <strong>检索后医学分诊线索</strong>
            {triageCriteria.length ? <ul>{triageCriteria.map((item) => <li key={item.criterion_id}><b>{item.label}</b><span>{item.value}</span></li>)}</ul> : <p>尚未形成靶点、研究目的或设计分诊线索。</p>}
          </section>
        </div>
        {searchContractIncomplete && <p className="authoring-search-contract-error" role="alert">检索合同版本过旧，请刷新页面后重试；系统不会按前端推测条件发起注册库检索。</p>}
        {visibleSearchMessage && <p>{visibleSearchMessage}</p>}
      </div>
      {reusableSnapshotId && <WritingReferencePanel projectId={projectId} variant="authoring" snapshotId={reusableSnapshotId} lockedIndication={searchPlan.registry_filter?.condition_term || journey.framing?.clinicaltrials_condition_term || journey.framing?.indication || ""} lockedPhase={journey.framing?.study_phase || ""} journey={journey} onJourneyChange={setJourney} selectedBriefIds={selectedBriefIds} onSelectedBriefIdsChange={setSelectedBriefIds} />}
      <div className="authoring-gate-checklist"><strong>{missing.length ? "尚未满足的准入条件" : "准入条件已满足"}</strong>{(gate?.requirements?.length ? gate.requirements : missing.map((label) => ({ label, satisfied: false, detail: "" }))).map((item) => <label key={item.label} className={item.satisfied ? "satisfied" : ""}><input type="checkbox" checked={item.satisfied || acknowledged.includes(item.label)} onChange={() => { if (item.satisfied) return; setAcknowledged((current) => current.includes(item.label) ? current.filter((value) => value !== item.label) : [...current, item.label]); }} disabled={readOnly || allowed || item.satisfied} /><span><b>{item.label}</b>{item.detail && <small>{item.detail}</small>}</span></label>)}</div>
      {readOnly ? <div className="authoring-writing-entry"><div>{ready && assemblyPlanReady ? <CheckCircle2 size={18} /> : <ShieldAlert size={18} />}<span><strong>{ready && assemblyPlanReady ? "当前文档基于已核对语料与方案结构建立" : allowed ? "当前文档基于已记录的准入状态建立" : "当前语料门未满足"}</strong><small>此处仅回看文档创建所依据的设计、方案结构与语料状态；调整需进入受控变更流程。</small></span></div></div> : existingDocument ? <div className="authoring-writing-entry"><div>{ready && assemblyPlanReady ? <CheckCircle2 size={18} /> : <ShieldAlert size={18} />}<span><strong>当前写作文档已建立</strong><small>研究设计变更提交后，返回编辑器完成受影响章节的重绑定、重新核对与审阅。</small></span></div></div> : !allowed ? <details className="authoring-override"><summary>在保留全部缺口的情况下例外进入写作</summary><p className="quiet-text">仅在项目确需先行建稿时使用。逐项确认上方全部缺口；补充说明为可选项。</p><label className="synopsis-override-reason"><span>例外说明（可选）</span><textarea rows={2} value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} placeholder="可选：说明当前为何先进入写作及后续资料计划" /></label><button className="primary-button" type="button" onClick={onOverride} disabled={busy === "override" || !allAcknowledged} title={!allAcknowledged ? "请先逐项确认全部缺口" : "记录例外并进入写作"}><ShieldAlert size={14} /> {busy === "override" ? "记录中" : "确认例外并放行"}</button></details> : <div className="authoring-writing-entry"><div>{writeEntryReady ? <CheckCircle2 size={18} /> : <ShieldAlert size={18} />}<span><strong>{writeEntryReady ? (ready ? "语料与方案结构均已就绪" : "已记录例外，可建立版本化方案工作稿") : ready ? "语料已就绪，仍需完成方案结构核对" : "例外已记录，但研究定义尚未完成版本绑定"}</strong><small>{writeEntryReady ? (ready ? "可以建立版本化方案工作稿。" : "已明确缺少公开语料；正式稿仍须以当前版本化研究定义为唯一事实来源。") : ready ? assemblyPlanMessage : "先完成两阶段研究定义的版本绑定；语料缺口和例外理由会持续保留并纳入审计链。"}</small></span></div>{ready && !assemblyPlanReady && onReviewAssemblyPlan && <button className="secondary-button" type="button" onClick={onReviewAssemblyPlan} disabled={assemblyPlanState.status === "loading" || assemblyPlanState.status === "refreshing"}><PenLine size={14} /> 查看待确认项</button>}<button className="primary-button" type="button" onClick={onCreateDocument} disabled={!writeEntryReady || busy === "create-document"} title={!writeEntryReady ? (ready ? assemblyPlanMessage : "请先完成两阶段研究定义版本绑定") : ready ? "建立版本化方案工作稿" : "在已记录例外的审计状态下建立版本化方案工作稿"}><FileText size={15} /> {busy === "create-document" ? "建立中" : writeEntryReady ? "进入写作平台" : ready ? "完成核对后进入写作" : "完成研究定义后进入写作"}</button></div>}
    </section>
  );
}

function Field({ label, required = false, className = "", children }) {
  const control = isValidElement(children)
    ? cloneElement(children, { "aria-required": required || undefined })
    : children;
  return <label className={`authoring-field ${className}`}><span>{label}{required && <b>*</b>}</span>{control}</label>;
}
function ListField({ label, required = false, value, onChange }) { return <Field label={`${label}（每行一项）`} required={required}><textarea rows={5} value={lineText(value)} onChange={(event) => onChange(lines(event.target.value))} /></Field>; }
function StructuredListField({ label, prefix, required = false, className = "", value = [], onChange }) {
  const rows = Array.isArray(value) ? value : [];
  const updateRow = (index, text) => onChange(rows.map((item, itemIndex) => itemIndex === index ? text : item));
  const deleteRow = (index) => onChange(rows.filter((_item, itemIndex) => itemIndex !== index));
  const addRow = () => onChange([...rows, ""]);
  return (
    <fieldset className={`authoring-structured-list ${className}`}>
      <legend>{label}{required && <b>*</b>}</legend>
      <div className="authoring-structured-list-rows">
        {rows.map((item, index) => (
          <div className="authoring-structured-list-row" key={`${prefix}-${index}`}>
            <span>{prefix}-{String(index + 1).padStart(2, "0")}</span>
            <textarea
              rows={2}
              aria-label={`${label} ${index + 1}`}
              value={item}
              onChange={(event) => updateRow(index, event.target.value)}
              placeholder={`填写${label}的具体条件、阈值、时间窗或例外`}
            />
            <button type="button" className="icon-button" onClick={() => deleteRow(index)} title={`删除 ${prefix}-${String(index + 1).padStart(2, "0")}`}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {!rows.length && <p>尚未建立规则。新增后将按 {prefix}-01 起连续编号，保存时写回统一PICOS事实。</p>}
      </div>
      <button type="button" className="authoring-structured-list-add" onClick={addRow}><Plus size={14} /> 新增{label}</button>
    </fieldset>
  );
}
function ApplicabilitySummary({ label, decision }) { return <div className="authoring-applicability-summary"><span><strong>{label}</strong><small>不适用</small></span><p>{decision?.reason || "尚未填写理由"}</p><span>{decision?.confirmed_by_medical_manager ? <CheckCircle2 size={14} /> : <ShieldAlert size={14} />}{decision?.confirmed_by_medical_manager ? "医学经理已确认" : "尚待医学经理确认"}</span></div>; }

function FactProposalCard({ proposal, decision, onAdopt, onEdit, onReject, busy }) {
  const [editing, setEditing] = useState(false);
  const [editedValue, setEditedValue] = useState(proposal.value || "");
  const evidenceKind = proposal.fact_kind || proposal.evidence_status || "unknown";
  const evidenceLabel = EVIDENCE_STATUS_LABELS[evidenceKind] || EVIDENCE_STATUS_LABELS.unknown;
  const confidenceLabel = CONFIDENCE_LABELS[proposal.confidence] || CONFIDENCE_LABELS.unknown;
  const effectiveDecision = decision || (proposal.decision !== "pending" ? proposal.decision : "");
  const decided = Boolean(effectiveDecision);
  const tone = proposal.field_path?.startsWith("high_impact_missing.")
    ? "gap"
    : evidenceKind === "conflict"
      ? "conflict"
      : evidenceKind === "unknown"
        ? "unknown"
        : evidenceKind === "ai_inferred"
          ? "inference"
          : "fact";
  return (
    <article className={`authoring-fact-proposal ${tone} ${decided ? "decided" : ""}`}>
      <div className="authoring-fact-proposal-head">
        <span className="authoring-fact-proposal-field" title={proposal.field_path}>{proposal.field_label || factFieldLabel(proposal.field_path)}</span>
        <span className={`authoring-fact-proposal-evidence ${evidenceKind}`}>{evidenceLabel} · 置信{confidenceLabel}</span>
      </div>
      {editing ? (
        <div className="authoring-fact-proposal-edit">
          <textarea rows={2} value={editedValue} onChange={(event) => setEditedValue(event.target.value)} placeholder="修订后的事实值；确认采用后写入版本化研究事实" />
          <div className="authoring-fact-proposal-edit-actions">
            <button type="button" onClick={() => { onEdit(editedValue); setEditing(false); }} disabled={busy}>采用修订</button>
            <button type="button" onClick={() => { setEditing(false); setEditedValue(proposal.value || ""); }}>取消</button>
          </div>
        </div>
      ) : (
        <p className="authoring-fact-proposal-value">{proposal.value || "尚无具体值；需项目资料或用户确认"}</p>
      )}
      {(proposal.rationale || proposal.source_summary) && <small className="authoring-fact-proposal-source">{proposal.rationale || proposal.source_summary}</small>}
      {proposal.conflict_note && <small className="authoring-fact-proposal-conflict">冲突：{proposal.conflict_note}</small>}
      {!editing && (
        <div className="authoring-fact-proposal-actions">
          <button type="button" className={effectiveDecision === "adopted" ? "decided" : ""} onClick={onAdopt} disabled={busy || decided} title="采用该事实并写入研究框架">{effectiveDecision === "adopted" ? <><CheckCircle2 size={13} /> 已采用</> : "采用"}</button>
          <button type="button" className={effectiveDecision === "edited" ? "decided" : ""} onClick={() => setEditing(true)} disabled={busy || decided} title="修订后采用">{effectiveDecision === "edited" ? <><PenLine size={13} /> 已修订</> : "修订"}</button>
          <button type="button" className={effectiveDecision === "rejected" ? "decided" : ""} onClick={onReject} disabled={busy || decided} title="拒绝该建议">{effectiveDecision === "rejected" ? <><XCircle size={13} /> 已拒绝</> : "拒绝"}</button>
        </div>
      )}
    </article>
  );
}

function ConversationalFactIntake({ factConversation, setFactConversation, onSubmit, onApplyProposal, busy, interactionLocked }) {
  const turns = factConversation.turns || [];
  const pendingInput = factConversation.pendingInput || "";
  const pendingTurnId = factConversation.pendingTurnId || "";
  const disabled = interactionLocked || busy === "fact-turn";
  const setInput = (value) => setFactConversation((current) => ({ ...current, pendingInput: value }));
  const submit = () => { if (pendingInput.trim()) onSubmit(); };
  const hasProposals = turns.some((turn) => turn.ai_response?.proposals?.length);
  return (
    <section className="authoring-conversation" aria-label="对话式事实采集">
      <header>
        <div>
          <Sparkles size={16} />
          <div>
            <strong>补充产品事实（自然语言）</strong>
            <span>可粘贴大段文字、药学资料摘要或临床前结论；独立AI拆解为可确认事实、推断、未知项、冲突和高影响缺口，每轮最多追问3个影响下游设计的问题。</span>
          </div>
        </div>
        <small>IB可选·缺少不阻断调研</small>
      </header>
      <div className="authoring-conversation-input">
        <textarea
          rows={4}
          value={pendingInput}
          onChange={(event) => setInput(event.target.value)}
          placeholder="例如：CMS-D1是抗IL-23p19单抗，静脉输注，首次人体，已有食蟹猴4周毒理，NOAEL 30mg/kg，暂无人体PK数据，关注输注反应和免疫原性。"
          disabled={disabled}
          aria-label="自然语言事实输入"
        />
        <button type="button" className="primary-button" onClick={submit} disabled={disabled || !pendingInput.trim()}>
          <Sparkles size={14} /> {busy === "fact-turn" ? "解析中" : "提交并拆解"}
        </button>
      </div>
      {turns.length === 0 ? (
        <p className="authoring-conversation-empty">尚未发起事实采集。无IB不阻断竞品调研；当前目标产品事实仅采用用户输入或已绑定来源，竞品信息不会自动写成本品事实。此处补充的自然语言会合并进入版本化事实。</p>
      ) : (
        <div className="authoring-conversation-turns">
          {turns.map((turn, turnIndex) => {
            const proposals = turn.ai_response?.proposals || [];
            const questions = turn.ai_response?.questions || [];
            const gaps = turn.ai_response?.high_impact_gaps || [];
            return (
              <div key={turn.turn_id || turnIndex} className="authoring-conversation-turn">
                <div className="authoring-conversation-user">
                  <small>用户输入 · 第{turnIndex + 1}轮</small>
                  <p>{turn.user_message}</p>
                </div>
                <div className="authoring-conversation-ai">
                  <small>AI拆解 · 待用户确认</small>
                  {turn.ai_response?.response_text && <p className="authoring-conversation-response">{turn.ai_response.response_text}</p>}
                  {proposals.length > 0 && (
                    <div className="authoring-fact-proposals">
                      {proposals.map((proposal) => (
                        <FactProposalCard
                          key={proposal.proposal_id}
                          proposal={proposal}
                          decision={turn.decisions?.[proposal.proposal_id]}
                          onAdopt={() => onApplyProposal(turn.turn_id || pendingTurnId, proposal.proposal_id, "adopted")}
                          onEdit={(value) => onApplyProposal(turn.turn_id || pendingTurnId, proposal.proposal_id, "edited", value)}
                          onReject={() => onApplyProposal(turn.turn_id || pendingTurnId, proposal.proposal_id, "rejected")}
                          busy={busy === `fact-apply-${proposal.proposal_id}`}
                        />
                      ))}
                    </div>
                  )}
                  {gaps.length > 0 && (
                    <div className="authoring-conversation-gaps">
                      <strong>高影响缺口</strong>
                      <ul>{gaps.map((gap, gapIndex) => { const fieldPath = typeof gap === "string" ? gap : gap.field_path; return <li key={gapIndex} title={fieldPath}>{typeof gap === "string" ? factGapLabel(gap) : gap.field_label || factGapLabel(fieldPath)}</li>; })}</ul>
                    </div>
                  )}
                  {questions.length > 0 && (
                    <div className="authoring-conversation-questions">
                      <strong>本轮问题（按下游影响排序）</strong>
                      <ol>{questions.map((question, questionIndex) => <li key={questionIndex}>{typeof question === "string" ? question : question.text}</li>)}</ol>
                    </div>
                  )}
                  {proposals.length === 0 && gaps.length === 0 && questions.length === 0 && (
                    <p className="authoring-conversation-no-findings">本次未识别到新的可确认事实或必须追问项；可在下方继续补充。</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {hasProposals && <p className="authoring-conversation-hint">采用或修订后立即写入本项目确认事实，不再进入第二次批准。</p>}
    </section>
  );
}
