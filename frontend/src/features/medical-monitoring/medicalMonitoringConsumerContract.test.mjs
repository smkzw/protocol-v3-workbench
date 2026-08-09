import assert from "node:assert/strict";
import {
  MedicalMonitoringConsumerContractError,
  buildMedicalMonitoringConsumerFixture,
} from "./medicalMonitoringConsumerContract.mjs";

const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);
const HASH_C = "c".repeat(64);

function event({ eventId, domain, subjectId, siteId, riskIds = [], evidenceId, locator }) {
  return {
    event_id: eventId,
    event_sha256: HASH_A,
    project_id: "project-demo",
    trial_id: "trial-demo",
    site_id: siteId,
    subject_id: subjectId,
    event_type: domain === "ae" ? "adverse_event" : "lab",
    source_domain: domain,
    title: domain === "ae" ? "AE记录" : "实验室",
    detail: domain === "ae" ? "AE source-bound detail" : "ALT source-bound detail",
    event_date: domain === "ae" ? "2026-04-12" : "2026-04",
    date_precision: domain === "ae" ? "day" : "month",
    raw_event_date: domain === "ae" ? "2026-04-12" : "2026-04",
    visit_label: domain === "ae" ? "Week 4" : "计划外访视",
    visit_number: domain === "ae" ? 4 : null,
    is_unscheduled: domain === "lab",
    related_risk_ids: riskIds,
    evidence_ids: [evidenceId],
    evidence_locators: [locator],
    rule_binding_ids: domain === "ae" ? ["rule-ae"] : [],
    completeness_status: "complete",
    uncertainty_state: "none",
  };
}

function point({ pointId, eventId, subjectId, siteId, domain, evidenceId, locator, riskIds = [] }) {
  return {
    point_id: pointId,
    event_id: eventId,
    event_sha256: HASH_A,
    subject_id: subjectId,
    site_id: siteId,
    domain,
    field_name: "VALUE",
    assessment_date: domain === "ae" ? "2026-04-12" : "2026-04",
    date_precision: domain === "ae" ? "day" : "month",
    visit_label: domain === "ae" ? "Week 4" : "计划外访视",
    visit_number: domain === "ae" ? 4 : null,
    value_status: "present",
    value: domain === "ae" ? "12.5" : "45",
    normalized_value: domain === "ae" ? "12.5" : "45",
    unit: domain === "ae" ? "grade" : "U/L",
    reference_range: domain === "lab" ? { high: "40" } : null,
    related_risk_ids: riskIds,
    evidence_ids: [evidenceId],
    evidence_locators: [locator],
    rule_binding_ids: domain === "ae" ? ["rule-ae"] : [],
    completeness_status: "complete",
    uncertainty_state: "none",
  };
}

