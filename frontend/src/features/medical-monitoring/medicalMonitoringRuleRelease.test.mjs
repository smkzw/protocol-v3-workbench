import assert from "node:assert/strict";

import {
  PROVISIONAL_INSPECTION_NOTE,
  RULE_RELEASE_STEPS,
  SHADOW_CONFIRMATION_NOTE,
  buildAutomaticShadowRunPayload,
  buildRulePackDraftPayload,
  buildRulePackPublishPayload,
  buildShadowConfirmationPayload,
  confirmedShadowRunView,
  frozenShadowBatches,
  isProvisionalInspection,
  latestPublishedRulePack,
  latestRulePack,
  normalizedRulePack,
  provisionalInspectionViewModel,
  provisionalSampleView,
  rulePackDiffView,
  rulePackDisplayKey,
  rulePackRules,
  ruleReleaseChainSteps,
  ruleReleaseErrorText,
  ruleReleaseNextAction,
  shadowBatchOptionLabel,
  shadowLineageEvidenceViewModel,
  sortedRulePacks,
} from "./medicalMonitoringRuleRelease.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

const packs = [
  {
    rule_pack_id: "monpack-1",
    protocol_version_id: "mpv-1",
    pack_revision: 1,
    status: "published",
    rule_revision_ids: ["r1", "r2"],
    published_at: "2026-07-20T09:00:00",
  },
  {
    rule_pack_id: "monpack-2",
    protocol_version_id: "mpv-1",
    pack_revision: 2,
    status: "draft",
    rule_revision_ids: ["r3"],
  },
  { rule_pack_id: "", status: "draft" },
  null,
];

const sorted = sortedRulePacks(packs);
check(sorted.length === 2, "drops malformed pack entries");
check(sorted[0].rulePackId === "monpack-2", "orders newest revision first");
check(latestRulePack(packs).rulePackId === "monpack-2", "selects the latest pack");
check(
  latestPublishedRulePack(packs).rulePackId === "monpack-1",
  "selects the latest published pack",
);
check(
  normalizedRulePack(packs[0]).statusLabel === "已发布",
  "renders a concise Chinese pack status",
);
const duplicatePacks = sortedRulePacks([
  { ...packs[0], rule_pack_id: "duplicate-pack", pack_revision: 3 },
  { ...packs[1], rule_pack_id: "duplicate-pack", pack_revision: 2 },
]);
check(duplicatePacks.length === 2, "keeps duplicate pack rows visible");
check(duplicatePacks.every((pack) => pack.displayIdentityState === "duplicate"), "marks duplicate pack identity");
check(
  rulePackDisplayKey(duplicatePacks[0]) !== rulePackDisplayKey(duplicatePacks[1]),
  "uses source-indexed display keys for duplicate packs",
);
check(latestRulePack([
  { ...packs[0], rule_pack_id: "duplicate-pack" },
  { ...packs[1], rule_pack_id: "duplicate-pack" },
]) === null, "does not choose an ambiguous latest pack");

const rules = rulePackRules({
  rules: [
    {
      rule_revision_id: "rr-1",
      rule_key: "ae_missing_report",
      title: "AE 漏报核查",
      status: "confirmed",
      severity: "high",
      required_domains: ["ae"],
      source_locator: "方案 5.2 节",
      state_version: 1,
    },
    { rule_key: "", status: "candidate" },
  ],
});
check(rules.length === 1, "drops malformed rule entries");
check(rules[0].statusLabel === "医学已确认", "adopted rules read as medically confirmed");
check(
  rules.every((rule) => rule.statusLabel !== "待医学批准"),
  "no secondary approval wording for adopted rules",
);

const inspectionPayload = {
  sample_set_id: "monshset-1",
  status: "provisional",
  rule_pack_id: "monpack-2",
  batch_id: "batch-7",
  batch_version: 3,
  samples: [
    {
      sample_id: "s-1",
      rule_key: "ae_missing_report",
      bucket: "positive",
      case_label: "受试者 S001 第 3 访视",
      business_key: "S001/AE-2",
      actual_matched: true,
      actual_evaluation_state: "true",
      actual_diagnostic_code: "",
      evidence_summary: "AE 记录未在 24 小时内上报。",
    },
    {
      sample_id: "s-2",
      rule_key: "ae_missing_report",
      bucket: "diagnostic",
      case_label: "受试者 S002",
      business_key: "S002/AE-1",
      actual_matched: false,
      actual_evaluation_state: "indeterminate",
      actual_diagnostic_code: "missing_required_domains",
      evidence_summary: "缺少必要数据域，无法判定。",
    },
  ],
};

