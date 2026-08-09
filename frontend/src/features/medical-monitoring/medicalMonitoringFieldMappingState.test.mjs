import assert from "node:assert/strict";

import {
  semanticQualityPresentation,
} from "./medicalMonitoringFieldMappingState.mjs";

const blocked = semanticQualityPresentation({
  status: "blocked",
  activation_disposition: "reject",
  global_blocker_count: 2,
  finding_groups: [
    { severity: "global_blocker", title_zh: "字段映射覆盖不完整" },
    { severity: "global_blocker", title_zh: "用药角色边界冲突" },
  ],
});
assert.deepEqual(blocked, {
  level: "blocked",
  title: "存在 2 个全局阻断，当前不能确认",
  detail: "字段映射覆盖不完整 · 用药角色边界冲突",
  blocksConfirmation: true,
});

const restricted = semanticQualityPresentation({
  status: "pass_with_warnings",
  activation_disposition: "activate_restricted",
  capability_blocker_count: 2,
  capability_states: [
    { capability_id: "raw_source_review", state: "ready" },
    { capability_id: "subject_timeline", state: "limited" },
    { capability_id: "lab_ctcae_rules", state: "blocked_by_quality" },
    { capability_id: "scale_recalculation", state: "limited" },
    { capability_id: "patient_profile", state: "limited" },
  ],
});
assert.deepEqual(restricted, {
  level: "restricted",
  title: "可启用，但以下分析将受限",
  detail: "受试者时间线 · 实验室异常与 CTCAE 分级 · 量表复算",
  blocksConfirmation: false,
});

const restrictedWithTopicFallback = semanticQualityPresentation({
  status: "pass_with_warnings",
  activation_disposition: "activate_restricted",
  finding_groups: [
    {
      severity: "capability_blocker",
      title_zh: "日期精度不足以支持精确时间规则",
      affected_capability_ids: ["future_capability_not_yet_labelled"],
    },
  ],
});
assert.equal(
  restrictedWithTopicFallback.detail,
  "日期精度不足以支持精确时间规则",
);
assert.equal(restrictedWithTopicFallback.blocksConfirmation, false);

const fullWithWarnings = semanticQualityPresentation({
  status: "pass_with_warnings",
  activation_disposition: "activate_full",
  warning_count: 1,
  finding_groups: [
    { severity: "review_warning", title_zh: "建议复核低置信度字段" },
  ],
});
assert.deepEqual(fullWithWarnings, {
  level: "warning",
  title: "字段映射可完整启用",
  detail: "建议核对：建议复核低置信度字段",
  blocksConfirmation: false,
});

const passed = semanticQualityPresentation({
  status: "passed",
  activation_disposition: "activate_full",
});
assert.deepEqual(passed, {
  level: "ready",
  title: "字段语义校验完全通过",
  detail: "全部已登记分析能力可用",
  blocksConfirmation: false,
});

const legacyRestricted = semanticQualityPresentation({
  status: "pass_with_warnings",
  capability_blocker_count: 1,
  finding_groups: [
    {
      severity: "capability_blocker",
      title_zh: "量表复算血缘不完整",
      affected_capability_ids: ["scale_recalculation"],
    },
  ],
});
assert.equal(legacyRestricted.level, "restricted");
assert.equal(legacyRestricted.detail, "量表复算");
assert.equal(legacyRestricted.blocksConfirmation, false);

const malformedCount = semanticQualityPresentation({
  status: "blocked",
  global_blocker_count: "2",
  finding_groups: [],
  capability_states: [],
});
assert.equal(malformedCount.level, "blocked");
assert.equal(malformedCount.blocksConfirmation, true);
assert.match(malformedCount.title, /形状异常/);

const malformedGroups = semanticQualityPresentation({
  status: "pass_with_warnings",
  finding_groups: "not-an-array",
});
assert.equal(malformedGroups.level, "blocked");
assert.equal(malformedGroups.blocksConfirmation, true);

console.log("medicalMonitoringFieldMappingState: 8 passed");
