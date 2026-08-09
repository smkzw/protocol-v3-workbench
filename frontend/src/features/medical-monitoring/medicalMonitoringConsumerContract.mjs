const DOMAIN_TO_FRONTEND_SOURCE = Object.freeze({
  visit: "SV",
  ae: "AE",
  mh: "MH",
  cm: "CM",
  ip: "IP",
  lab: "LB",
  vitals: "VS",
  ecg: "ECG",
  efficacy: "QS",
  finding: "FINDING",
  pd: "PD",
  other: "OTHER",
});

const SAFETY_DOMAINS = new Set(["ae", "lab", "vitals", "ecg"]);
const HASH_RE = /^[0-9a-f]{64}$/;

export class MedicalMonitoringConsumerContractError extends Error {
  constructor(message) {
    super(message);
    this.name = "MedicalMonitoringConsumerContractError";
  }
}

function required(value, field) {
  const text = value === null || value === undefined ? "" : String(value).trim();
  if (!text) throw new MedicalMonitoringConsumerContractError(`${field} is required`);
  return text;
}

function optional(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new MedicalMonitoringConsumerContractError(`${field} must be an object`);
  }
  return value;
}

function list(value, field) {
  if (!Array.isArray(value)) {
    throw new MedicalMonitoringConsumerContractError(`${field} must be a list`);
  }
  return value;
}

function uniqueStrings(value, field) {
  const result = list(value ?? [], field).map((item, index) => required(item, `${field}[${index}]`));
  if (new Set(result).size !== result.length) {
    throw new MedicalMonitoringConsumerContractError(`${field} must not contain duplicates`);
  }
  return [...result].sort();
}

function orderedStrings(value, field) {
  const result = list(value ?? [], field).map((item, index) => required(item, `${field}[${index}]`));
  if (new Set(result).size !== result.length) {
    throw new MedicalMonitoringConsumerContractError(`${field} must not contain duplicates`);
  }
  return result;
}

function hash(value, field) {
  if (typeof value !== "string" || !HASH_RE.test(value)) {
    throw new MedicalMonitoringConsumerContractError(`${field} must be a lowercase SHA-256 hex digest`);
  }
  return value;
}

function alignedEvidence(record, field) {
  const ids = orderedStrings(record.evidence_ids, `${field}.evidence_ids`);
  const locators = orderedStrings(record.evidence_locators, `${field}.evidence_locators`);
  if (ids.length !== locators.length) {
    throw new MedicalMonitoringConsumerContractError(`${field} evidence ids and locators must align`);
  }
  return ids.map((evidenceId, index) => ({ evidenceId, locator: locators[index] }))
    .sort((left, right) => left.evidenceId.localeCompare(right.evidenceId));
}

function nonNegativeInteger(value, field) {
  if (!Number.isInteger(value) || value < 0 || typeof value === "boolean") {
    throw new MedicalMonitoringConsumerContractError(`${field} must be a non-negative integer`);
  }
  return value;
}

function domainCounts(value, field) {
  const input = object(value, field);
  return Object.fromEntries(Object.entries(input)
    .map(([key, count]) => [
      required(key, `${field} key`),
      nonNegativeInteger(count, `${field}.${key}`),
    ])
    .sort(([left], [right]) => left.localeCompare(right)));
}

function normalizeRollup(record, expectedLevel, path) {
  const input = object(record, path);
  const level = required(input.level, `${path}.level`);
  if (level !== expectedLevel) {
    throw new MedicalMonitoringConsumerContractError(`${path}.level must be ${expectedLevel}`);
  }
  return Object.freeze({
    level,
    identity: required(input.identity, `${path}.identity`),
    event_ids: uniqueStrings(input.event_ids, `${path}.event_ids`),
    observation_ids: uniqueStrings(input.observation_ids, `${path}.observation_ids`),
    risk_instance_ids: uniqueStrings(input.risk_instance_ids, `${path}.risk_instance_ids`),
    domain_counts: domainCounts(input.domain_counts, `${path}.domain_counts`),
    incomplete_event_count: nonNegativeInteger(input.incomplete_event_count, `${path}.incomplete_event_count`),
    uncertain_event_count: nonNegativeInteger(input.uncertain_event_count, `${path}.uncertain_event_count`),
  });
}

