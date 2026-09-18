import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RegimenDesignWorkspace } from "./RegimenDesignWorkspace";

const done = { workflow_run_id: "design:one", status: "needs_information", can_resume: false,
  validation: { valid: true, proposal: { regimen: null, questions: ["请补充研究给药途径。"], coverage: [] } } };
afterEach(() => { cleanup(); localStorage.clear(); });
it("starts from a saved seed once and restores the same result without generation", async () => {
  const api = { startRegimenDesign: vi.fn(async () => done), getRegimenDesign: vi.fn(async () => done) };
  const view = render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" api={api} />);
  fireEvent.click(screen.getByRole("button", { name: "整理完整给药建议" }));
  await screen.findByText("请补充研究给药途径。");
  expect(api.startRegimenDesign.mock.calls[0].slice(0, 2)).toEqual(["one", "seed:one"]);
  view.unmount();
  render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" api={api} />);
  await screen.findByText("请补充研究给药途径。");
  expect(api.startRegimenDesign).toHaveBeenCalledTimes(1);
});
it("looks up a lost acknowledgement and never automatically starts again", async () => {
  const api = { startRegimenDesign: vi.fn(async () => { throw new Error("连接中断，记录待核对。"); }),
    recoverRegimenDesign: vi.fn(async () => done), getRegimenDesign: vi.fn(async () => done) };
  const view = render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" api={api} />);
  fireEvent.click(screen.getByRole("button", { name: "整理完整给药建议" }));
  await screen.findByText("连接中断，记录待核对。");
  expect(screen.queryByRole("button", { name: "整理完整给药建议" })).toBeNull();
  view.unmount();
  render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" api={api} />);
  await screen.findByText("请补充研究给药途径。");
  expect(api.recoverRegimenDesign).toHaveBeenCalledTimes(1);
  expect(api.startRegimenDesign).toHaveBeenCalledTimes(1);
});
it("does not apply a late response to a different seed", async () => {
  let finish;
  const api = { startRegimenDesign: vi.fn(() => new Promise(resolve => { finish = resolve; })) };
  const view = render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" api={api} />);
  fireEvent.click(screen.getByRole("button", { name: "整理完整给药建议" }));
  view.rerender(<RegimenDesignWorkspace projectId="one" seedRunId="seed:two" api={api} />);
  finish(done);
  await waitFor(() => expect(screen.queryByText("请补充研究给药途径。")).toBeNull());
  expect(screen.getByRole("button", { name: "整理完整给药建议" })).toBeTruthy();
});

it("resumes an explicitly queued job but never redispatches an unknown outcome", async () => {
  const key = "protocol-v3:regimen:" + JSON.stringify(["one", "seed:one"]);
  localStorage.setItem(key, JSON.stringify({ runId: "design:one" }));
  const api = { getRegimenDesign: vi.fn(async () => ({ workflow_run_id: "design:one", status: "running", can_resume: true })),
    resumeRegimenDesign: vi.fn(async () => done), startRegimenDesign: vi.fn() };
  const view = render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" api={api} />);
  await screen.findByText("请补充研究给药途径。");
  expect(api.resumeRegimenDesign).toHaveBeenCalledTimes(1);
  view.unmount();
  api.getRegimenDesign.mockResolvedValue({ workflow_run_id: "design:one", status: "blocked", can_resume: false });
  render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" api={api} />);
  await screen.findByText("本次设计结果需要核对，原资料和记录已保留。");
  expect(api.resumeRegimenDesign).toHaveBeenCalledTimes(1);
  expect(api.startRegimenDesign).not.toHaveBeenCalled();
});

it("pins the server study request before dispatch and recovers that exact request", async () => {
  const intent = {seed_run_id:'seed:one',study_definition_id:'study:a',expected_workflow_run_id:'design:one'};
  const api = {
    prepareRegimenDesign: vi.fn(async () => intent),
    startRegimenDesign: vi.fn(async () => {throw new Error('连接中断，记录待核对。');}),
    recoverRegimenDesign: vi.fn(async () => done),getRegimenDesign:vi.fn(async () => done),
  };
  const view=render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:a" actorId="user:a" api={api}/>);
  fireEvent.click(screen.getByRole('button',{name:'整理完整给药建议'}));
  await screen.findByText('连接中断，记录待核对。');
  expect(api.startRegimenDesign.mock.calls[0][1]).toEqual(intent);
  view.unmount();
  render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:a" actorId="user:a" api={api}/>);
  await screen.findByText('请补充研究给药途径。');
  expect(api.recoverRegimenDesign.mock.calls[0][1]).toEqual(intent);
  expect(api.prepareRegimenDesign).toHaveBeenCalledTimes(1);
  expect(api.startRegimenDesign).toHaveBeenCalledTimes(1);
});

