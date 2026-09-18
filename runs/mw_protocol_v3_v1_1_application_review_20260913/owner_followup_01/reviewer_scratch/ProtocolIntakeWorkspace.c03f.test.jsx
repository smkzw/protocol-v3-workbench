/* C03 followup scratch probes for the frozen ProtocolIntakeWorkspace flow. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ProtocolIntakeWorkspace } from "../../../../frontend/src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.jsx";

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const KEY = "protocol-v3:intake:p1";

function sourceRecord({ id, key, role = "project_primary" } = {}) {
  return {
    source: {
      source_artifact_id: id, logical_source_key: key, content_sha256: "a".repeat(64),
      source_role: role, source_version: "unidentified", jurisdiction: "unspecified",
      mime_type: DOCX_MIME, captured_at: "2026-09-13T08:00:00Z",
    },
    storage_key: `storage-${id}`, storage_revision: 1,
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function docxFile(name) {
  return new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], name, { type: DOCX_MIME });
}

function fakeApi({ sources = [], listImpl, startImpl, recoverImpl, resumeImpl, readImpl } = {}) {
  return {
    listSources: vi.fn(listImpl ?? (async () => ({ sources: sources.map((r) => JSON.parse(JSON.stringify(r))) }))),
    startResearchIntake: vi.fn(startImpl ?? (async () => ({ workflow_run_id: "run-new", status: "running", can_resume: true }))),
    recoverResearchIntake: vi.fn(recoverImpl ?? (async () => ({ workflow_run_id: "run-rec", status: "running", can_resume: true }))),
    resumeResearchIntake: vi.fn(resumeImpl ?? (async () => ({ workflow_run_id: "run-rec", status: "running", can_resume: false }))),
    getResearchIntake: vi.fn(readImpl ?? (async () => ({ workflow_run_id: "run-rec", status: "needs_information", can_resume: false, validation: null }))),
    importSource: vi.fn(async () => ({ replayed: false })),
    correctSourceMetadata: vi.fn(async () => ({ replayed: false })),
    sourceDownloadUrl: (projectId, sourceArtifactId) =>
      `/api/projects/${projectId}/protocol-workflow/sources/${encodeURIComponent(String(sourceArtifactId))}/content`,
  };
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("C03f: durable pending request", () => {
  it("W1 persists the pending request to localStorage before the POST resolves", async () => {
    const gate = deferred();
    const api = fakeApi({ sources: [sourceRecord({ id: "s-1", key: "方案.docx" })] });
    api.startResearchIntake.mockReturnValue(gate.promise);
    render(<ProtocolIntakeWorkspace projectId="p1" api={api} />);
    await screen.findByText("方案.docx");

    fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
    const saved = JSON.parse(window.localStorage.getItem(KEY));
    expect(saved.pendingRequest).toEqual({ userBrief: "", sourceArtifactIds: ["s-1"] });
    expect(document.querySelector("fieldset").disabled).toBe(true);

    gate.resolve({ workflow_run_id: "run-1", status: "running", can_resume: true });
    await waitFor(() => {
      expect(JSON.parse(window.localStorage.getItem(KEY)).pendingRequest).toBeNull();
    });
    expect(screen.getByText(/正在整理资料/)).toBeTruthy();
  });

  it("W2 reload recovers read-only and resumes only a queued resumable run once", async () => {
    window.localStorage.setItem(KEY, JSON.stringify({
      brief: "恢复说明",
      pendingRequest: { userBrief: "恢复说明", sourceArtifactIds: [] },
    }));
    const api = fakeApi();
    api.getResearchIntake
      .mockResolvedValueOnce({ workflow_run_id: "run-rec", status: "running", can_resume: true })
      .mockResolvedValue({ workflow_run_id: "run-rec", status: "needs_information", can_resume: false,
        validation: { proposal: { fields: {}, missing_fields: ["research_drug"] } } });
    render(<ProtocolIntakeWorkspace projectId="p1" api={api} />);

    await waitFor(() => expect(api.recoverResearchIntake).toHaveBeenCalledTimes(1));
    expect(api.recoverResearchIntake.mock.calls[0][1]).toEqual({ userBrief: "恢复说明", sourceArtifactIds: [] });
    await waitFor(() => expect(api.resumeResearchIntake).toHaveBeenCalledTimes(1));
    expect(screen.getByText(/还需要补充：研究药物/)).toBeTruthy();
    await waitFor(() => expect(api.getResearchIntake.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("W3 a synchronous double-click on prepare issues exactly one POST (parent ref guard)", async () => {
    const api = fakeApi({ sources: [sourceRecord({ id: "s-1", key: "方案.docx" })] });
    render(<ProtocolIntakeWorkspace projectId="p1" api={api} />);
    await screen.findByText("方案.docx");
    const button = screen.getByRole("button", { name: "准备写作材料" });
    fireEvent.click(button);
    fireEvent.click(button);
    await screen.findByText(/正在整理资料/);
    expect(api.startResearchIntake).toHaveBeenCalledTimes(1);
  });
});

describe("C03f: intake guards", () => {
  it("W4 staged batch files prohibit prepare until saved or cancelled", async () => {
    const api = fakeApi({ sources: [sourceRecord({ id: "s-1", key: "方案.docx" })] });
    render(<ProtocolIntakeWorkspace projectId="p1" api={api} />);
    await screen.findByText("方案.docx");
    expect(screen.getByRole("button", { name: "准备写作材料" }).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText(/选择要添加的DOCX文件/), {
      target: { files: [docxFile("新资料.docx"), docxFile("手册.docx")] },
    });
    expect(screen.getByRole("button", { name: "准备写作材料" }).disabled).toBe(true);
    expect(screen.getByText(/请先保存或取消待添加的文件/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "取消添加" }));
    expect(screen.getByRole("button", { name: "准备写作材料" }).disabled).toBe(false);
  });

  it("W5 a long brief is carried through untruncated", async () => {
    const api = fakeApi({ sources: [sourceRecord({ id: "s-1", key: "方案.docx" })] });
    render(<ProtocolIntakeWorkspace projectId="p1" api={api} />);
    await screen.findByText("方案.docx");
    const long = "长".repeat(600);
    fireEvent.change(screen.getByLabelText(/写作说明/), { target: { value: long } });
    fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
    await screen.findByText(/正在整理资料/);
    const payload = api.startResearchIntake.mock.calls[0][1];
    expect(payload.userBrief).toBe(long);
    expect(payload.userBrief.length).toBe(600);
  });

  it("W6 a 409 refresh preserves the brief and the exclusion, then uses the new identity", async () => {
    const v1 = sourceRecord({ id: "s-old", key: "方案.docx" });
    const v2 = sourceRecord({ id: "s-new", key: "方案.docx" });
    const api = fakeApi({ sources: [v1] });
    const conflict = new Error("所选资料已有变化，本次尚未开始整理。");
    conflict.status = 409;
    conflict.detail = { message: "所选资料已有变化，本次尚未开始整理。", next_step: "请刷新资料列表后重新选择。" };
    api.startResearchIntake
      .mockRejectedValueOnce(conflict)
      .mockResolvedValue({ workflow_run_id: "run-2", status: "running", can_resume: true });
    api.listSources
      .mockResolvedValueOnce({ sources: [v1] })
      .mockResolvedValue({ sources: [v2] });
    render(<ProtocolIntakeWorkspace projectId="p1" api={api} />);
    await screen.findByText("方案.docx");

    fireEvent.change(screen.getByLabelText(/写作说明/), { target: { value: "保留的说明" } });
    fireEvent.click(screen.getByLabelText("纳入后续写作：方案.docx")); // exclude the only source
    fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
    await screen.findByText(/本次尚未开始整理/);
    expect(screen.getByRole("button", { name: "更新资料列表" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "更新资料列表" }));
    await waitFor(() => expect(api.listSources).toHaveBeenCalledTimes(2));
    await screen.findByText("方案.docx");
    expect(screen.getByLabelText(/写作说明/).value).toBe("保留的说明");
    expect(api.startResearchIntake).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByLabelText("纳入后续写作：方案.docx")); // re-include current version
    fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
    await screen.findByText(/正在整理资料/);
    const retry = api.startResearchIntake.mock.calls[1][1];
    expect(retry.userBrief).toBe("保留的说明");
    expect(retry.sourceArtifactIds).toEqual(["s-new"]);
  });

  it("W7 unmount during recovery aborts and stays silent", async () => {
    window.localStorage.setItem(KEY, JSON.stringify({
      pendingRequest: { userBrief: "中止场景", sourceArtifactIds: [] },
    }));
    const gate = deferred();
    let recoverSignal = null;
    const api = fakeApi();
    api.recoverResearchIntake.mockImplementation((_p, _b, { signal } = {}) => {
      recoverSignal = signal;
      return gate.promise;
    });
    const view = render(<ProtocolIntakeWorkspace projectId="p1" api={api} />);
    await waitFor(() => expect(recoverSignal).not.toBeNull());
    view.unmount();
    expect(recoverSignal.aborted).toBe(true);
    gate.resolve({ workflow_run_id: "run-late", status: "running", can_resume: true });
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
});
