/* global __WORKBENCH_RUNTIME_EXPECTATION__ -- build-time injected define */
export const runtimeExpectation = Object.freeze(__WORKBENCH_RUNTIME_EXPECTATION__);

// NEW-4（R27 第1轮末修订）：dev 下 vite 启动时 define 固化的期望指纹会落后于
// 代码变更（改后端代码不重启 vite 则永远不更新），造成"漂移横幅常驻且刷新
// 无效"。dev 模式改为每次就绪检查时拉取同源 /runtime-build.json —— 该端点
// 由 vite 中间件按当前源码树逐请求现算（见 vite.config.mjs）——作为比对基准；
// prod 仍用 define 注入值（bundle 内固化为产物指纹与请求头注入）。
export async function loadDevRuntimeExpectation({ dev = Boolean(import.meta.env?.DEV) } = {}) {
  if (!dev) {
    return { expectation: runtimeExpectation, driftHint: "", live: false };
  }
  try {
    const response = await fetch("/runtime-build.json", { cache: "no-store" });
    if (!response.ok) return { expectation: runtimeExpectation, driftHint: "", live: false };
    const live = await response.json();
    if (!live || typeof live !== "object" || !live.expectedBackendBuildId) {
      return { expectation: runtimeExpectation, driftHint: "", live: false };
    }
    // P2-38（批三A）：横幅判定只看『运行中后端 buildid 落后于当前源码树』
    // （payload.backend_build_id vs live 期望，见 assessRuntimeReadiness）。
    // vite 启动指纹落后不再作为横幅条件——dev 下比对基准本就取自当前
    // 源码树（/runtime-build.json），vite 是否重启不影响判定正确性。
    return {
      expectation: Object.freeze({ ...runtimeExpectation, ...live }),
      live: true,
      driftHint: "请重启本子系统后端(5301)后刷新页面",
    };
  } catch {
    return { expectation: runtimeExpectation, driftHint: "", live: false };
  }
}

export function assessRuntimeReadiness(payload, {
  httpOk = true,
  httpStatus = 200,
  expectation = runtimeExpectation,
  driftHint = "",
} = {}) {
  const reasons = [];
  const warnings = [];
  if (!httpOk) {
    reasons.push(
      httpStatus > 0
        ? `运行环境检查未通过（HTTP ${httpStatus}），当前后端未提供兼容性合同`
        : "无法连接运行环境检查接口",
    );
  } else if (!payload || typeof payload !== "object") {
    reasons.push("未收到可识别的运行时准备信息");
  } else {
    if (payload.runtime_contract_schema !== expectation.runtimeContractSchema) {
      reasons.push("运行时合同结构与当前前端不一致");
    }
    if (payload.api_contract_version !== expectation.apiContractVersion) {
      reasons.push("前后端 API 合同版本不一致");
    }
    if (payload.backend_build_id !== expectation.expectedBackendBuildId) {
      // AGG25-P0-1: a pure backend rebuild must never deadlock the whole
      // workspace — build fingerprint drift is advisory; the hard gate keeps
      // contract schema/version, readiness and capability checks.
      // NEW-4: 文案给出可执行的处置指引（重启对象），不再让用户猜。
      warnings.push(
        `前后端构建不一致（当前源码树期望 ${expectation.expectedBackendBuildId}，`
        + `运行中后端 ${payload.backend_build_id || "未知"}）`
        + `${driftHint ? `——${driftHint}` : "，可能缺少最新修复，建议刷新页面或同步前后端"}`,
      );
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
    warnings: [...new Set(warnings)],
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