function sortedDifference(actual, expected) {
  const actualSet = new Set(actual);
  return expected.filter((value) => !actualSet.has(value)).sort();
}

function rollupSetStatus(actual, expected, identity, level) {
  const fields = ["event_ids", "observation_ids", "risk_instance_ids"];
  const missing = Object.fromEntries(fields.map((field) => [
    field,
    sortedDifference(actual[field], expected[field]),
  ]));
  const extra = Object.fromEntries(fields.map((field) => [
    field,
    sortedDifference(expected[field], actual[field]),
  ]));
  const countMismatches = [];
  if (Object.prototype.hasOwnProperty.call(actual, "domain_counts")
    && expected.domain_counts
    && JSON.stringify(actual.domain_counts) !== JSON.stringify(expected.domain_counts)) {
    countMismatches.push("domain_counts");
  }
  if (Object.prototype.hasOwnProperty.call(actual, "incomplete_event_count")
    && expected.incomplete_event_count !== undefined
    && actual.incomplete_event_count !== expected.incomplete_event_count) {
    countMismatches.push("incomplete_event_count");
  }
  if (Object.prototype.hasOwnProperty.call(actual, "uncertain_event_count")
    && expected.uncertain_event_count !== undefined
    && actual.uncertain_event_count !== expected.uncertain_event_count) {
    countMismatches.push("uncertain_event_count");
  }
  const mismatch = fields.some((field) => missing[field].length || extra[field].length) || countMismatches.length > 0;
  return {
    identity,
    level,
    status: mismatch ? "not_conserved" : "conserved",
    expectedCounts: Object.fromEntries(fields.map((field) => [field, expected[field].length])),
    actualCounts: Object.fromEntries(fields.map((field) => [field, actual[field].length])),
    countMismatches,
    missing,
    extra,
  };
}

function rollupMetadata(events) {
  return {
    domain_counts: Object.fromEntries([...events.reduce((counts, event) => {
      const domain = event.source_domain_code;
      counts.set(domain, (counts.get(domain) || 0) + 1);
      return counts;
    }, new Map()).entries()].sort(([left], [right]) => left.localeCompare(right))),
    incomplete_event_count: events.filter((event) => event.completeness_status !== "complete").length,
    uncertain_event_count: events.filter((event) => event.uncertainty_state !== "none").length,
  };
}

function groupIds(records, identityField) {
  const groups = new Map();
  records.forEach((record) => {
    const identity = record[identityField];
    if (!groups.has(identity)) groups.set(identity, []);
    groups.get(identity).push(record);
  });
  return groups;
}

function cloneJson(value, field) {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (error) {
    throw new MedicalMonitoringConsumerContractError(`${field} must be JSON-serializable`);
  }
}

function assertIdentity(value, expected, field) {
  if (required(value, field) !== expected) {
    throw new MedicalMonitoringConsumerContractError(`${field} does not match handoff identity`);
  }
}

