export class MedicalMonitoringAssuranceApiError extends Error {
  constructor(message, { status = 0, detail = null } = {}) {
    super(message);
    this.name = "MedicalMonitoringAssuranceApiError";
    this.status = status;
    this.detail = detail;
  }
}

function projectPath(projectId) {
  return encodeURIComponent(String(projectId || ""));
}

function taskPath(projectId, taskId = "") {
  return `/api/projects/${projectPath(projectId)}/monitoring/assurance/tasks/${encodeURIComponent(String(taskId))}`;
}

function serverOwnedTaskActionPayload(payload = {}) {
  const next = payload && typeof payload === "object" && !Array.isArray(payload)
    ? { ...payload }
    : {};
  // The backend derives actor/confirmed_by from its verified principal. Keep
  // transitional client identity fields out of every feature-owned action.
  delete next.actor;
  delete next.confirmed_by;
  return next;
}

export function createMedicalMonitoringAssuranceApi({ fetchImpl = globalThis.fetch } = {}) {
  if (typeof fetchImpl !== "function") {
    throw new MedicalMonitoringAssuranceApiError("当前环境不支持医学监查保障 API 请求。");
  }

  const request = async (path, options = {}) => {
    let response;
    try {
      response = await fetchImpl(path, {
        ...options,
        headers: { Accept: "application/json", ...(options.headers || {}) },
      });
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      throw new MedicalMonitoringAssuranceApiError(error?.message || "医学监查保障 API 请求失败。");
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload?.detail;
      const message = typeof detail === "object" ? detail.message : detail;
      throw new MedicalMonitoringAssuranceApiError(
        message || `医学监查保障 API ${response.status}`,
        { status: response.status, detail: payload },
      );
    }
    return payload;
  };

  return {
    listTasks(projectId, { mode = "", signal } = {}) {
      const query = mode ? `?mode=${encodeURIComponent(mode)}` : "";
      return request(`/api/projects/${projectPath(projectId)}/monitoring/assurance/tasks${query}`, { signal });
    },
    getTask(projectId, taskId, { signal } = {}) {
      return request(taskPath(projectId, taskId), { signal });
    },
    getAudit(projectId, taskId, { signal } = {}) {
      return request(`${taskPath(projectId, taskId)}/audit`, { signal });
    },
    evaluateReadiness(projectId, taskId, payload, { signal } = {}) {
      return request(`${taskPath(projectId, taskId)}/readiness`, {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    },
    recordFullRecomputeProof(projectId, taskId, payload, { signal } = {}) {
      return request(`${taskPath(projectId, taskId)}/full-recompute-proof`, {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(serverOwnedTaskActionPayload(payload)),
      });
    },
    generateRollups(projectId, taskId, payload, { signal } = {}) {
      return request(`${taskPath(projectId, taskId)}/rollups`, {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(serverOwnedTaskActionPayload(payload)),
      });
    },
    recordMedicalReview(projectId, taskId, payload, { signal } = {}) {
      return request(`${taskPath(projectId, taskId)}/medical-review`, {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(serverOwnedTaskActionPayload(payload)),
      });
    },
    completeTask(projectId, taskId, payload, { signal } = {}) {
      return request(`${taskPath(projectId, taskId)}/complete`, {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(serverOwnedTaskActionPayload(payload)),
      });
    },
    getProof(projectId, taskId, { signal } = {}) {
      return request(`${taskPath(projectId, taskId)}/full-recompute-proof`, { signal });
    },
    getRollups(projectId, taskId, { signal } = {}) {
      return request(`${taskPath(projectId, taskId)}/rollups`, { signal });
    },
    createTask(projectId, payload, { signal } = {}) {
      return request(`/api/projects/${projectPath(projectId)}/monitoring/assurance/tasks`, {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    },
  };
}
