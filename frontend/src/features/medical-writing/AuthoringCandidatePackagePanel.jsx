import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, ShieldAlert, Sparkles } from "lucide-react";

const PACKAGE_FIELD_LABELS = {
  "package.population": "研究人群模块",
  "package.intervention": "干预与合并治疗模块",
  "package.outcomes": "结局与终点模块",
  "package.statistics": "执行与统计模块",
  "package.soa": "研究流程表 SoA 模块",
  "package.design": "研究设计（正交维度）",
  "package.product": "产品画像模块",
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
  "design.crossover": "交叉设计",
  "design.open_label_extension": "开放标签延展",
  "design.sample_size_reestimation": "样本量再估计",
  "design.treatment_switch": "治疗转换",
  "framing.population_intent": "目标研究人群",
  "framing.design_pattern": "总体设计模式",
  "framing.product_profile.technology_type": "药物技术类型",
  "framing.product_profile.administration_routes": "给药途径",
  "framing.product_profile.exposure_scope": "暴露范围",
  "picos.population_summary": "研究人群概述",
  "picos.intervention_summary": "干预措施概述",
  "picos.comparator_summary": "对照组设计",
  "picos.primary_endpoint": "主要终点及评价时间",
  "picos.study_epochs": "研究阶段",
  "picos.design_archetype": "研究设计类型",
};

const ROLE_LABELS = {
  recommended: "推荐方案",
  alternative: "备选方案",
  pending_decision: "需您选择/补全",
};

// 这些字段后端只接受固定取值；以选择呈现，避免中文自然语言输入被
// 后端校验拒绝（T17 测试者4 P1-3）。选择"其他（自行填写）"后仍可
// 自由输入，保证非常规表述不被界面挡死。
const PACKAGE_ENUM_FREE_CHOICE = "__free_text__";
const PACKAGE_ENUM_OPTIONS = {
  "framing.product_profile.technology_type": [
    ["small_molecule", "小分子化学药物"],
    ["monoclonal_antibody", "单克隆抗体"],
    ["other_biologic", "其他生物制品"],
    ["rna_therapy", "RNA治疗"],
    ["cell_therapy", "细胞治疗"],
    ["gene_therapy", "基因治疗"],
    ["vaccine", "疫苗"],
    ["other", "其他"],
    ["unknown", "尚未确定"],
  ],
  "framing.product_profile.exposure_scope": [
    ["systemic", "全身暴露"],
    ["local", "局部暴露"],
    ["mixed", "全身+局部"],
    ["unknown", "尚未确定"],
  ],
  "framing.product_profile.device_dependency": [
    ["none", "不需要装置"],
    ["integrated", "一体化装置"],
    ["external", "外接装置"],
    ["unknown", "尚未确定"],
  ],
  "framing.product_profile.immunogenicity_relevance": [
    ["not_expected", "预期无免疫原性"],
    ["potential", "可能有免疫原性"],
    ["expected", "预期有免疫原性"],
    ["unknown", "尚未确定"],
  ],
  "picos.design_archetype": [
    ["randomized_exploratory", "随机探索性研究"],
    ["randomized_confirmatory", "随机确证性研究"],
    ["single_arm_early_phase", "早期单臂研究"],
    ["open_label_extension", "开放标签延展"],
    ["other", "其他"],
    ["", "尚未确定"],
  ],
  "framing.structured_design.randomization_mode": [
    ["randomized", "随机化"],
    ["non_randomized", "非随机"],
    ["other", "其他"],
    ["undecided", "尚未确定"],
  ],
  "framing.structured_design.blinding_mode": [
    ["double_blind", "双盲"],
    ["single_blind", "单盲"],
    ["triple_blind", "三盲"],
    ["open_label", "开放标签（不设盲）"],
    ["other", "其他"],
    ["undecided", "尚未确定"],
  ],
  "framing.structured_design.comparator_type": [
    ["placebo", "安慰剂对照"],
    ["active", "阳性药对照"],
    ["none_or_dose_escalation", "无对照/剂量递增"],
    ["other", "其他"],
    ["undecided", "尚未确定"],
  ],
};

const CONFIDENCE_LABELS = {
  high: "高",
  medium: "中",
  low: "低",
  none: "无",
};

const RECEIPT_CATEGORY_LABELS = {
  applied: "已应用",
  overridden: "已按您的修改写入",
  derived: "联动派生",
  skipped: "已跳过",
  invalidated: "依赖需重新核验",
};

export function packageFieldLabel(fieldPath) {
  const path = String(fieldPath || "").trim();
  if (!path) return "相关字段";
  if (PACKAGE_FIELD_LABELS[path]) return PACKAGE_FIELD_LABELS[path];
  const last = path.split(".").pop() || path;
  if (/[A-Za-z]/.test(path)) {
    return `相关字段（${last.replaceAll("_", " ")}）`;
  }
  return path;
}

export function resolvePathLabel(fieldPath, pathLabels = {}) {
  const path = String(fieldPath || "").trim();
  if (!path) return "相关字段";
  const fromMap = pathLabels[path];
  if (fromMap && fromMap !== path) return fromMap;
  return packageFieldLabel(path);
}

export function isCompositePrefillGroup(group) {
  const candidates = group?.candidates || [];
  return candidates.some(
    (item) => item?.candidate_scope === "module" || item?.candidate_scope === "design_package",
  );
}