function normalizeTimelineRecord(record, projectId, trialId, eventIds) {
  const input = object(record, "timeline record");
  const eventId = required(input.event_id, "timeline.event_id");
  if (eventIds.has(eventId)) {
    throw new MedicalMonitoringConsumerContractError(`duplicate timeline event: ${eventId}`);
  }
  eventIds.add(eventId);
  const domain = required(input.source_domain, `timeline.${eventId}.source_domain`).toLowerCase();
  if (!DOMAIN_TO_FRONTEND_SOURCE[domain]) {
    throw new MedicalMonitoringConsumerContractError(`timeline domain is unsupported: ${domain}`);
  }
  const evidence = alignedEvidence(input, `timeline.${eventId}`);
  const eventType = required(input.event_type, `timeline.${eventId}.event_type`);
  const relatedRiskIds = uniqueStrings(input.related_risk_ids, `timeline.${eventId}.related_risk_ids`);
  const ruleBindingIds = uniqueStrings(input.rule_binding_ids, `timeline.${eventId}.rule_binding_ids`);
  return Object.freeze({
    event_id: eventId,
    event_sha256: hash(input.event_sha256, `timeline.${eventId}.event_sha256`),
    project_id: projectId,
    trial_id: trialId,
    site_id: required(input.site_id, `timeline.${eventId}.site_id`),
    subject_id: required(input.subject_id, `timeline.${eventId}.subject_id`),
    event_type: eventType,
    source_domain: DOMAIN_TO_FRONTEND_SOURCE[domain],
    source_domain_code: domain,
    title: required(input.title, `timeline.${eventId}.title`),
    detail: required(input.detail, `timeline.${eventId}.detail`),
    event_date: optional(input.event_date),
    date_precision: required(input.date_precision, `timeline.${eventId}.date_precision`),
    raw_event_date: optional(input.raw_event_date),
    visit_code: "",
    visit_label: optional(input.visit_label),
    visit_number: input.visit_number === null || input.visit_number === undefined
      ? null
      : Number.isInteger(input.visit_number) && input.visit_number >= 0
        ? input.visit_number
        : (() => { throw new MedicalMonitoringConsumerContractError(`timeline.${eventId}.visit_number is invalid`); })(),
    is_unscheduled: input.is_unscheduled === true,
    related_risk_ids: relatedRiskIds,
    evidence_ids: evidence.map((item) => item.evidenceId),
    evidence_locators: evidence.map((item) => item.locator),
    source_locators: evidence.map((item) => item.locator),
    rule_binding_ids: ruleBindingIds,
    completeness_status: required(input.completeness_status, `timeline.${eventId}.completeness_status`),
    uncertainty_state: required(input.uncertainty_state, `timeline.${eventId}.uncertainty_state`),
  });
}

function normalizeMetricPoint(point, metricKey, domain, fieldName, timelineByEvent, pointIds) {
  const input = object(point, `metric ${metricKey} point`);
  const pointId = required(input.point_id, `metric.${metricKey}.point_id`);
  if (pointIds.has(pointId)) {
    throw new MedicalMonitoringConsumerContractError(`duplicate metric point: ${pointId}`);
  }
  pointIds.add(pointId);
  const eventId = required(input.event_id, `metric.${metricKey}.${pointId}.event_id`);
  const timeline = timelineByEvent.get(eventId);
  if (!timeline) {
    throw new MedicalMonitoringConsumerContractError(`metric point is not in timeline: ${pointId}`);
  }
  const eventHash = hash(input.event_sha256, `metric.${metricKey}.${pointId}.event_sha256`);
  if (eventHash !== timeline.event_sha256) {
    throw new MedicalMonitoringConsumerContractError(`metric point event hash mismatch: ${pointId}`);
  }
  assertIdentity(input.subject_id, timeline.subject_id, `metric.${metricKey}.${pointId}.subject_id`);
  assertIdentity(input.site_id, timeline.site_id, `metric.${metricKey}.${pointId}.site_id`);
  const inputDomain = required(input.domain, `metric.${metricKey}.${pointId}.domain`).toLowerCase();
  if (inputDomain !== domain) {
    throw new MedicalMonitoringConsumerContractError(`metric point domain mismatch: ${pointId}`);
  }
  const inputField = required(input.field_name, `metric.${metricKey}.${pointId}.field_name`);
  if (inputField !== fieldName) {
    throw new MedicalMonitoringConsumerContractError(`metric point field mismatch: ${pointId}`);
  }
  const evidence = alignedEvidence(input, `metric.${metricKey}.${pointId}`);
  const visitNumber = input.visit_number === null || input.visit_number === undefined
    ? null
    : Number.isInteger(input.visit_number) && input.visit_number >= 0
      ? input.visit_number
      : (() => { throw new MedicalMonitoringConsumerContractError(`metric.${metricKey}.${pointId}.visit_number is invalid`); })();
  return Object.freeze({
    point_id: pointId,
    event_id: eventId,
    event_sha256: eventHash,
    subject_id: required(input.subject_id, `metric.${metricKey}.${pointId}.subject_id`),
    site_id: required(input.site_id, `metric.${metricKey}.${pointId}.site_id`),
    domain: inputDomain,
    field_name: inputField,
    assessment_date: optional(input.assessment_date),
    date_precision: required(input.date_precision, `metric.${metricKey}.${pointId}.date_precision`),
    visit_code: "",
    visit_label: optional(input.visit_label),
    visit_number: visitNumber,
    value_status: required(input.value_status, `metric.${metricKey}.${pointId}.value_status`),
    value: optional(input.value),
    raw_value: optional(input.value),
    normalized_value: optional(input.normalized_value),
    unit: optional(input.unit),
    reference_range: input.reference_range === null || input.reference_range === undefined
      ? null
      : cloneJson(input.reference_range, `metric.${metricKey}.${pointId}.reference_range`),
    related_risk_ids: uniqueStrings(input.related_risk_ids, `metric.${metricKey}.${pointId}.related_risk_ids`),
    evidence_ids: evidence.map((item) => item.evidenceId),
    evidence_locators: evidence.map((item) => item.locator),
    source_locators: evidence.map((item) => item.locator),
    rule_binding_ids: uniqueStrings(input.rule_binding_ids, `metric.${metricKey}.${pointId}.rule_binding_ids`),
    completeness_status: required(input.completeness_status, `metric.${metricKey}.${pointId}.completeness_status`),
    uncertainty_state: required(input.uncertainty_state, `metric.${metricKey}.${pointId}.uncertainty_state`),
  });
}

