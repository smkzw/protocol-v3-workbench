import assert from "node:assert/strict";
import {
  metricConfigurationCandidateSource,
  metricConfigurationCandidateDisplayKey,
  metricConfigurationContext,
  metricConfigurationContextFromMonitoring,
  metricConfigurationDirectionLabel,
  metricConfigurationReviewState,
} from "./medicalMonitoringMetricConfiguration.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

const context = metricConfigurationContext({
  projectId: "proj-1",
  protocolVersionId: "protocol-1",
  batchId: "batch-1",
});
check(context.ready === true, "accepts a complete explicit candidate context");
check(context.missing.length === 0, "complete context has no missing identifiers");

const bindingContext = metricConfigurationContextFromMonitoring({
  projectId: "proj-1",
  routeState: { batch_id: "batch-route", protocol_version_id: "protocol-route" },
  binding: {
    batch_id: "batch-binding",
    protocol_version_id: "protocol-binding",
    display_batch: { batch_label: "do not use this label as an id" },
  },
});
check(bindingContext.batchId === "batch-route", "route batch id wins over binding fallback");
check(bindingContext.protocolVersionId === "protocol-route", "route protocol id wins over binding fallback");

const unbound = metricConfigurationReviewState({
  context: metricConfigurationContext({ projectId: "proj-1" }),
});
check(unbound.status === "context_unavailable", "unbound context is explicit");
check(unbound.message.includes("不把空态解释为无风险"), "unbound context keeps the no-risk boundary");

const loading = metricConfigurationReviewState({ context, loading: true });
check(loading.status === "loading", "loading state is explicit");

const payload = {
  status: "candidate_only",
  bundle_sha256: "a".repeat(64),
  medically_confirmed: false,
  usable_candidate_count: 1,
  candidates: [
    {
      candidate_id: "candidate-1",
      metric_key: "m1",
      metric_label: "MG-ADL",
      metric_kind: "efficacy",
      unit: "分",
      direction: "lower_is_better",
      field_profile_batch_id: "batch-1",
      fact_source_locator: "protocol.pdf:p12",
      review_flags: [],
    },
  ],
  issues: [{ code: "listing_field_sparse", subject: "m2", detail: "字段值稀疏" }],
  review: {
    candidate_only: true,
    requires_medical_confirmation: true,
  },
};
const review = metricConfigurationReviewState({ context, payload });
check(review.status === "candidate_only", "candidate-only payload remains review-only");
check(review.medicallyConfirmed === false, "candidate response cannot imply medical confirmation");
check(review.candidates.length === 1 && review.issues.length === 1, "preserves candidates and issues separately");
check(review.usableCandidateCount === 1, "preserves usable candidate count");
check(metricConfigurationCandidateSource(review.candidates[0]) === "protocol.pdf:p12 · batch-1", "shows source locator and profile batch");
check(metricConfigurationDirectionLabel("lower_is_better") === "越低越好", "maps known metric direction");
check(metricConfigurationDirectionLabel("unknown") === "方向待医学确认", "does not invent unknown direction");

const ambiguousReview = metricConfigurationReviewState({
  context,
  payload: {
    ...payload,
    candidates: [
      { candidate_id: "duplicate-candidate", metric_key: "m-1" },
      { candidate_id: "duplicate-candidate", metric_key: "m-2" },
      { metric_label: "缺少身份的指标" },
    ],
  },
});
check(
  ambiguousReview.candidates[0].identityState === "duplicate"
    && ambiguousReview.candidates[1].identityState === "duplicate"
    && ambiguousReview.candidates[2].identityState === "missing",
  "marks duplicate and missing metric candidate identities without dropping candidates",
);
check(
  metricConfigurationCandidateDisplayKey(ambiguousReview.candidates[0], 0)
    !== metricConfigurationCandidateDisplayKey(ambiguousReview.candidates[1], 1),
  "uses source-index display keys for duplicate metric candidates",
);

const confirmedPayload = metricConfigurationReviewState({
  context,
  payload: { ...payload, medically_confirmed: true },
});
check(confirmedPayload.status === "contract_error", "unexpected confirmed payload fails closed");

const failed = metricConfigurationReviewState({
  context,
  error: new Error("候选读取失败"),
});
check(failed.status === "read_error" && failed.message === "候选读取失败", "preserves read error state");

console.log(`medicalMonitoringMetricConfiguration: ${passed} checks passed`);
