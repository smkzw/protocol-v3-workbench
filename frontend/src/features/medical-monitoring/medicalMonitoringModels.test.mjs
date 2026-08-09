import assert from "node:assert/strict";
import { demoRiskRows, demoSubjects } from "./medicalMonitoringFixtures.mjs";
import {
  monitoringAiReadiness,
  monitoringFieldMappingCopy,
  medicalMonitoringRiskDisplayKey,
  monitoringRiskCategoryLabel,
  monitoringRiskRowsFromInbox,
  riskEvidenceCoverageMessage,
  riskEvidenceCoverageSummary,
  riskEvidenceLineageMessage,
  riskEvidenceLineageSummary,
  riskRowEvidenceBadge,
  riskChecklistCategoryTags,
  riskChecklistUpdatedDate,
  riskChecklistUpdatedSortValue,
  riskIndexRowsFromApi,
  riskStatusLabel,
  ruxDispositionStateFromStatus,
  severityLabel,
  terminalDispositionLabels,
} from "./medicalMonitoringModels.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

const configuredOnly = monitoringAiReadiness({
  configured: true,
  semantic_ai_tasks_enabled: false,
});
check(configuredOnly.configured === true, "preserves connection configured state");
check(configuredOnly.ready === false, "configured-only status is not semantic-AI ready");
check(configuredOnly.label.includes("不可运行"), "surfaces configured-but-blocked state");
const semanticReady = monitoringAiReadiness({
  configured: true,
  semantic_ai_tasks_enabled: true,
});
check(semanticReady.ready === true, "semantic-AI enabled status is runnable");
check(semanticReady.semantic_ai_tasks_enabled === true, "normalized monitoring status preserves semantic-AI readiness");
check(semanticReady.label === "独立AI可运行", "uses runnable monitoring label");

const unavailableMappingCopy = monitoringFieldMappingCopy(configuredOnly);
check(unavailableMappingCopy.ready === false, "mapping copy preserves unavailable AI state");
check(
  unavailableMappingCopy.entryDescription.includes("确定性规则仅处理技术元数据")
    && unavailableMappingCopy.entryDescription.includes("语义字段需配置后再识别"),
  "unavailable mapping copy distinguishes deterministic metadata from semantic fields",
);
check(
  !unavailableMappingCopy.entryAction.includes("AI")
    && !unavailableMappingCopy.startAction.includes("AI"),
  "unavailable mapping actions do not claim an AI call",
);
const readyMappingCopy = monitoringFieldMappingCopy(semanticReady);
check(readyMappingCopy.ready === true, "mapping copy preserves runnable AI state");
check(readyMappingCopy.entryAction === "AI识别并校对字段", "ready mapping action keeps AI-led wording");

const genericRoleReady = monitoringFieldMappingCopy({
  configured: true,
  ready: true,
  semantic_ai_tasks_enabled: false,
});
check(genericRoleReady.ready === false, "generic role readiness cannot enable semantic field mapping");

const inboxRows = monitoringRiskRowsFromInbox({
  items: [
    {
      item_id: "inbox-low",
      module: "medical_monitoring",
      item_type: "risk",
      risk_instance_id: "risk-low",
      risk_key: "VISIT-1",
      target_id: "S02001",
      title: "访视时间窗偏离",
      source_type: "monitoring_risk",
      priority: "low",
      status: "待医学复核",
      source_version: "batch_001:rev1",
      unread: false,
      updated_at: "2026-07-28T08:30:00Z",
      source_refs: [{ source_type: "listing_data_row" }],
    },
    {
      item_id: "ignore-writing",
      module: "medical_writing",
      item_type: "risk",
      priority: "critical",
    },
    {
      item_id: "inbox-high",
      module: "medical_monitoring",
      item_type: "risk",
      source_id: "risk-high",
      target_id: "S01003",
      title: "AE漏报风险",
      source_type: "monitoring_risk",
      priority: "high",
      status: "已转Safety/PV协作",
      source_version: "batch_002:rev7",
      unread: true,
      updated_at: "2026-07-29T01:02:03Z",
      owner_role: "医学总监",
      source_refs: [
        { source_type: "protocol_rule" },
        { source_type: "listing_data_row" },
      ],
    },
    {
      item_id: "inbox-explicit-site",
      module: "medical_monitoring",
      item_type: "risk",
      source_id: "risk-explicit-site",
      target_id: "10008",
      site_id: "10",
      title: "MG-K10安全性趋势需复核",
      source_type: "monitoring_risk",
      priority: "medium",
      status: "待医学复核",
      source_version: "batch_003:rev7",
      unread: true,
      updated_at: "2026-07-29T02:02:03Z",
      source_refs: [{ source_type: "listing_data_row" }],
    },
  ],
}, "003");