function normalizeMetric(metric, timelineByEvent, pointIds) {
  const input = object(metric, "safety metric");
  const domain = required(input.domain, "metric.domain").toLowerCase();
  if (!SAFETY_DOMAINS.has(domain)) {
    throw new MedicalMonitoringConsumerContractError(`metric domain is not an explicit safety domain: ${domain}`);
  }
  const fieldName = required(input.field_name, "metric.field_name");
  const metricKey = required(input.metric_key, "metric.metric_key");
  if (metricKey !== `${domain}:${fieldName}`) {
    throw new MedicalMonitoringConsumerContractError(`metric key does not match domain/field: ${metricKey}`);
  }
  const points = list(input.points, `metric.${metricKey}.points`)
    .map((point) => normalizeMetricPoint(point, metricKey, domain, fieldName, timelineByEvent, pointIds))
    .sort((left, right) => String(left.assessment_date).localeCompare(String(right.assessment_date)) || left.point_id.localeCompare(right.point_id));
  const units = [...new Set(points.map((point) => point.unit).filter(Boolean))];
  return Object.freeze({
    metric_key: metricKey,
    domain,
    field_name: fieldName,
    metric_label: fieldName,
    unit: units.length === 1 ? units[0] : "",
    points: Object.freeze(points),
  });
}

function normalizeRiskLink(record, eventIds, pointIds, subjectIds) {
  const input = object(record, "risk drilldown record");
  const riskInstanceId = required(input.risk_instance_id, "risk.risk_instance_id");
  const eventIdList = uniqueStrings(input.event_ids, `risk.${riskInstanceId}.event_ids`);
  const observationIdList = uniqueStrings(input.observation_ids, `risk.${riskInstanceId}.observation_ids`);
  if (eventIdList.some((eventId) => !eventIds.has(eventId))) {
    throw new MedicalMonitoringConsumerContractError(`risk link references an unknown event: ${riskInstanceId}`);
  }
  if (observationIdList.some((pointId) => !pointIds.has(pointId))) {
    throw new MedicalMonitoringConsumerContractError(`risk link references an unknown point: ${riskInstanceId}`);
  }
  const subjects = uniqueStrings(input.subject_ids, `risk.${riskInstanceId}.subject_ids`);
  if (subjects.some((subjectId) => !subjectIds.has(subjectId))) {
    throw new MedicalMonitoringConsumerContractError(`risk link references an unknown subject: ${riskInstanceId}`);
  }
  const evidence = alignedEvidence(input, `risk.${riskInstanceId}`);
  return Object.freeze({
    risk_instance_id: riskInstanceId,
    event_ids: eventIdList,
    observation_ids: observationIdList,
    subject_ids: subjects,
    site_ids: uniqueStrings(input.site_ids, `risk.${riskInstanceId}.site_ids`),
    evidence_ids: evidence.map((item) => item.evidenceId),
    evidence_locators: evidence.map((item) => item.locator),
    source_locators: evidence.map((item) => item.locator),
    rule_binding_ids: uniqueStrings(input.rule_binding_ids, `risk.${riskInstanceId}.rule_binding_ids`),
  });
}