it('does not carry a saved study-bound run into another study with the same seed', async () => {
  const api={prepareRegimenDesign:vi.fn(async (_p,seed,study)=>({seed_run_id:seed,study_definition_id:study,expected_workflow_run_id:'design:one'})),
    startRegimenDesign:vi.fn(async()=>done),getRegimenDesign:vi.fn(async()=>done)};
  const view=render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:a" actorId="user:a" api={api}/>);
  fireEvent.click(screen.getByRole('button',{name:'整理完整给药建议'}));
  await screen.findByText('请补充研究给药途径。');
  view.rerender(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:b" actorId="user:a" api={api}/>);
  expect(screen.queryByText('请补充研究给药途径。')).toBeNull();
  expect(screen.getByRole('button',{name:'整理完整给药建议'})).toBeTruthy();
  expect(api.startRegimenDesign).toHaveBeenCalledTimes(1);
});

it('preserves a legacy unknown request without recovering it against a study', async () => {
  const key = 'protocol-v3:regimen:' + JSON.stringify(['one','seed:one']);
  localStorage.setItem(key, JSON.stringify({pending:true}));
  const api = {recoverRegimenDesign:vi.fn(async()=>done),startRegimenDesign:vi.fn()};
  render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:a" api={api}/>);
  await screen.findByText('旧设计请求的研究归属尚未核实，原记录已保留。');
  expect(api.recoverRegimenDesign).not.toHaveBeenCalled();
  expect(api.startRegimenDesign).not.toHaveBeenCalled();
  expect(JSON.parse(localStorage.getItem(key))).toEqual({pending:true});
});

it('starts a study-bound successor explicitly and retains the old reference identity', async()=>{
  const key='protocol-v3:regimen:'+JSON.stringify(['one','seed:one','study:a']);
  localStorage.setItem(key,JSON.stringify({runId:'design:old'}));
  const intent={seed_run_id:'seed:one',study_definition_id:'study:a',expected_workflow_run_id:'design:new'};
  const old={...done,workflow_run_id:'design:old',study_definition_id:null};
  const next={...done,workflow_run_id:'design:new',study_definition_id:'study:a'};
  const api={getRegimenDesign:vi.fn(async(_p,id)=>id==='design:old'?old:next),
    prepareRegimenDesign:vi.fn(async()=>intent),startRegimenDesign:vi.fn(async()=>next)};
  render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:a" api={api}/>);
  fireEvent.click(await screen.findByRole('button',{name:'基于本研究整理新建议'}));
  await waitFor(()=>expect(JSON.parse(localStorage.getItem(key)).runId).toBe('design:new'));
  expect(JSON.parse(localStorage.getItem(key)).previousRunIds).toEqual(['design:old']);
  expect(api.startRegimenDesign).toHaveBeenCalledTimes(1);
  expect(api.startRegimenDesign.mock.calls[0][1]).toEqual(intent);
});

it('opens the previous reference without replacing the current failed request', async()=>{
  const proposal=(await import('../../../../tests/fixtures/regimen-card-fixture.json')).default;
  const key='protocol-v3:regimen:'+JSON.stringify(['one','seed:one','study:a']);
  const saved={runId:'design:new',previousRunIds:['design:old']};
  localStorage.setItem(key,JSON.stringify(saved));
  const api={getRegimenDesign:vi.fn(async(_p,id)=>id==='design:new'
    ?{workflow_run_id:id,status:'blocked',can_resume:false,study_definition_id:'study:a'}
    :{workflow_run_id:id,status:'ready_for_review',can_resume:false,validation:{proposal}}),
    sourceDownloadUrl:()=>'',startRegimenDesign:vi.fn()};
  render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:a" api={api}/>);
  fireEvent.click(await screen.findByRole('button',{name:'查看之前的给药建议（1）'}));
  await screen.findByText('之前的给药建议');
  expect(JSON.parse(localStorage.getItem(key))).toEqual(saved);
  expect(api.startRegimenDesign).not.toHaveBeenCalled();
});