check(inboxRows.length === 3, "monitoringRiskRowsFromInbox excludes non-monitoring items");
check(inboxRows[0].id === "inbox-high", "inbox risks sort by medical severity");
check(inboxRows[0].site === "01" && inboxRows[0].subject === "S01003", "maps subject and site fields");
check(
  inboxRows.find((row) => row.id === "inbox-explicit-site")?.site === "10",
  "prefers explicit site identity for subject ids without an S-prefixed site encoding",
);
check(inboxRows[0].batch === "003", "explicit display batch overrides source version");
check(
  inboxRows[0].source === "方案条款定位 / 原始数据 listing 行",
  "preserves protocol and listing source labels",
);
check(
  inboxRows.find((row) => row.id === "inbox-high")?.unread === true
    && inboxRows.find((row) => row.id === "inbox-explicit-site")?.unread === true
    && inboxRows.find((row) => row.id === "inbox-low")?.unread === false,
  "preserves read state independently",
);
check(
  riskChecklistUpdatedDate(inboxRows[0].age) === "2026-07-29",
  "shows the actual update date instead of read state",
);
check(
  inboxRows[0].dispositionState === "safety_pv_collaboration",
  "maps Safety/PV collaboration disposition",
);

const riskRows = riskIndexRowsFromApi({
  items: [
    {
      risk_instance_id: "risk-high",
      risk_key: "AE-MISS-001",
      title: "AE漏报风险",
      subject_id: "S01003",
      site_id: "01",
      primary_category: "safety_ae_mh",
      tags: ["safety_pv"],
      risk_category_code: "ae_missing_report",
      risk_category_label: "AE漏报",
      safety_pv_flag: true,
      taxonomy_version: "medical-monitoring-risk-taxonomy-v1",
      severity: "high",
      status: "action_required",
      detection_status: "action_required",
      work_item: {
        item_id: "monitoring-risk:risk-high",
        medical_disposition_status: "已说明，无需外部动作",
        medical_disposition_state: "explained_no_external_action",
        read_state: "read",
        unread: false,
        needs_action: false,
        query_workflow_state: "not_applicable",
        action_label: "查看医学处置记录",
        source_version: "monitoring:rev-3",
        source_refs: [],
        last_action_at: "2026-07-30T01:02:03Z",
      },
      source_batch_id: "batch_003",
      batch_delta: "new",
      rule_id: "AE-MH-001",
      created_at: "2026-07-29T01:02:03Z",
      rationale: "病历症状与AE表不一致",
      recommended_action: "医学复核",
      scope_type: "subject",
      scope_id: "S01003",
      confidence: 0.92,
      source_revision: "rev-3",
      evidence_span_ids: ["AE:row:3"],
    },
    {
      risk_id: "trial-risk",
      title: "项目级信号",
      primary_category: "cfdi",
      tags: [],
      risk_category_code: "other_medical_review",
      risk_category_label: "其他医学复核",
      safety_pv_flag: false,
      taxonomy_version: "medical-monitoring-risk-taxonomy-v1",
      severity: "medium",
      status: "in_review",
      disposition_status: "pending_review",
      updated_at: "2026-07-29T01:02:03Z",
      scope_type: "trial",
      confidence: 1,
    },
  ],
}, inboxRows);

check(riskRows.length === 2, "riskIndexRowsFromApi maps all snapshot risks");
check(riskRows[0].status === "已说明，无需外部动作", "unified work item overrides legacy inbox and engine status");
check(riskRows[0].detectionStatus === "action_required", "preserves the independent rule detection status");
check(riskRows[0].dispositionState === "explained_no_external_action", "maps the canonical medical disposition state");
check(riskRows[0].unread === false && riskRows[0].needsAction === false, "maps canonical read and action states");
check(riskRows[0].queryWorkflowState === "not_applicable", "maps query workflow separately");
check(riskRows[0].age.startsWith("2026/7/30"), "uses the latest medical action time in the checklist");
check(riskRows[0].batch === "003" && riskRows[0].batchDelta === "new", "maps batch fields");
check(riskRows[0].scopeLabel === "受试者 S01003", "maps subject scope label");
check(riskRows[0].sourceCompleteness === 92, "maps confidence to source completeness");
check(riskRows[0].evidenceLocators[0] === "AE:row:3", "keeps evidence locators read-only");
check(riskRows[1].status === "待医学复核", "defaults an unprojected medical disposition to pending review");
check(riskRows[1].scopeLabel === "整个试验", "maps trial scope label");

