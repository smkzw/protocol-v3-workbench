import test from "node:test";
import assert from "node:assert/strict";
import { createProtocolWorkspaceApi } from "./protocolWorkspaceApi.mjs";

test("regimen design uses the stored seed and preserves lookup versus execution", async () => {
  const calls = [];
  const api = createProtocolWorkspaceApi({ fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 200, json: async () => ({ workflow_run_id: "regimen:one" }) };
  } });
  const signal = new AbortController().signal;
  await api.startRegimenDesign("project/one", "seed:one", { signal });
  await api.recoverRegimenDesign("project/one", "seed:one", { signal });
  await api.getRegimenDesign("project/one", "regimen:one", { signal });
  await api.resumeRegimenDesign("project/one", "regimen:one", { signal });
  const base = "/api/projects/project%2Fone/protocol-workflow/design/regimen";
  assert.deepEqual(calls.map(call => call.url), [base, base + "/recover", base + "/regimen%3Aone", base + "/regimen%3Aone/resume"]);
  assert.deepEqual(calls.map(call => call.options.method), ["POST", "POST", "GET", "POST"]);
  assert.deepEqual(JSON.parse(calls[0].options.body), { seed_run_id: "seed:one" });
  assert.deepEqual(JSON.parse(calls[1].options.body), { seed_run_id: "seed:one" });
  assert.deepEqual(JSON.parse(calls[3].options.body), {});
  assert.ok(calls.every(call => call.options.signal === signal));
  const intent = { operation_id: "operation:one", expected_revision: 2, snapshot_sha256: "a".repeat(64) };
  await api.adoptRegimenDesign("project/one", "regimen:one", intent, { signal });
  assert.equal(calls[4].url, base + "/regimen%3Aone/adopt");
  assert.deepEqual(JSON.parse(calls[4].options.body), intent);
  await api.recoverRegimenAdoption("project/one", "regimen:one", intent, { signal });
  assert.equal(calls[5].url, base + "/regimen%3Aone/adopt/recover");
  assert.deepEqual(JSON.parse(calls[5].options.body), intent);
});

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

test("research context lists selected inputs and recovers original writes", async () => {
  const calls=[];
  const api=createProtocolWorkspaceApi({fetchImpl:async(url,options)=>{
    calls.push({url,options});return {ok:true,status:200,json:async()=>({studies:[]})};
  }});
  const intent={seed_run_id:'seed:one',operation_id:'operation:one',actor_id:'medical_manager',decided_at:'2026-09-13T08:00:00Z'};
  await api.listResearchStudies('project/one','seed:one');
  await api.createResearchContext('project/one',intent);
  await api.recoverResearchContext('project/one',intent);
  await api.updateResearchInputs('project/one','study:one',intent);
  await api.recoverResearchInputs('project/one','study:one',intent);
  const root='/api/projects/project%2Fone/protocol-workflow/design/regimen/study-context';
  assert.deepEqual(calls.map(c=>c.url),[root+'?seed_run_id=seed%3Aone',root,root+'/recover',
    root+'/study%3Aone/inputs',root+'/study%3Aone/inputs/recover']);
  assert.equal(calls[0].options.method,'GET');
  for(const call of calls.slice(1)) assert.deepEqual(JSON.parse(call.options.body),intent);
});

test('study-bound design transports the same prepared identity for start and recovery', async()=>{
  const calls=[];
  const api=createProtocolWorkspaceApi({fetchImpl:async(url,options)=>{
    calls.push({url,options});return {ok:true,status:200,json:async()=>({})};
  }});
  const intent={seed_run_id:'seed:one',study_definition_id:'study:one',expected_workflow_run_id:'regimen:original'};
  await api.prepareRegimenDesign('project/one','seed:one','study:one');
  await api.startRegimenDesign('project/one',intent);
  await api.recoverRegimenDesign('project/one',intent);
  const root='/api/projects/project%2Fone/protocol-workflow/design/regimen';
  assert.deepEqual(calls.map(c=>c.url),[root+'/prepare',root,root+'/recover']);
  assert.deepEqual(JSON.parse(calls[0].options.body),{seed_run_id:'seed:one',study_definition_id:'study:one'});
  for(const c of calls.slice(1))assert.deepEqual(JSON.parse(c.options.body),intent);
});