// Mirrors services/api/app/medical_writing_authoring_prefill_ai.py::
// _UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX.  The backend serializes candidate
// attributes with model defaults, so an absent adoption_mode/evidence_status
// is treated as its restrictive default (manual_only / insufficient) to stay
// fail-closed.
const UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX = "声称内容未在引用原文中出现：";

const COMPOSITE_BLOCK_REASON_LABELS = {
  unavailable: "候选不可用。",
  pending_decision: "该候选含待确认项；请对每个字段填写确认值或勾选跳过。",
  manual_only: "该候选标注为需逐项确认（manual_only）；请对每个字段填写确认值或勾选跳过。",
  insufficient: "该候选证据不足（insufficient）；请对每个字段填写确认值或勾选跳过。",
  unsupported_gap: "该候选存在未被来源原文支持的实质声明；请对每个字段填写确认值或勾选跳过。",
};

/**
 * Stable machine code for why a candidate cannot be adopted without per-path
 * decisions, or "" when the candidate is safe.  Mirrors the backend per-path
 * gate (``_composite_path_policy_restricted`` in
 * medical_writing_authoring_prefill.py): pending_decision role, manual_only
 * adoption mode, insufficient evidence status, or an unsupported-substantive
 * evidence gap all require an explicit override or explicit skip for every
 * contributed target path.  ``batch_allowed`` + supported + gap-free
 * candidates are safe and remain zero-override adoptable.
 */
export function compositeCandidateBlockedCode(candidate) {
  if (!candidate) return "unavailable";
  if (candidate.recommendation_role === "pending_decision") return "pending_decision";
  if (String(candidate.preview || "").includes("待确认")) return "pending_decision";
  const adoptionMode = String(candidate.adoption_mode || "").trim() || "manual_only";
  if (adoptionMode === "manual_only") return "manual_only";
  const evidenceStatus = String(candidate.evidence_status || "").trim() || "insufficient";
  if (evidenceStatus === "insufficient") return "insufficient";
  if ((candidate.evidence_gaps || []).some(
    (gap) => String(gap).startsWith(UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX),
  )) {
    return "unsupported_gap";
  }
  return "";
}

/**
 * Human-readable reason a composite candidate cannot be adopted without
 * per-path decisions, or "" when the candidate is safe.
 */
export function compositeCandidateBlockedReason(candidate) {
  const code = compositeCandidateBlockedCode(candidate);
  return COMPOSITE_BLOCK_REASON_LABELS[code] || "";
}

/**
 * Pending-like gating: a candidate is pending-like when it is restricted
 * (see ``compositeCandidateBlockedReason``).  Pending-like candidates must
 * never fill the recommended slot, must not be auto-selected, and require an
 * explicit decision on every contributed target path before adoption.
 */
export function isPendingCompositeCandidate(candidate) {
  return Boolean(compositeCandidateBlockedReason(candidate));
}

function looksLikeEnglishPath(path, label) {
  if (label && label !== path) return false;
  return /[A-Za-z]/.test(String(path || ""));
}