const duplicateRiskRows = riskIndexRowsFromApi({
  items: [
    {
      risk_instance_id: "duplicate-risk",
      risk_key: "duplicate-rule-a",
      title: "重复风险证据 A",
      severity: "high",
      status: "new",
    },
    {
      risk_instance_id: "duplicate-risk",
      risk_key: "duplicate-rule-b",
      title: "重复风险证据 B",
      severity: "medium",
      status: "new",
    },
  ],
});
check(duplicateRiskRows.length === 2, "retains every duplicate risk evidence row");
check(
  duplicateRiskRows.every((row) => row.identityAmbiguous === true)
    && duplicateRiskRows.every((row) => row.identityIssue.includes("重复")),
  "marks duplicate risk identity as ambiguous without dropping evidence",
);
check(
  duplicateRiskRows[0].sourceIndex === 0
    && duplicateRiskRows[1].sourceIndex === 1
    && medicalMonitoringRiskDisplayKey(duplicateRiskRows[0], duplicateRiskRows[0].sourceIndex)
      !== medicalMonitoringRiskDisplayKey(duplicateRiskRows[1], duplicateRiskRows[1].sourceIndex),
  "uses source-index display keys for duplicate risk rows",
);

check(
  riskEvidenceLineageSummary(riskRows).status === "partial",
  "flags a risk page when one rendered row lacks explicit source binding",
);
check(
  riskEvidenceLineageMessage(riskEvidenceLineageSummary(riskRows)).includes("不能据此判断数据完整"),
  "makes incomplete source binding fail-closed for data-sensitive reviewers",
);
check(
  riskEvidenceLineageSummary([
    { sourceRevision: "rev-1", sourceBatchId: "batch-1" },
    { sourceRevision: "rev-1", sourceBatchId: "batch-1" },
  ]).status === "bound",
  "recognizes a uniformly bound risk page without inferring freshness",
);
check(
  riskEvidenceLineageSummary([
    { sourceRevision: "rev-1" },
    { sourceRevision: "rev-2" },
  ]).status === "mixed",
  "distinguishes mixed source revisions from a single bound page",
);
check(
  riskEvidenceLineageSummary([{ batch: "003" }]).status === "partial"
    && riskEvidenceLineageMessage(riskEvidenceLineageSummary([{ batch: "003" }])).includes("批次号不足以证明"),
  "does not treat a batch label alone as a complete source revision binding",
);
const malformedLineage = riskEvidenceLineageSummary([{
  sourceRevision: 42,
  sourceBatchId: "batch-004",
}]);
check(
  malformedLineage.status === "partial"
    && malformedLineage.malformedBindingRows === 1
    && riskEvidenceLineageMessage(malformedLineage).includes("来源绑定字段形状异常"),
  "distinguishes malformed lineage tokens from ordinary missing binding",
);
check(
  riskRowEvidenceBadge({ evidenceLocators: ["listing:AE:row:4"], sourceRefs: [] }).label === "证据定位 1 条",
  "row badge requires explicit evidence locator",
);
check(
  riskRowEvidenceBadge({ sourceRefs: [{ source_type: "listing_data_row" }], evidenceLocators: [] }).status === "partial",
  "row badge keeps reference-only evidence partial",
);
check(
  riskRowEvidenceBadge({ title: "有标题但无定位" }).status === "missing",
  "row badge never infers evidence from title",
);
const evidenceCoverage = riskEvidenceCoverageSummary([
  { evidenceLocators: ["listing:AE:row:4"], sourceRefs: [] },
  { evidenceLocators: [], sourceRefs: [{ source_type: "listing_data_row" }] },
  { evidenceLocators: [], sourceRefs: [] },
  { evidenceLocators: "malformed", sourceRefs: [] },
]);
check(
  evidenceCoverage.status === "malformed"
    && evidenceCoverage.boundRows === 1
    && evidenceCoverage.referenceOnlyRows === 1
    && evidenceCoverage.missingRows === 1
    && evidenceCoverage.malformedRows === 1,
  "page evidence summary keeps bound, reference-only, missing, and malformed rows separate",
);
check(
  riskEvidenceCoverageMessage(evidenceCoverage).startsWith("当前页 4 条风险：")
    && riskEvidenceCoverageMessage(evidenceCoverage).includes("缺失/异常不等于无风险"),
  "page evidence message is explicitly scoped and fail-closed",
);
check(
  riskEvidenceCoverageSummary([{ title: "只有标题" }]).status === "missing"
    && riskEvidenceCoverageMessage(riskEvidenceCoverageSummary([{ title: "只有标题" }])).includes("当前页 1 条风险"),
  "page summary never infers evidence from title or page count",
);

