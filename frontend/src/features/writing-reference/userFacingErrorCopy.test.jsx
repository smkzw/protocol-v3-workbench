// 前端预清理批·③工程化语言清扫（用户指令20261003b，反例先红后绿）：
// 现场（R26/R27多轮）报错英文直出——『translation scope is not ready…』
// 『candidate is not approved for document ingestion』『HTTP 422』等后端
// 英文 detail 经各面板 `${error.message}` 拼接直接上屏。
//
// 契约：语料/写作各面板的用户可见错误文案必须经
// features/medical-writing/errorContract.mjs 的 medicalWritingSafeErrorText：
// 已知码→固定中文；中文文案原样保留；未知英文→受控中文兜底（技术原文进
// 诊断展开与后端日志，不上主文案）。
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { SharedPhase1CorpusPanel } from "./SharedPhase1CorpusPanel";

const PANEL_FILES = [
  "WritingReferencePanel.jsx",
  "ReferenceTranslationBatchPanel.jsx",
  "ReferencePreparationBatchPanel.jsx",
  "SharedPhase1CorpusPanel.jsx",
  "MixedOcrReviewPanel.jsx",
];

const PANEL_DIR = resolve(import.meta.dirname, ".");
const LITERATURE_PANEL = resolve(
  import.meta.dirname,
  "../medical-writing/MedicalWritingLiteraturePanel.jsx",
);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("engineering-language sweep (fe cleanup r1 ③)", () => {
  it("panels no longer splice raw backend error text into user-facing copy", async () => {
    for (const file of PANEL_FILES) {
      const source = await readFile(resolve(PANEL_DIR, file), "utf8");
      expect(
        source,
        `${file} 不得把原始 error.message 直接拼进用户可见文案`,
      ).not.toMatch(/set[A-Za-z]*\([^)]*`[^`]*\$\{error\.message\}/);
    }
    const literature = await readFile(LITERATURE_PANEL, "utf8");
    expect(literature).not.toMatch(
      /set[A-Za-z]*\([^)]*`[^`]*\$\{error\.message\}/,
    );
  });

  it("panels route user-facing copy through the controlled humanizer", async () => {
    for (const file of PANEL_FILES) {
      const source = await readFile(resolve(PANEL_DIR, file), "utf8");
      expect(source, `${file} 应引用 medicalWritingSafeErrorText`).toContain(
        "medicalWritingSafeErrorText",
      );
    }
  });

  it("an English backend detail renders as controlled Chinese, not raw text", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 422,
      json: async () => ({
        detail: "candidate is not approved for document ingestion",
      }),
    })));

    render(<SharedPhase1CorpusPanel />);

    const messageNode = await waitFor(() => {
      const node = screen.getByText(/共享语料读取失败/);
      expect(node).toBeTruthy();
      return node;
    });
    const message = messageNode.textContent;
    expect(message).not.toContain("candidate is not approved");
    expect(message).not.toContain("HTTP 422");
    expect(message).toMatch(/[\u4e00-\u9fff]/);
  });
});
