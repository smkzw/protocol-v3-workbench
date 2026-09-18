import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RegimenAdoptionCard } from "./RegimenAdoptionCard";
import proposal from "../../../../tests/fixtures/regimen-card-fixture.json";

afterEach(() => { cleanup(); localStorage.clear(); });
const current = { definition: { study_definition_id: "study:one", revision: 1 }, revision_sha256: "a".repeat(64) };
const receipt = { study_definition_id: "study:one", revision: 2, revision_sha256: "b".repeat(64),
  effective_decision: { decision_record_id: "decision:one" }, definition: { study_definition_id: "study:one", revision: 2 } };
const props = { projectId: "project:one", studyDefinitionId: "study:one", actorId: "user:one", runId: "design:one", proposal };

it("persists one explicit intent and reads its saved receipt on reopen", async () => {
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn(async () => receipt), recoverRegimenAdoption: vi.fn(async () => receipt) };
  const view = render(<RegimenAdoptionCard {...props} api={api} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  await screen.findByText("本次选择已保存");
  const intent = api.adoptRegimenDesign.mock.calls[0][2];
  expect(intent.snapshot_sha256).toBe(current.revision_sha256);
  expect(intent.expected_revision).toBe(1);
  expect(intent.reason.length).toBeGreaterThan(0);
  view.unmount();
  render(<RegimenAdoptionCard {...props} api={api} />);
  await screen.findByText("本次选择已保存");
  expect(api.recoverRegimenAdoption.mock.calls[0][2]).toEqual(intent);
  expect(api.adoptRegimenDesign).toHaveBeenCalledTimes(1);
});
it("keeps an uncertain commit for readonly lookup without a second adoption", async () => {
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn(async () => { throw new Error("连接中断"); }),
    recoverRegimenAdoption: vi.fn(async () => receipt) };
  render(<RegimenAdoptionCard {...props} api={api} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  await screen.findByRole("button", { name: "核对本次确认" });
  expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "核对本次确认" }));
  await screen.findByText("本次选择已保存");
  expect(api.adoptRegimenDesign).toHaveBeenCalledTimes(1);
});

it("refreshes a definitively rejected revision and requires a new explicit confirmation", async () => {
  const api = { getStudyDefinition: vi.fn().mockResolvedValueOnce(current).mockResolvedValue({
    definition: { study_definition_id: "study:one", revision: 2 }, revision_sha256: "c".repeat(64) }),
    sourceDownloadUrl: () => "", adoptRegimenDesign: vi.fn().mockRejectedValueOnce(Object.assign(
      new Error("研究版本已更新，请重新查看。"), { status: 409 })).mockResolvedValue({ ...receipt, revision: 3,
        definition: { study_definition_id: "study:one", revision: 3 } }) };
  render(<RegimenAdoptionCard {...props} api={api} />);
  const button = screen.getByRole("button", { name: "确认这套给药方案" });
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  await waitFor(() => expect(api.getStudyDefinition).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(button.disabled).toBe(false));
  expect(api.adoptRegimenDesign).toHaveBeenCalledTimes(1);
  fireEvent.click(button);
  await screen.findByText("本次选择已保存");
  const first = api.adoptRegimenDesign.mock.calls[0][2];
  const second = api.adoptRegimenDesign.mock.calls[1][2];
  expect(second.operation_id).not.toBe(first.operation_id);
  expect(second.snapshot_sha256).toBe("c".repeat(64));
  expect(second.expected_revision).toBe(2);
});

it("does not call a pre-adoption version a successful save", async () => {
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn(async () => ({...receipt, revision: 1, definition: current.definition})) };
  render(<RegimenAdoptionCard {...props} api={api} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  await screen.findByRole("button", { name: "核对本次确认" });
  expect(screen.queryByText("本次选择已保存")).toBeNull();
});

it("separates awaiting reconciliation from an active request and shows saved feedback at the action", async () => {
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn(async () => { throw new Error("连接中断"); }),
    recoverRegimenAdoption: vi.fn(async () => receipt) };
  render(<RegimenAdoptionCard {...props} api={api} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  const lookup = await screen.findByRole("button", { name: "核对本次确认" });
  expect(screen.queryByText("正在处理中，请稍候。")).toBeNull();
  expect(screen.getByText("本次提交待核对，请先找回原确认记录。")).toBeTruthy();
  fireEvent.click(lookup);
  await screen.findByText("本次选择已保存");
  expect(screen.queryByText("监管答辩级·需确认")).toBeNull();
  expect(screen.getByRole("button", { name: "原确认记录已保存" }).disabled).toBe(true);
});

