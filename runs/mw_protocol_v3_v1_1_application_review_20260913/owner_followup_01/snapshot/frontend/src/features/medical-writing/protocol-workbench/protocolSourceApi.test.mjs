import test from "node:test";
import assert from "node:assert/strict";
import { createProtocolWorkspaceApi } from "./protocolWorkspaceApi.mjs";

test("metadata correction changes descriptors without uploading file bytes", async () => {
  const metadata = { source_role: "company_style_only", source_version: "1.3", jurisdiction: "CN" };
  const api = createProtocolWorkspaceApi({ fetchImpl: async (url, options) => {
    assert.equal(url, "/api/projects/one/protocol-workflow/sources/source%3Aold/metadata");
    assert.equal(options.method, "PATCH");
    assert.equal(options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(options.body), metadata);
    return { ok: true, status: 200, json: async () => ({ replayed: false }) };
  } });
  assert.deepEqual(await api.correctSourceMetadata("one", "source:old", metadata), { replayed: false });
});

test("source upload preserves bytes and lets the browser provide multipart boundary", async () => {
  const file = new Blob(["source bytes"], { type: "application/octet-stream" });
  const api = createProtocolWorkspaceApi({ fetchImpl: async (url, options) => {
    assert.equal(url, "/api/projects/project%2Fone/protocol-workflow/sources");
    assert.equal(options.headers["Content-Type"], undefined);
    assert.equal(await options.body.get("file").text(), "source bytes");
    assert.equal(options.body.get("source_role"), "project_primary");
    assert.equal(options.body.get("source_version"), null);
    return { ok: true, status: 200, json: async () => ({ replayed: false }) };
  } });
  assert.deepEqual(await api.importSource("project/one", {
    file, logicalSourceKey: "ib", sourceRole: "project_primary",
  }), { replayed: false });
});

test("source conflict retains the server's actionable explanation", async () => {
  const api = createProtocolWorkspaceApi({ fetchImpl: async () => ({
    ok: false, status: 409, json: async () => ({ detail: {
      message: "原记录已保留，请核对版本。", next_step: "按原记录继续。",
    } }),
  }) });
  await assert.rejects(api.listSources("project"), (error) => {
    assert.equal(error.status, 409);
    assert.equal(error.message, "原记录已保留，请核对版本。");
    return true;
  });
});

test("parse and original download use the selected immutable source", async () => {
  const calls = [];
  const api = createProtocolWorkspaceApi({ fetchImpl: async (url) => {
    calls.push(url); return { ok: true, status: 200, json: async () => ({ blocks: [] }) };
  } });
  await api.getSourceParse("one", "source:old");
  assert.equal(calls[0], "/api/projects/one/protocol-workflow/sources/source%3Aold/parse");
  assert.equal(api.sourceDownloadUrl("one", "source:old"),
    "/api/projects/one/protocol-workflow/sources/source%3Aold/content");
});

test("research intake carries selected identities and reads the same durable job", async () => {
  const calls = [];
  const api = createProtocolWorkspaceApi({ fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 202, json: async () => ({ workflow_run_id: "seed:one" }) };
  } });
  const controller = new AbortController();
  const response = await api.startResearchIntake("project/one", {
    userBrief: "保持这段说明", sourceArtifactIds: ["source:one"],
  }, { signal: controller.signal });
  assert.equal(response.workflow_run_id, "seed:one");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    user_brief: "保持这段说明", source_artifact_ids: ["source:one"],
  });
  assert.equal(calls[0].options.signal, controller.signal);
  assert.equal(calls[0].url, "/api/projects/project%2Fone/protocol-workflow/research-intake");
  await api.getResearchIntake("project/one", response.workflow_run_id);
  assert.equal(calls[1].options.method, "GET");
  assert.equal(calls[1].url, "/api/projects/project%2Fone/protocol-workflow/research-intake/seed%3Aone");
  await api.resumeResearchIntake("project/one", "seed:one");
  assert.equal(calls[2].options.method, "POST");
  assert.equal(calls[2].url, "/api/projects/project%2Fone/protocol-workflow/research-intake/seed%3Aone/resume");
  await api.recoverResearchIntake("project/one", { userBrief: "原说明", sourceArtifactIds: ["source:old"] });
  assert.equal(calls[3].url, "/api/projects/project%2Fone/protocol-workflow/research-intake/recover");
  assert.deepEqual(JSON.parse(calls[3].options.body), { user_brief: "原说明", source_artifact_ids: ["source:old"] });
});
