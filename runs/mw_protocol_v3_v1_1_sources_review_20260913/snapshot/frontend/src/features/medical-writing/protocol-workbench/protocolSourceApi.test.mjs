import test from "node:test";
import assert from "node:assert/strict";
import { createProtocolWorkspaceApi } from "./protocolWorkspaceApi.mjs";

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
