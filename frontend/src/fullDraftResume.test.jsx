// 自检r2-4观察②反例：失败/取消的全文初稿任务都必须提供续跑入口。
// 现场（r2-2续推，运维帽主动cancel后）：resume按钮仅在 status==="failed"
// 渲染——cancelled 任务无任何恢复入口，且「生成全文初稿」幂等复用已结束
// 任务后前端空转轮询直到报错，用户无从续跑。
import { describe, expect, it } from "vitest";
import {
  fullDraftResumeVisible,
  fullDraftReusedTerminal,
} from "./App";

describe("全文初稿续跑入口覆盖 failed 与 cancelled（r2-4观察②）", () => {
  it("cancelled 与 failed 都显示续跑入口；进行中/完成态不显示", () => {
    expect(fullDraftResumeVisible("cancelled")).toBe(true);
    expect(fullDraftResumeVisible("failed")).toBe(true);
    expect(fullDraftResumeVisible("running")).toBe(false);
    expect(fullDraftResumeVisible("queued")).toBe(false);
    expect(fullDraftResumeVisible("completed")).toBe(false);
    expect(fullDraftResumeVisible(undefined)).toBe(false);
  });

  it("幂等复用命中终态任务时给出明确指引而非空转轮询", () => {
    expect(fullDraftReusedTerminal("cancelled")).toBe(true);
    expect(fullDraftReusedTerminal("failed")).toBe(true);
    expect(fullDraftReusedTerminal("queued")).toBe(false);
    expect(fullDraftReusedTerminal("completed")).toBe(false);
  });
});
