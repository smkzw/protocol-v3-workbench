/* C03 scratch: protocolWorkspaceApi invalid-response edge probes (node:test). */
import test from "node:test";
import assert from "node:assert/strict";
import { createProtocolWorkspaceApi } from "../../../frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs";

test("C1 200 with invalid JSON body -> typed Chinese error, no leak of raw body", async () => {
  const api = createProtocolWorkspaceApi({ fetchImpl: async () => ({
    ok: true, status: 200, json: async () => { throw new SyntaxError("Unexpected token < in JSON"); },
  }) });
  await assert.rejects(api.listSources("p"), (error) => {
    assert.equal(error.name, "ProtocolWorkspaceApiError");
    assert.equal(error.status, 200);
    assert.equal(error.message, "方案工作台返回内容无法解析，本次请求未能完成。");
    assert.equal(error.detail, null);
    return true;
  });
});

test("C2 non-ok with string detail (FastAPI default) -> generic Chinese message, detail null", async () => {
  const api = createProtocolWorkspaceApi({ fetchImpl: async () => ({
    ok: false, status: 500, json: async () => ({ detail: "Internal Server Error" }),
  }) });
  await assert.rejects(api.listSources("p"), (error) => {
    assert.equal(error.status, 500);
    assert.equal(error.message, "方案工作台未能完成本次操作。");
    assert.equal(error.detail, null);
    return true;
  });
});

test("C3 non-ok detail object with audit-shaped keys -> only the four public fields survive", async () => {
  const api = createProtocolWorkspaceApi({ fetchImpl: async () => ({
    ok: false, status: 409,
    json: async () => ({ detail: {
      message: "资料已有变化。", next_step: "请刷新。", machine_code: "seed_source_selection_stale",
      object_id: "run-123", attempts: 3, owner: "agent1", recovery_action: "retry_later",
      can_retry: false,
    } }),
  }) });
  await assert.rejects(api.startResearchIntake("p", { userBrief: "", sourceArtifactIds: [] }), (error) => {
    assert.deepEqual(error.detail, {
      message: "资料已有变化。", next_step: "请刷新。", can_retry: false,
    });
    return true;
  });
});

test("C4 202 intake response missing body fields still resolves without inventing state", async () => {
  const api = createProtocolWorkspaceApi({ fetchImpl: async () => ({
    ok: true, status: 202, json: async () => ({}),
  }) });
  const payload = await api.startResearchIntake("p", { userBrief: "b", sourceArtifactIds: ["s"] });
  assert.deepEqual(payload, {});
});
