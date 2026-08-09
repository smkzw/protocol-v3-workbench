import assert from "node:assert/strict";
import {
  dateAtStudyDay,
  eventCategoryClassName,
  eventTone,
  hasActualTimelineDate,
  laneForEvent,
  metricRiskCount,
  metricDataCoverage,
  metricDisplayRows,
  monitoringStatusClass,
  normalizeMonitoringSubjectProfile,
  plannedVisitAxis,
  profileDomainCoverage,
  profileMetricEmptyStateMessage,
  profileSubjectMeta,
  referenceEventTooltip,
  referenceRiskCards,
  referenceTimelineLanes,
  relatedTimelineEvents,
  riskPromptDisplayKey,
  riskPromptDisplayRows,
  riskPromptEvidenceSummary,
  shortTimelineEventLabel,
  subjectCenterGroups,
  subjectCatalogDisplayRows,
  subjectCatalogSubjectId,
  subjectEvidenceLineageSummary,
  subjectSourceLocator,
  subjectSourceLocatorState,
  timelineHeaderMeta,
  timelineDataCoverage,
  timelineEventCategoryKey,
  timelineEventCategoryLabel,
  timelineEventSelectionKey,
  timelineLaneClassName,
  timelineLegendItems,
  timelineLegendLabel,
  timelineVisitDisplayRows,
  trendPointDisplayRows,
  visitAxisFromEvents,
} from "./medicalMonitoringSubjectModels.mjs";

const events = [
  {
    event_id: "visit_scr",
    event_type: "visit",
    visit_code: "SCR",
    visit_label: "筛选",
    study_day: -7,
    event_date: "2026-06-24",
    title: "筛选访视",
  },
  {
    event_id: "visit_d1",
    event_type: "visit",
    visit_code: "D1",
    visit_label: "随机/给药",
    study_day: 1,
    event_date: "2026-07-02",
    title: "随机/给药",
  },
  {
    event_id: "ip_pause",
    event_type: "dose_adjustment",
    source_domain: "DA",
    source_record_id: "DA-1",
    visit_code: "W1",
    study_day: 8,
    title: "试验药物暂停用药",
    detail: "因不良事件暂停试验药物",
    clinical_interpretation: "独立于CM记录",
  },
  {
    event_id: "ip_resume",
    event_type: "dose_adjustment",
    source_domain: "DA",
    visit_code: "W2",
    study_day: 15,
    title: "试验药物重新用药",
    detail: "恢复原剂量",
  },
  {
    event_id: "cm_1",
    event_type: "concomitant_medication",
    source_domain: "CM",
    visit_code: "SCR",
    study_day: -3,
    title: "氯雷他定",
    detail: "筛选期使用禁用药，洗脱不足",
    related_risk_ids: ["risk_cm"],
  },
  {
    event_id: "ae_1",
    event_type: "adverse_event",
    source_domain: "AE",
    visit_code: "W1",
    study_day: 8,
    title: "头痛",
    detail: "轻度头痛",
  },
  {
    event_id: "ae_review",
    event_type: "adverse_event",
    source_domain: "AE",
    visit_code: "W2",
    study_day: 15,
    title: "AE关系需医学复核",
    detail: "与试验药物关系待确认",
    related_risk_ids: ["risk_ae"],
  },
  {
    event_id: "mh_1",
    event_type: "medical_history",
    source_domain: "MH",
    visit_code: "SCR",
    study_day: -7,
    title: "既往史",
    detail: "病史记录",
  },
  {
    event_id: "lab_1",
    event_type: "lab",
    source_domain: "LBHEMA",
    visit_code: "W1",
    study_day: 8,
    title: "ANC降低",
    detail: "1.48*10^9/L",
    clinical_interpretation: "低于参考范围",
  },
  {
    event_id: "pd_1",
    event_type: "protocol_deviation",
    source_domain: "PD",
    visit_code: "W1",
    study_day: 8,
    title: "访视时间窗偏离",
    detail: "超窗",
  },
  {
    event_id: "query_1",
    event_type: "query",
    source_domain: "Query",
    visit_code: "W1",
    study_day: 8,
    title: "补充说明",
    detail: "待中心回复",
  },
];