check(isProvisionalInspection(inspectionPayload), "recognizes the provisional inspection");
check(
  !isProvisionalInspection({ status: "shadow_passed" }),
  "never treats a trusted pass label as provisional",
);
const inspection = provisionalInspectionViewModel(inspectionPayload);
check(inspection.sampleSetId === "monshset-1", "carries the frozen sample set id");
check(inspection.statusLabel === "自动影子样本待医学确认", "provisional status stays explicit");
check(inspection.samples.length === 2, "renders every sample");
const hitSample = provisionalSampleView(inspectionPayload.samples[0]);
check(hitSample.outcomeLabel === "实际命中", "shows the actual hit outcome");
check(hitSample.outcomeTone === "hit", "maps hit tone for styling");
check(hitSample.bucketLabel === "命中样本", "labels the positive bucket");
const indeterminateSample = provisionalSampleView(inspectionPayload.samples[1]);
check(indeterminateSample.outcomeLabel === "不可判定", "shows the indeterminate outcome");
check(
  indeterminateSample.diagnosticCode === "missing_required_domains",
  "keeps the actual diagnostic code",
);

const provisionalVocabulary = JSON.stringify({
  inspection,
  hitSample,
  indeterminateSample,
  note: PROVISIONAL_INSPECTION_NOTE,
});
check(
  !provisionalVocabulary.includes("验证通过")
    && !provisionalVocabulary.includes("shadow_passed")
    && !provisionalVocabulary.includes("可信"),
  "provisional projection never uses trusted or passed vocabulary",
);
check(
  SHADOW_CONFIRMATION_NOTE.includes("不是再次批准规则"),
  "confirmation copy separates sample confirmation from rule adoption",
);

const confirmedRun = confirmedShadowRunView({
  shadow_run_id: "monrun-1",
  case_count: 3,
  passed_count: 3,
  failed_count: 0,
  diagnostic_case_count: 1,
  diagnostic_passed_count: 1,
  diagnostic_failed_count: 0,
});
check(confirmedRun.allPassed, "trusted run reports full agreement after confirmation");
check(confirmedRun.total === 4 && confirmedRun.passed === 4, "sums standard and diagnostic cases");
check(
  confirmedShadowRunView({ shadow_run_id: "x", case_count: 0, diagnostic_case_count: 0 }).label
    === "已确认影子样本",
  "handles an empty confirmed run",
);

const diff = rulePackDiffView({
  added_rule_keys: ["rule_c"],
  changed_rule_keys: ["rule_a"],
  superseded_rule_keys: [],
});
check(diff.summary === "相较当前已发布规则包：新增 1 条 · 变更 1 条", "summarizes material changes");
check(rulePackDiffView(null) === null, "no diff without impact payload");
check(
  rulePackDiffView({ added_rule_keys: [], changed_rule_keys: [], superseded_rule_keys: [] }) === null,
  "no diff card for an unchanged pack",
);

