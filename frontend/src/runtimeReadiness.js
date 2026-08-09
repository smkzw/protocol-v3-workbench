export const runtimeExpectation = Object.freeze(__WORKBENCH_RUNTIME_EXPECTATION__);

export function assessRuntimeReadiness(payload, { httpOk = true, httpStatus = 200 } = {}) {
  const reasons = [];
  if (!httpOk) {
    reasons.push(
      httpStatus > 0
        ? `运行环境检查未通过（HTTP ${httpStatus}），当前后端未提供兼容性合同`
        : "无法连接运行环境检查接口",
    );
  } else if (!payload || typeof payload !== "object") {
    reasons.push("未收到可识别的运行时准备信息");
  } else {
    if (payload.runtime_contract_schema !== runtimeExpectation.runtimeContractSchema) {
      reasons.push("运行时合同结构与当前前端不一致");
    }
    if (payload.api_contract_version !== runtimeExpectation.apiContractVersion) {
      reasons.push("前后端 API 合同版本不一致");
    }
    if (payload.backend_build_id !== runtimeExpectation.expectedBackendBuildId) {
      reasons.push("后端构建与当前前端构建不一致");
    }
    if (payload.ready !== true) {
      reasons.push("后端尚未满足医学写作必需能力");
    }
    if (Array.isArray(payload.missing_capabilities) && payload.missing_capabilities.length) {
      reasons.push(`缺少必需能力：${payload.missing_capabilities.join("、")}`);
    }
  }
  return {
    ready: reasons.length === 0,
    reasons: [...new Set(reasons)],
    payload: payload && typeof payload === "object" ? payload : null,
  };
}

export function installApiContractFetch(target = globalThis) {
  if (!target?.fetch || target.__workbenchContractFetchInstalled) return;
  const nativeFetch = target.fetch.bind(target);
  target.fetch = (input, init = {}) => {
    const rawUrl = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input?.url || "";
    const currentOrigin = target.location?.origin || "http://127.0.0.1";
    const resolved = new URL(rawUrl, currentOrigin);
    if (resolved.origin !== currentOrigin || !resolved.pathname.startsWith("/api/")) {
      return nativeFetch(input, init);
    }
    const requestHeaders = typeof Request !== "undefined" && input instanceof Request
      ? input.headers
      : undefined;
    const headers = new Headers(requestHeaders);
    new Headers(init.headers || {}).forEach((value, key) => headers.set(key, value));
    headers.set(runtimeExpectation.clientContractHeader, runtimeExpectation.apiContractVersion);
    headers.set("X-Workbench-Frontend-Build", runtimeExpectation.frontendBuildId);
    return nativeFetch(input, { ...init, headers });
  };
  target.__workbenchContractFetchInstalled = true;
}
