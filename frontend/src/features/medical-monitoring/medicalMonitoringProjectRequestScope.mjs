function normalizedProjectId(value) {
  return String(value || "").trim();
}

export function createMedicalMonitoringProjectRequestScope(projectId) {
  const boundProjectId = normalizedProjectId(projectId);
  if (!boundProjectId) {
    throw new TypeError("projectId is required");
  }

  const activeRequests = new Map();
  let disposed = false;

  function begin(key) {
    const requestKey = String(key || "").trim();
    if (!requestKey) {
      throw new TypeError("request key is required");
    }

    activeRequests.get(requestKey)?.controller.abort();
    const controller = new AbortController();
    const request = {
      controller,
      key: requestKey,
      projectId: boundProjectId,
      signal: controller.signal,
    };
    if (disposed) {
      controller.abort();
      return request;
    }
    activeRequests.set(requestKey, request);
    return request;
  }

  function activate() {
    disposed = false;
  }

  function isCurrent(request) {
    return Boolean(
      !disposed
      && request
      && request.projectId === boundProjectId
      && !request.signal.aborted
      && activeRequests.get(request.key) === request,
    );
  }

  function finish(request) {
    if (request && activeRequests.get(request.key) === request) {
      activeRequests.delete(request.key);
    }
  }

  function cancel(key) {
    const requestKey = String(key || "").trim();
    const request = activeRequests.get(requestKey);
    if (!request) return;
    request.controller.abort();
    activeRequests.delete(requestKey);
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    activeRequests.forEach((request) => request.controller.abort());
    activeRequests.clear();
  }

  return {
    activate,
    begin,
    cancel,
    dispose,
    finish,
    isCurrent,
    projectId: boundProjectId,
  };
}
