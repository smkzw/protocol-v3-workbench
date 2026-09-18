import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ProtocolWorkspaceApiError } from "./protocolWorkspaceApi.mjs";
import { ProtocolSourceIntake } from "./ProtocolSourceIntake";

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function sourceRecord({
  id,
  key,
  role = "project_primary",
  version = "unidentified",
  jurisdiction = "unspecified",
} = {}) {
  return {
    source: {
      source_artifact_id: id,
      logical_source_key: key,
      content_sha256: "a".repeat(64),
      source_role: role,
      source_version: version,
      jurisdiction,
      mime_type: DOCX_MIME,
      captured_at: "2026-09-13T08:00:00Z",
    },
    storage_key: `storage-${id}`,
    storage_revision: 1,
  };
}

function createFakeApi({ sources = [], listImpl, importImpl, correctImpl } = {}) {
  return {
    listSources: vi.fn(
      listImpl ??
        (async () => ({
          sources: sources.map((record) => JSON.parse(JSON.stringify(record))),
        })),
    ),
    importSource: vi.fn(importImpl ?? (async () => ({ replayed: false }))),
    correctSourceMetadata: vi.fn(correctImpl ?? (async () => ({ replayed: false }))),
    sourceDownloadUrl: (projectId, sourceArtifactId) =>
      `/api/projects/${projectId}/protocol-workflow/sources/${encodeURIComponent(String(sourceArtifactId))}/content`,
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function docxFile(name, bytes = [0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x06, 0x00]) {
  return new File([new Uint8Array(bytes)], name, { type: DOCX_MIME });
}

async function stageAndSave(file, role) {
  fireEvent.change(screen.getByLabelText(/选择要添加的DOCX文件/), {
    target: { files: [file] },
  });
  fireEvent.change(screen.getByLabelText("资料类别"), { target: { value: role } });
  fireEvent.click(screen.getByRole("button", { name: "保存到资料" }));
}

afterEach(() => {
  cleanup();
});

describe("ProtocolSourceIntake", () => {
  it("loads saved sources and shows them with human-readable details and original download links", async () => {
    const api = createFakeApi({
      sources: [
        sourceRecord({ id: "s-1", key: "指导原则.docx", role: "regulatory_or_guideline" }),
        sourceRecord({
          id: "s-2",
          key: "竞品方案.docx",
          role: "competitor_full_protocol",
          version: "2023版",
          jurisdiction: "美国",
        }),
      ],
    });

    render(<ProtocolSourceIntake projectId="p1" api={api} />);

    expect(api.listSources).toHaveBeenCalledWith("p1", {
      signal: expect.any(AbortSignal),
    });
    await screen.findByText("指导原则.docx");
    expect(screen.getByText(/法规或指导原则/)).toBeTruthy();
    expect(screen.getByText(/版本未注明/)).toBeTruthy();
    expect(screen.getByText(/地区未注明/)).toBeTruthy();
    expect(screen.getByText(/竞品完整方案/)).toBeTruthy();
    // The card meta line is one element per card: assert by substring.
    expect(screen.getByText(/版本：2023版/)).toBeTruthy();
    expect(screen.getByText(/地区：美国/)).toBeTruthy();

    const links = screen.getAllByRole("link", { name: /下载原文件/ });
    expect(links[0].getAttribute("href")).toBe(
      "/api/projects/p1/protocol-workflow/sources/s-1/content",
    );
    expect(links[1].getAttribute("href")).toBe(
      "/api/projects/p1/protocol-workflow/sources/s-2/content",
    );
  });

  it("shows a quiet empty state when the project has no saved sources", async () => {
    const api = createFakeApi({ sources: [] });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/还没有已保存的资料/);
  });
  it("offers every backend source role with a human-readable label", async () => {
    const api = createFakeApi({ sources: [] });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/还没有已保存的资料/);

    fireEvent.change(screen.getByLabelText(/选择要添加的DOCX文件/), {
      target: { files: [docxFile("角色列表.docx")] },
    });

    expect(screen.getAllByRole("option").map((option) => option.value)).toEqual([
      "",
      "project_primary",
      "regulatory_or_guideline",
      "competitor_full_protocol",
      "registry_only",
      "peer_reviewed",
      "company_style_only",
      "endpoint_or_instrument",
    ]);
    expect(screen.getByRole("option", { name: "终点定义或评估工具" })).toBeTruthy();
  });

  it("does not render the prepare action without an onPrepare callback", async () => {
    const api = createFakeApi({ sources: [] });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/还没有已保存的资料/);

    expect(screen.queryByRole("button", { name: "准备写作材料" })).toBeNull();
  });

  it("stages a DOCX, requires an explicit role, and passes original file metadata to the API", async () => {
    const saved = sourceRecord({ id: "s-new", key: "试验方案.docx", role: "company_style_only" });
    const api = createFakeApi({
      sources: [],
      importImpl: async () => ({
        source: saved,
        current: saved,
        replayed: false,
        medical_admission: "pending",
      }),
    });

    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/还没有已保存的资料/);

    const file = docxFile("试验方案.docx");
    fireEvent.change(screen.getByLabelText(/选择要添加的DOCX文件/), {
      target: { files: [file] },
    });
    expect(screen.getByText(/将添加：试验方案\.docx/)).toBeTruthy();

    // No role chosen yet: the save action stays unavailable (no default role).
    expect(screen.getByRole("button", { name: "保存到资料" }).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("资料类别"), { target: { value: "company_style_only" } });
    expect(screen.getByRole("button", { name: "保存到资料" }).disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "保存到资料" }));

    await screen.findByText("已保存。");
    await screen.findByText("试验方案.docx");

    expect(api.importSource).toHaveBeenCalledTimes(1);
    const [projectId, payload, options] = api.importSource.mock.calls[0];
    expect(projectId).toBe("p1");
    expect(payload.file).toBe(file);
    expect(payload.file.size).toBe(8);
    expect(payload.logicalSourceKey).toBe("试验方案.docx");
    expect(payload.sourceRole).toBe("company_style_only");
    // Version and jurisdiction are never inferred from the file name.
    expect(payload.sourceVersion).toBe("");
    expect(payload.jurisdiction).toBe("");
    expect(options.signal).toBeInstanceOf(AbortSignal);

    // The staging panel is closed after the real save; no source list re-fetch
    // was needed because the response carried the current record.
    expect(screen.queryByRole("button", { name: "保存到资料" })).toBeNull();
    expect(api.listSources).toHaveBeenCalledTimes(1);
  });

  it("rejects non-DOCX files quietly without calling the API", async () => {
    const api = createFakeApi({ sources: [] });
    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/还没有已保存的资料/);

    fireEvent.change(screen.getByLabelText(/选择要添加的DOCX文件/), {
      target: { files: [new File([new Uint8Array([1])], "笔记.pdf", { type: "application/pdf" })] },
    });

    expect(screen.getByText(/请选择DOCX格式的Word文件/)).toBeTruthy();
    expect(api.importSource).not.toHaveBeenCalled();
  });

  it("preserves the saved record and shows server guidance when a correction conflicts", async () => {
    const record = sourceRecord({ id: "s-old", key: "旧记录.docx", role: "project_primary" });
    const api = createFakeApi({
      sources: [record],
      correctImpl: async () => {
        throw new ProtocolWorkspaceApiError("资料已有新版本，本次更正没有覆盖新版本。", {
          status: 409,
          detail: {
            message: "资料已有新版本，本次更正没有覆盖新版本。",
            responsible_area: "source",
            can_retry: false,
            next_step: "请刷新资料列表，在当前版本上更正。",
          },
        });
      },
    });

    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText("旧记录.docx");

    fireEvent.click(screen.getByRole("button", { name: "更正类别或版本" }));
    fireEvent.change(screen.getByLabelText("更正类别"), { target: { value: "peer_reviewed" } });
    fireEvent.click(screen.getByRole("button", { name: "保存更正" }));

    await screen.findByText(/本次更正没有覆盖新版本/);
    expect(screen.getByText(/请刷新资料列表，在当前版本上更正/)).toBeTruthy();

    // The PATCH carries complete metadata: the edited role plus the retained
    // version and jurisdiction, and never re-uploads bytes.
    expect(api.correctSourceMetadata).toHaveBeenCalledTimes(1);
    const [projectId, sourceArtifactId, body, options] = api.correctSourceMetadata.mock.calls[0];
    expect(projectId).toBe("p1");
    expect(sourceArtifactId).toBe("s-old");
    expect(body).toEqual({
      source_role: "peer_reviewed",
      source_version: "unidentified",
      jurisdiction: "unspecified",
    });
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(api.importSource).not.toHaveBeenCalled();

    // The record survives the failed correction; the list is re-read once so
    // the current version is shown, and the editor is closed.
    await waitFor(() => expect(api.listSources).toHaveBeenCalledTimes(2));
    expect(screen.getByText("旧记录.docx")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "保存更正" })).toBeNull();
  });

  it("applies a successful correction and keeps untouched fields", async () => {
    const original = sourceRecord({ id: "s-old", key: "旧记录.docx", role: "project_primary" });
    const corrected = sourceRecord({
      id: "s-corr",
      key: "旧记录.docx",
      role: "peer_reviewed",
      version: "2.1",
      jurisdiction: "中国",
    });
    const api = createFakeApi({
      sources: [original],
      correctImpl: async () => ({ source: corrected, current: corrected, replayed: false }),
    });

    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText("旧记录.docx");

    fireEvent.click(screen.getByRole("button", { name: "更正类别或版本" }));
    fireEvent.change(screen.getByLabelText("更正类别"), { target: { value: "peer_reviewed" } });
    fireEvent.change(screen.getByLabelText(/版本（留空保持原值）/), { target: { value: "2.1" } });
    fireEvent.change(screen.getByLabelText(/地区（留空保持原值）/), { target: { value: "中国" } });
    fireEvent.click(screen.getByRole("button", { name: "保存更正" }));

    await screen.findByText(/已保存更正/);
    expect(screen.getByText(/同行评审文献/)).toBeTruthy();
    expect(screen.getByText(/版本：2\.1/)).toBeTruthy();
    expect(screen.getByText(/地区：中国/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "保存更正" })).toBeNull();
    expect(api.listSources).toHaveBeenCalledTimes(1);
  });

  it("treats a replayed upload as already saved and uses the current identity, not the historical receipt", async () => {
    const historical = sourceRecord({ id: "s-hist", key: "方案.docx", version: "1.0" });
    const current = sourceRecord({ id: "s-curr", key: "方案.docx", version: "2.0" });
    const onPrepare = vi.fn();
    const api = createFakeApi({
      sources: [],
      importImpl: async () => ({ source: historical, current, replayed: true }),
    });

    render(<ProtocolSourceIntake projectId="p1" api={api} onPrepare={onPrepare} />);
    await screen.findByText(/还没有已保存的资料/);

    await stageAndSave(docxFile("方案.docx"), "project_primary");

    // Quiet replay status instead of a fresh-save claim.
    await screen.findByText(/此前已保存/);
    expect(screen.queryByText("已保存。")).toBeNull();

    // The card reflects the CURRENT identity (version 2.0), and prepare hands
    // the current id to the parent — never the historical s-hist receipt.
    await screen.findByText(/版本：2\.0/);
    fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
    expect(onPrepare).toHaveBeenCalledTimes(1);
    expect(onPrepare.mock.calls[0][0]).toEqual({
      userBrief: "",
      sourceArtifactIds: ["s-curr"],
    });

    // Deselecting the card removes its current identity from the payload.
    fireEvent.click(screen.getByLabelText("纳入后续写作：方案.docx"));
    fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
    expect(onPrepare.mock.calls[1][0]).toEqual({ userBrief: "", sourceArtifactIds: [] });
    expect(api.listSources).toHaveBeenCalledTimes(1);
  });

  it("keeps the writing brief through a source refresh and passes it to prepare", async () => {
    const saved = sourceRecord({ id: "s-new", key: "老年方案补充.docx" });
    const onPrepare = vi.fn();
    const api = createFakeApi({
      sources: [],
      importImpl: async () => ({ source: saved, current: saved, replayed: false }),
    });

    let brief = "";
    const onBriefChange = vi.fn((next) => {
      brief = next;
    });
    const view = render(
      <ProtocolSourceIntake
        projectId="p1"
        api={api}
        brief={brief}
        onBriefChange={onBriefChange}
        onPrepare={onPrepare}
      />,
    );
    await screen.findByText(/还没有已保存的资料/);

    fireEvent.change(screen.getByLabelText(/写作说明/), { target: { value: "侧重老年亚组" } });
    expect(onBriefChange).toHaveBeenCalledWith("侧重老年亚组");
    view.rerender(
      <ProtocolSourceIntake
        projectId="p1"
        api={api}
        brief="侧重老年亚组"
        onBriefChange={onBriefChange}
        onPrepare={onPrepare}
      />,
    );

    await stageAndSave(docxFile("老年方案补充.docx"), "project_primary");
    await screen.findByText("已保存。");

    expect(screen.getByLabelText(/写作说明/).value).toBe("侧重老年亚组");
    fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
    expect(onPrepare.mock.calls[0][0]).toEqual({
      userBrief: "侧重老年亚组",
      sourceArtifactIds: ["s-new"],
    });
  });

  it("discards a delayed source list from a previous project after a project switch", async () => {
    const p1Deferred = deferred();
    let p1Signal = null;
    const p1Record = sourceRecord({ id: "s-p1", key: "一号线.docx" });
    const p2Record = sourceRecord({ id: "s-p2", key: "二号线.docx" });
    const api = createFakeApi({
      listImpl: (projectId, { signal } = {}) => {
        if (projectId === "p1") {
          p1Signal = signal;
          return p1Deferred.promise;
        }
        return Promise.resolve({ sources: [p2Record] });
      },
    });

    const view = render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await waitFor(() => expect(p1Signal).not.toBeNull());

    view.rerender(<ProtocolSourceIntake projectId="p2" api={api} />);

    // The stale p1 request is aborted; only p2 data may ever reach the UI.
    expect(p1Signal.aborted).toBe(true);
    await screen.findByText("二号线.docx");

    p1Deferred.resolve({ sources: [p1Record] });
    await waitFor(() => {
      expect(screen.queryByText("一号线.docx")).toBeNull();
    });
    expect(screen.getByText("二号线.docx")).toBeTruthy();
  });

  it("aborts the in-flight request on unmount and never applies it afterwards", async () => {
    const p1Deferred = deferred();
    let p1Signal = null;
    const api = createFakeApi({
      listImpl: (_projectId, { signal } = {}) => {
        p1Signal = signal;
        return p1Deferred.promise;
      },
    });

    const view = render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await waitFor(() => expect(p1Signal).not.toBeNull());

    view.unmount();
    expect(p1Signal.aborted).toBe(true);

    p1Deferred.resolve({ sources: [sourceRecord({ id: "s-late", key: "迟到文件.docx" })] });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText(/迟到文件/)).toBeNull();
  });

  it("does not claim a save when the response has no current source identity", async () => {
    const api = createFakeApi({
      sources: [],
      importImpl: async () => ({ replayed: false }),
    });

    render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/还没有已保存的资料/);

    await stageAndSave(docxFile("未确认.docx"), "project_primary");

    await screen.findByText(/未能确认/);
    expect(screen.queryByText("已保存。")).toBeNull();
    expect(api.listSources).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/还没有已保存的资料/)).toBeTruthy();
  });

  it("keeps an excluded source excluded when a correction creates its current identity", async () => {
    const original = sourceRecord({ id: "s-old", key: "需更正.docx" });
    const corrected = sourceRecord({
      id: "s-corr",
      key: "需更正.docx",
      role: "peer_reviewed",
    });
    const onPrepare = vi.fn();
    const api = createFakeApi({
      sources: [original],
      correctImpl: async () => ({ source: corrected, current: corrected, replayed: false }),
    });

    render(<ProtocolSourceIntake projectId="p1" api={api} onPrepare={onPrepare} />);
    await screen.findByText("需更正.docx");
    fireEvent.click(screen.getByLabelText("纳入后续写作：需更正.docx"));

    fireEvent.click(screen.getByRole("button", { name: "更正类别或版本" }));
    fireEvent.change(screen.getByLabelText("更正类别"), {
      target: { value: "peer_reviewed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存更正" }));

    await screen.findByText(/已保存更正/);
    fireEvent.click(screen.getByRole("button", { name: "准备写作材料" }));
    expect(onPrepare).toHaveBeenCalledWith({
      userBrief: "",
      sourceArtifactIds: [],
    });
  });

  it("isolates a delayed upload from a project switch and unlocks the new project", async () => {
    const uploadDeferred = deferred();
    let uploadSignal = null;
    const p1Record = sourceRecord({ id: "s-p1-upload", key: "一号上传.docx" });
    const api = createFakeApi({
      listImpl: (projectId) => Promise.resolve({ sources: projectId === "p1" ? [] : [] }),
      importImpl: (projectId, _payload, { signal } = {}) => {
        if (projectId === "p1") {
          uploadSignal = signal;
          return uploadDeferred.promise;
        }
        return Promise.resolve({ current: p1Record, replayed: false });
      },
    });

    const view = render(<ProtocolSourceIntake projectId="p1" api={api} />);
    await screen.findByText(/还没有已保存的资料/);
    await stageAndSave(docxFile("一号上传.docx"), "project_primary");
    await waitFor(() => expect(uploadSignal).not.toBeNull());

    view.rerender(<ProtocolSourceIntake projectId="p2" api={api} />);
    await screen.findByText(/还没有已保存的资料/);
    expect(uploadSignal.aborted).toBe(true);
    expect(screen.getByLabelText(/选择要添加的DOCX文件/).disabled).toBe(false);

    uploadDeferred.resolve({ source: p1Record, current: p1Record, replayed: false });
    await waitFor(() => {
      expect(screen.queryByText("一号上传.docx")).toBeNull();
      expect(screen.queryByText("已保存。")).toBeNull();
    });
  });

  it("shows the server's load failure with a manual retry instead of looping", async () => {
    const record = sourceRecord({ id: "s-1", key: "指导原则.docx" });
    const api = createFakeApi({});
    api.listSources
      .mockRejectedValueOnce(
        new ProtocolWorkspaceApiError("方案资料暂时读取不到。", {
          status: 503,
          detail: { message: "方案资料暂时读取不到。", next_step: "请稍后重试。" },
        }),
      )
      .mockResolvedValue({ sources: [record] });

    render(<ProtocolSourceIntake projectId="p1" api={api} />);

    await screen.findByText(/方案资料暂时读取不到/);
    expect(screen.getByText(/请稍后重试/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await screen.findByText("指导原则.docx");
    expect(api.listSources).toHaveBeenCalledTimes(2);
  });
});


