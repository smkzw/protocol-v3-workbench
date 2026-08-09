import { describe, expect, it } from "vitest";

import {
  previewPageCountBasisLabel,
  previewPageSummary,
  previewStatusLabel,
} from "./MedicalWritingPreviewPanel";

describe("medical writing preview truth boundary", () => {
  it("keeps the estimate and Word receipt labels distinct", () => {
    expect(previewPageCountBasisLabel("style_profile_estimate")).toBe("快速估算");
    expect(previewPageCountBasisLabel("microsoft_word_receipt")).toBe("Word已核验");
    expect(previewStatusLabel("fast_preview")).toBe("快速分页预览");
    expect(previewStatusLabel("word_verified")).toBe("Microsoft Word/PDF核验");
  });

  it("summarizes page evidence without assuming every page has locators", () => {
    expect(previewPageSummary({ section_ids: ["s1", "s2"], block_ids: ["b1"] })).toBe("2个章节 · 1个内容块");
    expect(previewPageSummary({})).toBe("0个章节 · 0个内容块");
  });
});