function normalizeSubject(
  record,
  projectId,
  trialId,
  scopeSha256,
  handoffSha256,
  timelineByEvent,
  pointIds,
  riskLinksById,
  metricsBySubject,
) {
  const input = object(record, "subject consumer record");
  const subjectId = required(input.subject_id, "subject.subject_id");
  const siteId = required(input.site_id, `subject.${subjectId}.site_id`);
  const eventIds = uniqueStrings(input.event_ids, `subject.${subjectId}.event_ids`);
  if (eventIds.some((eventId) => !timelineByEvent.has(eventId))) {
    throw new MedicalMonitoringConsumerContractError(`subject references an unknown event: ${subjectId}`);
  }
  const observationIds = uniqueStrings(input.observation_ids, `subject.${subjectId}.observation_ids`);
  if (observationIds.some((pointId) => !pointIds.has(pointId))) {
    throw new MedicalMonitoringConsumerContractError(`subject references an unknown point: ${subjectId}`);
  }
  const riskIds = uniqueStrings(input.risk_instance_ids, `subject.${subjectId}.risk_instance_ids`);
  if (riskIds.some((riskId) => !riskLinksById.has(riskId))) {
    throw new MedicalMonitoringConsumerContractError(`subject references an unknown risk: ${subjectId}`);
  }
  const timeline = eventIds.map((eventId) => timelineByEvent.get(eventId));
  if (timeline.some((event) => event.site_id !== siteId)) {
    throw new MedicalMonitoringConsumerContractError(`subject site does not conserve timeline events: ${subjectId}`);
  }
  const safetyTrends = metricsBySubject.get(subjectId) || [];
  const riskLinks = riskIds.map((riskId) => riskLinksById.get(riskId));
  if (riskLinks.some((risk) => !risk.subject_ids.includes(subjectId))) {
    throw new MedicalMonitoringConsumerContractError(`subject risk links do not include subject: ${subjectId}`);
  }
  const timelineEventIds = uniqueStrings(input.timeline_event_ids, `subject.${subjectId}.timeline_event_ids`);
  if (timelineEventIds.join("\u0000") !== eventIds.join("\u0000")) {
    throw new MedicalMonitoringConsumerContractError(`subject timeline ids do not conserve events: ${subjectId}`);
  }
  const safetyMetricKeys = uniqueStrings(input.safety_metric_keys, `subject.${subjectId}.safety_metric_keys`);
  const expectedMetricKeys = safetyTrends.map((metric) => metric.metric_key).sort();
  if (safetyMetricKeys.join("\u0000") !== expectedMetricKeys.join("\u0000")) {
    throw new MedicalMonitoringConsumerContractError(`subject metric keys do not conserve metrics: ${subjectId}`);
  }
  const limitations = [];
  if (!eventIds.length) limitations.push("empty_consumer_timeline");
  if (!safetyTrends.length) limitations.push("empty_safety_metrics");
  const rawProfile = {
    project_id: projectId,
    trial_id: trialId,
    subject_id: subjectId,
    scope_sha256: scopeSha256,
    consumer_handoff_sha256: handoffSha256,
    subject: { subject_id: subjectId, site_id: siteId },
    timeline,
    efficacy_trends: [],
    safety_trends: safetyTrends,
    risk_prompts: [],
    review_focus: [],
    domain_availability: [],
    risk_links: riskLinks,
    limitations,
  };
  return Object.freeze({
    id: subjectId,
    site: siteId,
    status: "",
    profile: "",
    rawProfile,
    efficacyMetrics: Object.freeze([]),
    safetyMetrics: Object.freeze(safetyTrends),
    timeline: Object.freeze(timeline),
    risks: Object.freeze([]),
    labs: Object.freeze([]),
    queries: Object.freeze([]),
    prompts: Object.freeze([]),
    reviewFocus: Object.freeze([]),
    riskLinks: Object.freeze(riskLinks),
    consumerRecord: Object.freeze({
      subject_id: subjectId,
      site_id: siteId,
      event_ids: eventIds,
      observation_ids: observationIds,
      risk_instance_ids: riskIds,
      timeline_event_ids: timelineEventIds,
      safety_metric_keys: safetyMetricKeys,
    }),
  });
}