it("can explicitly remove mistaken source version and region without re-upload", async () => {
  const original = sourceRecord({ id: "wrong", key: "资料.docx", version: "误填版本", jurisdiction: "误填地区" });
  const corrected = sourceRecord({ id: "cleared", key: "资料.docx" });
  const api = createFakeApi({ sources: [original], correctImpl: async () => ({ current: corrected }) });
  render(<ProtocolSourceIntake projectId="p1" api={api} />);
  await screen.findByText("资料.docx");
  fireEvent.click(screen.getByRole("button", { name: "更正类别或版本" }));
  fireEvent.click(screen.getByRole("button", { name: "版本改为未注明" }));
  fireEvent.click(screen.getByRole("button", { name: "地区改为未注明" }));
  fireEvent.click(screen.getByRole("button", { name: "保存更正" }));
  await screen.findByText("已保存更正。");
  expect(api.correctSourceMetadata.mock.calls[0][2]).toEqual({ source_role: "project_primary", source_version: "unidentified", jurisdiction: "unspecified" });
  expect(api.importSource).not.toHaveBeenCalled();
});


it("imports a selected group once in order using the same chosen source role", async () => {
  const files = [docxFile("方案.docx"), docxFile("手册.docx")];
  const api = createFakeApi({ importImpl: async (_project, body) => ({ current: sourceRecord({ id: body.file.name, key: body.file.name }) }) });
  render(<ProtocolSourceIntake projectId="p1" api={api} />);
  await screen.findByText(/还没有已保存的资料/);
  const input = screen.getByLabelText(/选择要添加的DOCX文件/);
  expect(input.multiple).toBe(true);
  fireEvent.change(input, { target: { files } });
  fireEvent.change(screen.getByLabelText("资料类别"), { target: { value: "project_primary" } });
  fireEvent.click(screen.getByRole("button", { name: "保存到资料" }));
  await waitFor(() => expect(api.importSource).toHaveBeenCalledTimes(2));
  await screen.findByText("手册.docx");
  expect(api.importSource.mock.calls.map(call => call[1].file)).toEqual(files);
  expect(api.importSource.mock.calls.map(call => call[1].sourceRole)).toEqual(["project_primary", "project_primary"]);
  expect(api.listSources).toHaveBeenCalledTimes(1);
});

