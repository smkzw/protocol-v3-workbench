const API_PREFIX = "/api/projects";

function monitoringModulePath(projectId, suffix = "") {
  const base = `${API_PREFIX}/${encodeSegment(requireId(projectId, "projectId"))}/modules/medical-monitoring`;
  return suffix ? `${base}/${suffix}` : base;
}

function monitoringAiPath(projectId, suffix = "") {
  const base = `${API_PREFIX}/${encodeSegment(requireId(projectId, "projectId"))}/modules/medical-monitoring/ai`;
  return suffix ? `${base}/${suffix}` : base;
}

export const MEDICAL_MONITORING_QUERY_PATHS = Object.freeze({
  moduleSummary: (projectId) => `${API_PREFIX}/${encodeSegment(projectId)}/modules/medical-monitoring/summary`,
  subjects: (projectId) => `${API_PREFIX}/${encodeSegment(projectId)}/monitoring/subjects`,
  subjectMonitoring: (projectId, subjectId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/subjects/${encodeSegment(subjectId)}/monitoring`
  ),
  currentRiskSnapshot: (projectId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/modules/medical-monitoring/risk-snapshots/current`
  ),
  currentRiskExport: (projectId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/modules/medical-monitoring/risk-snapshots/current/export`
  ),
  riskTaxonomy: (projectId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/modules/medical-monitoring/risk-taxonomy`
  ),
  riskHistory: (projectId, riskKey) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/monitoring/risks/${encodeSegment(riskKey)}/history`
  ),
  riskEvidence: (projectId, riskInstanceId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/monitoring/risks/${encodeSegment(riskInstanceId)}/evidence-fragment`
  ),
  batches: (projectId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/monitoring/batches`
  ),
  batch: (projectId, batchId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/monitoring/batches/${encodeSegment(batchId)}`
  ),
  dailyRuns: (projectId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/monitoring/daily-runs`
  ),
  dailyRunReadiness: (projectId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/monitoring/daily-runs/readiness`
  ),
  dailyRun: (projectId, runId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/monitoring/daily-runs/${encodeSegment(runId)}`
  ),
  protocolVersions: (projectId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/modules/medical-monitoring/protocol-versions`
  ),
  protocolPreparation: (projectId, protocolVersionId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/modules/medical-monitoring/protocol-preparation/protocol-versions/${encodeSegment(protocolVersionId)}`
  ),
  metricConfigurationCandidates: (projectId, protocolVersionId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/modules/medical-monitoring/metric-configuration/protocol-versions/${encodeSegment(protocolVersionId)}/candidates`
  ),
  ruleTemplateRecommendation: (projectId, factRevisionId) => (
    `${API_PREFIX}/${encodeSegment(projectId)}/modules/medical-monitoring/rule-template-recommendations/facts/${encodeSegment(factRevisionId)}`
  ),
  rulePacks: (projectId) => monitoringModulePath(projectId, "rule-packs"),
  rulePack: (projectId, rulePackId) => monitoringModulePath(
    projectId,
    `rule-packs/${encodeSegment(rulePackId)}`,
  ),
  rulePackDiff: (projectId, previousRulePackId, currentRulePackId) => (
    monitoringModulePath(
      projectId,
      `rule-packs/${encodeSegment(previousRulePackId)}/diff/${encodeSegment(currentRulePackId)}`,
    )
  ),
  rulePackShadowLineageEvidence: (projectId, rulePackId) => monitoringModulePath(
    projectId,
    `rule-packs/${encodeSegment(rulePackId)}/shadow-lineage-evidence`,
  ),
});

export class MedicalMonitoringApiError extends Error {
  constructor(message, { status = 0, url = "", detail = null } = {}) {
    super(message);
    this.name = "MedicalMonitoringApiError";
    this.status = status;
    this.url = url;
    this.detail = detail;
  }
}

function requireId(value, label) {
  const clean = value === null || value === undefined ? "" : String(value).trim();
  if (!clean) throw new TypeError(`${label} is required`);
  return clean;
}

function encodeSegment(value) {
  return encodeURIComponent(requireId(value, "path identifier"));
}

