// R9（第8轮末修订动作2）P0-18 输入层门前端契约：样本量声明内联警告。
// 现场（GER601 proj_user_1dc601868b26）：『两组各45例…差6分、SD 12、
// α=0.05双侧、80%把握度』在第二步表单原样通过——声明与自己的假设矛盾
// （复算需63例/组）无任何提示，错误数字一路走到导出件。
// 契约：sampleSizeDeclarationCheck 与后端 sample_size_declaration_check
// 同语义（仅UX预警用；硬门在服务端 commit_stage）——
// - GER601/f96adb/dad0 三组不一致文本 → status=不一致 + 复算明细文案；
// - 基准轮正向工艺（比例型设计51/102/192）→ 不得误拦；
// - 自洽声明（63例/组）→ status=自洽；
// - 无声明普通文本 → null（不适用）。
import { describe, expect, it } from "vitest";

import { sampleSizeDeclarationCheck } from "./MedicalWritingAuthoringJourneySetup";

describe("sample size declaration check (P0-18 frontend UX gate)", () => {
  it("GER601 45例/组 vs 复算63例/组 flags inconsistency with recalculation copy", () => {
    const check = sampleSizeDeclarationCheck(
      "两组各45例共90例；按GERD-HRQL组间差6分、SD 12、α=0.05双侧、80%把握度探索性设定。",
    );
    expect(check.status).toBe("不一致");
    expect(check.declaredPerGroup).toBe(45);
    expect(check.requiredPerGroup).toBe(63);
    expect(check.detail).toContain("63例/组");
    expect(check.detail).toContain("45例/组");
    expect(check.detail).toContain("请修正声明或调整假设");
  });

  it("f96adb 45 vs 33 and dad0 40 vs 51 both flag", () => {
    expect(sampleSizeDeclarationCheck("每组45例；按组间差4.5%、SD 6.5%、双侧α=0.05、把握度80%设定。"))
      .toMatchObject({ status: "不一致", declaredPerGroup: 45, requiredPerGroup: 33 });
    expect(sampleSizeDeclarationCheck("40例/组；按组间差25米、SD 45米、双侧α=0.05、把握度80%估算。"))
      .toMatchObject({ status: "不一致", declaredPerGroup: 40, requiredPerGroup: 51 });
  });

  it("proportion-based craft (benchmark positive) is not falsely blocked", () => {
    const check = sampleSizeDeclarationCheck(
      "本研究按两比例之差的检验计算样本量：基于外部锚点预期应答率47.4%与对照22.5%，单侧α=0.025、把握度80%，需51例/组（两个队列共102例，考虑脱落扩展至192例）。",
    );
    expect(check.status).not.toBe("不一致");
  });

  it("consistent declaration passes and unrelated text is not applicable", () => {
    expect(sampleSizeDeclarationCheck("按组间差6分、SD 12、双侧α=0.05、把握度80%，需63例/组。"))
      .toMatchObject({ status: "自洽", requiredPerGroup: 63 });
    expect(sampleSizeDeclarationCheck("本研究为随机双盲安慰剂对照研究。")).toBeNull();
  });
});