export function moduleIncludeLines(candidate, pathLabels = {}) {
  const fromPreview = String(candidate?.preview || "")
    .split(/[；;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (fromPreview.length > 1) return fromPreview;
  const fromTargets = (candidate?.target_paths || []).map((path) => resolvePathLabel(path, pathLabels));
  if (fromTargets.length) return fromTargets;
  return fromPreview;
}

export function compactCandidatePreview(candidate, maxSegments = 4) {
  const segments = String(candidate?.preview || "")
    .split(/[；;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (!segments.length) return packageFieldLabel(candidate?.field_path);
  if (segments.length <= maxSegments) return segments.join("；");
  return `${segments.slice(0, maxSegments).join("；")}；其余设计已纳入整包建议`;
}

const STRUCTURED_VALUE_KEY_LABELS = Object.freeze({
  enabled: "启用状态",
  planned: "计划状态",
  features: "具体特征",
  labels: "标签",
  mode: "模式",
  model: "模式",
  type: "类型",
  blinded_roles: "盲态角色",
  purpose: "用途",
  src: "SRC",
  dmc: "DMC",
  parts: "研究Part",
  sequence: "序列",
  available_part_types: "可选Part类型",
});

const STRUCTURED_VALUE_ENUM_LABELS = Object.freeze({
  randomized: "随机",
  non_randomized: "非随机",
  open_label: "开放标签",
  single_blind: "单盲",
  double_blind: "双盲",
  triple_blind: "三盲",
  placebo: "安慰剂对照",
  active: "阳性/活性对照",
  none_or_dose_escalation: "无对照/剂量递增",
  planned: "计划",
  unplanned: "不计划",
  undecided: "待确认",
});

function structuredValueKeyLabel(key) {
  return STRUCTURED_VALUE_KEY_LABELS[key]
    || String(key || "").replaceAll("_", " ");
}

function humanizeStructuredValue(value) {
  if (value == null || value === "") return "待确认";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") {
    return STRUCTURED_VALUE_ENUM_LABELS[value] || value;
  }
  if (Array.isArray(value)) {
    if (!value.length) return "未设置";
    return value.map((item) => humanizeStructuredValue(item)).join("、");
  }
  if (typeof value === "object") {
    const entries = Object.entries(value).filter(([, item]) => item !== undefined);
    if (!entries.length) return "未设置";
    return entries
      .map(([key, item]) => `${structuredValueKeyLabel(key)}：${humanizeStructuredValue(item)}`)
      .join("；");
  }
  return String(value);
}

export function collectCompositePrefillGroups(prefillPackage) {
  return Object.values(prefillPackage?.field_candidates || {})
    .filter(isCompositePrefillGroup)
    .sort((left, right) => String(left.field_path).localeCompare(String(right.field_path)));
}

export function sortCompositeCandidates(group) {
  const candidates = [...(group?.candidates || [])];
  const recommendedId = group?.recommended_candidate_id;
  const recommendedById = candidates.find((item) => item.candidate_id === recommendedId);
  // Empty recommendation stays empty: the server deliberately leaves
  // recommended_candidate_id="" when no candidate is safe to recommend, and
  // a slot that points at a pending-like candidate is no recommendation
  // either.  Never promote the first non-pending alternative into the slot.
  const recommended = recommendedById && !isPendingCompositeCandidate(recommendedById)
    ? recommendedById
    : null;
  candidates.sort((left, right) => {
    if (recommended) {
      if (left.candidate_id === recommended.candidate_id) return -1;
      if (right.candidate_id === recommended.candidate_id) return 1;
    }
    const leftPending = isPendingCompositeCandidate(left);
    const rightPending = isPendingCompositeCandidate(right);
    if (!leftPending && rightPending) return -1;
    if (leftPending && !rightPending) return 1;
    if (left.recommendation_role === "recommended" && right.recommendation_role !== "recommended") return -1;
    if (right.recommendation_role === "recommended" && left.recommendation_role !== "recommended") return 1;
    return String(left.candidate_id).localeCompare(String(right.candidate_id));
  });
  const alternatives = candidates
    .filter((item) => item.candidate_id !== recommended?.candidate_id)
    .slice(0, 4);
  const displayCandidates = recommended
    ? [recommended, ...alternatives].filter(Boolean)
    : candidates.slice(0, 5);
  return { recommended, alternatives, displayCandidates };
}

export function formatPathValue(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    if (!value.length) return "（空列表）";
    return value.map((item) => humanizeStructuredValue(item)).join("；");
  }
  return humanizeStructuredValue(value);
}

/**
 * Paths a pending-like (restricted) candidate needs an explicit decision on
 * before adoption.  The backend per-path gate requires an override or
 * explicit skip for EVERY contributed target path of a restricted
 * candidate — AI-resolved values are never carried as implicit overrides.
 * Safe candidates return an empty list (zero-override adoption).
 */
export function compositeDecisionPaths(candidate) {
  if (!isPendingCompositeCandidate(candidate)) return [];
  return (candidate?.target_paths || []).filter(Boolean);
}

export function hasUsableSourceText(evidenceRefs = []) {
  return (evidenceRefs || []).some((item) => String(item?.source_text || "").trim());
}

/**
 * Adoption readiness mirrors the backend composite per-path gate: safe
 * candidates (batch_allowed + supported + gap-free) may submit without
 * per-path drafts; pending-like candidates (pending_decision / manual_only /
 * insufficient / unsupported-substantive-gap) require an explicit override
 * or explicit skip on EVERY contributed target path before the adopt action
 * may be enabled — the UI never shows an enabled action that is guaranteed
 * to be policy-rejected.
 */
export function compositeAdoptionReady(candidate, pathOverrides = {}, pathSkips = {}) {
  if (!candidate) return false;
  const targets = candidate.target_paths || [];
  if (!targets.length) return false;
  if (!isPendingCompositeCandidate(candidate)) return true;
  return compositeDecisionPaths(candidate).every((path) => {
    if (pathSkips[path]) return true;
    if (!(path in pathOverrides)) return false;
    const value = pathOverrides[path];
    if (value == null) return false;
    if (typeof value === "string") return value.trim().length > 0;
    if (Array.isArray(value)) return value.length > 0;
    return true;
  });
}

export function splitCompositeListValue(value) {
  const seen = new Set();
  return String(value || "")
    .split(/[\n；;]+/)
    .map((item) => item.trim())
    .filter((item) => {
      if (!item || seen.has(item)) return false;
      seen.add(item);
      return true;
    });
}

function stableManualInstrumentId(value) {
  let hash = 2166136261;
  for (const character of value) {
    hash ^= character.codePointAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return `manual_instrument_${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function serializeAssessmentInstrumentItems(items) {
  return items.map((item) => {
    if (item.startsWith("{") && item.endsWith("}")) {
      try {
        const parsed = JSON.parse(item);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
      } catch {
        // Keep malformed JSON-like input as the user's instrument name.
      }
    }
    return {
      instrument_id: stableManualInstrumentId(item),
      canonical_name_zh: item,
      instrument_kind: "other",
      confirmation_status: "candidate",
    };
  });
}

export function serializeCompositePathOverride(candidate, path, value) {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!trimmed) return "";
  const candidateValue = candidate?.structured_value?.[path];
  if (!Array.isArray(candidateValue)) return trimmed;

  const items = splitCompositeListValue(value);
  const hasStructuredItems = candidateValue.some(
    (item) => item && typeof item === "object" && !Array.isArray(item),
  );
  if (hasStructuredItems || path === "picos.assessment_instruments") {
    return serializeAssessmentInstrumentItems(items);
  }
  return items;
}

/** Build request path_overrides: only non-skipped entries with real values. */
export function buildCompositePathOverrides(candidate, pathOverrides = {}, pathSkips = {}) {
  const result = {};
  for (const path of candidate?.target_paths || []) {
    if (pathSkips[path]) {
      delete result[path];
      continue;
    }
    if (!(path in pathOverrides)) continue;
    const value = pathOverrides[path];
    if (value == null) continue;
    if (typeof value === "string") {
      const serialized = serializeCompositePathOverride(candidate, path, value);
      if (serialized === "" || (Array.isArray(serialized) && !serialized.length)) continue;
      result[path] = serialized;
      continue;
    }
    result[path] = value;
  }
  return result;
}

export function collectExplicitCompositeSkips(candidate, pathSkips = {}) {
  return (candidate?.target_paths || []).filter((path) => Boolean(pathSkips[path]));
}

export function receiptSummaryMessage(receipt) {
  if (!receipt) return "";
  if (receipt.replayed) return "已应用（幂等回放）";
  if (receipt.package_marked_stale) return "建议包已标记为需更新，请重新生成后再采用。";
  const applied = receipt.applied_paths?.length || 0;
  const overridden = receipt.overridden_paths?.length || 0;
  const skipped = receipt.skipped_paths?.length || 0;
  return `组合采用完成：应用${applied}项，修改${overridden}项，跳过${skipped}项。`;
}

function EvidenceBlock({ evidenceRefs = [] }) {
  const withText = (evidenceRefs || []).filter((item) => String(item?.source_text || "").trim());
  const withoutText = (evidenceRefs || []).filter((item) => !String(item?.source_text || "").trim());
  if (!withText.length && !withoutText.length) {
    return null;
  }
  return (
    <div className="authoring-package-evidence" data-evidence-status={withText.length ? "has-source-text" : "insufficient"}>
      {withText.map((item, index) => (
        <blockquote key={`${item.source_id || "src"}-${index}`} className="authoring-package-source-text">
          <span>竞品实践 / 来源原文</span>
          <p>{item.source_text}</p>
        </blockquote>
      ))}
      {!withText.length && (
        <div className="authoring-package-evidence insufficient">
          <span>证据不足</span>
          <p>暂无可用的竞品原文；仅有定位信息时不视为已展示证据。</p>
        </div>
      )}
      {(withoutText.length > 0 || withText.some((item) => item.locator || item.source_id)) && (
        <details className="authoring-package-trace-details">
          <summary>溯源详情（定位/哈希，默认折叠）</summary>
          <ul>
            {(evidenceRefs || []).map((item, index) => (
              <li key={`trace-${item.source_id || index}`}>
                <strong>{item.source_kind || "来源"}</strong>
                <small>{item.locator || item.source_id || "无定位"}</small>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function PathDecisionRow({
  path,
  label,
  candidateValue,
  overrideValue,
  skipped,
  allowSkip = false,
  disabled,
  onOverrideChange,
  onSkipToggle,
}) {
  const displayValue = formatPathValue(candidateValue);
  const primaryLabel = label && label !== path ? label : packageFieldLabel(path);
  const listValued = Array.isArray(candidateValue);
  const enumOptions = !listValued ? PACKAGE_ENUM_OPTIONS[path] : null;
  const overrideText = typeof overrideValue === "string"
    ? overrideValue
    : overrideValue == null ? "" : formatPathValue(overrideValue);
  const knownChoice = enumOptions?.some(([value]) => value === overrideText);
  // 枚举字段的自由输入只应通过显式"其他"入口进入；建议值恰为合法枚举时
  // 也直接落在对应选项上，用户不改就不用碰输入框。
  const freeChoice = enumOptions != null && overrideText !== "" && !knownChoice;
  const selectValue = freeChoice
    ? PACKAGE_ENUM_FREE_CHOICE
    : overrideText === "" ? "" : overrideText;
  const overridePlaceholder = listValued
    ? path === "picos.assessment_instruments"
      ? "每行或用分号分隔一个量表/评估工具"
      : "每行或用分号分隔一项；空项和重复项会被忽略"
    : "填写后采用您的表述；留空且不跳过则待补全";
  return (
    <div className={`authoring-package-path-row ${skipped ? "skipped" : ""}`} data-target-path={path}>
      <div className="authoring-package-path-head">
        <strong title={path}>{primaryLabel}</strong>
      </div>
      <div className="authoring-package-path-candidate">
        <span>建议值</span>
        <p>{displayValue || "（空）"}</p>
      </div>
      <label className="authoring-package-path-override">
        <span>您的确认/修改</span>
        {enumOptions ? (
          <>
            <select
              value={selectValue}
              onChange={(event) => {
                const next = event.target.value;
                onOverrideChange(path, next === PACKAGE_ENUM_FREE_CHOICE ? "" : next);
              }}
              disabled={disabled || skipped}
              aria-label={`${primaryLabel}选择取值`}
            >
              <option value="">请选择…</option>
              {enumOptions.map(([value, text]) => (
                <option key={value} value={value}>{text}</option>
              ))}
              <option value={PACKAGE_ENUM_FREE_CHOICE}>其他（自行填写）</option>
            </select>
            {freeChoice && (
              <textarea
                rows={2}
                value={overrideText}
                onChange={(event) => onOverrideChange(path, event.target.value)}
                disabled={disabled || skipped}
                placeholder={overridePlaceholder}
                aria-label={`${primaryLabel}自由填写`}
              />
            )}
          </>
        ) : (
          <textarea
            rows={2}
            value={overrideText}
            onChange={(event) => onOverrideChange(path, event.target.value)}
            disabled={disabled || skipped}
            placeholder={overridePlaceholder}
            aria-label={`${primaryLabel}确认或修改`}
          />
        )}
      </label>
      {allowSkip && (
        <label className="authoring-package-path-skip">
          <input
            type="checkbox"
            checked={Boolean(skipped)}
            onChange={() => onSkipToggle(path)}
            disabled={disabled}
          />
          <span>本次跳过该字段</span>
        </label>
      )}
    </div>
  );
}

function CompositeReceiptPanel({ receipt }) {
  if (!receipt) return null;
  const skippedItems = (receipt.skipped_paths || []).map((item) => (
    typeof item === "string" ? { path: item, reason: "" } : item
  ));
  const categories = [
    { key: "applied", paths: receipt.applied_paths || [], className: "applied" },
    { key: "overridden", paths: receipt.overridden_paths || [], className: "overridden" },
    { key: "derived", paths: receipt.derived_paths || [], className: "derived" },
    {
      key: "skipped",
      paths: skippedItems.map((item) => item.path),
      className: "skipped",
      details: skippedItems,
    },
    { key: "invalidated", paths: receipt.invalidated_dependents || [], className: "invalidated" },
  ].filter((item) => item.paths.length > 0 || (item.key === "skipped" && item.details?.length));

  return (
    <section
      className={`authoring-package-receipt ${receipt.replayed ? "replayed" : ""} ${receipt.package_marked_stale ? "stale" : ""}`}
      data-testid="composite-adopt-receipt"
      data-replayed={receipt.replayed ? "true" : "false"}
      data-package-stale={receipt.package_marked_stale ? "true" : "false"}
      aria-live="polite"
    >
      <header>
        <CheckCircle2 size={15} />
        <div>
          <strong>{receiptSummaryMessage(receipt)}</strong>
          <small>
            {packageFieldLabel(receipt.package_field_path) || "组合候选"}
            {receipt.candidate_id ? ` · ${receipt.candidate_id}` : ""}
            {receipt.journey_revision_after ? ` · 修订 ${receipt.journey_revision_before}→${receipt.journey_revision_after}` : ""}
          </small>
        </div>
      </header>
      {receipt.replayed && <p className="authoring-package-receipt-flag replayed" data-receipt-flag="replayed">已应用（幂等回放）</p>}
      {receipt.package_marked_stale && <p className="authoring-package-receipt-flag stale" data-receipt-flag="stale">建议包已过期或标记为需更新，请重新生成后再继续采用。</p>}
      {categories.length > 0 && (
        <details className="authoring-package-receipt-categories">
          <summary>写入明细（默认折叠）</summary>
          <div className="authoring-package-receipt-categories-body">
            {categories.map((category) => (
              <div key={category.key} className={`authoring-package-receipt-category ${category.className}`} data-receipt-category={category.key}>
                <strong>{RECEIPT_CATEGORY_LABELS[category.key]}</strong>
                <ul>
                  {category.key === "skipped"
                    ? (category.details || []).map((item) => (
                      <li key={item.path}>
                        <span>{resolvePathLabel(item.path)}</span>
                        {item.reason ? <small>{item.reason}</small> : null}
                      </li>
                    ))
                    : category.paths.map((path) => <li key={path}>{resolvePathLabel(path)}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

function CandidateCard({
  candidate,
  isRecommended,
  selected,
  pathLabels,
  pathOverrides,
  pathSkips,
  readOnly,
  busy,
  onSelect,
  onOverrideChange,
  onSkipToggle,
}) {
  const role = candidate.recommendation_role || (isRecommended ? "recommended" : "alternative");
  const pending = isPendingCompositeCandidate(candidate);
  const sourceOk = hasUsableSourceText(candidate.evidence_refs);
  const targets = candidate.target_paths || [];
  const pendingPaths = compositeDecisionPaths(candidate);
  const labeledTargets = targets.map((path) => ({
    path,
    label: resolvePathLabel(path, pathLabels),
  }));
  const englishTargetPaths = targets.filter((path) => looksLikeEnglishPath(path, pathLabels[path] || path));
  const hasClinicalTradeoffs = candidate.clinical_tradeoffs?.length > 0;
  const hasReviewDetails = candidate.evidence_gaps?.length > 0
    || candidate.limitations?.length > 0;
  const hasRunMeta = Boolean(
    candidate.candidate_id
    || candidate.ai_run_id
    || candidate.evidence_catalog_id
    || candidate.evidence_catalog_sha256
    || englishTargetPaths.length
    || candidate.adoption_mode,
  );
  const compactSummary = candidate.rationale
    || (sourceOk ? "已关联可核验来源原文。" : "当前证据不足，选择后可查看详情。");

  return (
    <article
      className={`authoring-package-candidate ${isRecommended ? "recommended" : ""} ${selected ? "selected" : ""} ${pending ? "pending" : ""} ${candidate.state === "user_confirmed" ? "confirmed" : ""}`}
      data-candidate-id={candidate.candidate_id}
      data-recommendation-role={role}
      data-candidate-scope={candidate.candidate_scope}
      data-candidate-detail={selected ? "expanded" : "compact"}
    >
      <button
        type="button"
        className="authoring-package-candidate-select"
        onClick={() => onSelect(candidate.candidate_id)}
        disabled={readOnly || Boolean(busy)}
        aria-pressed={selected}
        aria-expanded={selected}
        title={readOnly ? "只读模式不可切换方案" : busy ? "正在处理中，请稍候" : "选择该组合方案"}
      >
        <div className="authoring-package-candidate-select-copy">
          <span className="authoring-package-candidate-role">
            {candidate.state === "user_confirmed" ? <CheckCircle2 size={13} /> : isRecommended ? <Sparkles size={13} /> : null}
            {candidate.state === "user_confirmed" ? "已采用" : ROLE_LABELS[role] || "方案"}
          </span>
          <strong>{compactCandidatePreview(candidate)}</strong>
          {!selected && <small>{compactSummary}</small>}
        </div>
        <small className="authoring-package-candidate-confidence">
          {CONFIDENCE_LABELS[candidate.confidence] || "未知"}置信
        </small>
      </button>
      {selected && <div className="authoring-package-candidate-body">
        {candidate.rationale && (
          <div className="authoring-package-why-recommend">
            <strong>为何推荐</strong>
            <p className="authoring-package-rationale">{candidate.rationale}</p>
          </div>
        )}
        {hasClinicalTradeoffs && (
          <div className="authoring-package-tradeoffs" data-tradeoffs-priority="primary">
            <strong>临床差异 / 权衡</strong>
            <ul>{candidate.clinical_tradeoffs.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        )}
        {selected && pending && (
          <div className="authoring-package-path-decisions" data-testid="pending-path-decisions">
            <header>
              <ShieldAlert size={14} />
              <span>{compositeCandidateBlockedReason(candidate) || "该方案需逐项确认后采用。"}</span>
            </header>
            {pendingPaths.map((path) => (
              <PathDecisionRow
                key={path}
                path={path}
                label={resolvePathLabel(path, pathLabels)}
                candidateValue={candidate.structured_value?.[path]}
                overrideValue={pathOverrides[path]}
                skipped={Boolean(pathSkips[path])}
                allowSkip
                disabled={readOnly || Boolean(busy)}
                onOverrideChange={onOverrideChange}
                onSkipToggle={onSkipToggle}
              />
            ))}
            {!pendingPaths.length && <p>当前没有需要确认的字段。</p>}
          </div>
        )}
        {selected && !pending && targets.length > 0 && (
          <details className="authoring-package-optional-overrides">
            <summary>按字段微调后再采用</summary>
            {targets.map((path) => (
              <PathDecisionRow
                key={path}
                path={path}
                label={resolvePathLabel(path, pathLabels)}
                candidateValue={candidate.structured_value?.[path]}
                overrideValue={pathOverrides[path]}
                skipped={false}
                disabled={readOnly || Boolean(busy)}
                onOverrideChange={onOverrideChange}
                onSkipToggle={onSkipToggle}
              />
            ))}
          </details>
        )}
        <details className="authoring-package-basis-details">
          <summary>展开依据与全部字段</summary>
          <div className="authoring-package-basis-body">
            <EvidenceBlock evidenceRefs={candidate.evidence_refs} />
            {!sourceOk && <p className="authoring-package-insufficient-flag">当前没有可直接展示的来源原文。</p>}
            {hasReviewDetails && (
              <div className="authoring-package-review-grid">
                {candidate.evidence_gaps?.length > 0 && (
                  <div className="authoring-package-gaps">
                    <strong>证据缺口</strong>
                    <ul>{candidate.evidence_gaps.map((item) => <li key={item}>{item}</li>)}</ul>
                  </div>
                )}
                {candidate.limitations?.length > 0 && (
                  <div className="authoring-package-limitations">
                    <strong>局限</strong>
                    <ul>{candidate.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
                  </div>
                )}
              </div>
            )}
            {labeledTargets.length > 0 && (
              <div className="authoring-package-targets">
                <strong>受影响字段</strong>
                <ul>{labeledTargets.map((item) => <li key={item.path} title={item.path}>{item.label}</li>)}</ul>
              </div>
            )}
            {hasRunMeta && (
              <details className="authoring-package-run-meta">
                <summary>运行元数据</summary>
                <dl>
                  {candidate.candidate_id && <div><dt>候选标识</dt><dd>{candidate.candidate_id}</dd></div>}
                  {candidate.ai_run_id && <div><dt>AI运行</dt><dd>{candidate.ai_run_id}</dd></div>}
                  {candidate.evidence_catalog_id && <div><dt>证据目录</dt><dd>{candidate.evidence_catalog_id}</dd></div>}
                  {candidate.evidence_catalog_sha256 && <div><dt>目录哈希</dt><dd>{candidate.evidence_catalog_sha256}</dd></div>}
                  {candidate.adoption_mode && <div><dt>采用模式</dt><dd>{candidate.adoption_mode === "batch_allowed" ? "允许组合采用" : "需逐项确认"}</dd></div>}
                  {englishTargetPaths.length > 0 && <div><dt>内部路径</dt><dd><ul>{englishTargetPaths.map((path) => <li key={path}>{path}</li>)}</ul></dd></div>}
                </dl>
              </details>
            )}
          </div>
        </details>
      </div>}
    </article>
  );
}

/**
 * Recommendation-first composite candidate package panel.
 * Pure presentation: no network calls. Parent owns journey/package and adopt.
 */
export function AuthoringCandidatePackagePanel({
  groups = [],
  packageRevision = 0,
  pathLabels = {},
  busy = "",
  readOnly = false,
  receipt = null,
  onAdoptComposite,
}) {
  const compositeGroups = useMemo(
    () => (groups || []).filter(isCompositePrefillGroup),
    [groups],
  );
  const [activeFieldPath, setActiveFieldPath] = useState("");
  const [selectedByField, setSelectedByField] = useState({});
  const [overridesByField, setOverridesByField] = useState({});
  const [skipsByField, setSkipsByField] = useState({});

  useEffect(() => {
    if (!compositeGroups.length) {
      setActiveFieldPath("");
      return;
    }
    if (!compositeGroups.some((group) => group.field_path === activeFieldPath)) {
      setActiveFieldPath(
        compositeGroups.find((group) => group.field_path === "package.design")?.field_path
        || compositeGroups[0].field_path,
      );
    }
  }, [compositeGroups, activeFieldPath]);

  useEffect(() => {
    setSelectedByField({});
    setOverridesByField({});
    setSkipsByField({});
  }, [packageRevision]);

  if (!compositeGroups.length) {
    return (
      <section className="authoring-package-panel empty" data-testid="authoring-candidate-package-panel" aria-label="研究设计组合推荐">
        <header>
          <Sparkles size={15} />
          <div>
            <strong>组合推荐包</strong>
            <small>当前尚无组合推荐方案。完成公开检索与语料准备后会在此出现。</small>
          </div>
        </header>
      </section>
    );
  }

  const activeGroup = compositeGroups.find((group) => group.field_path === activeFieldPath) || compositeGroups[0];
  const { recommended, alternatives, displayCandidates } = sortCompositeCandidates(activeGroup);
  // Empty recommendation stays no recommendation: never auto-select the
  // first display candidate when the server left the slot empty or the
  // slot points at a pending-like candidate.
  const selectedId = selectedByField[activeGroup.field_path] || recommended?.candidate_id || "";
  const selectedCandidate = displayCandidates.find((item) => item.candidate_id === selectedId) || null;
  const fieldOverrides = overridesByField[activeGroup.field_path] || {};
  const fieldSkips = skipsByField[activeGroup.field_path] || {};
  const pending = isPendingCompositeCandidate(selectedCandidate);
  const pendingPaths = compositeDecisionPaths(selectedCandidate);
  const ready = compositeAdoptionReady(selectedCandidate, fieldOverrides, fieldSkips);
  const confirmed = selectedCandidate?.state === "user_confirmed";
  const adoptBusy = busy === "prefill-composite-adopt" || busy === `prefill-composite-adopt-${activeGroup.field_path}`;
  const adoptDisabled = readOnly || Boolean(busy) || !selectedCandidate || !ready || confirmed
    || !["module", "design_package"].includes(selectedCandidate?.candidate_scope);

  const setSelected = (candidateId) => {
    setSelectedByField((current) => ({ ...current, [activeGroup.field_path]: candidateId }));
  };
  const setOverride = (path, value) => {
    setOverridesByField((current) => ({
      ...current,
      [activeGroup.field_path]: {
        ...(current[activeGroup.field_path] || {}),
        [path]: value,
      },
    }));
    if (value && String(value).trim()) {
      setSkipsByField((current) => {
        const nextField = { ...(current[activeGroup.field_path] || {}) };
        delete nextField[path];
        return { ...current, [activeGroup.field_path]: nextField };
      });
    }
  };
  const toggleSkip = (path) => {
    setSkipsByField((current) => {
      const nextField = { ...(current[activeGroup.field_path] || {}) };
      if (nextField[path]) delete nextField[path];
      else nextField[path] = true;
      return { ...current, [activeGroup.field_path]: nextField };
    });
  };
  const handleAdopt = () => {
    if (adoptDisabled || typeof onAdoptComposite !== "function") return;
    const pathOverrides = buildCompositePathOverrides(selectedCandidate, fieldOverrides, fieldSkips);
    const skippedPaths = collectExplicitCompositeSkips(selectedCandidate, fieldSkips);
    onAdoptComposite(activeGroup.field_path, selectedCandidate, pathOverrides, skippedPaths);
  };

  return (
    <section className="authoring-package-panel" data-testid="authoring-candidate-package-panel" aria-label="研究设计组合推荐">
      <header>
        <Sparkles size={15} />
        <div>
          <strong>AI推荐研究方案</strong>
          <small>先审阅整套设计与关键差异；采用后仍可在高级微调中逐项修改。</small>
        </div>
      </header>
      <nav className="authoring-package-tabs" aria-label="组合推荐模块">
        {compositeGroups.map((group) => {
          const rec = sortCompositeCandidates(group).recommended;
          const isConfirmed = group.candidates?.some((item) => item.state === "user_confirmed");
          return (
            <button
              key={group.field_path}
              type="button"
              className={group.field_path === activeGroup.field_path ? "active" : ""}
              data-package-field={group.field_path}
              aria-pressed={group.field_path === activeGroup.field_path}
              onClick={() => setActiveFieldPath(group.field_path)}
            >
              <span>{packageFieldLabel(group.field_path)}</span>
              <small>
                {isConfirmed ? "有采用记录" : ROLE_LABELS[rec?.recommendation_role] || "待审阅"}
              </small>
            </button>
          );
        })}
      </nav>
      <div className="authoring-package-workspace" data-package-field={activeGroup.field_path}>
        <div className="authoring-package-candidates">
          {selectedCandidate && (
            <CandidateCard
              key={selectedCandidate.candidate_id}
              candidate={selectedCandidate}
              isRecommended={selectedCandidate.candidate_id === recommended?.candidate_id}
              selected
              pathLabels={pathLabels}
              pathOverrides={fieldOverrides}
              pathSkips={fieldSkips}
              readOnly={readOnly}
              busy={busy}
              onSelect={setSelected}
              onOverrideChange={setOverride}
              onSkipToggle={toggleSkip}
            />
          )}
          {!selectedCandidate && (
            <div className="authoring-package-empty-slot" data-testid="composite-empty-slot">
              <p>该分组当前没有推荐方案；请从下方候选中选择，或先完成待决字段后采用。</p>
            </div>
          )}
          {!selectedCandidate && displayCandidates.length > 0 && (
            <div className="authoring-package-candidate-list" data-testid="composite-no-recommendation-list">
              {displayCandidates.map((candidate) => (
                <CandidateCard
                  key={candidate.candidate_id}
                  candidate={candidate}
                  isRecommended={false}
                  selected={false}
                  pathLabels={pathLabels}
                  pathOverrides={fieldOverrides}
                  pathSkips={fieldSkips}
                  readOnly={readOnly}
                  busy={busy}
                  onSelect={setSelected}
                  onOverrideChange={setOverride}
                  onSkipToggle={toggleSkip}
                />
              ))}
            </div>
          )}
          {selectedCandidate && displayCandidates.length > 1 && (
            <details className="authoring-package-alternatives">
              <summary>查看其他方案与关键差异</summary>
              <div>
                {displayCandidates
                  .filter((candidate) => candidate.candidate_id !== selectedCandidate?.candidate_id)
                  .map((candidate) => (
                    <CandidateCard
                      key={candidate.candidate_id}
                      candidate={candidate}
                      isRecommended={candidate.candidate_id === recommended?.candidate_id}
                      selected={false}
                      pathLabels={pathLabels}
                      pathOverrides={fieldOverrides}
                      pathSkips={fieldSkips}
                      readOnly={readOnly}
                      busy={busy}
                      onSelect={setSelected}
                      onOverrideChange={setOverride}
                      onSkipToggle={toggleSkip}
                    />
                  ))}
              </div>
            </details>
          )}
          {selectedCandidate && alternatives.length === 0 && <p className="authoring-package-no-alternatives">当前没有实质备选方案。</p>}
        </div>
        <aside className="authoring-package-actions" aria-label="组合采用">
          <div className="authoring-package-action-summary">
            <strong>{packageFieldLabel(activeGroup.field_path)}</strong>
            <p>
              {!selectedCandidate
                ? "该分组当前没有推荐方案；请从候选中选择，或先处理待决字段。"
                : pending
                  ? pendingPaths.length
                    ? `该方案需逐项确认：请对 ${pendingPaths.length} 个字段填写确认值或勾选跳过。`
                    : "该方案需逐项确认后采用。"
                  : "可直接采用；仅在确有项目差异时再展开修改。"}
            </p>
            {pending && !ready && selectedCandidate && (
              <p className="authoring-package-pending-hint" data-testid="pending-gating-hint">
                完成上方字段确认后即可整包采用。
              </p>
            )}
          </div>
          {!readOnly && (
            <button
              type="button"
              className="primary-button authoring-package-adopt-button"
              data-action="adopt-composite"
              data-testid="adopt-composite-button"
              data-package-field={activeGroup.field_path}
              data-candidate-id={selectedCandidate?.candidate_id || ""}
              onClick={handleAdopt}
              disabled={adoptDisabled}
              title={
                confirmed ? "该组合方案已采用"
                  : readOnly ? "只读模式不可采用"
                    : busy ? "正在处理中，请稍候"
                      : !selectedCandidate ? "该分组没有推荐方案；请先从候选中选择"
                        : pending && !ready ? (compositeCandidateBlockedReason(selectedCandidate) || "请先对每个字段确认或跳过")
                          : "一次请求采用组合候选，并自动填入下方字段"
              }
            >
              {adoptBusy ? "写入中" : confirmed ? "已采用推荐方案" : selectedCandidate?.candidate_id === recommended?.candidate_id ? "一键采用推荐方案" : "采用所选方案"}
            </button>
          )}
          {pending && pendingPaths.length > 0 && (
            <p className="authoring-package-pending-badge" data-recommendation-role="pending_decision">
              <ChevronDown size={13} /> {pendingPaths.length}项待决定
            </p>
          )}
        </aside>
      </div>
      <CompositeReceiptPanel receipt={receipt} />
    </section>
  );
}

export default AuthoringCandidatePackagePanel;