function appendQuery(path, values) {
  const params = new URLSearchParams();
  Object.entries(values || {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") return;
    params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function joinBaseUrl(baseUrl, path) {
  const base = String(baseUrl || "").replace(/\/+$/, "");
  return `${base}${path}`;
}

async function responsePayload(response) {
  if (response.status === 204) return null;
  const contentType = response.headers?.get?.("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function errorMessage(payload, response) {
  if (payload && typeof payload === "object") {
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail && typeof payload.detail === "object") {
      if (typeof payload.detail.message === "string") return payload.detail.message;
      if (typeof payload.detail.code === "string") return payload.detail.code;
    }
    if (typeof payload.message === "string") return payload.message;
  }
  if (typeof payload === "string" && payload.trim()) return payload.trim();
  return `Medical monitoring query failed (${response.status})`;
}

function serverOwnedPayload(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return body;
  // Identity is resolved from the verified server principal. Drop a
  // transitional client actor field before any feature request is sent.
  const { actor: _clientActor, ...payload } = body;
  return payload;
}

export function createMedicalMonitoringApi({
  fetchImpl = globalThis.fetch,
  baseUrl = "",
} = {}) {
  if (typeof fetchImpl !== "function") {
    throw new TypeError("fetchImpl must be a function");
  }

  async function get(path, { signal } = {}) {
    const url = joinBaseUrl(baseUrl, path);
    const response = await fetchImpl(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal,
    });
    const payload = await responsePayload(response);
    if (!response.ok) {
      throw new MedicalMonitoringApiError(errorMessage(payload, response), {
        status: response.status,
        url,
        detail: payload,
      });
    }
    return payload;
  }

  async function post(path, { signal, body, headers = {} } = {}) {
    const url = joinBaseUrl(baseUrl, path);
    const requestBody = body instanceof Blob || body instanceof ArrayBuffer
      ? body
      : serverOwnedPayload(body);
    const hasJsonBody = requestBody !== undefined
      && !(requestBody instanceof Blob)
      && !(requestBody instanceof ArrayBuffer);
    const response = await fetchImpl(url, {
      method: "POST",
      headers: {
        Accept: "application/json",
        ...(hasJsonBody ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      ...(requestBody === undefined
        ? {}
        : { body: hasJsonBody ? JSON.stringify(requestBody) : requestBody }),
      signal,
    });
    const payload = await responsePayload(response);
    if (!response.ok) {
      throw new MedicalMonitoringApiError(errorMessage(payload, response), {
        status: response.status,
        url,
        detail: payload,
      });
    }
    return payload;
  }

  async function download(path, { signal, fallbackFilename } = {}) {
    const url = joinBaseUrl(baseUrl, path);
    const response = await fetchImpl(url, {
      method: "GET",
      headers: { Accept: "application/zip" },
      signal,
    });
    if (!response.ok) {
      const payload = await responsePayload(response);
      throw new MedicalMonitoringApiError(errorMessage(payload, response), {
        status: response.status,
        url,
        detail: payload,
      });
    }
    const disposition = response.headers?.get?.("content-disposition") || "";
    const filenameMatch = disposition.match(/filename="([^"]+)"/i);
    return {
      blob: await response.blob(),
      filename: filenameMatch?.[1] || fallbackFilename || "medical-risk-checklist.zip",
    };
  }

  async function patch(path, { signal, body, headers = {} } = {}) {
    const url = joinBaseUrl(baseUrl, path);
    const response = await fetchImpl(url, {
      method: "PATCH",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...headers,
      },
      body: JSON.stringify(body),
      signal,
    });
    const payload = await responsePayload(response);
    if (!response.ok) {
      throw new MedicalMonitoringApiError(errorMessage(payload, response), {
        status: response.status,
        url,
        detail: payload,
      });
    }
    return payload;
  }

  return Object.freeze({
    getModuleSummary(projectId, options = {}) {
      return get(MEDICAL_MONITORING_QUERY_PATHS.moduleSummary(
        requireId(projectId, "projectId"),
      ), options);
    },

    listSubjects(projectId, options = {}) {
      return get(MEDICAL_MONITORING_QUERY_PATHS.subjects(
        requireId(projectId, "projectId"),
      ), options);
    },

    getSubjectMonitoring(projectId, subjectId, options = {}) {
      return get(MEDICAL_MONITORING_QUERY_PATHS.subjectMonitoring(
        requireId(projectId, "projectId"),
        requireId(subjectId, "subjectId"),
      ), options);
    },

    getRiskSnapshot(projectId, {
      signal,
      snapshotId,
      siteId,
      subjectId,
      riskKey,
      riskInstanceId,
      riskCategoryCode,
      riskItem,
      severity,
      dispositionStatus,
      updatedAt,
      status,
      batchDelta,
      includeTerminal,
      sortBy,
      sortDirection,
      page,
      pageSize,
    } = {}) {
      const path = appendQuery(
        MEDICAL_MONITORING_QUERY_PATHS.currentRiskSnapshot(
          requireId(projectId, "projectId"),
        ),
        {
          snapshot_id: snapshotId,
          site_id: siteId,
          subject_id: subjectId,
          risk_key: riskKey,
          risk_instance_id: riskInstanceId,
          risk_category_code: riskCategoryCode,
          risk_item: riskItem,
          severity,
          disposition_status: dispositionStatus,
          updated_at: updatedAt,
          status,
          batch_delta: batchDelta,
          include_terminal: includeTerminal,
          sort_by: sortBy,
          sort_direction: sortDirection,
          page,
          page_size: pageSize,
        },
      );
      return get(path, { signal });
    },

    exportRiskSnapshot(projectId, {
      signal,
      snapshotId,
      siteId,
      subjectId,
      riskKey,
      riskInstanceId,
      riskCategoryCode,
      riskItem,
      severity,
      dispositionStatus,
      updatedAt,
      status,
      batchDelta,
      includeTerminal,
      sortBy,
      sortDirection,
    } = {}) {
      const path = appendQuery(
        MEDICAL_MONITORING_QUERY_PATHS.currentRiskExport(
          requireId(projectId, "projectId"),
        ),
        {
          snapshot_id: snapshotId,
          site_id: siteId,
          subject_id: subjectId,
          risk_key: riskKey,
          risk_instance_id: riskInstanceId,
          risk_category_code: riskCategoryCode,
          risk_item: riskItem,
          severity,
          disposition_status: dispositionStatus,
          updated_at: updatedAt,
          status,
          batch_delta: batchDelta,
          include_terminal: includeTerminal,
          sort_by: sortBy,
          sort_direction: sortDirection,
        },
      );
      return download(path, {
        signal,
        fallbackFilename: "medical-risk-checklist.zip",
      });
    },

    getRiskTaxonomy(projectId, options = {}) {
      return get(MEDICAL_MONITORING_QUERY_PATHS.riskTaxonomy(
        requireId(projectId, "projectId"),
      ), options);
    },

    getRiskHistory(projectId, riskKey, options = {}) {
      return get(MEDICAL_MONITORING_QUERY_PATHS.riskHistory(
        requireId(projectId, "projectId"),
        requireId(riskKey, "riskKey"),
      ), options);
    },

    getRiskEvidence(projectId, riskInstanceId, { locator, signal } = {}) {
      const path = appendQuery(
        MEDICAL_MONITORING_QUERY_PATHS.riskEvidence(
          requireId(projectId, "projectId"),
          requireId(riskInstanceId, "riskInstanceId"),
        ),
        { locator: requireId(locator, "locator") },
      );
      return get(path, { signal });
    },

    listBatches(projectId, options = {}) {
      return get(
        MEDICAL_MONITORING_QUERY_PATHS.batches(requireId(projectId, "projectId")),
        options,
      );
    },

    getDailyRunReadiness(projectId, batchId, { signal } = {}) {
      return get(
        appendQuery(
          MEDICAL_MONITORING_QUERY_PATHS.dailyRunReadiness(
            requireId(projectId, "projectId"),
          ),
          { batch_id: requireId(batchId, "batchId") },
        ),
        { signal },
      );
    },

    getBatch(projectId, batchId, options = {}) {
      return get(
        MEDICAL_MONITORING_QUERY_PATHS.batch(
          requireId(projectId, "projectId"),
          requireId(batchId, "batchId"),
        ),
        options,
      );
    },

    listProtocolVersions(projectId, options = {}) {
      return get(
        MEDICAL_MONITORING_QUERY_PATHS.protocolVersions(
          requireId(projectId, "projectId"),
        ),
        options,
      );
    },

    getProtocolPreparationStatus(
      projectId,
      protocolVersionId,
      options = {},
    ) {
      return get(
        `${MEDICAL_MONITORING_QUERY_PATHS.protocolPreparation(
          requireId(projectId, "projectId"),
          requireId(protocolVersionId, "protocolVersionId"),
        )}/status`,
        options,
      );
    },

    getMetricConfigurationCandidates(
      projectId,
      protocolVersionId,
      batchId,
      { signal } = {},
    ) {
      return get(
        appendQuery(
          MEDICAL_MONITORING_QUERY_PATHS.metricConfigurationCandidates(
            requireId(projectId, "projectId"),
            requireId(protocolVersionId, "protocolVersionId"),
          ),
          { batch_id: requireId(batchId, "batchId") },
        ),
        { signal },
      );
    },

    startProtocolPreparation(
      projectId,
      protocolVersionId,
      { topicIds = [], signal } = {},
    ) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.protocolPreparation(
          requireId(projectId, "projectId"),
          requireId(protocolVersionId, "protocolVersionId"),
        )}/start`,
        {
          signal,
          body: { topic_ids: topicIds },
        },
      );
    },

    decideProtocolPreparationCandidate(
      projectId,
      protocolVersionId,
      candidateId,
      payload,
      options = {},
    ) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.protocolPreparation(
          requireId(projectId, "projectId"),
          requireId(protocolVersionId, "protocolVersionId"),
        )}/candidates/${encodeSegment(
          requireId(candidateId, "candidateId"),
        )}/decision`,
        { ...options, body: payload },
      );
    },

    getRuleTemplateRecommendationStatus(
      projectId,
      factRevisionId,
      { expectedFactStateVersion, signal } = {},
    ) {
      const path = appendQuery(
        `${MEDICAL_MONITORING_QUERY_PATHS.ruleTemplateRecommendation(
          requireId(projectId, "projectId"),
          requireId(factRevisionId, "factRevisionId"),
        )}/status`,
        {
          expected_fact_state_version: requireId(
            expectedFactStateVersion,
            "expectedFactStateVersion",
          ),
        },
      );
      return get(path, { signal });
    },

    startRuleTemplateRecommendation(
      projectId,
      factRevisionId,
      payload,
      options = {},
    ) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.ruleTemplateRecommendation(
          requireId(projectId, "projectId"),
          requireId(factRevisionId, "factRevisionId"),
        )}/start`,
        { ...options, body: payload },
      );
    },

    decideRuleTemplateRecommendation(
      projectId,
      factRevisionId,
      candidateId,
      payload,
      options = {},
    ) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.ruleTemplateRecommendation(
          requireId(projectId, "projectId"),
          requireId(factRevisionId, "factRevisionId"),
        )}/candidates/${encodeSegment(
          requireId(candidateId, "candidateId"),
        )}/decision`,
        { ...options, body: payload },
      );
    },

    intakeBatchFile(projectId, file, {
      signal,
      idempotencyKey,
      classificationOverrideReason = "",
    } = {}) {
      if (!(file instanceof Blob)) throw new TypeError("file must be a Blob");
      const filename = requireId(file.name || "listing.xlsx", "filename");
      const path = appendQuery(
        `${MEDICAL_MONITORING_QUERY_PATHS.batches(requireId(projectId, "projectId"))}/intake-file`,
        {
          filename,
          idempotency_key: requireId(idempotencyKey, "idempotencyKey"),
          classification_override_reason: classificationOverrideReason,
        },
      );
      return post(path, {
        signal,
        body: file,
        headers: { "Content-Type": "application/octet-stream" },
      });
    },

    confirmSourceContent(projectId, sourceEntryId, payload, options = {}) {
      return post(
        `${API_PREFIX}/${encodeSegment(requireId(projectId, "projectId"))}/sources/${encodeSegment(requireId(sourceEntryId, "sourceEntryId"))}/content-validation/confirm`,
        { ...options, body: payload },
      );
    },

    recordBatchValidationEvidence(projectId, batchId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.batch(
          requireId(projectId, "projectId"),
          requireId(batchId, "batchId"),
        )}/validation-evidence`,
        { ...options, body: payload },
      );
    },

    confirmBatchFullSnapshot(projectId, batchId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.batch(
          requireId(projectId, "projectId"),
          requireId(batchId, "batchId"),
        )}/confirm-full-snapshot`,
        { ...options, body: payload },
      );
    },

    transitionBatch(projectId, batchId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.batch(
          requireId(projectId, "projectId"),
          requireId(batchId, "batchId"),
        )}/transition`,
        { ...options, body: payload },
      );
    },

    getBatchDiff(projectId, previousBatchId, currentBatchId, {
      signal,
      offset,
      limit,
    } = {}) {
      const path = appendQuery(
        `${API_PREFIX}/${encodeSegment(requireId(projectId, "projectId"))}/monitoring/batch-diff`,
        {
          previous_batch_id: requireId(previousBatchId, "previousBatchId"),
          current_batch_id: requireId(currentBatchId, "currentBatchId"),
          offset,
          limit,
        },
      );
      return get(path, { signal });
    },

    listDailyRuns(projectId, options = {}) {
      return get(
        MEDICAL_MONITORING_QUERY_PATHS.dailyRuns(
          requireId(projectId, "projectId"),
        ),
        options,
      );
    },

    getDailyRun(projectId, runId, options = {}) {
      return get(
        MEDICAL_MONITORING_QUERY_PATHS.dailyRun(
          requireId(projectId, "projectId"),
          requireId(runId, "runId"),
        ),
        options,
      );
    },

    prepareDailyRun(projectId, payload, options = {}) {
      return post(
        MEDICAL_MONITORING_QUERY_PATHS.dailyRuns(
          requireId(projectId, "projectId"),
        ),
        { ...options, body: payload },
      );
    },

    processDailyRun(projectId, runId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.dailyRun(
          requireId(projectId, "projectId"),
          requireId(runId, "runId"),
        )}/process`,
        { ...options, body: payload },
      );
    },

    executeDailyRunRules(projectId, runId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.dailyRun(
          requireId(projectId, "projectId"),
          requireId(runId, "runId"),
        )}/execute-rules`,
        { ...options, body: payload },
      );
    },

    submitDailyRunAi(projectId, runId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.dailyRun(
          requireId(projectId, "projectId"),
          requireId(runId, "runId"),
        )}/submit-ai`,
        { ...options, body: payload },
      );
    },

    getDailyRunAiProgress(projectId, runId, options = {}) {
      return get(
        `${MEDICAL_MONITORING_QUERY_PATHS.dailyRun(
          requireId(projectId, "projectId"),
          requireId(runId, "runId"),
        )}/ai-progress`,
        options,
      );
    },

    assembleDailyRunRisks(projectId, runId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.dailyRun(
          requireId(projectId, "projectId"),
          requireId(runId, "runId"),
        )}/assemble-risks`,
        { ...options, body: payload },
      );
    },

    acknowledgeDailyRunPartial(projectId, runId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.dailyRun(
          requireId(projectId, "projectId"),
          requireId(runId, "runId"),
        )}/acknowledge-partial`,
        { ...options, body: payload },
      );
    },

    markDailyRunReady(projectId, runId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.dailyRun(
          requireId(projectId, "projectId"),
          requireId(runId, "runId"),
        )}/ready-to-confirm`,
        { ...options, body: payload },
      );
    },

    confirmDailyRun(projectId, runId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.dailyRun(
          requireId(projectId, "projectId"),
          requireId(runId, "runId"),
        )}/confirm`,
        { ...options, body: payload },
      );
    },

    startFieldMapping(projectId, batchId, {
      signal,
      chunkSize = 12,
      retryFailed = false,
    } = {}) {
      return post(
        monitoringAiPath(projectId, "field-mapping-jobs"),
        {
          signal,
          body: {
            batch_id: requireId(batchId, "batchId"),
            chunk_size: chunkSize,
            retry_failed: Boolean(retryFailed),
          },
        },
      );
    },

    getFieldMappingStatus(projectId, batchId, options = {}) {
      return get(
        appendQuery(
          monitoringAiPath(projectId, "field-mapping-status"),
          { batch_id: requireId(batchId, "batchId") },
        ),
        options,
      );
    },

    listMonitoringAiJobs(projectId, {
      signal,
      taskType = "",
      businessKeyPrefix = "",
    } = {}) {
      return get(
        appendQuery(
          monitoringAiPath(projectId, "jobs"),
          {
            task_type: taskType,
            business_key_prefix: businessKeyPrefix,
          },
        ),
        { signal },
      );
    },

    getMonitoringAiJob(projectId, jobId, options = {}) {
      return get(
        monitoringAiPath(
          projectId,
          `jobs/${encodeSegment(requireId(jobId, "jobId"))}`,
        ),
        options,
      );
    },

    decideMonitoringAiCandidate(
      projectId,
      candidateId,
      payload,
      options = {},
    ) {
      return post(
        monitoringAiPath(
          projectId,
          `candidates/${encodeSegment(requireId(candidateId, "candidateId"))}/decision`,
        ),
        { ...options, body: payload },
      );
    },

    assembleMappingDraft(
      projectId,
      { batchId, fullProfileSha256 },
      options = {},
    ) {
      return post(
        monitoringAiPath(projectId, "mapping-drafts/assemble"),
        {
          ...options,
          body: {
            batch_id: requireId(batchId, "batchId"),
            full_profile_sha256: requireId(
              fullProfileSha256,
              "fullProfileSha256",
            ),
          },
        },
      );
    },

    adoptFieldMappingRun(projectId, {
      batchId,
      fullProfileSha256,
      reason,
    }, options = {}) {
      return post(
        monitoringAiPath(projectId, "field-mapping-runs/adopt"),
        {
          ...options,
          body: {
            batch_id: requireId(batchId, "batchId"),
            full_profile_sha256: requireId(
              fullProfileSha256,
              "fullProfileSha256",
            ),
            reason: requireId(reason, "reason"),
          },
        },
      );
    },

    getMappingDraft(projectId, draftId, options = {}) {
      return get(
        monitoringAiPath(
          projectId,
          `mapping-drafts/${encodeSegment(requireId(draftId, "draftId"))}`,
        ),
        options,
      );
    },

    getMappingRevision(projectId, mappingRevision, options = {}) {
      return get(
        monitoringAiPath(
          projectId,
          `mapping-revisions/${encodeSegment(
            requireId(mappingRevision, "mappingRevision"),
          )}`,
        ),
        options,
      );
    },

    editMappingDraftField(
      projectId,
      draftId,
      payload,
      options = {},
    ) {
      return patch(
        monitoringAiPath(
          projectId,
          `mapping-drafts/${encodeSegment(requireId(draftId, "draftId"))}/field`,
        ),
        { ...options, body: payload },
      );
    },

    confirmMappingDraft(projectId, draftId, payload, options = {}) {
      return post(
        monitoringAiPath(
          projectId,
          `mapping-drafts/${encodeSegment(requireId(draftId, "draftId"))}/confirm`,
        ),
        { ...options, body: payload },
      );
    },

    listRulePacks(projectId, options = {}) {
      return get(
        MEDICAL_MONITORING_QUERY_PATHS.rulePacks(requireId(projectId, "projectId")),
        options,
      );
    },

    getRulePack(projectId, rulePackId, options = {}) {
      return get(
        MEDICAL_MONITORING_QUERY_PATHS.rulePack(
          requireId(projectId, "projectId"),
          requireId(rulePackId, "rulePackId"),
        ),
        options,
      );
    },

    getRulePackDiff(projectId, previousRulePackId, currentRulePackId, options = {}) {
      return get(
        MEDICAL_MONITORING_QUERY_PATHS.rulePackDiff(
          requireId(projectId, "projectId"),
          requireId(previousRulePackId, "previousRulePackId"),
          requireId(currentRulePackId, "currentRulePackId"),
        ),
        options,
      );
    },

    createRulePackDraft(projectId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.rulePacks(
          requireId(projectId, "projectId"),
        )}/drafts`,
        { ...options, body: payload },
      );
    },

    startRulePackShadow(projectId, rulePackId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.rulePack(
          requireId(projectId, "projectId"),
          requireId(rulePackId, "rulePackId"),
        )}/start-shadow`,
        { ...options, body: payload },
      );
    },

    runAutomaticShadow(projectId, rulePackId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.rulePack(
          requireId(projectId, "projectId"),
          requireId(rulePackId, "rulePackId"),
        )}/automatic-shadow-runs`,
        { ...options, body: payload },
      );
    },

    listShadowSampleSets(projectId, rulePackId, options = {}) {
      return get(
        `${MEDICAL_MONITORING_QUERY_PATHS.rulePack(
          requireId(projectId, "projectId"),
          requireId(rulePackId, "rulePackId"),
        )}/shadow-sample-sets`,
        options,
      );
    },

    listShadowRuns(projectId, rulePackId, options = {}) {
      return get(
        `${MEDICAL_MONITORING_QUERY_PATHS.rulePack(
          requireId(projectId, "projectId"),
          requireId(rulePackId, "rulePackId"),
        )}/shadow-runs`,
        options,
      );
    },

    getRulePackShadowLineageEvidence(projectId, rulePackId, options = {}) {
      return get(
        MEDICAL_MONITORING_QUERY_PATHS.rulePackShadowLineageEvidence(
          requireId(projectId, "projectId"),
          requireId(rulePackId, "rulePackId"),
        ),
        options,
      );
    },

    confirmRulePackShadow(projectId, rulePackId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.rulePack(
          requireId(projectId, "projectId"),
          requireId(rulePackId, "rulePackId"),
        )}/confirm-shadow`,
        { ...options, body: payload },
      );
    },

    publishRulePack(projectId, rulePackId, payload, options = {}) {
      return post(
        `${MEDICAL_MONITORING_QUERY_PATHS.rulePack(
          requireId(projectId, "projectId"),
          requireId(rulePackId, "rulePackId"),
        )}/publish`,
        { ...options, body: payload },
      );
    },

  });
}