/**
 * Validate one serialized C6 handoff and expose the existing frontend's raw
 * profile vocabulary. This is a fixture boundary, not a risk authority or a
 * source parser. `expectedHandoffSha256` is optional but should be supplied by
 * a trusted producer when a fixture crosses a process boundary.
 */
export function buildMedicalMonitoringConsumerFixture(payload, { expectedHandoffSha256 = "" } = {}) {
  const handoff = object(payload, "consumer handoff");
  const projectId = required(handoff.project_id, "handoff.project_id");
  const trialId = required(handoff.trial_id, "handoff.trial_id");
  const scopeSha256 = hash(handoff.scope_sha256, "handoff.scope_sha256");
  const handoffSha256 = hash(handoff.handoff_sha256, "handoff.handoff_sha256");
  if (expectedHandoffSha256 && handoffSha256 !== hash(expectedHandoffSha256, "expectedHandoffSha256")) {
    throw new MedicalMonitoringConsumerContractError("handoff_sha256 does not match trusted fixture hash");
  }

  const eventIds = new Set();
  const timeline = list(handoff.timeline, "handoff.timeline")
    .map((record) => normalizeTimelineRecord(record, projectId, trialId, eventIds))
    .sort((left, right) => String(left.event_date).localeCompare(String(right.event_date)) || left.event_id.localeCompare(right.event_id));
  const timelineByEvent = new Map(timeline.map((event) => [event.event_id, event]));
  const pointIds = new Set();
  const metrics = list(handoff.safety_metrics, "handoff.safety_metrics")
    .map((metric) => normalizeMetric(metric, timelineByEvent, pointIds))
    .sort((left, right) => left.metric_key.localeCompare(right.metric_key));
  const metricsBySubject = new Map();
  metrics.forEach((metric) => metric.points.forEach((point) => {
    if (!metricsBySubject.has(point.subject_id)) metricsBySubject.set(point.subject_id, []);
    metricsBySubject.get(point.subject_id).push(metric);
  }));
  metricsBySubject.forEach((subjectMetrics, subjectId) => {
    metricsBySubject.set(subjectId, [...new Map(subjectMetrics.map((metric) => [metric.metric_key, metric])).values()]);
  });
  const allSubjectIds = new Set(list(handoff.subjects, "handoff.subjects").map((record) => required(record.subject_id, "subject.subject_id")));
  const riskLinks = list(handoff.risk_drilldown, "handoff.risk_drilldown")
    .map((record) => normalizeRiskLink(record, eventIds, pointIds, allSubjectIds))
    .sort((left, right) => left.risk_instance_id.localeCompare(right.risk_instance_id));
  const timelineRiskIds = new Set(timeline.flatMap((event) => event.related_risk_ids));
  riskLinks.forEach((risk) => {
    if (!timelineRiskIds.has(risk.risk_instance_id)) {
      throw new MedicalMonitoringConsumerContractError(
        `risk link is not bound to a timeline risk: ${risk.risk_instance_id}`,
      );
    }
    const eventSites = new Set(risk.event_ids.map((eventId) => timelineByEvent.get(eventId).site_id));
    if (eventSites.size !== risk.site_ids.length || [...eventSites].some((siteId) => !risk.site_ids.includes(siteId))) {
      throw new MedicalMonitoringConsumerContractError(
        `risk link site ids do not conserve linked events: ${risk.risk_instance_id}`,
      );
    }
    if (risk.event_ids.some((eventId) => !timelineByEvent.get(eventId).related_risk_ids.includes(risk.risk_instance_id))) {
      throw new MedicalMonitoringConsumerContractError(
        `risk link is not listed on every linked event: ${risk.risk_instance_id}`,
      );
    }
  });
  const riskLinksById = new Map(riskLinks.map((risk) => [risk.risk_instance_id, risk]));
  const subjects = list(handoff.subjects, "handoff.subjects")
    .map((record) => normalizeSubject(
      record,
      projectId,
      trialId,
      scopeSha256,
      handoffSha256,
      timelineByEvent,
      pointIds,
      riskLinksById,
      metricsBySubject,
    ));
  const subjectIds = subjects.map((subject) => subject.id);
  if (new Set(subjectIds).size !== subjectIds.length) {
    throw new MedicalMonitoringConsumerContractError("handoff.subjects must not contain duplicates");
  }
  const timelineEventIds = [...eventIds].sort();
  const timelineObservationIds = [...pointIds].sort();
  const riskInstanceIds = riskLinks.map((risk) => risk.risk_instance_id).sort();
  const projectRollup = normalizeRollup(handoff.project_rollup, "project", "handoff.project_rollup");
  if (projectRollup.identity !== projectId) {
    throw new MedicalMonitoringConsumerContractError("project rollup identity does not match handoff project");
  }
  const projectConservation = rollupSetStatus(projectRollup, {
    event_ids: timelineEventIds,
    observation_ids: timelineObservationIds,
    risk_instance_ids: riskInstanceIds,
    ...rollupMetadata(timeline),
  }, projectRollup.identity, "project");
  if (projectConservation.status !== "conserved") {
    throw new MedicalMonitoringConsumerContractError("project rollup does not conserve normalized handoff ids");
  }

  const siteRollups = list(handoff.site_rollups, "handoff.site_rollups")
    .map((record) => normalizeRollup(record, "site", "handoff.site_rollups"));
  const siteRollupById = new Map();
  siteRollups.forEach((rollup) => {
    if (siteRollupById.has(rollup.identity)) {
      throw new MedicalMonitoringConsumerContractError(`duplicate site rollup: ${rollup.identity}`);
    }
    siteRollupById.set(rollup.identity, rollup);
  });
  const timelineBySite = groupIds(timeline, "site_id");
  const metricPoints = metrics.flatMap((metric) => metric.points);
  const pointsBySite = groupIds(metricPoints, "site_id");
  const expectedSiteIds = [...new Set([
    ...timelineBySite.keys(),
    ...pointsBySite.keys(),
  ])].sort();
  const siteRows = expectedSiteIds.map((siteId) => {
    const events = timelineBySite.get(siteId) || [];
    const points = pointsBySite.get(siteId) || [];
    const expected = {
      event_ids: events.map((event) => event.event_id).sort(),
      observation_ids: points.map((point) => point.point_id).sort(),
      risk_instance_ids: [...new Set(events.flatMap((event) => event.related_risk_ids))].sort(),
      ...rollupMetadata(events),
    };
    const rollup = siteRollupById.get(siteId);
    if (!rollup) {
      return {
        identity: siteId,
        level: "site",
        status: "missing",
        expectedCounts: {
          event_ids: expected.event_ids.length,
          observation_ids: expected.observation_ids.length,
          risk_instance_ids: expected.risk_instance_ids.length,
        },
        actualCounts: { event_ids: 0, observation_ids: 0, risk_instance_ids: 0 },
        countMismatches: ["rollup_missing"],
        missing: {
          event_ids: expected.event_ids,
          observation_ids: expected.observation_ids,
          risk_instance_ids: expected.risk_instance_ids,
        },
        extra: { event_ids: [], observation_ids: [], risk_instance_ids: [] },
      };
    }
    return rollupSetStatus(rollup, expected, siteId, "site");
  });
  const extraSiteRows = siteRollups
    .filter((rollup) => !expectedSiteIds.includes(rollup.identity))
    .map((rollup) => ({
      ...rollupSetStatus(
        rollup,
        { event_ids: [], observation_ids: [], risk_instance_ids: [] },
        rollup.identity,
        "site",
      ),
      status: "not_conserved",
      countMismatches: ["unknown_site_rollup"],
    }));
  const allSiteRows = [...siteRows, ...extraSiteRows];
  const siteConservationStatus = expectedSiteIds.length === 0
    ? siteRollups.length ? "not_conserved" : "empty"
    : siteRollups.length === 0
      ? "missing"
      : extraSiteRows.length || allSiteRows.some((row) => row.status === "not_conserved")
        ? "not_conserved"
        : siteRollups.length < expectedSiteIds.length
          ? "partial"
          : "conserved";

  const expectedSubjectIds = [...new Set([
    ...timeline.map((event) => event.subject_id),
    ...subjects.map((subject) => subject.id),
  ])].sort();
  const subjectsById = new Map(subjects.map((subject) => [subject.id, subject]));
  const timelineBySubject = groupIds(timeline, "subject_id");
  const pointsBySubject = groupIds(metricPoints, "subject_id");
  const subjectRows = expectedSubjectIds.map((subjectId) => {
    const events = timelineBySubject.get(subjectId) || [];
    const points = pointsBySubject.get(subjectId) || [];
    const expected = {
      event_ids: events.map((event) => event.event_id).sort(),
      observation_ids: points.map((point) => point.point_id).sort(),
      risk_instance_ids: [...new Set(events.flatMap((event) => event.related_risk_ids))].sort(),
    };
    const subject = subjectsById.get(subjectId);
    if (!subject) {
      return {
        identity: subjectId,
        level: "subject",
        status: "missing",
        expectedCounts: {
          event_ids: expected.event_ids.length,
          observation_ids: expected.observation_ids.length,
          risk_instance_ids: expected.risk_instance_ids.length,
        },
        actualCounts: { event_ids: 0, observation_ids: 0, risk_instance_ids: 0 },
        countMismatches: ["rollup_missing"],
        missing: expected,
        extra: { event_ids: [], observation_ids: [], risk_instance_ids: [] },
      };
    }
    return rollupSetStatus({
      event_ids: subject.consumerRecord.event_ids,
      observation_ids: subject.consumerRecord.observation_ids,
      risk_instance_ids: subject.consumerRecord.risk_instance_ids,
    }, expected, subjectId, "subject");
  });
  const subjectConservationStatus = expectedSubjectIds.length === 0
    ? "empty"
    : subjectRows.some((row) => row.status === "not_conserved")
      ? "not_conserved"
      : subjectRows.some((row) => row.status === "missing")
        ? "partial"
        : "conserved";
  const rollupConservation = Object.freeze({
    project: Object.freeze(projectConservation),
    sites: Object.freeze({
      status: siteConservationStatus,
      expectedSiteIds,
      providedSiteIds: siteRollups.map((rollup) => rollup.identity).sort(),
      rows: Object.freeze(allSiteRows),
    }),
    subjects: Object.freeze({
      status: subjectConservationStatus,
      expectedSubjectIds,
      providedSubjectIds: subjects.map((subject) => subject.id).sort(),
      rows: Object.freeze(subjectRows),
    }),
  });
  const declaredLimitations = uniqueStrings(handoff.limitations, "handoff.limitations");
  const limitations = uniqueStrings([
    ...declaredLimitations,
    ...(siteConservationStatus === "missing" ? ["site_rollups_missing"] : []),
    ...(siteConservationStatus === "partial" ? ["site_rollups_partial"] : []),
    ...(subjectConservationStatus === "partial" ? ["subject_rollups_partial"] : []),
  ], "handoff.limitations");
  const sourcePayload = cloneJson(handoff, "handoff");
  const fixture = {
    contract_version: "medical_monitoring.consumer_fixture.v1",
    project_id: projectId,
    trial_id: trialId,
    scope_sha256: scopeSha256,
    handoff_sha256: handoffSha256,
    timeline: Object.freeze(timeline),
    safety_metrics: Object.freeze(metrics),
    risk_links: Object.freeze(riskLinks),
    subjects: Object.freeze(subjects.sort((left, right) => left.id.localeCompare(right.id))),
    site_rollups: Object.freeze(siteRollups),
    project_rollup: Object.freeze(projectRollup),
    rollup_conservation: rollupConservation,
    limitations,
    source_handoff: Object.freeze(sourcePayload),
  };
  return Object.freeze(fixture);
}

export { DOMAIN_TO_FRONTEND_SOURCE };