check(
  riskChecklistCategoryTags(riskRows[0]).join("|") === "AE漏报|Safety/PV",
  "adds Safety/PV as a secondary tag without replacing the medical category",
);
check(
  riskChecklistCategoryTags({
    title: "标题故意写成MH漏报",
    rationale: "自由文本故意写成禁用药",
    risk_category_label: "实验室异常",
    safety_pv_flag: false,
  })[0] === "实验室异常",
  "title and rationale cannot change the backend category",
);
check(
  riskChecklistCategoryTags({
    title: "禁用药洗脱不足",
    type: "protocol_deviation",
    tags: ["safety_pv"],
  }).join("|") === "其他医学复核",
  "legacy title type and tags cannot infer a category or Safety/PV flag",
);
check(
  riskChecklistCategoryTags({
    risk_category_label: "禁用合并用药PD",
    safety_pv_flag: true,
  }).join("|") === "禁用合并用药PD|Safety/PV",
  "uses only explicit backend category and additive Safety/PV projection",
);
check(
  riskRows[0].riskCategoryCode === "ae_missing_report"
    && riskRows[0].taxonomyVersion === "medical-monitoring-risk-taxonomy-v1",
  "preserves backend taxonomy identity",
);
check(
  riskRows[0].safetyPvFlag === true && riskRows[1].safetyPvFlag === false,
  "preserves Safety/PV as an independent backend flag",
);

const malformedEvidenceRows = riskIndexRowsFromApi({
  items: [
    {
      risk_instance_id: "malformed-evidence",
      risk_key: "malformed-evidence-key",
      title: "证据字段形状异常",
      severity: "high",
      tags: "safety_pv",
      evidence_span_ids: "AE:row:bad-shape",
      work_item: {
        item_id: "monitoring-risk:malformed-evidence",
        source_refs: { source_type: "listing_data_row" },
      },
    },
  ],
}, [
  {
    id: "legacy-malformed-evidence",
    riskId: "malformed-evidence",
    sourceRefs: "not-an-array",
    sourceEvidenceShape: "malformed",
  },
]);
check(malformedEvidenceRows.length === 1, "malformed evidence shape does not drop the risk row");
check(
  malformedEvidenceRows[0].evidenceLocators.length === 0
    && malformedEvidenceRows[0].sourceRefs.length === 0
    && malformedEvidenceRows[0].tags.length === 0,
  "malformed evidence, source refs, and tags degrade to empty arrays",
);
check(
  malformedEvidenceRows[0].sourceEvidenceShape === "malformed",
  "malformed evidence shape is explicitly marked and cannot become valid evidence",
);

const workItemEvidenceRows = riskIndexRowsFromApi({
  items: [{
    risk_instance_id: "work-item-source",
    risk_key: "work-item-source-key",
    title: "保留 work-item 来源定位",
    severity: "medium",
    evidence_span_ids: ["docx:protocol:visit-1"],
    work_item: {
      item_id: "monitoring-risk:work-item-source",
      source_refs: [{ source_type: "protocol_rule", locator: "docx:protocol:visit-1" }],
    },
  }],
}, []);
check(
  workItemEvidenceRows[0].sourceRefs[0]?.source_type === "protocol_rule",
  "keeps valid work-item source references instead of overwriting them with legacy inbox refs",
);

const malformedInboxRows = monitoringRiskRowsFromInbox({
  items: [{
    item_id: "inbox-malformed-source",
    module: "medical_monitoring",
    item_type: "risk",
    source_id: "risk-malformed-source",
    title: "来源引用形状异常",
    source_refs: "not-an-array",
    priority: "medium",
    status: "待医学复核",
  }],
});
check(
  malformedInboxRows[0].sourceRefs.length === 0
    && malformedInboxRows[0].sourceEvidenceShape === "malformed",
  "inbox source references fail closed with an explicit malformed marker",
);
const malformedSourceFieldRows = monitoringRiskRowsFromInbox({
  items: [{
    item_id: "inbox-malformed-source-field",
    module: "medical_monitoring",
    item_type: "risk",
    source_id: "risk-malformed-source-field",
    source_refs: [{ locator: 42 }],
  }],
});
check(
  malformedSourceFieldRows[0].sourceRefs.length === 0
    && malformedSourceFieldRows[0].sourceEvidenceShape === "malformed",
  "malformed source locator fields cannot become evidence",
);