const draftPack = normalizedRulePack(packs[1]);
const noPackSteps = ruleReleaseChainSteps({});
check(noPackSteps[0].state === "current" && noPackSteps[4].state === "locked", "starts at the draft step");
check(
  ruleReleaseNextAction({}).label === "组建规则包草稿",
  "first action assembles the draft pack",
);
const draftSteps = ruleReleaseChainSteps({ pack: draftPack });
check(draftSteps[0].state === "done" && draftSteps[1].state === "current", "draft pack moves to shadow");
check(
  ruleReleaseNextAction({ pack: draftPack }).label === "运行自动影子检查",
  "draft pack next action runs the automatic inspection",
);
const shadowPack = normalizedRulePack({ ...packs[1], status: "shadow" });
const provisionalSteps = ruleReleaseChainSteps({ pack: shadowPack, inspection });
check(
  provisionalSteps[1].state === "done" && provisionalSteps[2].state === "current",
  "provisional inspection moves to sample confirmation",
);
check(
  ruleReleaseNextAction({ pack: shadowPack, inspection }).label === "确认影子样本结果",
  "provisional inspection next action confirms the samples",
);
const shadowWithoutInspection = ruleReleaseChainSteps({ pack: shadowPack });
check(
  shadowWithoutInspection[1].state === "current" && shadowWithoutInspection[2].state === "locked",
  "shadow stage without samples still waits for the automatic inspection",
);
const confirmedPack = normalizedRulePack({ ...packs[1], status: "confirmed" });
check(
  ruleReleaseNextAction({ pack: confirmedPack }).label === "发布规则包",
  "confirmed pack next action publishes explicitly",
);
const publishedPack = normalizedRulePack({ ...packs[1], status: "published" });
const readySteps = ruleReleaseChainSteps({
  pack: publishedPack,
  readiness: { ready: true },
});
check(readySteps.every((step) => step.state === "done"), "published and ready closes the chain");
check(
  ruleReleaseChainSteps({ pack: publishedPack, readiness: { ready: false } })[4].state === "current",
  "unready published pack keeps the readiness step open",
);
check(RULE_RELEASE_STEPS.length === 5, "keeps the five-step product chain");

let draftError = null;
try {
  buildRulePackDraftPayload({ protocolVersionId: "mpv-1", factRevisionIds: [] });
} catch (error) {
  draftError = error;
}
check(draftError instanceof TypeError, "draft payload requires confirmed facts");
const draftPayload = buildRulePackDraftPayload({
  protocolVersionId: "mpv-1",
  factRevisionIds: ["f-1", "f-1", " f-2 ", ""],
});
check(
  draftPayload.fact_revision_ids.join(",") === "f-1,f-2",
  "draft payload deduplicates fact revisions",
);
check(!("deterministic_template" in draftPayload), "draft payload never submits rule templates");

const shadowPayload = buildAutomaticShadowRunPayload({ batchId: "batch-7", expectedPackRevision: 2 });
check(
  Object.keys(shadowPayload).sort().join(",") === "batch_id,expected_pack_revision",
  "automatic shadow submits only the batch choice",
);
check(
  !("case_ids" in shadowPayload) && !("row_fingerprints" in shadowPayload)
    && !("mapping_revision" in shadowPayload),
  "automatic shadow payload has no engineering fields",
);
let shadowError = null;
try {
  buildAutomaticShadowRunPayload({ batchId: " " });
} catch (error) {
  shadowError = error;
}
check(shadowError instanceof TypeError, "automatic shadow requires a frozen batch");

const confirmPayload = buildShadowConfirmationPayload({
  sampleSetId: "monshset-1",
  expectedPackRevision: 2,
});
check(
  confirmPayload.sample_set_id === "monshset-1" && !("shadow_run_id" in confirmPayload),
  "confirmation submits the frozen sample set only",
);
let confirmError = null;
try {
  buildShadowConfirmationPayload({});
} catch (error) {
  confirmError = error;
}
check(confirmError instanceof TypeError, "confirmation requires the frozen sample set");

check(
  buildRulePackPublishPayload({ expectedPackRevision: 2 }).expected_pack_revision === 2,
  "publish carries the optimistic concurrency token",
);
check(
  !("expected_pack_revision" in buildRulePackPublishPayload({})),
  "publish token stays optional",
);

const frozen = frozenShadowBatches([
  { batch_id: "b-1", state: "frozen", created_at: "2026-07-28T08:00:00", row_count: 128 },
  { batch_id: "b-2", state: "parsed" },
  { batch_id: "", state: "frozen" },
]);
check(frozen.length === 1 && frozen[0].batchId === "b-1", "only frozen batches can seed samples");
check(
  shadowBatchOptionLabel(frozen[0]).includes("128"),
  "batch option shows the frozen record count",
);
const duplicateFrozen = frozenShadowBatches([
  { batch_id: "dup-batch", state: "frozen", created_at: "2026-07-28T08:00:00", row_count: 10 },
  { batch_id: "dup-batch", state: "frozen", created_at: "2026-07-29T08:00:00", row_count: 11 },
  { batch_id: "unique-batch", state: "frozen", created_at: "2026-07-30T08:00:00", row_count: 12 },
]);
check(duplicateFrozen.length === 3, "keeps duplicate frozen batches visible");
check(
  duplicateFrozen.slice(0, 2).every((batch) => batch.displayIdentityState === "duplicate"),
  "marks duplicate frozen batch identity",
);
check(
  new Set(duplicateFrozen.map((batch) => batch.displayKey)).size === 3,
  "uses source-indexed display keys for frozen batches",
);
check(duplicateFrozen[2].displayIdentityState === "ready", "keeps a unique frozen batch selectable");

