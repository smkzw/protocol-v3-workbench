import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RegimenAdoptionCard } from "../../../../../frontend/src/features/medical-writing/protocol-workbench/RegimenAdoptionCard.jsx";
import proposal from "../../../../../frontend/tests/fixtures/regimen-card-fixture.json";

afterEach(() => { cleanup(); localStorage.clear(); });
const current = { definition: { study_definition_id: "study:one", revision: 1 }, revision_sha256: "a".repeat(64) };
const receipt = { study_definition_id: "study:one", revision: 2, revision_sha256: "b".repeat(64),
  effective_decision: { decision_record_id: "decision:one" }, definition: { study_definition_id: "study:one", revision: 2 } };
const props = { projectId: "project:one", studyDefinitionId: "study:one", actorId: "user:one", runId: "design:one", proposal };

it("keeps 500 as unknown lookup and never treats it as a configuration retry", async () => {
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn(async () => { throw Object.assign(new Error("当前操作的结果尚未确认。"), { status: 500 }); }),
    recoverRegimenAdoption: vi.fn(async () => { throw Object.assign(new Error("尚未查到本次确认的保存回执，原方案与操作记录已保留。"), { status: 404, detail: { message: "尚未查到本次确认的保存回执，原方案与操作记录已保留。" } }); }) };
  render(<RegimenAdoptionCard {...props} api={api} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  await screen.findByRole("button", { name: "核对本次确认" });
  expect(screen.queryByRole("button", { name: "配置恢复后继续保存原选择" })).toBeNull();
  expect(screen.queryByText("正在处理中，请稍候。")).toBeNull();
  expect(screen.getByText("本次提交待核对，请先找回原确认记录。")).toBeTruthy();
  expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "核对本次确认" }));
  await screen.findByText("尚未查到本次确认的保存回执，原方案与操作记录已保留。");
  expect(api.adoptRegimenDesign).toHaveBeenCalledTimes(1);
});

it("does not auto-adopt a remembered unexecuted 424 choice on reopen", async () => {
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn().mockRejectedValueOnce(Object.assign(new Error("工作台配置尚未就绪，本次操作未执行。"), { status: 424, detail: { message: "工作台配置尚未就绪，本次操作未执行。" } })).mockResolvedValue(receipt),
    recoverRegimenAdoption: vi.fn() };
  const view = render(<RegimenAdoptionCard {...props} api={api} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  await screen.findByRole("button", { name: "配置恢复后继续保存原选择" });
  expect(api.adoptRegimenDesign).toHaveBeenCalledTimes(1);
  const first = api.adoptRegimenDesign.mock.calls[0][2];
  view.unmount();
  render(<RegimenAdoptionCard {...props} api={api} />);
  await screen.findByRole("button", { name: "配置恢复后继续保存原选择" });
  expect(api.recoverRegimenAdoption).not.toHaveBeenCalled();
  expect(api.adoptRegimenDesign).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("本次选择已保存")).toBeNull();
  expect(screen.queryByText("正在处理中，请稍候。")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "配置恢复后继续保存原选择" }));
  await screen.findByText("本次选择已保存");
  expect(api.adoptRegimenDesign.mock.calls[1][2]).toEqual(first);
  expect(screen.getByText("原确认记录已保留；后续研究修改的有效性以当前研究版本为准。")).toBeTruthy();
  expect(screen.getByRole("button", { name: "原确认记录已保存" }).disabled).toBe(true);
});