function handoff() {
  return {
    project_id: "project-demo",
    trial_id: "trial-demo",
    scope_sha256: HASH_C,
    timeline: [
      event({
        eventId: "event-ae-001",
        domain: "ae",
        subjectId: "subject-001",
        siteId: "site-001",
        riskIds: ["risk-001"],
        evidenceId: "evidence-ae-001",
        locator: "listing:AE:row:1",
      }),
      event({
        eventId: "event-lab-002",
        domain: "lab",
        subjectId: "subject-002",
        siteId: "site-002",
        riskIds: ["risk-001"],
        evidenceId: "evidence-lab-002",
        locator: "listing:LAB:row:2",
      }),
    ],
    safety_metrics: [
      {
        metric_key: "ae:VALUE",
        domain: "ae",
        field_name: "VALUE",
        points: [point({
          pointId: "observation-ae-001",
          eventId: "event-ae-001",
          subjectId: "subject-001",
          siteId: "site-001",
          domain: "ae",
          evidenceId: "evidence-ae-001",
          locator: "listing:AE:row:1",
          riskIds: ["risk-001"],
        })],
      },
      {
        metric_key: "lab:VALUE",
        domain: "lab",
        field_name: "VALUE",
        points: [point({
          pointId: "observation-lab-002",
          eventId: "event-lab-002",
          subjectId: "subject-002",
          siteId: "site-002",
          domain: "lab",
          evidenceId: "evidence-lab-002",
          locator: "listing:LAB:row:2",
          riskIds: ["risk-001"],
        })],
      },
    ],
    risk_drilldown: [{
      risk_instance_id: "risk-001",
      event_ids: ["event-ae-001", "event-lab-002"],
      observation_ids: ["observation-ae-001", "observation-lab-002"],
      subject_ids: ["subject-001", "subject-002"],
      site_ids: ["site-001", "site-002"],
      evidence_ids: ["evidence-ae-001", "evidence-lab-002"],
      evidence_locators: ["listing:AE:row:1", "listing:LAB:row:2"],
      rule_binding_ids: ["rule-ae"],
    }],
    subjects: [
      {
        subject_id: "subject-001",
        site_id: "site-001",
        event_ids: ["event-ae-001"],
        observation_ids: ["observation-ae-001"],
        risk_instance_ids: ["risk-001"],
        timeline_event_ids: ["event-ae-001"],
        safety_metric_keys: ["ae:VALUE"],
      },
      {
        subject_id: "subject-002",
        site_id: "site-002",
        event_ids: ["event-lab-002"],
        observation_ids: ["observation-lab-002"],
        risk_instance_ids: ["risk-001"],
        timeline_event_ids: ["event-lab-002"],
        safety_metric_keys: ["lab:VALUE"],
      },
    ],
    site_rollups: [],
    project_rollup: {
      level: "project",
      identity: "project-demo",
      event_ids: ["event-ae-001", "event-lab-002"],
      observation_ids: ["observation-ae-001", "observation-lab-002"],
      risk_instance_ids: ["risk-001"],
      domain_counts: { ae: 1, lab: 1 },
      incomplete_event_count: 0,
      uncertain_event_count: 0,
    },
    limitations: [],
    handoff_sha256: HASH_B,
  };
}

const fixture = buildMedicalMonitoringConsumerFixture(handoff(), { expectedHandoffSha256: HASH_B });
assert.equal(fixture.contract_version, "medical_monitoring.consumer_fixture.v1");
assert.deepEqual(fixture.timeline.map((item) => item.source_domain), ["LB", "AE"]);
const aeTimeline = fixture.timeline.find((item) => item.event_id === "event-ae-001");
assert.equal(aeTimeline.event_type, "adverse_event");
assert.equal(aeTimeline.visit_code, "", "visit code remains unavailable, not guessed from label");
assert.deepEqual(fixture.safety_metrics.map((metric) => metric.metric_key), ["ae:VALUE", "lab:VALUE"]);
assert.equal(fixture.subjects[0].rawProfile.subject.site_id, "site-001");
assert.equal(fixture.subjects[0].rawProfile.safety_trends[0].points[0].raw_value, "12.5");
assert.equal(fixture.subjects[0].risks.length, 0, "risk severity/title is not invented from a link");
assert.equal(fixture.subjects[0].riskLinks[0].risk_instance_id, "risk-001");
assert.deepEqual(fixture.risk_links[0].evidence_locators, ["listing:AE:row:1", "listing:LAB:row:2"]);
assert.equal(fixture.rollup_conservation.project.status, "conserved");
assert.equal(fixture.rollup_conservation.sites.status, "missing", "empty site rollups are explicit, not no-center evidence");
assert.ok(fixture.limitations.includes("site_rollups_missing"));
assert.equal(fixture.rollup_conservation.subjects.status, "conserved");

const siteComplete = handoff();
siteComplete.site_rollups = [
  {
    level: "site",
    identity: "site-001",
    event_ids: ["event-ae-001"],
    observation_ids: ["observation-ae-001"],
    risk_instance_ids: ["risk-001"],
    domain_counts: { ae: 1 },
    incomplete_event_count: 0,
    uncertain_event_count: 0,
  },
  {
    level: "site",
    identity: "site-002",
    event_ids: ["event-lab-002"],
    observation_ids: ["observation-lab-002"],
    risk_instance_ids: ["risk-001"],
    domain_counts: { lab: 1 },
    incomplete_event_count: 0,
    uncertain_event_count: 0,
  },
];
const completeFixture = buildMedicalMonitoringConsumerFixture(siteComplete, { expectedHandoffSha256: HASH_B });
assert.equal(completeFixture.rollup_conservation.sites.status, "conserved");
assert.deepEqual(completeFixture.rollup_conservation.sites.providedSiteIds, ["site-001", "site-002"]);