const malformedInboxSourceTokenRows = monitoringRiskRowsFromInbox({
  items: [{
    item_id: "inbox-malformed-source-token",
    module: "medical_monitoring",
    item_type: "risk",
    source_id: "risk-malformed-source-token",
    source_version: 42,
  }],
}, 7);
check(
  malformedInboxSourceTokenRows.length === 1
    && malformedInboxSourceTokenRows[0].batch === "-"
    && malformedInboxSourceTokenRows[0].sourceVersion === ""
    && malformedInboxSourceTokenRows[0].sourceTokenShape === "malformed",
  "malformed inbox source tokens fail closed without crashing or becoming a batch label",
);

const malformedApiSourceTokenRows = riskIndexRowsFromApi({
  items: [{
    risk_instance_id: "malformed-api-source-token",
    risk_key: "malformed-api-source-token-key",
    source_batch_id: 42,
    source_revision: { revision: "rev-1" },
  }],
}, []);
check(
  malformedApiSourceTokenRows.length === 1
    && malformedApiSourceTokenRows[0].batch === "-"
    && malformedApiSourceTokenRows[0].sourceRevision === ""
    && malformedApiSourceTokenRows[0].sourceVersion === ""
    && malformedApiSourceTokenRows[0].triggerWindow === "来源绑定形状异常"
    && malformedApiSourceTokenRows[0].sourceTokenShape === "malformed",
  "malformed API source tokens fail closed without crashing or becoming a trigger window",
);

check(monitoringRiskCategoryLabel("实验室异常") === "实验室异常", "uses the supplied backend label");
check(monitoringRiskCategoryLabel("") === "其他医学复核", "empty category degrades conservatively");
check(severityLabel("critical") === "紧急" && severityLabel("medium") === "中", "maps severity labels");
check(riskStatusLabel("accepted_no_action") === "接受不处理", "maps risk status labels");
check(ruxDispositionStateFromStatus("未知状态") === "pending_review", "unknown disposition stays pending");
check(
  terminalDispositionLabels.pd_update === "已转PD补充/更新",
  "exports terminal disposition labels",
);

check(riskChecklistUpdatedDate("2026/7/9 4:05:06") === "2026-07-09", "normalizes display date");
check(
  riskChecklistUpdatedSortValue("2026-7-9 4:05:06") === "20260709040506",
  "normalizes sortable date and time",
);
check(
  riskChecklistUpdatedSortValue("2026-7-9 4:05:06")
    < riskChecklistUpdatedSortValue("2026-10-1 00:00:00"),
  "sortable timestamp preserves chronology",
);
check(riskChecklistUpdatedDate("未读") === "", "non-date display values do not become dates");

check(monitoringRiskRowsFromInbox(undefined).length === 0, "empty inbox returns no risk rows");
check(monitoringRiskRowsFromInbox({ items: "malformed" }).length === 0, "malformed inbox items fail closed");
check(
  monitoringRiskRowsFromInbox({ items: [{ module: "medical_monitoring", item_type: "risk", item_id: 42, source_id: "risk-42" }] }).length === 0,
  "malformed inbox risk identity fails closed",
);
check(riskIndexRowsFromApi(undefined).length === 0, "empty risk index returns no risk rows");
check(riskIndexRowsFromApi({ items: "malformed" }, "malformed").length === 0, "malformed risk index items fail closed");
check(
  riskIndexRowsFromApi({ items: [{ risk_instance_id: 42, risk_key: "risk-42" }] }).length === 0,
  "malformed risk index identity fails closed",
);
check(riskIndexRowsFromApi({ items: [] }, undefined).length === 0, "missing inbox rows are accepted");

check(demoRiskRows.length === 5, "demo risk fixtures require explicit import");
check(demoSubjects.length === 2, "demo subject fixtures require explicit import");
check(
  !("demoRiskRows" in await import("./medicalMonitoringModels.mjs")),
  "production model module does not export demo fallback",
);
check(
  !("demoSubjects" in await import("./medicalMonitoringModels.mjs")),
  "production model module does not import or expose demo subjects",
);

console.log(`medicalMonitoringModels: ${passed} passed`);