assert.equal(laneForEvent(events[2]), "IP");
assert.equal(laneForEvent(events[4]), "CM");
assert.notEqual(laneForEvent(events[2]), laneForEvent(events[4]));
assert.equal(timelineEventCategoryKey(events[2]), "dose_adjustment_paused");
assert.equal(timelineEventCategoryKey(events[3]), "dose_adjustment_resumed");
assert.equal(timelineEventCategoryKey(events[4]), "concomitant_medication_risk");
assert.equal(timelineEventCategoryKey(events[5]), "adverse_event");
assert.equal(timelineEventCategoryKey(events[6]), "adverse_event_review");
assert.equal(timelineEventCategoryKey(events[8]), "lab_hematology");
assert.equal(timelineEventCategoryLabel(events[2]), "试验药物暂停");
assert.equal(timelineEventCategoryLabel(events[4]), "禁限用药/洗脱风险");
assert.equal(eventCategoryClassName(events[2]), "event-category-dose-adjustment-paused");
assert.equal(eventCategoryClassName(events[4]), "event-category-concomitant-medication-risk");
assert.notEqual(eventCategoryClassName(events[2]), eventCategoryClassName(events[4]));
assert.equal(eventTone(events[4]), "critical");
assert.equal(eventTone(events[8]), "warning");
assert.equal(eventTone(events[7]), "source");
assert.equal(timelineLaneClassName("PD_QUERY"), "lane-pd-query");
assert.equal(shortTimelineEventLabel(events[2], 0), "DA1");
assert.equal(shortTimelineEventLabel(events[4], 0), "CM1");

const lanes = referenceTimelineLanes(events.filter((event) => event.event_type !== "visit"));
assert.deepEqual(lanes.slice(0, 4).map((lane) => lane.key), ["AE", "IP", "CM", "MH"]);
assert.equal(lanes.find((lane) => lane.key === "IP").events.length, 2);
assert.equal(lanes.find((lane) => lane.key === "CM").events.length, 1);
assert.equal(lanes.find((lane) => lane.key === "LAB").events.length, 1);
assert.equal(lanes.find((lane) => lane.key === "PD_QUERY").events.length, 2);
assert.equal(lanes.find((lane) => lane.key === "IP").events[0].selectionKey, "event:ip_pause");

