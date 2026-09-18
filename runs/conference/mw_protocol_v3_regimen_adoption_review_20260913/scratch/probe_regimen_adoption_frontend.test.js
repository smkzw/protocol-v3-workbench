import { createElement, StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RegimenAdoptionCard } from "@scratch-workbench/RegimenAdoptionCard.jsx";
import { RegimenDesignWorkspace } from "@scratch-workbench/RegimenDesignWorkspace.jsx";
import proposal from "@scratch-fixture";

afterEach(() => { cleanup(); localStorage.clear(); });

const current = { definition: { study_definition_id: "study:one", revision: 1 }, revision_sha256: "a".repeat(64) };
const receipt = { study_definition_id: "study:one", revision: 2, revision_sha256: "b".repeat(64),
  effective_decision: { decision_record_id: "decision:one" }, definition: { study_definition_id: "study:one", revision: 2 } };
const props = { projectId: "project:one", studyDefinitionId: "study:one", actorId: "user:one", runId: "design:one", proposal, api: null };

it("strict mode may repeat readonly recovery but never applies twice", async () => {
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn(async () => receipt), recoverRegimenAdoption: vi.fn(async () => receipt) };
  render(createElement(StrictMode, null, createElement(RegimenAdoptionCard, { ...props, api })));
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  await screen.findByText("本次选择已保存");
  expect(api.adoptRegimenDesign).toHaveBeenCalledTimes(1);
});

it("does not apply a late adoption receipt after the study identity changes", async () => {
  let finish;
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn(() => new Promise(resolve => { finish = resolve; })),
    recoverRegimenAdoption: vi.fn(async () => receipt) };
  const view = render(createElement(RegimenAdoptionCard, { ...props, api }));
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  view.rerender(createElement(RegimenAdoptionCard, { ...props, studyDefinitionId: "study:two", api }));
  finish(receipt);
  await waitFor(() => expect(screen.queryByText("本次选择已保存")).toBeNull());
  expect(api.adoptRegimenDesign).toHaveBeenCalledTimes(1);
});

it("keeps an uncertain 5xx pointer and does not auto-apply after a 404 lookup", async () => {
  const api = { getStudyDefinition: vi.fn(async () => current), sourceDownloadUrl: () => "",
    adoptRegimenDesign: vi.fn().mockRejectedValueOnce(Object.assign(new Error("暂时无法确认保存结果"), { status: 500 })),
    recoverRegimenAdoption: vi.fn(async () => { throw Object.assign(new Error("尚未查到本次确认的保存回执，原方案与操作记录已保留。"), { status: 404, detail: { message: "尚未查到本次确认的保存回执，原方案与操作记录已保留。" } }); }) };
  render(createElement(RegimenAdoptionCard, { ...props, api }));
  await waitFor(() => expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  await screen.findByRole("button", { name: "核对本次确认" });
  expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "核对本次确认" }));
  await screen.findByText("尚未查到本次确认的保存回执，原方案与操作记录已保留。");
  expect(api.adoptRegimenDesign).toHaveBeenCalledTimes(1);
});

it("does not auto-start a replacement design under strict mode after a lost ack", async () => {
  const done = { workflow_run_id: "design:one", status: "needs_information", can_resume: false,
    validation: { valid: true, proposal: { regimen: null, questions: ["请补充研究给药途径。"], coverage: [] } } };
  const api = { startRegimenDesign: vi.fn(async () => { throw Object.assign(new Error("连接中断，记录待核对。"), { status: 0 }); }),
    recoverRegimenDesign: vi.fn(async () => done), getRegimenDesign: vi.fn(async () => done) };
  render(createElement(StrictMode, null, createElement(RegimenDesignWorkspace, { projectId: "one", seedRunId: "seed:one", api })));
  fireEvent.click(screen.getByRole("button", { name: "整理完整给药建议" }));
  await screen.findByText("连接中断，记录待核对。");
  expect(api.startRegimenDesign).toHaveBeenCalledTimes(1);
  cleanup();
  render(createElement(StrictMode, null, createElement(RegimenDesignWorkspace, { projectId: "one", seedRunId: "seed:one", api })));
  await screen.findByText("请补充研究给药途径。");
  expect(api.startRegimenDesign).toHaveBeenCalledTimes(1);
  expect(api.recoverRegimenDesign.mock.calls.length).toBeGreaterThanOrEqual(1);
});