check(
  ruleReleaseErrorText({ detail: { detail: { message: "字段映射已变化。" } } })
    === "字段映射已变化。",
  "surfaces the precise server failure message",
);
check(
  ruleReleaseErrorText(new Error("network")),
  "falls back to the transport error message",
);
check(
  ruleReleaseErrorText(null, "默认提示") === "默认提示",
  "falls back to the supplied default",
);

const lineagePayload = {
  project_id: "p-1",
  rule_pack_id: "monpack-9",
  shadow_rule_pack_id: "monpack-7",
  items: [
    {
      ...inspectionPayload,
      sample_set_id: "monshset-1",
      samples: [inspectionPayload.samples[0]],
    },
    { ...inspectionPayload, sample_set_id: "monshset-2" },
  ],
  confirmation: {
    confirmation_id: "monconf-1",
    sample_set_id: "monshset-1",
    trusted_shadow_run_id: "monrun-1",
    confirmed_at: "2026-07-29T10:00:00",
  },
};
const lineageView = shadowLineageEvidenceViewModel(lineagePayload);
check(
  lineageView.shadowRulePackId === "monpack-7",
  "carries the shadow-stage ancestor pack id",
);
check(
  lineageView.sampleSet.sampleSetId === "monshset-1",
  "confirmation pins the exact confirmed sample set",
);
check(
  lineageView.sampleSet.confirmed === true
    && lineageView.sampleSet.samples.every((sample) => sample.confirmed === true),
  "marks every confirmed evidence sample row",
);
check(
  lineageView.sampleSet.statusLabel === "医学已确认",
  "confirmed lineage evidence reads as medically confirmed",
);
check(
  lineageView.sampleSet.samples.length === 1
    && lineageView.sampleSet.samples[0].outcomeLabel === "实际命中",
  "reuses the existing sample normalization for lineage rows",
);
check(
  lineageView.confirmation.confirmedAt === "2026-07-29T10:00:00"
    && lineageView.confirmation.sampleSetId === "monshset-1",
  "exposes only confirmation time and set identity",
);

const unconfirmedLineage = shadowLineageEvidenceViewModel({
  ...lineagePayload,
  confirmation: null,
});
check(
  unconfirmedLineage.sampleSet.sampleSetId === "monshset-2",
  "without a confirmation the latest sample set is restored",
);
check(
  unconfirmedLineage.sampleSet.confirmed === false
    && unconfirmedLineage.sampleSet.statusLabel === "自动影子样本待医学确认",
  "unconfirmed lineage evidence stays provisional",
);

const emptyLineage = shadowLineageEvidenceViewModel({
  project_id: "p-1",
  rule_pack_id: "monpack-3",
  shadow_rule_pack_id: "",
  items: [],
  confirmation: null,
});
check(
  emptyLineage.sampleSet === null && emptyLineage.shadowRulePackId === "",
  "a pack without a shadow ancestor has no lineage evidence",
);
check(
  shadowLineageEvidenceViewModel(null) === null,
  "a missing payload yields no lineage evidence view",
);

const lineageVocabulary = JSON.stringify({
  confirmed: lineageView,
  provisional: unconfirmedLineage,
  empty: emptyLineage,
});
check(
  lineageVocabulary.includes("医学已确认")
    && !lineageVocabulary.includes("验证通过")
    && !lineageVocabulary.includes("shadow_passed"),
  "lineage evidence keeps the guarded vocabulary",
);

console.log(`medicalMonitoringRuleRelease: ${passed} passed`);
