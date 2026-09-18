/**
 * Protocol v3 workbench API client contract (frozen plan Task 1.9).
 *
 * Non-visual transport contract only: builds route-safe v3 URLs under
 * `/api/projects/{project_id}/protocol-workflow`, injectable fetch, JSON
 * headers, business-shaped methods matching the implemented endpoints and a
 * typed Chinese-native error.  It never converts an HTTP/network/invalid-JSON
 * failure into an empty success, never exposes audit payloads (machine codes,
 * object ids, attempts, owners, recovery actions, audit detail/context), and
 * carries no local absolute paths.  Non-ok error `detail` is normalized to
 * exactly the four approved public fields (`message`, `responsible_area`,
 * `can_retry`, `next_step`) when they exist; every other top-level or nested
 * server key is discarded.  User-facing messages contain no English/program
 * labels and no API/backend/log wording.  There is no exception-card method:
 * clients never invent a catalog failure.
 */

export class ProtocolWorkspaceApiError extends Error {
  constructor(message, { status = 0, detail = null } = {}) {
    super(message);
    this.name = "ProtocolWorkspaceApiError";
    this.status = status;
    this.detail = detail;
  }
}

function projectPath(projectId) {
  return encodeURIComponent(String(projectId || ""));
}

function workflowPath(projectId, workflowRunId) {
  return `/api/projects/${projectPath(projectId)}/protocol-workflow/workflow-runs/${encodeURIComponent(String(workflowRunId))}`;
}