it("retains a rejected configuration intent and retries the same choice only on request", async () => {
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn().mockRejectedValueOnce(Object.assign(new Error("工作台配置尚未就绪，本次操作未执行。"),
      { status: 424 })).mockResolvedValue(receipt), recoverRegimenAdoption: vi.fn() };
  render(<RegimenAdoptionCard {...props} api={api} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  const retry = await screen.findByRole("button", { name: "配置恢复后继续保存原选择" });
  expect(screen.queryByRole("button", { name: "核对本次确认" })).toBeNull();
  expect(api.adoptRegimenDesign).toHaveBeenCalledTimes(1);
  fireEvent.click(retry);
  await screen.findByText("本次选择已保存");
  expect(api.adoptRegimenDesign.mock.calls[1][2]).toEqual(api.adoptRegimenDesign.mock.calls[0][2]);
  expect(api.recoverRegimenAdoption).not.toHaveBeenCalled();
});

it("reopens a known unexecuted choice without misreporting an unknown commit", async () => {
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn().mockRejectedValueOnce(Object.assign(new Error("配置尚未就绪，本次未执行。"),
      { status: 424 })).mockResolvedValue(receipt), recoverRegimenAdoption: vi.fn() };
  const view = render(<RegimenAdoptionCard {...props} api={api} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  await screen.findByRole("button", { name: "配置恢复后继续保存原选择" });
  view.unmount();
  render(<RegimenAdoptionCard {...props} api={api} />);
  const retry = await screen.findByRole("button", { name: "配置恢复后继续保存原选择" });
  expect(api.recoverRegimenAdoption).not.toHaveBeenCalled();
  fireEvent.click(retry);
  await screen.findByText("本次选择已保存");
  expect(api.adoptRegimenDesign.mock.calls[1][2]).toEqual(api.adoptRegimenDesign.mock.calls[0][2]);
});

it.each([
  ['current','decision:one','当前研究内容下，这份确认仍有效。'],
  ['stale','decision:one','研究内容已变化，这份历史确认需要重新核对。'],
  ['current','decision:later','本研究已有后续给药确认，此处保留原确认记录。'],
  ['unverified','decision:one','原确认已保存，当前有效性尚未核实。'],
])('separates saved receipt from current decision validity %s/%s', async(validity,decisionId,text)=>{
  const key='protocol-v3:regimen-adoption:'+JSON.stringify([props.projectId,props.studyDefinitionId,props.runId]);
  localStorage.setItem(key,JSON.stringify({expected_revision:1,operation_id:'operation:original'}));
  const api={recoverRegimenAdoption:vi.fn(async()=>receipt),sourceDownloadUrl:()=>'',
    getDecisionGraph:vi.fn(async()=>({project_id:props.projectId,study_definition_id:props.studyDefinitionId,
      records:[{decision_key:'decision:dose-regimen',decision_record_id:decisionId,current_validity:validity}]}))};
  render(<RegimenAdoptionCard {...props} api={api}/>);
  await screen.findByText(text);
  expect(screen.getByText('本次选择已保存')).toBeTruthy();
});

it('keeps an unbound reference read-only while allowing its historical receipt to reopen', async () => {
  const api={getStudyDefinition:vi.fn(async()=>current),sourceDownloadUrl:()=>'',
    adoptRegimenDesign:vi.fn(),recoverRegimenAdoption:vi.fn(async()=>receipt)};
  const view=render(<RegimenAdoptionCard {...props} freshAdoptionAllowed={false} api={api}/>);
  await screen.findByText('这份旧建议尚未结合本研究参数，请先整理本研究的给药建议。');
  expect(screen.getByRole('button',{name:'确认这套给药方案'}).disabled).toBe(true);
  expect(api.adoptRegimenDesign).not.toHaveBeenCalled();
  view.unmount();
  localStorage.setItem('protocol-v3:regimen-adoption:'+JSON.stringify([props.projectId,props.studyDefinitionId,props.runId]),
    JSON.stringify({operation_id:'old:operation',expected_revision:1}));
  render(<RegimenAdoptionCard {...props} freshAdoptionAllowed={false} api={api}/>);
  await screen.findByText('本次选择已保存');
  expect(api.recoverRegimenAdoption).toHaveBeenCalledTimes(1);
  expect(api.adoptRegimenDesign).not.toHaveBeenCalled();
});
