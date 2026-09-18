import { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProtocolIntakeWorkspace } from "./ProtocolIntakeWorkspace";
const completed = { workflow_run_id: "seed:one", status: "needs_information", validation: {
  proposal: { fields: { research_drug: [{ candidate: "示例药物", reason: "来自写作说明", basis: "user" }] }, missing_fields: ["indication"] },
} };
function api(overrides = {}) {
  return { listSources: vi.fn(async () => ({ sources: [] })), sourceDownloadUrl: () => "",
    startResearchIntake: vi.fn(async () => completed), getResearchIntake: vi.fn(async () => completed), ...overrides };
}
afterEach(() => { cleanup(); localStorage.clear(); });
it("keeps brief and job on reopen without submitting again", async () => {
  const client = api();
  const view = render(<ProtocolIntakeWorkspace projectId="project-one" api={client} />);
  await screen.findByText(/还没有已保存的资料/);
  fireEvent.change(screen.getByLabelText("写作说明（可选）"), { target: { value: "研究示例药物" } });
  fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
  await screen.findByText("示例药物");
  expect(screen.getByText(/适应症/)).toBeTruthy();
  expect(client.startResearchIntake.mock.calls[0][1]).toEqual({ userBrief: "研究示例药物", sourceArtifactIds: [] });
  view.unmount();
  render(<ProtocolIntakeWorkspace projectId="project-one" api={client} />);
  await screen.findByText("示例药物");
  expect(screen.getByLabelText("写作说明（可选）").value).toBe("研究示例药物");
  expect(client.startResearchIntake).toHaveBeenCalledTimes(1);
});
it("ignores late submissions after changing project and prevents double submission", async () => {
  let resolve;
  const pending = new Promise(r => { resolve = r; });
  const client = api({ startResearchIntake: vi.fn(() => pending) });
  const view = render(<ProtocolIntakeWorkspace projectId="project-one" api={client} />);
  await screen.findByText(/还没有已保存的资料/);
  const button = screen.getByRole("button", { name: "准备写作材料" });
  fireEvent.click(button); fireEvent.click(button);
  expect(client.startResearchIntake).toHaveBeenCalledTimes(1);
  view.rerender(<ProtocolIntakeWorkspace projectId="project-two" api={client} />);
  resolve(completed);
  await screen.findByText(/还没有已保存的资料/);
  await waitFor(() => expect(screen.queryByText("示例药物")).toBeNull());
  expect(localStorage.getItem("protocol-v3:intake:project-two")).toBeNull();
});
it("keeps brief after a lost acknowledgement with no automatic resubmission", async () => {
  const client = api({ startResearchIntake: vi.fn(async () => { throw new Error("连接暂时中断。"); }) });
  render(<ProtocolIntakeWorkspace projectId="project-one" api={client} />);
  await screen.findByText(/还没有已保存的资料/);
  fireEvent.change(screen.getByLabelText("写作说明（可选）"), { target: { value: "保留这段说明" } });
  fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
  await screen.findByText("连接暂时中断。");
  expect(screen.getByLabelText("写作说明（可选）").value).toBe("保留这段说明");
  expect(client.startResearchIntake).toHaveBeenCalledTimes(1);
});



it("resumes an explicitly resumable saved job once on reopen without starting a new job", async () => {
  localStorage.setItem("protocol-v3:intake:project-one", JSON.stringify({ brief: "保留说明", runId: "seed:one" }));
  const pending = { workflow_run_id: "seed:one", status: "running", can_resume: true };
  const client = api({ getResearchIntake: vi.fn().mockResolvedValueOnce(pending).mockResolvedValue(completed),
    resumeResearchIntake: vi.fn(async () => pending) });
  render(<ProtocolIntakeWorkspace projectId="project-one" api={client} />);
  await waitFor(() => expect(client.resumeResearchIntake).toHaveBeenCalledTimes(1));
  await screen.findByText("示例药物", {}, { timeout: 3000 });
  expect(client.resumeResearchIntake.mock.calls[0].slice(0, 2)).toEqual(["project-one", "seed:one"]);
  expect(client.startResearchIntake).not.toHaveBeenCalled();
});


it("locates a lost acknowledgement by its saved original request after reopening", async () => {
  const client = api({ startResearchIntake: vi.fn(async () => { throw new Error("回执连接中断。"); }),
    recoverResearchIntake: vi.fn(async () => completed) });
  const view = render(<ProtocolIntakeWorkspace projectId="project-one" api={client} />);
  await screen.findByText(/还没有已保存的资料/);
  fireEvent.change(screen.getByLabelText("写作说明（可选）"), { target: { value: "原始整理说明" } });
  fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
  await screen.findByText("回执连接中断。");
  view.unmount();
  render(<ProtocolIntakeWorkspace projectId="project-one" api={client} />);
  await waitFor(() => expect(client.recoverResearchIntake).toHaveBeenCalledTimes(1));
  await screen.findByText("示例药物");
  expect(client.recoverResearchIntake.mock.calls[0].slice(0, 2)).toEqual(["project-one", { userBrief: "原始整理说明", sourceArtifactIds: [] }]);
  expect(client.startResearchIntake).toHaveBeenCalledTimes(1);
});


it("refreshes changed source choices without discarding the writing brief", async () => {
  const client = api({ startResearchIntake: vi.fn(async () => { throw Object.assign(new Error("资料已有变化。"), { status: 409 }); }) });
  render(<ProtocolIntakeWorkspace projectId="project-one" api={client} />);
  await screen.findByText(/还没有已保存的资料/);
  fireEvent.change(screen.getByLabelText("写作说明（可选）"), { target: { value: "仍要保留的说明" } });
  fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
  await screen.findByText("资料已有变化。");
  fireEvent.click(screen.getByRole("button", { name: "更新资料列表" }));
  await waitFor(() => expect(client.listSources).toHaveBeenCalledTimes(2));
  expect(screen.getByLabelText("写作说明（可选）").value).toBe("仍要保留的说明");
});


it("strict-mode restoration may repeat readonly lookup but never starts a replacement job", async () => {
  localStorage.setItem("protocol-v3:intake:project-one", JSON.stringify({ brief: "原说明", pendingRequest: { userBrief: "原说明", sourceArtifactIds: [] } }));
  const pending = { workflow_run_id: "seed:one", status: "running", can_resume: true };
  const client = api({ recoverResearchIntake: vi.fn(async () => pending),
    getResearchIntake: vi.fn().mockResolvedValueOnce(pending).mockResolvedValue(completed),
    resumeResearchIntake: vi.fn(async () => pending) });
  render(<StrictMode><ProtocolIntakeWorkspace projectId="project-one" api={client} /></StrictMode>);
  await screen.findByText("示例药物", {}, { timeout: 3000 });
  expect(client.startResearchIntake).not.toHaveBeenCalled();
  expect(client.resumeResearchIntake).toHaveBeenCalledTimes(1);
});
