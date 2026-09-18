/* C03 scratch-only UI challenge tests for the frozen ProtocolSourceIntake. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ProtocolWorkspaceApiError } from "../../../frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs";
import { ProtocolSourceIntake } from "../../../frontend/src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.jsx";

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function sourceRecord({ id, key, role = "project_primary", version = "unidentified", jurisdiction = "unspecified" } = {}) {
  return {
    source: {
      source_artifact_id: id, logical_source_key: key, content_sha256: "a".repeat(64),
      source_role: role, source_version: version, jurisdiction, mime_type: DOCX_MIME,
      captured_at: "2026-09-13T08:00:00Z",
    },
    storage_key: `storage-${id}`, storage_revision: 1,
  };
}

function createFakeApi({ sources = [], listImpl, importImpl, correctImpl } = {}) {
  return {
    listSources: vi.fn(listImpl ?? (async () => ({ sources: sources.map((r) => JSON.parse(JSON.stringify(r))) }))),
    importSource: vi.fn(importImpl ?? (async () => ({ replayed: false }))),
    correctSourceMetadata: vi.fn(correctImpl ?? (async () => ({ replayed: false }))),
    sourceDownloadUrl: (projectId, sourceArtifactId) =>
      `/api/projects/${projectId}/protocol-workflow/sources/${encodeURIComponent(String(sourceArtifactId))}/content`,
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

async function stageAndSave(file, role) {
  fireEvent.change(screen.getByLabelText(/选择要添加的DOCX文件/), { target: { files: [file] } });
  fireEvent.change(screen.getByLabelText("资料类别"), { target: { value: role } });
  fireEvent.click(screen.getByRole("button", { name: "保存到资料" }));
}

afterEach(() => { cleanup(); });

describe("C03 challenge: double-click guards", () => {
  it("U1 a synchronous double-click on 保存到资料 performs exactly one import", async () => {
    const saved = sourceRecord({ id: "s-new", key: "试验方案.docx" });
    const gate = deferred();
    const api = createFakeApi({ importImpl: async () => { await gate.promise; return { current: saved }; } });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/还没有已保存的资料/);

    const file = docxFile("试验方案.docx");
    fireEvent.change(screen.getByLabelText(/选择要添加的DOCX文件/), { target: { files: [file] } });
    fireEvent.change(screen.getByLabelText("资料类别"), { target: { value: "project_primary" } });
    const save = screen.getByRole("button", { name: "保存到资料" });
    fireEvent.click(save);
    fireEvent.click(save); // second synchronous click before any re-render

    gate.resolve();
    await screen.findByText("已保存。");
    expect(api.importSource).toHaveBeenCalledTimes(1);
  });

  it("U2 a synchronous double-click on 保存更正 performs exactly one correction", async () => {
    const gate = deferred();
    const corrected = sourceRecord({ id: "s-corr", key: "旧记录.docx", role: "peer_reviewed" });
    const api = createFakeApi({
      sources: [sourceRecord({ id: "s-old", key: "旧记录.docx" })],
      correctImpl: async () => { await gate.promise; return { current: corrected }; },
    });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText("旧记录.docx");
    fireEvent.click(screen.getByRole("button", { name: "更正类别或版本" }));
    fireEvent.change(screen.getByLabelText("更正类别"), { target: { value: "peer_reviewed" } });
    const submit = screen.getByRole("button", { name: "保存更正" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    gate.resolve();
    await screen.findByText(/已保存更正/);
    expect(api.correctSourceMetadata).toHaveBeenCalledTimes(1);
  });

  it("U3 a synchronous double-click on 准备写作材料 fires onPrepare twice (state-only guard)", async () => {
    const onPrepare = vi.fn();
    const api = createFakeApi({ sources: [sourceRecord({ id: "s-1", key: "方案.docx" })] });
    render(<ProtocolSourceIntake projectId="p1" api={api} onPrepare={onPrepare} />);
    await screen.findByText("方案.docx");
    const prepare = screen.getByRole("button", { name: "准备写作材料" });
    fireEvent.click(prepare);
    fireEvent.click(prepare);
    expect(onPrepare).toHaveBeenCalledTimes(2);
    expect(onPrepare.mock.calls[0][0]).toEqual(onPrepare.mock.calls[1][0]);
  });
});

describe("C03 challenge: invalid server responses", () => {
  it("U4 a 200 list response without a sources array shows a Chinese error with manual retry", async () => {
    let attempts = 0;
    const api = createFakeApi({
      listImpl: async () => {
        attempts += 1;
        return attempts === 1 ? {} : { sources: [sourceRecord({ id: "s-1", key: "恢复.docx" })] };
      },
    });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/资料列表返回不完整/);
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await screen.findByText("恢复.docx");
    expect(api.listSources).toHaveBeenCalledTimes(2);
  });

  it("U5 a transport-level failure (status 0) shows the fallback message and refreshes after import failure", async () => {
    const api = createFakeApi({
      sources: [],
      importImpl: async () => {
        throw new ProtocolWorkspaceApiError("方案工作台请求失败。", { status: 0, detail: null });
      },
    });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/还没有已保存的资料/);
    await stageAndSave(docxFile("网络.docx"), "project_primary");
    await screen.findByText("方案工作台请求失败。");
    await waitFor(() => expect(api.listSources).toHaveBeenCalledTimes(2));
    // The failed file stays staged for a later manual retry.
    expect(screen.getByText(/将添加：网络\.docx/)).toBeTruthy();
  });

  it("U6 an unshapely correction response closes the editor, explains, and refreshes", async () => {
    const api = createFakeApi({
      sources: [sourceRecord({ id: "s-old", key: "旧记录.docx" })],
      correctImpl: async () => ({ replayed: false }),
    });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText("旧记录.docx");
    fireEvent.click(screen.getByRole("button", { name: "更正类别或版本" }));
    fireEvent.change(screen.getByLabelText("更正类别"), { target: { value: "peer_reviewed" } });
    fireEvent.click(screen.getByRole("button", { name: "保存更正" }));
    await screen.findByText(/更正结果未能确认当前资料/);
    await waitFor(() => expect(api.listSources).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "保存更正" })).toBeNull();
    expect(screen.getByText("旧记录.docx")).toBeTruthy();
  });
});

describe("C03 challenge: correction-clear interactions", () => {
  it("U7 typing after clicking 版本改为未注明 revives the typed value and clears the clear flag", async () => {
    const corrected = sourceRecord({ id: "s-c", key: "资料.docx", version: "4.0" });
    const api = createFakeApi({
      sources: [sourceRecord({ id: "s-o", key: "资料.docx", version: "1.0" })],
      correctImpl: async () => ({ current: corrected }),
    });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText("资料.docx");
    fireEvent.click(screen.getByRole("button", { name: "更正类别或版本" }));
    fireEvent.change(screen.getByLabelText(/版本（留空保持原值）/), { target: { value: "3.0" } });
    fireEvent.click(screen.getByRole("button", { name: "版本改为未注明" }));
    expect(screen.getByText(/保存后版本将改为未注明/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/版本（留空保持原值）/), { target: { value: "4.0" } });
    expect(screen.queryByText(/保存后版本将改为未注明/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "保存更正" }));
    await screen.findByText(/已保存更正/);
    expect(api.correctSourceMetadata.mock.calls[0][2]).toEqual({
      source_role: "project_primary", source_version: "4.0", jurisdiction: "unspecified",
    });
  });

  it("U8 clear flags alone submit 未注明/未注明 even when current values are set", async () => {
    const corrected = sourceRecord({ id: "s-c", key: "资料.docx" });
    const api = createFakeApi({
      sources: [sourceRecord({ id: "s-o", key: "资料.docx", version: "9.9", jurisdiction: "某地" })],
      correctImpl: async () => ({ current: corrected }),
    });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText("资料.docx");
    fireEvent.click(screen.getByRole("button", { name: "更正类别或版本" }));
    fireEvent.click(screen.getByRole("button", { name: "版本改为未注明" }));
    fireEvent.click(screen.getByRole("button", { name: "地区改为未注明" }));
    fireEvent.click(screen.getByRole("button", { name: "保存更正" }));
    await screen.findByText(/已保存更正/);
    expect(api.correctSourceMetadata.mock.calls[0][2]).toEqual({
      source_role: "project_primary", source_version: "unidentified", jurisdiction: "unspecified",
    });
  });
});

describe("C03 challenge: abort safety around correction", () => {
  it("U9 unmount during an in-flight correction aborts it and stays silent", async () => {
    const gate = deferred();
    let correctionSignal = null;
    const api = createFakeApi({
      sources: [sourceRecord({ id: "s-old", key: "旧记录.docx" })],
      correctImpl: async (_p, _id, _body, { signal } = {}) => {
        correctionSignal = signal;
        return gate.promise;
      },
    });
    const view = render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText("旧记录.docx");
    fireEvent.click(screen.getByRole("button", { name: "更正类别或版本" }));
    fireEvent.change(screen.getByLabelText("更正类别"), { target: { value: "peer_reviewed" } });
    fireEvent.click(screen.getByRole("button", { name: "保存更正" }));
    await waitFor(() => expect(correctionSignal).not.toBeNull());
    view.unmount();
    expect(correctionSignal.aborted).toBe(true);
    gate.resolve({ current: sourceRecord({ id: "s-x", key: "旧记录.docx" }) });
    await new Promise((r) => setTimeout(r, 0));
  });

  it("U10 switching project during an in-flight correction aborts it and unlocks the new project", async () => {
    const gate = deferred();
    let correctionSignal = null;
    const api = createFakeApi({
      listImpl: async () => ({ sources: [] }),
      correctImpl: async (_p, _id, _body, { signal } = {}) => {
        correctionSignal = signal;
        return gate.promise;
      },
    });
    const view = render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/还没有已保存的资料/);
    // Stage a source on p1 so a correction target exists without a server list.
    fireEvent.change(screen.getByLabelText(/选择要添加的DOCX文件/), {
      target: { files: [docxFile("项目一.docx")] },
    });
    const saved = sourceRecord({ id: "s-p1", key: "项目一.docx" });
    api.importSource.mockImplementation(async () => ({ current: saved }));
    fireEvent.change(screen.getByLabelText("资料类别"), { target: { value: "project_primary" } });
    fireEvent.click(screen.getByRole("button", { name: "保存到资料" }));
    await screen.findByText("已保存。");

    fireEvent.click(screen.getByRole("button", { name: "更正类别或版本" }));
    fireEvent.change(screen.getByLabelText("更正类别"), { target: { value: "peer_reviewed" } });
    fireEvent.click(screen.getByRole("button", { name: "保存更正" }));
    await waitFor(() => expect(correctionSignal).not.toBeNull());

    view.rerender(<ProtocolSourceIntake projectId="p2" api={api} />);
    expect(correctionSignal.aborted).toBe(true);
    await screen.findByText(/还没有已保存的资料/);
    expect(screen.getByLabelText(/选择要添加的DOCX文件/).disabled).toBe(false);
    gate.resolve({ current: saved });
    await waitFor(() => expect(screen.queryByText(/已保存更正/)).toBeNull());
  });
});
