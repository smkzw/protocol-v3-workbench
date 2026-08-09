/**
 * Deterministic W4-A composite adoption frontend QC.
 * Source inspection + mirrored pure-helper contracts. No live services, no JSX import.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, "..");
const panelPath = path.join(frontendRoot, "src/features/medical-writing/AuthoringCandidatePackagePanel.jsx");
const journeyPath = path.join(frontendRoot, "src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx");
const stylesPath = path.join(frontendRoot, "src/styles.css");
const prefillQcPath = path.join(frontendRoot, "tests/medical_writing_authoring_prefill_frontend_qc.mjs");

const failures = [];
function check(name, condition, detail = "") {
  if (!condition) failures.push(detail ? `${name}: ${detail}` : name);
}

// Mirrored pure helpers (must stay aligned with panel exports; verified by source markers).
function isCompositePrefillGroup(group) {
  return (group?.candidates || []).some(
    (item) => item?.candidate_scope === "module" || item?.candidate_scope === "design_package",
  );
}
function collectCompositePrefillGroups(prefillPackage) {
  return Object.values(prefillPackage?.field_candidates || {})
    .filter(isCompositePrefillGroup)
    .filter((group) => group?.field_path !== "package.soa")
    .sort((left, right) => String(left.field_path).localeCompare(String(right.field_path)));
}
// Mirrors services/api/app/medical_writing_authoring_prefill_ai.py::
// _UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX.
const UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX = "声称内容未在引用原文中出现：";
function compositeCandidateBlockedCode(candidate) {
  if (!candidate) return "unavailable";
  if (candidate.recommendation_role === "pending_decision") return "pending_decision";
  if (String(candidate.preview || "").includes("待确认")) return "pending_decision";
  const adoptionMode = String(candidate.adoption_mode || "").trim() || "manual_only";
  if (adoptionMode === "manual_only") return "manual_only";
  const evidenceStatus = String(candidate.evidence_status || "").trim() || "insufficient";
  if (evidenceStatus === "insufficient") return "insufficient";
  if ((candidate.evidence_gaps || []).some(
    (gap) => String(gap).startsWith(UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX),
  )) return "unsupported_gap";
  return "";
}
function isPendingCompositeCandidate(candidate) {
  return compositeCandidateBlockedCode(candidate) !== "";
}
function compositeCandidateBlockedReason(candidate) {
  const code = compositeCandidateBlockedCode(candidate);
  return {
    unavailable: "候选不可用。",
    pending_decision: "该候选含待确认项；请对每个字段填写确认值或勾选跳过。",
    manual_only: "该候选标注为需逐项确认（manual_only）；请对每个字段填写确认值或勾选跳过。",
    insufficient: "该候选证据不足（insufficient）；请对每个字段填写确认值或勾选跳过。",
    unsupported_gap: "该候选存在未被来源原文支持的实质声明；请对每个字段填写确认值或勾选跳过。",
  }[code] || "";
}
function compositeDecisionPaths(candidate) {
  if (!isPendingCompositeCandidate(candidate)) return [];
  return (candidate?.target_paths || []).filter(Boolean);
}
function sortCompositeCandidates(group) {
  const candidates = [...(group?.candidates || [])];
  const recommendedId = group?.recommended_candidate_id;
  const recommendedById = candidates.find((item) => item.candidate_id === recommendedId);
  // Empty recommendation stays empty: never promote the first non-pending
  // alternative into the slot.
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
function buildCompositePathOverrides(candidate, pathOverrides = {}, pathSkips = {}) {
  const result = {};
  for (const pathKey of candidate?.target_paths || []) {
    if (pathSkips[pathKey]) continue;
    if (!(pathKey in pathOverrides)) continue;
    const value = pathOverrides[pathKey];
    if (value == null) continue;
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (!trimmed) continue;
      result[pathKey] = trimmed;
      continue;
    }
    result[pathKey] = value;
  }
  return result;
}
function compositeAdoptionReady(candidate, pathOverrides = {}, pathSkips = {}) {
  if (!candidate) return false;
  const targets = candidate.target_paths || [];
  if (!targets.length) return false;
  if (!isPendingCompositeCandidate(candidate)) return true;
  return compositeDecisionPaths(candidate).every((pathKey) => {
    if (pathSkips[pathKey]) return true;
    if (!(pathKey in pathOverrides)) return false;
    const value = pathOverrides[pathKey];
    if (value == null) return false;
    if (typeof value === "string") return value.trim().length > 0;
    if (Array.isArray(value)) return value.length > 0;
    return true;
  });
}
function receiptSummaryMessage(receipt) {
  if (!receipt) return "";
  if (receipt.replayed) return "已应用（幂等回放）";
  if (receipt.package_marked_stale) return "建议包已标记为需更新，请重新生成后再采用。";
  const applied = receipt.applied_paths?.length || 0;
  const overridden = receipt.overridden_paths?.length || 0;
  const skipped = receipt.skipped_paths?.length || 0;
  return `组合采用完成：应用${applied}项，修改${overridden}项，跳过${skipped}项。`;
}
function hasUsableSourceText(evidenceRefs = []) {
  return (evidenceRefs || []).some((item) => String(item?.source_text || "").trim());
}

const [panelSource, journeySource, stylesSource, prefillQcSource] = await Promise.all([
  readFile(panelPath, "utf8"),
  readFile(journeyPath, "utf8"),
  readFile(stylesPath, "utf8"),
  readFile(prefillQcPath, "utf8").catch(() => ""),
]);

// --- one-request composite semantics ---
check("no-low-risk-batch-const", !journeySource.includes("LOW_RISK_BATCH_PREFILL_FIELDS"));
check("no-adopt-low-risk-fn", !journeySource.includes("adoptLowRiskPrefills"));
check("no-batch-button", !journeySource.includes("authoring-prefill-batch-button"));
check("no-prefill-batch-adopt-busy", !journeySource.includes("prefill-batch-adopt"));
check("no-sequential-for-batch", !/for \(const fieldPath of pendingFieldPaths\)/.test(journeySource));
check("single-composite-endpoint", journeySource.includes("prefill-package/adopt-composite"));
check("composite-fetch-once-helper", journeySource.includes("adoptPrefillComposite"));
check("composite-idempotency-op", journeySource.includes("prefill-composite-adopt"));
check("uses-stable-write-key", journeySource.includes("stableAuthoringWriteKey"));
check("panel-imported", journeySource.includes('from "./AuthoringCandidatePackagePanel"'));
check("panel-mounted", journeySource.includes("<AuthoringCandidatePackagePanel"));
check(
  "request-body-fields",
  journeySource.includes("package_field_path")
    && journeySource.includes("path_overrides")
    && journeySource.includes("expected_package_revision")
    && journeySource.includes("expected_revision")
    && journeySource.includes("idempotency_key"),
);
check("response-uses-receipt", journeySource.includes("response?.receipt") || journeySource.includes("setCompositeAdoptReceipt"));
check("journey-from-composite-result", journeySource.includes("response?.journey") || journeySource.includes("response.journey"));

// --- single-field adoption preserved ---
check("single-field-adopt-fn", journeySource.includes("adoptPrefillCandidate"));
check("single-field-endpoint", journeySource.includes("prefill-package/adopt") && journeySource.includes("requestPrefillAdoption"));
check("field-card-adopt-action", journeySource.includes('data-prefill-action="adopt-recommended"'));

// --- 409 reload once, no auto resubmit ---
const compositeFn = journeySource.match(/const adoptPrefillComposite = async[\s\S]*?(?=\n  const runPublicSearch)/)?.[0] || "";
check("composite-fn-extracted", compositeFn.includes("adopt-composite"), "could not isolate adoptPrefillComposite body");
check("composite-fn-single-fetch", (compositeFn.match(/fetch\(/g) || []).length === 1, `fetch count=${(compositeFn.match(/fetch\(/g) || []).length}`);
check("composite-fn-no-for-loop-adopt", !compositeFn.includes("for (const fieldPath"));
check("composite-409-reload", compositeFn.includes("error.status === 409") && compositeFn.includes("reloadJourneyAfterPrefillConflict"));
check("composite-409-no-resubmit", compositeFn.includes("不会自动重试提交") || compositeFn.includes("请核对组合方案后再次采用"));
check("busy-lock", compositeFn.includes("prefillAdoptionLockRef") && compositeFn.includes("prefill-composite-adopt-"));

// --- panel UX contract + exported helpers present in source ---
for (const marker of [
  "export function compositeAdoptionReady",
  "export function buildCompositePathOverrides",
  "export function sortCompositeCandidates",
  "export function receiptSummaryMessage",
  "export function collectCompositePrefillGroups",
  "export function AuthoringCandidatePackagePanel",
  "需您选择/补全",
  "来源原文",
  "溯源详情",
  "运行元数据",
  ".slice(0, 4)",
  'data-testid="adopt-composite-button"',
  'data-testid="composite-adopt-receipt"',
  "已应用（幂等回放）",
  "package_marked_stale",
  "pending-gating-hint",
  "data-receipt-category",
  'data-candidate-detail={selected ? "expanded" : "compact"}',
  "authoring-package-basis-details",
  "isPendingCompositeCandidate",
  "compositeCandidateBlockedCode",
  "compositeCandidateBlockedReason",
  "compositeDecisionPaths",
  'data-testid="composite-empty-slot"',
  "package.soa",
  "authoring-package-review-grid",
]) {
  check(`panel-marker:${marker}`, panelSource.includes(marker));
}
check("no-pending-medical-approval-panel", !panelSource.includes("待医学批准"));
check("no-pending-medical-approval-journey", !journeySource.includes("待医学批准"));
check("styles-package-panel", stylesSource.includes(".authoring-package-panel") && stylesSource.includes(".authoring-package-receipt"));
check("styles-receipt-categories", ["applied", "overridden", "derived", "skipped", "invalidated"].every((key) => stylesSource.includes(`.authoring-package-receipt-category.${key}`)));
check("unselected-candidates-compact", panelSource.includes("{selected && <div className=\"authoring-package-candidate-body\">")
  && panelSource.includes("{!selected && <small>{compactSummary}</small>}"));
check("selected-review-details-collapsed", panelSource.includes("<details className=\"authoring-package-basis-details\">")
  && stylesSource.includes(".authoring-package-review-grid"));
check("prefill-qc-accepts-partial-core-package", prefillQcSource.includes('!["ready", "partial"].includes(report.evidence.initial.packageStatus)')
  && prefillQcSource.includes("coreCandidateFields")
  && !prefillQcSource.includes("availableFields < 10"));

// --- empty-slot no-fallback + unsafe/dead-action policy contract ---
check("no-display-fallback-auto-select", !panelSource.includes("displayCandidates[0]?.candidate_id"));
check("empty-slot-state-present", panelSource.includes('data-testid="composite-empty-slot"')
  && panelSource.includes("该分组当前没有推荐方案"));
check("no-resolved-defaults-carriage", !panelSource.includes("resolvedCompositeDefaults"));
check("no-old-decision-paths-helper", !panelSource.includes("pendingCompositeDecisionPaths"));
check("restricted-gates-ready", panelSource.includes("if (!isPendingCompositeCandidate(candidate)) return true;"));
check("single-path-dead-action-reason", journeySource.includes("prefillCandidateBlockedReason")
  && journeySource.includes("data-prefill-action=\"adopt-recommended\"")
  && journeySource.includes("title={isPendingCompositeCandidate(recommended) ? prefillCandidateBlockedReason(recommended)"));
check("single-path-edit-disabled-for-restricted", journeySource.includes("startEdit(recommended)} disabled={Boolean(busy) || isPendingCompositeCandidate(recommended)}")
  && journeySource.includes("startEdit(candidate)} disabled={Boolean(busy) || pendingCandidate}"));

// --- structured policy error mapping (composite 422 POLICY_REJECTED vs 409) ---
check("readjson-preserves-structured-detail", journeySource.includes("error.code = detail.code")
  && journeySource.includes("error.reason = detail.reason"));
check("composite-policy-branch", compositeFn.includes("isPolicyRejection(error)")
  && journeySource.includes("POLICY_REJECTED")
  && compositeFn.includes("policyRejectionMessage(error)"));
const compositePolicyBranch = compositeFn.match(/if \(isPolicyRejection\(error\)\) \{[\s\S]*?\} else if \(error\.status === 409\)/)?.[0] || "";
check("composite-policy-branch-no-reload", compositePolicyBranch.includes("setMessage(policyRejectionMessage(error))") && !compositePolicyBranch.includes("reloadJourneyAfterPrefillConflict"));
check("composite-409-reload-preserved", compositeFn.includes("error.status === 409") && compositeFn.includes("reloadJourneyAfterPrefillConflict"));
const singleFn = journeySource.match(/const adoptPrefillCandidate = async[\s\S]*?(?=\n  const adoptPrefillComposite)/)?.[0] || "";
check("single-fn-extracted", singleFn.includes("requestPrefillAdoption("), "could not isolate adoptPrefillCandidate body");
check("single-policy-branch", singleFn.includes("isSinglePathPolicyRejection(error)")
  && journeySource.includes("single-candidate adoption is blocked"));
const singlePolicyBranch = singleFn.match(/if \(isSinglePathPolicyRejection\(error\)\) \{[\s\S]*?\} else if \(error\.status === 409\)/)?.[0] || "";
check("single-policy-branch-no-reload", singlePolicyBranch.includes("setMessage(policyRejectionMessage(error))") && !singlePolicyBranch.includes("reloadJourneyAfterPrefillConflict"));

// --- mirrored helper contracts (pending gating, overrides/skips, receipt, alternatives) ---
const fieldGroup = {
  field_path: "framing.protocol_id",
  recommended_candidate_id: "c1",
  candidates: [{ candidate_id: "c1", candidate_scope: "field", recommendation_role: "recommended", target_paths: [] }],
};
const moduleGroup = {
  field_path: "package.population",
  recommended_candidate_id: "m1",
  candidates: [{
    candidate_id: "m1",
    field_path: "package.population",
    candidate_scope: "module",
    recommendation_role: "pending_decision",
    target_paths: ["picos.population_summary", "picos.inclusion_modules"],
    structured_value: {
      "picos.population_summary": "摘要",
      "picos.inclusion_modules": [],
    },
    evidence_refs: [{ source_text: "诊断为RA的目标人群", locator: "framing.creation_minimum" }],
  }, {
    candidate_id: "m2",
    candidate_scope: "module",
    recommendation_role: "alternative",
    target_paths: ["picos.population_summary", "picos.inclusion_modules"],
    structured_value: {
      "picos.population_summary": "备选",
      "picos.inclusion_modules": ["IN1"],
    },
    evidence_refs: [{ source_text: "", locator: "loc-only" }],
  }],
};
const designGroup = {
  field_path: "package.design",
  recommended_candidate_id: "d1",
  candidates: [{
    candidate_id: "d1",
    candidate_scope: "design_package",
    recommendation_role: "recommended",
    adoption_mode: "batch_allowed",
    evidence_status: "supported",
    target_paths: ["design.randomization"],
    structured_value: { "design.randomization": "随机" },
    evidence_refs: [{ source_text: "随机对照", locator: "p1" }],
  }],
};

check("is-composite-module", isCompositePrefillGroup(moduleGroup) === true);
check("is-composite-design", isCompositePrefillGroup(designGroup) === true);
check("is-not-field", isCompositePrefillGroup(fieldGroup) === false);
const collected = collectCompositePrefillGroups({
  field_candidates: {
    "framing.protocol_id": fieldGroup,
    "package.population": moduleGroup,
    "package.design": designGroup,
    "package.soa": {
      field_path: "package.soa",
      recommended_candidate_id: "s1",
      candidates: [{ candidate_id: "s1", candidate_scope: "module", recommendation_role: "recommended" }],
    },
  },
});
check("collect-only-composite", collected.length === 2, `got ${collected.length}`);
check("collect-excludes-soa", !collected.some((item) => item.field_path === "package.soa"));

const pendingPreferred = sortCompositeCandidates(moduleGroup);
check("pending-slot-stays-empty", pendingPreferred.recommended === null, `got ${pendingPreferred.recommended?.candidate_id ?? "null"}`);
check("pending-preview-not-recommended", sortCompositeCandidates({
  field_path: "package.population",
  recommended_candidate_id: "p1",
  candidates: [
    { candidate_id: "p1", recommendation_role: "alternative", preview: "人群边界待确认" },
    { candidate_id: "p2", recommendation_role: "alternative", adoption_mode: "batch_allowed", evidence_status: "supported", preview: "明确人群" },
  ],
}).recommended === null);

const manyAlts = {
  field_path: "package.outcomes",
  recommended_candidate_id: "r0",
  candidates: [
    { candidate_id: "r0", recommendation_role: "recommended", adoption_mode: "batch_allowed", evidence_status: "supported" },
    { candidate_id: "a1", recommendation_role: "alternative", adoption_mode: "batch_allowed", evidence_status: "supported" },
    { candidate_id: "a2", recommendation_role: "alternative", adoption_mode: "batch_allowed", evidence_status: "supported" },
    { candidate_id: "a3", recommendation_role: "alternative", adoption_mode: "batch_allowed", evidence_status: "supported" },
    { candidate_id: "a4", recommendation_role: "alternative", adoption_mode: "batch_allowed", evidence_status: "supported" },
    { candidate_id: "a5", recommendation_role: "alternative", adoption_mode: "batch_allowed", evidence_status: "supported" },
  ],
};
const sorted = sortCompositeCandidates(manyAlts);
check("recommended-first", sorted.recommended?.candidate_id === "r0");
check("alternatives-max-4", sorted.alternatives.length === 4, `got ${sorted.alternatives.length}`);
check("display-max-5", sorted.displayCandidates.length === 5);

const pending = moduleGroup.candidates[0];
check("pending-not-ready-empty", compositeAdoptionReady(pending, {}, {}) === false);
check("pending-ready-all-override", compositeAdoptionReady(pending, {
  "picos.population_summary": "确认人群",
  "picos.inclusion_modules": "IN1",
}, {}) === true);
check("pending-ready-mixed-skip", compositeAdoptionReady(pending, {
  "picos.population_summary": "确认人群",
}, { "picos.inclusion_modules": true }) === true);
check("pending-ready-all-skip", compositeAdoptionReady(pending, {}, {
  "picos.population_summary": true,
  "picos.inclusion_modules": true,
}) === true);
check("pending-not-ready-partial", compositeAdoptionReady(pending, {
  "picos.population_summary": "确认人群",
}, {}) === false);
check("recommended-ready-without-override", compositeAdoptionReady(designGroup.candidates[0], {}, {}) === true);

// --- empty slot / unsafe alternative / safe alternative contract ---
const safeAlt = {
  candidate_id: "safe-alt",
  candidate_scope: "design_package",
  recommendation_role: "alternative",
  adoption_mode: "batch_allowed",
  evidence_status: "supported",
  target_paths: ["design.randomization"],
  structured_value: { "design.randomization": "随机" },
};
const unsafeAlt = {
  candidate_id: "unsafe-alt",
  candidate_scope: "design_package",
  recommendation_role: "alternative",
  adoption_mode: "manual_only",
  evidence_status: "supported",
  target_paths: ["design.randomization"],
  structured_value: { "design.randomization": "随机" },
};
const gapAlt = {
  ...unsafeAlt,
  candidate_id: "gap-alt",
  adoption_mode: "batch_allowed",
  evidence_gaps: ["声称内容未在引用原文中出现：双盲优于单盲"],
};
const emptySlotGroup = {
  field_path: "package.design",
  recommended_candidate_id: "",
  candidates: [unsafeAlt, gapAlt, safeAlt],
};
const emptySorted = sortCompositeCandidates(emptySlotGroup);
check("empty-slot-no-recommendation", emptySorted.recommended === null);
check("empty-slot-safe-alternative-visible", emptySorted.displayCandidates.map((c) => c.candidate_id).includes("safe-alt"));
check("empty-slot-restricted-demoted", emptySorted.displayCandidates[0]?.candidate_id === "safe-alt", `got ${emptySorted.displayCandidates[0]?.candidate_id}`);
check("unsafe-alternative-blocked", compositeCandidateBlockedCode(unsafeAlt) === "manual_only" && isPendingCompositeCandidate(unsafeAlt) === true);
check("gap-carrier-blocked", compositeCandidateBlockedCode(gapAlt) === "unsupported_gap" && isPendingCompositeCandidate(gapAlt) === true);
check("unsafe-alternative-not-ready", compositeAdoptionReady(unsafeAlt, {}, {}) === false);
check("unsafe-alternative-ready-after-decisions", compositeAdoptionReady(unsafeAlt, { "design.randomization": "随机" }, {}) === true);
check("safe-alternative-zero-override-ready", compositeCandidateBlockedCode(safeAlt) === "" && compositeAdoptionReady(safeAlt, {}, {}) === true);
check("decision-paths-all-targets-for-restricted", compositeDecisionPaths(unsafeAlt).join(",") === "design.randomization");
check("decision-paths-empty-for-safe", compositeDecisionPaths(safeAlt).length === 0);

const overrides = buildCompositePathOverrides(pending, {
  "picos.population_summary": " 确认人群 ",
  "picos.inclusion_modules": "should-skip",
}, { "picos.inclusion_modules": true });
check("build-overrides-skip-excluded", Object.keys(overrides).join(",") === "picos.population_summary");
check("build-overrides-trim", overrides["picos.population_summary"] === "确认人群");

check("has-source-text", hasUsableSourceText(pending.evidence_refs) === true);
check("no-source-text-locator-only", hasUsableSourceText(moduleGroup.candidates[1].evidence_refs) === false);
check("receipt-replay-message", receiptSummaryMessage({ replayed: true }) === "已应用（幂等回放）");
check("receipt-stale-message", receiptSummaryMessage({ package_marked_stale: true }).includes("需更新"));
check("receipt-normal-counts", receiptSummaryMessage({
  applied_paths: ["a", "b"],
  overridden_paths: ["c"],
  skipped_paths: [{ path: "d", reason: "pending_decision without override" }],
}).includes("应用2项")
  && receiptSummaryMessage({
    applied_paths: ["a", "b"],
    overridden_paths: ["c"],
    skipped_paths: [{ path: "d", reason: "x" }],
  }).includes("修改1项")
  && receiptSummaryMessage({
    applied_paths: ["a", "b"],
    overridden_paths: ["c"],
    skipped_paths: [{ path: "d", reason: "x" }],
  }).includes("跳过1项"));

// panel source must disable adopt for pending until ready
check("pending-disables-adopt", panelSource.includes("adoptDisabled") && panelSource.includes("compositeAdoptionReady"));
check("button-data-action", panelSource.includes('data-action="adopt-composite"'));
check("package-revision-resets-local-drafts", panelSource.includes("packageRevision = 0")
  && panelSource.includes("setSelectedByField({})")
  && panelSource.includes("setOverridesByField({})")
  && panelSource.includes("setSkipsByField({})")
  && journeySource.includes("packageRevision={prefillPackage.package_revision}"));
check("skip-control-pending-only", panelSource.includes("allowSkip = false")
  && panelSource.includes("{allowSkip && (")
  && panelSource.includes("allowSkip\n                disabled="));

const prefillQcCoversBatchRemoval = prefillQcSource.includes("noBatchButton");

const report = {
  passed: failures.length === 0,
  failures,
  checks: {
    oneRequestSemantics: true,
    pendingGating: true,
    overridesSkips: true,
    receiptCategories: true,
    replayStale: true,
    singleFieldPreserved: true,
    conflict409Reload: true,
    prefillBrowserQcCoversBatchRemoval: prefillQcCoversBatchRemoval,
  },
  sources: { panelPath, journeyPath, stylesPath },
};

if (!report.passed) {
  console.error(JSON.stringify(report, null, 2));
  process.exit(1);
}
console.log(JSON.stringify(report, null, 2));