const missingProjectObservation = handoff();
missingProjectObservation.project_rollup.observation_ids = [];
assert.throws(
  () => buildMedicalMonitoringConsumerFixture(missingProjectObservation, { expectedHandoffSha256: HASH_B }),
  /project rollup does not conserve normalized handoff ids/,
);

const mismatchedProjectIdentity = handoff();
mismatchedProjectIdentity.project_rollup.identity = "other-project";
assert.throws(
  () => buildMedicalMonitoringConsumerFixture(mismatchedProjectIdentity, { expectedHandoffSha256: HASH_B }),
  /project rollup identity does not match handoff project/,
);

const inconsistentSite = handoff();
inconsistentSite.site_rollups = [{
  level: "site",
  identity: "site-001",
  event_ids: ["event-ae-001"],
  observation_ids: [],
  risk_instance_ids: ["risk-001"],
  domain_counts: { ae: 1 },
  incomplete_event_count: 0,
  uncertain_event_count: 0,
}];
const inconsistentSiteFixture = buildMedicalMonitoringConsumerFixture(inconsistentSite, { expectedHandoffSha256: HASH_B });
assert.equal(inconsistentSiteFixture.rollup_conservation.sites.status, "not_conserved");
assert.equal(inconsistentSiteFixture.rollup_conservation.sites.rows[0].status, "not_conserved");

const inconsistentSiteCounts = handoff();
inconsistentSiteCounts.site_rollups = [{
  level: "site",
  identity: "site-001",
  event_ids: ["event-ae-001"],
  observation_ids: ["observation-ae-001"],
  risk_instance_ids: ["risk-001"],
  domain_counts: { ae: 2 },
  incomplete_event_count: 0,
  uncertain_event_count: 0,
}];
const inconsistentSiteCountsFixture = buildMedicalMonitoringConsumerFixture(inconsistentSiteCounts, { expectedHandoffSha256: HASH_B });
assert.ok(inconsistentSiteCountsFixture.rollup_conservation.sites.rows[0].countMismatches.includes("domain_counts"));

const invalidSiteLevel = handoff();
invalidSiteLevel.site_rollups = [{
  level: "project",
  identity: "site-001",
  event_ids: [],
  observation_ids: [],
  risk_instance_ids: [],
  domain_counts: {},
  incomplete_event_count: 0,
  uncertain_event_count: 0,
}];
assert.throws(
  () => buildMedicalMonitoringConsumerFixture(invalidSiteLevel, { expectedHandoffSha256: HASH_B }),
  /handoff\.site_rollups\.level must be site/,
);

assert.throws(
  () => buildMedicalMonitoringConsumerFixture(handoff(), { expectedHandoffSha256: HASH_A }),
  MedicalMonitoringConsumerContractError,
);

const tampered = handoff();
tampered.timeline[0].evidence_locators = ["listing:LAB:row:tampered"];
tampered.handoff_sha256 = HASH_A;
assert.throws(
  () => buildMedicalMonitoringConsumerFixture(tampered, { expectedHandoffSha256: HASH_B }),
  /handoff_sha256 does not match trusted fixture hash/,
);

const unsupportedMetric = handoff();
unsupportedMetric.safety_metrics[0].domain = "mh";
unsupportedMetric.safety_metrics[0].metric_key = "mh:VALUE";
assert.throws(
  () => buildMedicalMonitoringConsumerFixture(unsupportedMetric, { expectedHandoffSha256: HASH_B }),
  /explicit safety domain/,
);

for (const [field, invalidValue] of [
  ["scope_sha256", HASH_C.toUpperCase()],
  ["scope_sha256", ` ${HASH_C}`],
  ["scope_sha256", 123],
  ["scope_sha256", "g".repeat(64)],
  ["handoff_sha256", HASH_B.toUpperCase()],
  ["handoff_sha256", ` ${HASH_B}`],
  ["handoff_sha256", 123],
]) {
  const invalid = handoff();
  invalid[field] = invalidValue;
  assert.throws(
    () => buildMedicalMonitoringConsumerFixture(invalid),
    /lowercase SHA-256 hex digest/,
  );
}

const invalidTimelineDigest = handoff();
invalidTimelineDigest.timeline[0].event_sha256 = HASH_A.toUpperCase();
assert.throws(
  () => buildMedicalMonitoringConsumerFixture(invalidTimelineDigest),
  /lowercase SHA-256 hex digest/,
);

console.log("medicalMonitoringConsumerContract: 33 passed");
