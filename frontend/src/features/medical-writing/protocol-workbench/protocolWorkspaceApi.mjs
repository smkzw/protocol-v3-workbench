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
 * clients never invent a catalog failure. A recognized manuscript-save conflict
 * carries a separate closed recoveryKind; display detail still has four fields.
 */

export class ProtocolWorkspaceApiError extends Error {
  constructor(message, { status = 0, detail = null, recoveryKind = null } = {}) {
    super(message);
    this.name = "ProtocolWorkspaceApiError";
    this.status = status;
    this.detail = detail;
    if (recoveryKind) this.recoveryKind = recoveryKind;
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
      // One internal recovery type, separate from the four display fields.
      // Do not propagate arbitrary machine/audit codes or infer from copy text.
      const recoveryKind = response.status === 409
        && path.endsWith('/manuscript-draft/save')
        && rawDetail?.code === 'manuscript_document_revision_changed'
        ? 'document_revision_changed' : null;
      throw new ProtocolWorkspaceApiError(message, {
        status: response.status,
        detail,
        recoveryKind,
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
  const regimenPath = projectId =>
    `/api/projects/${projectPath(projectId)}/protocol-workflow/design/regimen`;
  const elementsPath = projectId =>
    `/api/projects/${projectPath(projectId)}/protocol-workflow/design/elements`;
  const manuscriptSourcesPath = (projectId, runId) =>
    `/api/projects/${projectPath(projectId)}/protocol-workflow/manuscript-sources/${encodeURIComponent(String(runId))}`;
  const chapterPath = (projectId, studyId, nodeId) =>
    `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyId))}/chapters/${encodeURIComponent(String(nodeId))}/draft`;
  const manuscriptPath = (projectId, studyId) =>
    `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyId))}/manuscript-draft`;

  return {
    prepareManuscriptDraft(projectId, studyId, preparation, { signal } = {}) {
      return post(`${manuscriptPath(projectId, studyId)}/prepare`, preparation, signal);
    },
    startManuscriptDraft(projectId, studyId, intent, { signal } = {}) {
      return post(manuscriptPath(projectId, studyId), intent, signal);
    },
    recoverManuscriptDraft(projectId, studyId, intent, { signal } = {}) {
      return post(`${manuscriptPath(projectId, studyId)}/recover`, intent, signal);
    },
    prepareManuscriptSave(projectId, studyId, intent, { signal } = {}) {
      return post(`${manuscriptPath(projectId, studyId)}/save/prepare`, intent, signal);
    },
    saveManuscriptDraft(projectId, studyId, intent, { signal } = {}) {
      return post(`${manuscriptPath(projectId, studyId)}/save`, intent, signal);
    },
    recoverManuscriptSave(projectId, studyId, intent, { signal } = {}) {
      return post(`${manuscriptPath(projectId, studyId)}/save/recover`, intent, signal);
    },
    editManuscriptDraft(projectId, studyId, intent, { signal } = {}) {
      return post(`${manuscriptPath(projectId, studyId)}/edits`, intent, signal);
    },
    prepareManuscriptSourceIdentity(projectId, studyId, seedRunId, { signal } = {}) {
      return post(`/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyId))}/manuscript-sources/prepare`,
        { seed_run_id: seedRunId }, signal);
    },
    prepareManuscriptSources(projectId, studyId, seedRunId, { signal, expectedWorkflowRunId } = {}) {
      return post(`/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyId))}/manuscript-sources`,
        { seed_run_id: seedRunId, ...(expectedWorkflowRunId ? { expected_workflow_run_id: expectedWorkflowRunId } : {}) }, signal);
    },
    getManuscriptSources(projectId, runId, { signal } = {}) {
      return get(manuscriptSourcesPath(projectId, runId), signal);
    },
    resumeManuscriptSources(projectId, runId, { signal } = {}) {
      return post(`${manuscriptSourcesPath(projectId, runId)}/resume`, {}, signal);
    },
    retryManuscriptSources(projectId, runId, retryDecisionId, { signal } = {}) {
      return post(`${manuscriptSourcesPath(projectId, runId)}/retry`, { retry_decision_id: retryDecisionId }, signal);
    },
    prepareChapterDraft(projectId, studyId, nodeId, preparation, { signal } = {}) {
      return post(`${chapterPath(projectId, studyId, nodeId)}/prepare`, preparation, signal);
    },
    startChapterDraft(projectId, studyId, nodeId, intent, { signal } = {}) {
      return post(chapterPath(projectId, studyId, nodeId), intent, signal);
    },
    recoverChapterDraft(projectId, studyId, nodeId, intent, { signal } = {}) {
      return post(`${chapterPath(projectId, studyId, nodeId)}/recover`, intent, signal);
    },
    adoptResearchInformation(projectId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/research-information`, intent, signal);
    },
    recoverResearchInformation(projectId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/research-information/recover`, intent, signal);
    },
    listResearchStudies(projectId, seedRunId, { signal } = {}) {
      return get(`${regimenPath(projectId)}/study-context?seed_run_id=${encodeURIComponent(String(seedRunId))}`, signal);
    },
    createResearchContext(projectId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/study-context`, intent, signal);
    },
    recoverResearchContext(projectId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/study-context/recover`, intent, signal);
    },
    updateResearchInputs(projectId, studyId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/study-context/${encodeURIComponent(String(studyId))}/inputs`, intent, signal);
    },
    recoverResearchInputs(projectId, studyId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/study-context/${encodeURIComponent(String(studyId))}/inputs/recover`, intent, signal);
    },
    prepareRegimenDesign(projectId, seedRunId, studyDefinitionId, { signal } = {}) {
      return post(`${regimenPath(projectId)}/prepare`, {seed_run_id: seedRunId, study_definition_id: studyDefinitionId}, signal);
    },
    startRegimenDesign(projectId, intent, { signal } = {}) {
      return post(regimenPath(projectId), typeof intent === 'string' ? {seed_run_id: intent} : intent, signal);
    },
    recoverRegimenDesign(projectId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/recover`, typeof intent === 'string' ? {seed_run_id: intent} : intent, signal);
    },
    getRegimenDesign(projectId, workflowRunId, { signal } = {}) {
      return get(`${regimenPath(projectId)}/${encodeURIComponent(String(workflowRunId))}`, signal);
    },
    resumeRegimenDesign(projectId, workflowRunId, { signal } = {}) {
      return post(`${regimenPath(projectId)}/${encodeURIComponent(String(workflowRunId))}/resume`, {}, signal);
    },
    adoptRegimenDesign(projectId, workflowRunId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/${encodeURIComponent(String(workflowRunId))}/adopt`, intent, signal);
    },
    recoverRegimenAdoption(projectId, workflowRunId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/${encodeURIComponent(String(workflowRunId))}/adopt/recover`, intent, signal);
    },
    prepareDesignElements(projectId, seedRunId, studyDefinitionId, { signal } = {}) {
      return post(`${elementsPath(projectId)}/prepare`,
        { seed_run_id: seedRunId, study_definition_id: studyDefinitionId }, signal);
    },
    startDesignElements(projectId, intent, { signal } = {}) {
      return post(elementsPath(projectId), intent, signal);
    },
    recoverDesignElements(projectId, intent, { signal } = {}) {
      return post(`${elementsPath(projectId)}/recover`, intent, signal);
    },
    getDesignElements(projectId, workflowRunId, { signal, studyDefinitionId } = {}) {
      const suffix = studyDefinitionId ? `?study_definition_id=${encodeURIComponent(String(studyDefinitionId))}` : "";
      return get(`${elementsPath(projectId)}/${encodeURIComponent(String(workflowRunId))}${suffix}`, signal);
    },
    resumeDesignElements(projectId, workflowRunId, { signal } = {}) {
      return post(`${elementsPath(projectId)}/${encodeURIComponent(String(workflowRunId))}/resume`, {}, signal);
    },
    adoptDesignCard(projectId, workflowRunId, card, intent, { signal } = {}) {
      return post(`${elementsPath(projectId)}/${encodeURIComponent(String(workflowRunId))}/adopt/${encodeURIComponent(String(card))}`,
        intent, signal);
    },
    recoverDesignCard(projectId, workflowRunId, card, intent, { signal } = {}) {
      return post(`${elementsPath(projectId)}/${encodeURIComponent(String(workflowRunId))}/adopt/${encodeURIComponent(String(card))}/recover`,
        intent, signal);
    },
    adoptSeedCard(projectId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/seed-card`, intent, signal);
    },
    recoverSeedCard(projectId, intent, { signal } = {}) {
      return post(`${regimenPath(projectId)}/seed-card/recover`, intent, signal);
    },
    startResearchIntake(projectId, { userBrief = "", sourceArtifactIds = [] }, { signal } = {}) {
      return post(intakePath(projectId), {
        user_brief: userBrief, source_artifact_ids: sourceArtifactIds,
      }, signal);
    },
    recoverResearchIntake(projectId, { userBrief = "", sourceArtifactIds = [] }, { signal } = {}) {
      return post(`${intakePath(projectId)}/recover`, {
        user_brief: userBrief, source_artifact_ids: sourceArtifactIds,
      }, signal);
    },
    resumeResearchIntake(projectId, workflowRunId, { signal } = {}) {
      return post(`${intakePath(projectId)}/${encodeURIComponent(String(workflowRunId))}/resume`, {}, signal);
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
    getSemanticDocument(projectId, studyDefinitionId, documentId, { signal } = {}) {
      return get(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}/documents/${encodeURIComponent(String(documentId))}`,
        signal,
      );
    },
    getManuscriptPlan(projectId, studyDefinitionId, { signal } = {}) {
      return get(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}/manuscript-plan`,
        signal,
      );
    },
    deriveChapterFacts(projectId, studyDefinitionId, { signal } = {}) {
      return post(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}/manuscript-draft/chapter-facts/derive`,
        {}, signal,
      );
    },
    getSavedManuscriptDocument(projectId, studyDefinitionId, { signal } = {}) {
      return get(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}/manuscript-draft/saved`,
        signal,
      );
    },
    getChapterFactsStatus(projectId, studyDefinitionId, { signal } = {}) {
      return get(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}/manuscript-draft/chapter-facts/derive`,
        signal,
      );
    },
    getChapterFactsResidual(projectId, studyDefinitionId, { signal } = {}) {
      return get(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}/manuscript-draft/chapter-facts/residual`,
        signal,
      );
    },
    confirmChapterFactsResidual(projectId, studyDefinitionId, intent, { signal } = {}) {
      return post(
        `/api/projects/${projectPath(projectId)}/protocol-workflow/study-definitions/${encodeURIComponent(String(studyDefinitionId))}/manuscript-draft/chapter-facts/residual/confirm`,
        intent, signal,
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
