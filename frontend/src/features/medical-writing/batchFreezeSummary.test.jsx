// 第10轮末修订（P1-51）：批量冻结批结果的人话汇总与跳过清单。
// 现场（r10-A 卡67）：首轮110→43后连点8次零反馈——后端 skipped+reason
// 已返回但前端只显示一句汇总，跳过章既不可见也无下一步；缺的是
// 『跳过清单行内可见+每行原因』而非强冻占位章。
// 契约：
// - line：冻结N/跳过M/失败K 逐段人话（0段不显示）；
// - skippedItems：逐章『编号 标题』+原因（空 section_id 的“已全冻”
//   占位条目不进清单，改为 line 尾注）；
// - failures 逐条保留原始错误（版本冲突类指引刷新重试）。
import { describe, expect, it } from "vitest";

import { buildBatchFreezeSummary } from "./batchFreezeSummary.mjs";

describe("batch freeze summary (P1-51)", () => {
  it("renders frozen/skipped/failed segments and per-section skip reasons", () => {
    const summary = buildBatchFreezeSummary({
      frozen_section_ids: ["s1", "s2", "s3"],
      skipped: [
        {
          section_id: "sec_62",
          section_heading: "研究治疗给药",
          reason_code: "working_copy_not_saved",
          message: "该章节尚未保存工作副本，请先保存后再冻结。",
        },
        {
          section_id: "sec_63",
          section_heading: "剂量调整",
          reason_code: "working_copy_quarantined",
          message: "当前历史版本已隔离，请先确认绑定或恢复权威基线。",
        },
      ],
      failures: [
        { section_id: "sec_70", section_heading: "统计学", error: "版本冲突，请刷新后重试该章" },
      ],
      readiness_ready: false,
      readiness_gaps_remaining: 2,
    });
    expect(summary.line).toContain("已冻结 3 个章节");
    expect(summary.line).toContain("跳过 2 个章节");
    expect(summary.line).toContain("失败 1 个章节");
    expect(summary.skippedItems).toHaveLength(2);
    expect(summary.skippedItems[0].label).toContain("研究治疗给药");
    expect(summary.skippedItems[0].reason).toContain("尚未保存");
    expect(summary.failuresCount).toBe(1);
  });

  it("all-frozen placeholder skip becomes a tail note not a list item", () => {
    const summary = buildBatchFreezeSummary({
      frozen_section_ids: [],
      skipped: [
        { section_id: "", reason_code: "already_frozen", message: "全部待冻章节均已冻结，无需重复操作。" },
      ],
      failures: [],
    });
    expect(summary.skippedItems).toHaveLength(0);
    expect(summary.line).toContain("此前批次已全部冻结");
    expect(summary.line).toContain("已冻结 0 个章节");
  });

  it("clean batch shows no skip or failure segment", () => {
    const summary = buildBatchFreezeSummary({ frozen_section_ids: ["a"] });
    expect(summary.line).toBe("已冻结 1 个章节。");
    expect(summary.skippedItems).toHaveLength(0);
    expect(summary.failuresCount).toBe(0);
  });
});