export function createProtocolWorkspaceApi({ fetchImpl = globalThis.fetch } = {}) {
  if (typeof fetchImpl !== "function") {
    throw new ProtocolWorkspaceApiError("当前环境不支持方案工作台请求。");
  }

  const request = async (path, options = {}) => {
    let response;
    try {
      response = await fetchImpl(path, {
        ...options,
        headers: { Accept: "application/json", ...(options.headers || {}) },
      });
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      // Network/transport failures never leak the underlying (possibly
      // English/program) message into user-facing copy.
      throw new ProtocolWorkspaceApiError("方案工作台请求失败。", {
        status: 0,
        detail: null,
      });
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      throw new ProtocolWorkspaceApiError(
        "方案工作台返回内容无法解析，本次请求未能完成。",
        { status: response.status, detail: null },
      );
    }
    if (!response.ok) {
      const rawDetail = payload && typeof payload === "object" ? payload.detail : null;
      // Normalize defensively: keep ONLY the four approved public fields
      // (message / responsible_area / can_retry / next_step) and discard any
      // top-level or nested audit-shaped key (machine codes, object ids,
      // attempts, owners, recovery actions, audit detail/context).
      let detail = null;
      if (rawDetail && typeof rawDetail === "object") {
        const normalized = {};
        if (typeof rawDetail.message === "string") normalized.message = rawDetail.message;
        if (typeof rawDetail.responsible_area === "string") normalized.responsible_area = rawDetail.responsible_area;
        if (typeof rawDetail.can_retry === "boolean") normalized.can_retry = rawDetail.can_retry;
        if (typeof rawDetail.next_step === "string") normalized.next_step = rawDetail.next_step;
        if (Object.keys(normalized).length > 0) detail = normalized;
      }
      const message =
        detail && typeof detail.message === "string"
          ? detail.message
          : "方案工作台未能完成本次操作。";
      throw new ProtocolWorkspaceApiError(message, {
        status: response.status,
        detail,
      });
    }
    return payload;
  };

  const post = (path, body, signal) =>
    request(path, {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

  const get = (path, signal) => request(path, { method: "GET", signal });
  const sourcePath = (projectId) =>
    `/api/projects/${projectPath(projectId)}/protocol-workflow/sources`;

  const intakePath = (projectId) =>
    `/api/projects/${projectPath(projectId)}/protocol-workflow/research-intake`;

  return {
    startResearchIntake(projectId, { userBrief = "", sourceArtifactIds = [] }, { signal } = {}) {
      return post(intakePath(projectId), {
        user_brief: userBrief, source_artifact_ids: sourceArtifactIds,
      }, signal);
    },
    getResearchIntake(projectId, workflowRunId, { signal } = {}) {
      return get(`${intakePath(projectId)}/${encodeURIComponent(String(workflowRunId))}`, signal);
    },
    importSource(projectId, { file, logicalSourceKey, sourceRole, sourceVersion, jurisdiction }, { signal } = {}) {
      const form = new FormData();
      form.append("file", file, file.name || "source.docx");
      form.append("logical_source_key", logicalSourceKey);
      form.append("source_role", sourceRole);
      if (sourceVersion) form.append("source_version", sourceVersion);
      if (jurisdiction) form.append("jurisdiction", jurisdiction);
      return request(sourcePath(projectId), { method: "POST", body: form, signal });
    },
    listSources(projectId, { signal } = {}) {
      return get(sourcePath(projectId), signal);
    },
    correctSourceMetadata(projectId, sourceArtifactId, metadata, { signal } = {}) {
      return request(`${sourcePath(projectId)}/${encodeURIComponent(String(sourceArtifactId))}/metadata`, {
        method: "PATCH", signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(metadata),
      });
    },
    getSourceParse(projectId, sourceArtifactId, { signal } = {}) {
      return get(`${sourcePath(projectId)}/${encodeURIComponent(String(sourceArtifactId))}/parse`, signal);
    },
    sourceDownloadUrl(projectId, sourceArtifactId) {
      return `${sourcePath(projectId)}/${encodeURIComponent(String(sourceArtifactId))}/content`;
    },
    createStudyDefinition(projectId, payload, { signal } = {}) {
      return post(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions`,
        payload,
        signal,
      );
    },
    applyStudyDecision(projectId, studyDefinitionId, payload, { signal } = {}) {
      return post(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}/decisions`,
        payload,
        signal,
      );
    },
    getStudyDefinition(projectId, studyDefinitionId, { signal } = {}) {
      return get(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}`,
        signal,
      );
    },
    getStudyDefinitionEvents(projectId, studyDefinitionId, { signal } = {}) {
      return get(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}/events`,
        signal,
      );
    },
    getDecisionGraph(projectId, studyDefinitionId, { signal } = {}) {
      return get(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}/decision-graph`,
        signal,
      );
    },
    getWorkflowRun(projectId, workflowRunId, { signal } = {}) {
      return get(`${workflowPath(projectId, workflowRunId)}`, signal);
    },
    getWorkflowRunProgress(projectId, workflowRunId, studyDefinitionId, { signal } = {}) {
      return get(
        `${workflowPath(projectId, workflowRunId)}/progress?study_definition_id=${encodeURIComponent(String(studyDefinitionId))}`,
        signal,
      );
    },
    getWorkflowRunGates(projectId, workflowRunId, studyDefinitionId, { signal } = {}) {
      return get(
        `${workflowPath(projectId, workflowRunId)}/gates?study_definition_id=${encodeURIComponent(String(studyDefinitionId))}`,
        signal,
      );
    },
    getWorkflowRunDecisionRequests(projectId, workflowRunId, studyDefinitionId, { signal } = {}) {
      return get(
        `${workflowPath(projectId, workflowRunId)}/decision-requests?study_definition_id=${encodeURIComponent(String(studyDefinitionId))}`,
        signal,
      );
    },
    pinRunManifest(projectId, workflowRunId, payload, { signal } = {}) {
      return post(`${workflowPath(projectId, workflowRunId)}/manifest`, payload, signal);
    },
    decomposeWorkPackages(projectId, workflowRunId, payload, { signal } = {}) {
      return post(`${workflowPath(projectId, workflowRunId)}/decomposition`, payload, signal);
    },
  };
}