const duplicateAndMissingIdentityLanes = referenceTimelineLanes([
  { event_type: "adverse_event", event_date: "2026-07-01", source_locator: "listing:AE:row:1", title: "A" },
  { event_type: "adverse_event", event_date: "2026-07-02", source_locator: "listing:AE:row:1", title: "B" },
  { event_type: "adverse_event", event_date: "2026-07-03", title: "C" },
]);
const duplicateAndMissingKeys = duplicateAndMissingIdentityLanes.find((lane) => lane.key === "AE").events.map((item) => item.selectionKey);
assert.equal(new Set(duplicateAndMissingKeys).size, 3);
assert.match(duplicateAndMissingKeys[0], /^source-locator:/);
assert.match(duplicateAndMissingKeys[1], /^source-locator:.*#2$/);
assert.match(duplicateAndMissingKeys[2], /^fallback:AE:/);
assert.equal(timelineEventSelectionKey({ source_record_id: "row-1" }), "source-record:row-1");

const legend = timelineLegendItems(lanes);
assert.equal(legend.some((item) => item.className === "event-category-dose-adjustment-paused"), true);
assert.equal(legend.some((item) => item.className === "event-category-concomitant-medication-risk"), true);
assert.equal(
  timelineLegendLabel({ laneLabel: "合并用药（非试验用药）", label: "CM非试验用药" }),
  "合并用药（非试验用药）",
);

assert.deepEqual(visitAxisFromEvents(events).map((visit) => visit.code), ["SCR", "D1"]);
const visitIdentityRows = timelineVisitDisplayRows([
  { anchorId: "visit-1", code: "V1", date: "2026-07-01" },
  { anchorId: "visit-1", code: "V1-repeat", date: "2026-07-02" },
  { code: "V2", date: "2026-07-03" },
  { anchorId: "visit-2", code: "V3", date: "2026-07-04" },
]);
assert.deepEqual(visitIdentityRows.map((row) => row.displayIdentityState), ["duplicate", "duplicate", "missing", "ready"]);
assert.equal(new Set(visitIdentityRows.map((row) => row.displayKey)).size, visitIdentityRows.length);
assert.match(visitIdentityRows[2].displayIdentityIssue, /缺少 anchor_id/);
assert.equal(visitIdentityRows[0].visit.code, "V1");
assert.equal(dateAtStudyDay("2026-07-02", 8), "2026-07-09");
assert.equal(dateAtStudyDay("2026-07-02", -7), "2026-06-24");
assert.equal(dateAtStudyDay("", 8), "");
assert.equal(dateAtStudyDay("2026-02-31", 8), "");
assert.equal(hasActualTimelineDate("2026-02-28"), true);
assert.equal(hasActualTimelineDate("2026-02-29"), false);
assert.equal(hasActualTimelineDate("2026-02"), false);
assert.equal(hasActualTimelineDate("2026-07-02"), true);
assert.equal(hasActualTimelineDate("2026-99-02"), false);

const dateBoundCoverage = timelineDataCoverage(
  [{ date: "2026-06-24" }, { date: "2026-07-02" }],
  [{ event_date: "2026-07-09" }],
);
assert.deepEqual(dateBoundCoverage, {
  totalVisits: 2,
  datedVisits: 2,
  undatedVisits: 0,
  invalidVisitDates: 0,
  totalEvents: 1,
  datedEvents: 1,
  undatedEvents: 0,
  invalidEventDates: 0,
  hasDateAxis: true,
  status: "date_bound",
});
const partialDateCoverage = timelineDataCoverage(
  [{ date: "", plannedDay: 14 }, { date: "2026-07-02" }],
  [{ event_date: "2026-07-09" }, { event_date: "2026-02-29", study_day: 21 }],
);
assert.equal(partialDateCoverage.hasDateAxis, true);
assert.equal(partialDateCoverage.status, "partial_dates");
assert.equal(partialDateCoverage.undatedVisits, 1);
assert.equal(partialDateCoverage.undatedEvents, 1);
assert.equal(partialDateCoverage.invalidEventDates, 1);
const noDateAxisCoverage = timelineDataCoverage(
  [{ date: "", plannedDay: 14 }],
  [{ event_date: "2014", date_precision: "year" }],
);
assert.equal(noDateAxisCoverage.hasDateAxis, false);
assert.equal(noDateAxisCoverage.status, "no_actual_dates");
assert.equal(noDateAxisCoverage.invalidEventDates, 1);

const subject = {
  id: "10008",
  site: "10",
  rawProfile: {
    visit_anchors: [
      {
        anchor_id: "anchor_scr",
        visit_code: "SCR",
        visit_label: "筛选",
        actual_study_day: -7,
        actual_date: "2026-06-24",
        is_unscheduled: false,
      },
      {
        anchor_id: "anchor_d1",
        visit_code: "D1",
        visit_label: "随机/给药",
        planned_study_day: 1,
        actual_study_day: 1,
        actual_date: "2026-07-02",
        is_unscheduled: false,
      },
      {
        anchor_id: "anchor_uns",
        visit_code: "UNS",
        visit_label: "计划外访视",
        actual_study_day: 8,
        actual_date: "2026-07-09",
        is_unscheduled: true,
      },
    ],
    subject: {
      site_id: "10",
      screening_number: "SCR-10008",
      randomization_number: "R-10008",
      treatment_arm: "试验组",
      enrollment_status: "治疗期",
      baseline_visit_date: "2026-07-02",
      first_dose_date: "2026-07-02",
      latest_visit_code: "W2",
      latest_visit_label: "第2周",
      latest_visit_date: "2026-07-16",
    },
    timeline: events,
    risk_prompts: [
      {
        prompt_id: "prompt_washout",
        risk_type: "washout",
        prompt_text: "洗脱期不足",
        recommended_action: "核对合并用药",
      },
      {
        prompt_id: "prompt_ae",
        risk_type: "ae_lab",
        prompt_text: "AE与实验室联合复核",
        status: "open",
      },
    ],
  },
};

const plannedVisits = plannedVisitAxis(subject, events);
assert.equal(plannedVisits[0].code, "SCR");
assert.equal(plannedVisits[1].code, "D1");
assert.equal(plannedVisits[2].date, "2026-07-09");
assert.equal(plannedVisits.at(-1).code, "UNS");
assert.equal(plannedVisits.at(-1).isUnscheduled, true);

const riskCards = referenceRiskCards(subject);
assert.equal(riskCards.length, 3);
assert.equal(riskCards[0].title, "潜在合并用药违背");
assert.equal(riskCards[1].body, "超窗");
assert.equal(riskCards[2].body.includes("AE关系需医学复核"), false);
assert.match(riskCards[2].body, /头痛/);
assert.match(riskCards[2].body, /轻度头痛/);
assert.match(riskCards[2].body, /AE与实验室联合复核/);
assert.equal(riskCards[2].body.includes("ANC降低"), false);
assert.equal(riskCards[2].body.includes("说明书\/IB"), false);
assert.equal(riskCards[2].body.includes("感染\/实验室风险"), false);

const promptDisplayRows = riskPromptDisplayRows([
  { prompt_id: "prompt-duplicate", title: "重复提示 A" },
  { prompt_id: "prompt-duplicate", title: "重复提示 B" },
  { title: "缺少身份提示" },
]);
assert.equal(promptDisplayRows.length, 3);
assert.deepEqual(promptDisplayRows.map((prompt) => prompt.displayIdentityState), ["duplicate", "duplicate", "missing"]);
assert.equal(new Set(promptDisplayRows.map((prompt) => prompt.displayKey)).size, 3);
assert.equal(riskPromptDisplayKey(promptDisplayRows[1], 99), promptDisplayRows[1].displayKey);
assert.match(promptDisplayRows[0].displayIdentityIssue, /prompt_id 重复/);
assert.match(promptDisplayRows[2].displayIdentityIssue, /缺少 prompt_id/);

const suppliedSafetyBasisSubject = {
  ...subject,
  rawProfile: {
    ...subject.rawProfile,
    timeline: subject.rawProfile.timeline.map((event) => (
      event.event_id === "ae_1"
        ? { ...event, safety_reference: "IB 2.1：已提供的安全性依据", source_locator: "AE:row:6" }
        : event
    )),
  },
};
const suppliedSafetyBasisCard = referenceRiskCards(suppliedSafetyBasisSubject)[2].body;
assert.match(suppliedSafetyBasisCard, /安全性依据：IB 2\.1：已提供的安全性依据/);
assert.match(suppliedSafetyBasisCard, /AE来源：AE:row:6/);

const linkedLabSubject = {
  ...subject,
  rawProfile: {
    ...subject.rawProfile,
    timeline: subject.rawProfile.timeline.map((event) => (
      event.event_id === "lab_1"
        ? { ...event, related_event_ids: ["ae_1"], source_locator: "LB:row:8" }
        : event
    )),
  },
};
const linkedLabCard = referenceRiskCards(linkedLabSubject)[2].body;
assert.match(linkedLabCard, /关联实验室：ANC降低/);
assert.match(linkedLabCard, /实验室来源：LB:row:8/);

const malformedLinkedLabSubject = {
  ...subject,
  rawProfile: {
    ...subject.rawProfile,
    timeline: subject.rawProfile.timeline.map((event) => (
      event.event_id === "ae_1"
        ? { ...event, event_id: 42 }
        : event.event_id === "lab_1"
          ? { ...event, related_event_ids: [42], source_locator: "LB:row:9" }
          : event
    )),
  },
};
const malformedLinkedLabCard = referenceRiskCards(malformedLinkedLabSubject)[2].body;
assert.equal(malformedLinkedLabCard.includes("关联实验室：ANC降低"), false);
assert.match(malformedLinkedLabCard, /关联实验室未自动合并/);
assert.match(malformedLinkedLabCard, /形状异常/);
assert.match(malformedLinkedLabCard, /不能据此判定无风险/);

const sparseRiskSubject = {
  rawProfile: {
    timeline: [{ event_type: "concomitant_medication", source_domain: "CM" }],
    risk_prompts: [],
  },
};
assert.doesNotThrow(() => referenceRiskCards(sparseRiskSubject));
assert.match(referenceRiskCards(sparseRiskSubject)[0].body, /CM事件/);

const noRiskEvidenceSubject = { rawProfile: { timeline: [], risk_prompts: [] } };
const noRiskEvidenceCards = referenceRiskCards(noRiskEvidenceSubject);
assert.match(noRiskEvidenceCards[0].body, /未提供合并用药证据/);
assert.match(noRiskEvidenceCards[1].body, /未提供可用于入排违背判断的 PD\/病史证据/);
assert.equal(noRiskEvidenceCards[1].body.includes("当前规则"), false);

const boundLineage = subjectEvidenceLineageSummary({
  rawProfile: {
    source_revision: "monsrcv_subject_001",
    timeline: [{ source_locator: "listing:AE:row:4" }],
    efficacy_trends: [{ points: [{ source_record_id: "listing:QS:row:7" }] }],
    safety_trends: [],
    risk_prompts: [{ evidence_span_ids: ["listing:AE:row:4"] }],
  },
});
assert.equal(boundLineage.status, "bound");
assert.equal(boundLineage.totalRecords, 3);
assert.equal(boundLineage.tracedRecords, 3);
assert.equal(boundLineage.untracedRecords, 0);
assert.match(boundLineage.message, /monsrcv_subject_001/);

const partialLineage = subjectEvidenceLineageSummary({
  rawProfile: {
    source_revision: "monsrcv_subject_002",
    timeline: [{ source_locator: "listing:AE:row:4" }, { title: "无定位事件" }],
    efficacy_trends: [{ points: [{ value: 1, assessment_date: "2026-07-01" }] }],
    risk_prompts: [],
  },
});
assert.equal(partialLineage.status, "partial");
assert.equal(partialLineage.totalRecords, 3);
assert.equal(partialLineage.tracedRecords, 1);
assert.equal(partialLineage.untracedRecords, 2);
assert.match(partialLineage.message, /不能据此证明完整性/);

const malformedLocatorLineage = subjectEvidenceLineageSummary({
  rawProfile: {
    source_revision: "monsrcv_subject_003",
    timeline: [{ source_locators: ["listing:AE:row:4", 17] }],
    efficacy_trends: [],
    safety_trends: [],
    risk_prompts: [],
  },
});
assert.equal(malformedLocatorLineage.status, "partial");
assert.equal(malformedLocatorLineage.label, "来源定位需核对");
assert.equal(malformedLocatorLineage.tracedRecords, 0);
assert.equal(malformedLocatorLineage.malformedLocatorRecords, 1);
assert.match(malformedLocatorLineage.message, /形状异常/);

const malformedLineageToken = subjectEvidenceLineageSummary({
  rawProfile: {
    source_revision: 42,
    source_batch_id: "batch-005",
    timeline: [{ source_locator: "listing:AE:row:9" }],
    efficacy_trends: [],
    safety_trends: [],
    risk_prompts: [],
  },
});
assert.equal(malformedLineageToken.status, "partial");
assert.equal(malformedLineageToken.label, "来源绑定形状异常");
assert.equal(malformedLineageToken.sourceRevision, "");
assert.equal(malformedLineageToken.sourceBatch, "batch-005");
assert.equal(malformedLineageToken.malformedLineageFields, 1);
assert.match(malformedLineageToken.message, /来源修订\/批次字段有 1 项形状异常/);

const batchOnlyLineage = subjectEvidenceLineageSummary({
  rawProfile: { source_batch_id: "batch-004", timeline: [], efficacy_trends: [], safety_trends: [], risk_prompts: [] },
});
assert.equal(batchOnlyLineage.status, "partial");
assert.equal(batchOnlyLineage.label, "仅有批次标识");
assert.match(batchOnlyLineage.message, /source_revision\/source_version/);

const unboundLineage = subjectEvidenceLineageSummary({
  rawProfile: { timeline: [{ source_record_id: "listing:AE:row:4" }], risk_prompts: [] },
});
assert.equal(unboundLineage.status, "unbound");
assert.equal(unboundLineage.tracedRecords, 1);
assert.match(unboundLineage.message, /原始 listing/);

const legacyLineage = subjectEvidenceLineageSummary({
  rawProfile: { source_revision: "legacy", timeline: [], risk_prompts: [] },
});
assert.equal(legacyLineage.status, "unbound");
assert.equal(legacyLineage.sourceRevision, "");

assert.equal(subjectEvidenceLineageSummary({}).status, "empty");
assert.equal(subjectSourceLocator({ title: "仅有标题", event_date: "2026-07-01" }), "");
assert.equal(subjectSourceLocator({ source_locators: ["listing:AE:row:4", "listing:LB:row:2"] }), "listing:AE:row:4、listing:LB:row:2");
assert.equal(subjectSourceLocator({ evidence_span_ids: ["span:1"] }), "span:1");
const malformedLocator = subjectSourceLocatorState({ source_locators: ["listing:AE:row:4", 17, ""] });
assert.equal(malformedLocator.status, "malformed");
assert.equal(malformedLocator.label, "来源定位形状异常");
assert.equal(malformedLocator.locator, "listing:AE:row:4");
assert.match(malformedLocator.message, /不能据此证明来源真实性/);
assert.equal(subjectSourceLocator({ source_locators: ["listing:AE:row:4", 17] }), "listing:AE:row:4");
const linkedRiskEvidence = riskPromptEvidenceSummary({
  related_event_ids: ["ae-1", "ae-1"],
  related_metric_keys: ["anc"],
  related_risk_ids: ["risk-ae"],
  evidence_span_ids: ["listing:AE:row:4"],
});
assert.deepEqual(linkedRiskEvidence.eventIds, ["ae-1"]);
assert.deepEqual(linkedRiskEvidence.metricKeys, ["anc"]);
assert.deepEqual(linkedRiskEvidence.riskIds, ["risk-ae"]);
assert.equal(linkedRiskEvidence.label, "关联事件 1 · 指标 1 · 证据 1");
assert.match(linkedRiskEvidence.message, /医学判断/);
const unlinkedRiskEvidence = riskPromptEvidenceSummary({ title: "只有提示文字" });
assert.equal(unlinkedRiskEvidence.label, "未绑定关联事实");
assert.match(unlinkedRiskEvidence.message, /不能据此判定无风险/);
const malformedRiskEvidence = riskPromptEvidenceSummary({
  title: "关联字段形状异常",
  related_event_ids: "ae-1",
  related_metric_keys: ["anc", 2],
  evidence_span_ids: ["listing:AE:row:4"],
});
assert.equal(malformedRiskEvidence.shapeStatus, "malformed");
assert.equal(malformedRiskEvidence.label, "关联证据形状异常");
assert.deepEqual(malformedRiskEvidence.eventIds, ["ae-1"]);
assert.deepEqual(malformedRiskEvidence.metricKeys, ["anc"]);
assert.match(malformedRiskEvidence.message, /形状异常/);

const malformedProfile = normalizeMonitoringSubjectProfile({
  subject: { key_medical_context: "not-an-array" },
  timeline: [{ event_type: "lab", related_risk_ids: "risk-scalar", is_unscheduled: "false" }],
  efficacy_trends: [{ metric_label: "疗效", points: [{ related_risk_ids: "risk-scalar", risk_flag: "false" }] }, "not-a-metric"],
  safety_trends: null,
  risk_prompts: false,
  review_focus: ["保留此提示", false],
  domain_availability: { status: "available" },
  capability_mode: "not-a-mode",
  capability_states: [],
  capability_limitations: { subject_timeline: ["mapping_pending", false] },
});
assert.deepEqual(malformedProfile.timeline[0].related_risk_ids, []);
assert.equal(malformedProfile.timeline[0].is_unscheduled, undefined);
assert.deepEqual(malformedProfile.safety_trends, []);
assert.deepEqual(malformedProfile.efficacy_trends[0].points[0].related_risk_ids, []);
assert.equal(malformedProfile.efficacy_trends[0].points[0].risk_flag, undefined);
assert.deepEqual(malformedProfile.review_focus, ["保留此提示"]);
assert.ok(malformedProfile.profile_shape_warnings.includes("timeline[0].related_risk_ids"));
assert.ok(malformedProfile.profile_shape_warnings.includes("subject.key_medical_context"));
assert.ok(malformedProfile.profile_shape_warnings.includes("risk_prompts"));
assert.equal(malformedProfile.capability_mode, "restricted");
assert.deepEqual(malformedProfile.capability_limitations.subject_timeline, ["mapping_pending"]);
assert.ok(malformedProfile.profile_shape_warnings.includes("capability_mode"));
assert.ok(malformedProfile.profile_shape_warnings.includes("capability_states"));
assert.doesNotThrow(() => normalizeMonitoringSubjectProfile("malformed-profile"));
assert.equal(normalizeMonitoringSubjectProfile("malformed-profile"), null);

const sparseProfile = normalizeMonitoringSubjectProfile({ subject: { subject_id: "sparse-001" } });
assert.deepEqual(sparseProfile.timeline, []);
assert.deepEqual(sparseProfile.efficacy_trends, []);
assert.deepEqual(sparseProfile.safety_trends, []);
assert.deepEqual(sparseProfile.risk_prompts, []);
assert.deepEqual(sparseProfile.review_focus, []);
assert.deepEqual(sparseProfile.domain_availability, []);
assert.deepEqual(sparseProfile.capability_limitations, {});
assert.equal(sparseProfile.subject.subject_id, "sparse-001");
assert.deepEqual(sparseProfile.profile_shape_warnings, []);

const timelineMeta = timelineHeaderMeta(subject, events);
assert.equal(timelineMeta.center, "中心 10");
assert.equal(timelineMeta.window, "2026-06-24 ~ 2026-07-16");
assert.equal(timelineMeta.sexAgeStatus, "性别未提供 | 年龄未提供 | 治疗期");
assert.equal(timelineMeta.randomization, "R-10008");

const tooltip = referenceEventTooltip(events[2], "DA1");
assert.equal(tooltip.includes("DA1"), true);
assert.equal(tooltip.includes("独立于CM记录"), true);

const partialDateTooltip = referenceEventTooltip({
  event_date: "2014",
  raw_event_date: "2014-UK-UK",
  date_precision: "year",
  title: "既往史",
}, "MH1");
assert.equal(partialDateTooltip.includes("2014-UK-UK"), true);
assert.equal(partialDateTooltip.includes("日期精度：年"), true);
assert.equal(partialDateTooltip.includes("时间轴定位：2014"), true);

const groups = subjectCenterGroups([
  { id: "10002", site: "10" },
  { id: "06021", site: "06" },
  { id: "10001", site: "10" },
]);
assert.deepEqual(groups.map((group) => group.center), ["06", "10"]);
assert.deepEqual(groups[1].subjects.map((item) => item.id), ["10001", "10002"]);
assert.deepEqual(subjectCenterGroups([]), []);

const catalogRows = subjectCatalogDisplayRows([
  { id: "S-001", site: "01" },
  { id: "S-001", site: "02" },
  { subject_id: "S-002", site: "01" },
  { id: "", site: "03" },
]);
assert.equal(catalogRows[0].displayIdentityState, "duplicate");
assert.equal(catalogRows[1].displayIdentityState, "duplicate");
assert.equal(catalogRows[2].displayIdentityState, "ready");
assert.equal(subjectCatalogSubjectId(catalogRows[2]), "S-002");
assert.equal(catalogRows[3].displayIdentityState, "missing");
assert.match(catalogRows[3].displayIdentityIssue, /仅可读/);
assert.equal(new Set(catalogRows.map((row) => row.displayKey)).size, catalogRows.length);

const meta = profileSubjectMeta(subject);
assert.equal(meta.find((item) => item.label === "随机号").value, "R-10008");
assert.equal(meta.find((item) => item.label === "最近访视").value, "W2 / 第2周 / 2026-07-16");
assert.equal(metricRiskCount({ points: [{ risk_flag: true }, { normality: "low" }, { normality: "normal" }] }), 2);
assert.deepEqual(metricDataCoverage({ points: [
  { value: 1.2, assessment_date: "2026-07-01" },
  { value: "-", assessment_date: "2026-07-02" },
  { value: null, assessment_date: "2026-07-03" },
] }), {
  totalPoints: 3,
  numericPoints: 1,
  drawablePoints: 1,
  invalidValuePoints: 2,
  datedPoints: 3,
  undatedDatePoints: 0,
  hasDrawableValues: true,
  status: "partial_numeric_or_date",
});
assert.equal(metricDataCoverage({ points: [{ value: "未提供", assessment_date: "2026-07-01" }] }).status, "no_numeric_values");
assert.equal(metricDataCoverage({ points: [{ value: 1.2 }] }).status, "no_actual_dates");
assert.equal(metricDataCoverage({ points: [] }).status, "empty");
const metricIdentityRows = metricDisplayRows([
  { metric_key: "duplicate-metric", metric_label: "重复指标 A", points: [] },
  { metric_key: "duplicate-metric", metric_label: "重复指标 B", points: [] },
  { points: [] },
], "efficacy");
assert.equal(metricIdentityRows[0].displayIdentityState, "duplicate");
assert.equal(metricIdentityRows[1].displayIdentityState, "duplicate");
assert.equal(metricIdentityRows[2].displayIdentityState, "missing");
assert.notEqual(metricIdentityRows[0].displayKey, metricIdentityRows[1].displayKey);
assert.match(metricIdentityRows[2].displayIdentityIssue, /缺少 metric_key/);
const trendPointIdentityRows = trendPointDisplayRows([
  { point_id: "point-1", value: 1.1 },
  { point_id: "point-1", value: 1.2 },
  { value: 1.3 },
  { point_id: "point-2", value: 1.4 },
], "efficacy-metric");
assert.equal(trendPointIdentityRows[0].displayIdentityState, "duplicate");
assert.equal(trendPointIdentityRows[1].displayIdentityState, "duplicate");
assert.equal(trendPointIdentityRows[2].displayIdentityState, "missing");
assert.equal(trendPointIdentityRows[3].displayIdentityState, "ready");
assert.equal(new Set(trendPointIdentityRows.map((row) => row.displayKey)).size, trendPointIdentityRows.length);
assert.match(trendPointIdentityRows[2].displayIdentityIssue, /缺少 point_id/);
assert.equal(trendPointIdentityRows[0].point.value, 1.1);
assert.match(profileMetricEmptyStateMessage({ rawProfile: null, efficacyMetrics: [] }, "efficacy"), /尚未载入完整疗效趋势/);
assert.match(profileMetricEmptyStateMessage({ rawProfile: { capability_mode: "restricted" }, safetyMetrics: [] }, "safety"), /受限模式/);
assert.match(profileMetricEmptyStateMessage({ rawProfile: { domain_availability: [{ domain: "EFFICACY", status: "absent" }] }, efficacyMetrics: [] }, "efficacy"), /来源未提供/);
assert.match(profileMetricEmptyStateMessage({ rawProfile: { domain_availability: [{ domain: "laboratory", status: "available" }] }, safetyMetrics: [] }, "safety"), /未提供可用的安全性趋势/);
const explicitCoverage = profileDomainCoverage({
  domain_availability: [
    { domain: "adverse_event", label: "ignored label", status: "available", source_locator: "listing:AE:row:4" },
    { domain: "laboratory", status: "absent" },
    { domain: "efficacy", status: "unmapped" },
    { domain: "study_drug", status: "unsupported" },
    { domain: "custom_domain", label: "自定义域", status: "future-status" },
  ],
  efficacy_trends: [{ metric_key: "must-not-infer" }],
});
assert.equal(explicitCoverage.declarationState, "declared");
assert.equal(explicitCoverage.declaredCount, 5);
assert.equal(explicitCoverage.availableCount, 1);
assert.equal(explicitCoverage.domains[0].label, "AE");
assert.equal(explicitCoverage.domains[0].statusLabel, "已提供");
assert.equal(explicitCoverage.domains[0].sourceLocator, "listing:AE:row:4");
assert.equal(explicitCoverage.domains[1].statusLabel, "未见记录");
assert.equal(explicitCoverage.domains[2].statusLabel, "尚未映射");
assert.equal(explicitCoverage.domains[3].statusLabel, "当前不支持");
assert.equal(explicitCoverage.domains[4].status, "unknown");
assert.equal(explicitCoverage.domains[4].statusLabel, "状态待核对");
assert.match(explicitCoverage.disclaimer, /不代表该域无风险/);
const missingCoverage = profileDomainCoverage({ efficacy_trends: [{ metric_key: "must-not-infer" }] });
assert.equal(missingCoverage.declarationState, "missing");
assert.equal(missingCoverage.domains.length, 0);
assert.match(missingCoverage.declarationMessage, /未提供数据域覆盖声明/);
const emptyCoverage = profileDomainCoverage({ domain_availability: [] });
assert.equal(emptyCoverage.declarationState, "empty");
assert.match(emptyCoverage.declarationMessage, /空列表不代表/);
const malformedCoverage = profileDomainCoverage({ domain_availability: { status: "available" } });
assert.equal(malformedCoverage.declarationState, "malformed");
assert.equal(malformedCoverage.domains[0].status, "malformed");
const rowMalformedCoverage = profileDomainCoverage({ domain_availability: [{ domain: "AE" }, "bad-row"] });
assert.equal(rowMalformedCoverage.domains[0].status, "malformed");
assert.equal(rowMalformedCoverage.domains[1].status, "malformed");
const normalizedMalformedCoverage = profileDomainCoverage(malformedProfile);
assert.equal(normalizedMalformedCoverage.declarationState, "malformed");
assert.match(normalizedMalformedCoverage.declarationMessage, /形状异常/);
const mixedShapeCoverage = profileDomainCoverage({
  domain_availability: [{ domain: "adverse_event", status: "available" }],
  profile_shape_warnings: ["domain_availability[1]"],
});
assert.equal(mixedShapeCoverage.declarationState, "declared_with_shape_warning");
assert.equal(mixedShapeCoverage.domains.at(-1).status, "malformed");
assert.deepEqual(
  relatedTimelineEvents(events, ["protocol_deviation", "query"]).map((event) => event.event_id),
  ["pd_1", "query_1"],
);
assert.equal(monitoringStatusClass("高风险复核"), "danger");
assert.equal(monitoringStatusClass("high"), "warning");
assert.equal(monitoringStatusClass("已关闭"), "success");
assert.equal(monitoringStatusClass("待载入"), "info");

console.log("medicalMonitoringSubjectModels tests passed");