it("halts a group on an uncertain result and preserves both saved records and unsubmitted files", async () => {
  const files = [docxFile("第一.docx"), docxFile("第二.docx"), docxFile("第三.docx")];
  const first = sourceRecord({ id: "first", key: "第一.docx" });
  const api = createFakeApi({ listImpl: async () => ({ sources: [first] }), importImpl: async (_project, body) => {
    if (body.file === files[0]) return { current: first };
    throw new Error("连接中断，保存结果尚待确认。");
  } });
  render(<ProtocolSourceIntake projectId="p1" api={api} />);
  await screen.findByText("第一.docx");
  fireEvent.change(screen.getByLabelText(/选择要添加的DOCX文件/), { target: { files } });
  fireEvent.change(screen.getByLabelText("资料类别"), { target: { value: "project_primary" } });
  fireEvent.click(screen.getByRole("button", { name: "保存到资料" }));
  await screen.findByText("连接中断，保存结果尚待确认。");
  await waitFor(() => expect(api.listSources).toHaveBeenCalledTimes(2));
  expect(api.importSource).toHaveBeenCalledTimes(2);
  expect(screen.getByText("第一.docx")).toBeTruthy();
  expect(screen.getByText(/将添加：第二.docx/)).toBeTruthy();
  expect(screen.getByText(/第三.docx/)).toBeTruthy();
});