test('basic research information preserves original adoption and recovery intent', async () => {
  const calls=[];
  const api=createProtocolWorkspaceApi({fetchImpl:async (url,options)=>{
    calls.push({url,options});return {ok:true,status:200,json:async()=>({})};
  }});
  const intent={seed_run_id:'seed:one',selections:{clinical_phase:0},operation_id:'operation:one'};
  const signal=new AbortController().signal;
  await api.adoptResearchInformation('project/one',intent,{signal});
  await api.recoverResearchInformation('project/one',intent,{signal});
  assert.deepEqual(calls.map(c=>c.url),[
    '/api/projects/project%2Fone/protocol-workflow/design/regimen/research-information',
    '/api/projects/project%2Fone/protocol-workflow/design/regimen/research-information/recover']);
  assert.ok(calls.every(c=>c.options.method==='POST'&&c.options.signal===signal));
  assert.deepEqual(JSON.parse(calls[1].options.body),intent);
});
test('manuscript preparation reads current research without sending invented facts', async () => {
  const calls=[];
  const api=createProtocolWorkspaceApi({fetchImpl:async(url,options)=>{
    calls.push({url,options});return {ok:true,status:200,json:async()=>({scope:'chapter_fact_readiness'})};
  }});
  const signal=new AbortController().signal;
  const result=await api.getManuscriptPlan('project/one','study:one',{signal});
  assert.equal(result.scope,'chapter_fact_readiness');
  assert.equal(calls[0].url,'/api/projects/project%2Fone/protocol-workflow/study-definitions/study%3Aone/manuscript-plan');
  assert.equal(calls[0].options.method,'GET');
  assert.equal(calls[0].options.signal,signal);
  assert.equal(calls[0].options.body,undefined);
});

test('manuscript sources and chapter generation preserve original identities and recovery', async () => {
  const calls=[];
  const api=createProtocolWorkspaceApi({fetchImpl:async(url,options)=>{
    calls.push({url,options});return {ok:true,status:200,json:async()=>({})};
  }});
  const signal=new AbortController().signal;
  const preparation={source_run_id:'sources:one',study_revision_sha256:'a'.repeat(64)};
  const intent={...preparation,expected_workflow_run_id:'chapter:original'};
  await api.prepareManuscriptSources('project/one','study:one','seed:one',{signal});
  await api.getManuscriptSources('project/one','sources:one',{signal});
  await api.resumeManuscriptSources('project/one','sources:one',{signal});
  await api.retryManuscriptSources('project/one','sources:one','retry:one',{signal});
  await api.prepareChapterDraft('project/one','study:one','node/one',preparation,{signal});
  await api.startChapterDraft('project/one','study:one','node/one',intent,{signal});
  await api.recoverChapterDraft('project/one','study:one','node/one',intent,{signal});
  const base='/api/projects/project%2Fone/protocol-workflow';
  const chapter=base+'/study-definitions/study%3Aone/chapters/node%2Fone/draft';
  assert.deepEqual(calls.map(c=>c.url),[
    base+'/study-definitions/study%3Aone/manuscript-sources',base+'/manuscript-sources/sources%3Aone',
    base+'/manuscript-sources/sources%3Aone/resume',base+'/manuscript-sources/sources%3Aone/retry',
    chapter+'/prepare',chapter,chapter+'/recover']);
  assert.deepEqual(calls.map(c=>c.options.method),['POST','GET','POST','POST','POST','POST','POST']);
  assert.deepEqual(JSON.parse(calls[0].options.body),{seed_run_id:'seed:one'});
  assert.deepEqual(JSON.parse(calls[3].options.body),{retry_decision_id:'retry:one'});
  assert.deepEqual(JSON.parse(calls[4].options.body),preparation);
  for(const call of calls.slice(5))assert.deepEqual(JSON.parse(call.options.body),intent);
  assert.ok(calls.every(c=>c.options.signal===signal));
});
