import { afterEach, describe, expect, it, vi } from "vitest";

import {
  assessRuntimeReadiness,
  loadDevRuntimeExpectation,
  runtimeExpectation,
} from "./runtimeReadiness";

const matchingPayload = (expectation = runtimeExpectation) => ({
  runtime_contract_schema: expectation.runtimeContractSchema,
  api_contract_version: expectation.apiContractVersion,
  backend_build_id: expectation.expectedBackendBuildId,
  ready: true,
  missing_capabilities: [],
});

const LIVE_TREE_EXPECTATION = {
  ...runtimeExpectation,
  expectedBackendBuildId: "api-livetree000000000000",
};

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("medical writing runtime readiness gate contract", () => {
  it("keeps a fully matching payload ready with no warnings", () => {
    const result = assessRuntimeReadiness(matchingPayload());
    expect(result.ready).toBe(true);
    expect(result.reasons).toEqual([]);
    expect(result.warnings).toEqual([]);
  });

  it("treats a backend build drift as a warning instead of a blocker (AGG25-P0-1)", () => {
    const result = assessRuntimeReadiness({
      ...matchingPayload(),
      backend_build_id: "api-drifted000000000000",
    });
    expect(result.ready).toBe(true);
    expect(result.reasons).toEqual([]);
    expect(result.warnings.length).toBeGreaterThan(0);
    expect(result.warnings.join("\n")).toContain("构建不一致");
  });

  it("still blocks on contract version, schema, readiness, and capability gaps", () => {
    const contract = assessRuntimeReadiness({
      ...matchingPayload(),
      api_contract_version: "some-other-version",
    });
    expect(contract.ready).toBe(false);
    expect(contract.reasons.join("\n")).toContain("API 合同版本不一致");

    const schema = assessRuntimeReadiness({
      ...matchingPayload(),
      runtime_contract_schema: "some-other-schema",
    });
    expect(schema.ready).toBe(false);

    const notReady = assessRuntimeReadiness({ ...matchingPayload(), ready: false });
    expect(notReady.ready).toBe(false);

    const capabilities = assessRuntimeReadiness({
      ...matchingPayload(),
      missing_capabilities: ["translation_body"],
    });
    expect(capabilities.ready).toBe(false);
    expect(capabilities.reasons.join("\n")).toContain("缺少必需能力");
  });

  // NEW-4（R27 第1轮末修订）：dev 模式下期望指纹必须来自每次请求现算的
  // /runtime-build.json（当前源码树），而不是 vite 启动时 define 固化的旧值。
  // 反例（R27 现场）：后端已重启吃到新码，vite 仍持旧期望 → 漂移横幅常驻
  // 且刷新无效。dev 拉取同源 live 期望后，"运行中后端 == 当前源码树" 必须
  // 判定为无后端漂移。
  it("NEW-4: dev live expectation matching the running backend yields no drift warning", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...runtimeExpectation })));
    const dev = await loadDevRuntimeExpectation({ dev: true });
    expect(dev.live).toBe(true);
    const result = assessRuntimeReadiness(matchingPayload(dev.expectation), {
      expectation: dev.expectation,
      driftHint: dev.driftHint,
    });
    expect(result.ready).toBe(true);
    expect(result.warnings).toEqual([]);
  });

  // vite 启动早于代码变更（R27 现场方向）：live 期望 ≠ vite 启动时期望时，
  // 即便运行中后端已是新码，也要有一条指名"重启vite"的独立告警——横幅指向
  // 正确的重启对象，而不是泛泛的"刷新页面或同步前后端"。
  it("P2-38: vite startup fingerprint drift is no longer a banner condition", async () => {
    // 修订（批三A）：vite启动指纹落后于源码树不再作为横幅硬条件——运行中
    // 后端与当前源码树一致即无警示（此前常驻『请重启vite』横幅功能无损）。
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(LIVE_TREE_EXPECTATION)));
    const dev = await loadDevRuntimeExpectation({ dev: true });
    expect(dev.viteDriftWarning || "").toBe("");
    const result = assessRuntimeReadiness(matchingPayload(dev.expectation), {
      expectation: dev.expectation,
      driftHint: dev.driftHint,
    });
    expect(result.ready).toBe(true);
    expect(result.warnings).toEqual([]);
  });

  // 反方向（vite 树与当前树一致、后端旧）：提示给状态说明与升级路径。
  // 第2轮修订（NEW-7 残留去越权）：不指挥用户重启服务（测试者无服务
  // 权限，红线3），改为『服务同步中，请稍后刷新或联系集成人』；同时
  // 保留不误导去重启 vite 的旧约束。
  it("NEW-4: stale backend (startup tree equals live tree) reports sync state without commanding a restart", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...runtimeExpectation })));
    const dev = await loadDevRuntimeExpectation({ dev: true });
    expect(dev.live).toBe(true);
    expect(dev.expectation.expectedBackendBuildId).toBe(runtimeExpectation.expectedBackendBuildId);
    expect(dev.viteDriftWarning || "").toBe("");
    const result = assessRuntimeReadiness(
      matchingPayload({ ...runtimeExpectation, expectedBackendBuildId: "api-stalebackend00000" }),
      { expectation: dev.expectation, driftHint: dev.driftHint },
    );
    expect(result.ready).toBe(true);
    expect(result.warnings.join("\n")).toContain("服务同步中");
    expect(result.warnings.join("\n")).toContain("联系集成人");
    expect(result.warnings.join("\n")).not.toContain("重启");
    expect(result.warnings.join("\n")).not.toContain("重启vite");
  });

  // prod（非 dev）不拉取 /runtime-build.json，仍用 define 注入的期望。
  it("NEW-4: prod keeps the define-injected expectation and never fetches", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const dev = await loadDevRuntimeExpectation({ dev: false });
    expect(dev.live).toBe(false);
    expect(dev.expectation).toBe(runtimeExpectation);
    expect(dev.driftHint).toBe("");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // /runtime-build.json 取不到时回退 define 期望且不产生指引（不误报）。
  it("NEW-4: dev falls back to the define expectation when the endpoint is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "no" }, { ok: false, status: 404 })));
    const dev = await loadDevRuntimeExpectation({ dev: true });
    expect(dev.live).toBe(false);
    expect(dev.expectation).toBe(runtimeExpectation);
    expect(dev.driftHint).toBe("");
  });
});
