// 前端预清理批·②全页宽守卫 + ④不和谐换行（用户指令20261003b）。
//
// ②现场感知"整体UI偏左不用满页宽"：DOM实测（实现师20261004，1440×900，
// camofox）全部导航页主内容 198→1422（1224/1260≈97%），写作页 1340/1376，
// 无任何页级 max-width 钳制——感知不成立，不造假改宽度。此测试是防回归
// 守卫：壳层必须保持流式满宽（180px侧栏+minmax(0,1fr)主列，禁 max-width）。
//
// ④现场证据：R26-MW"匹配维度表把汉字竖着挤成一列"（首列 64px 固定宽，
// 4-5字中文标签在窄抽屉内逐字换行）；R27-R1-D 截图22"底部适应性设计/交叉/
// OLE/DMC一排下拉挤在一起、换行错位"（authoring-structured-planned-grid
// 无任何CSS规则）。
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const STYLES = await readFile(
  resolve(import.meta.dirname, "../../styles.css"),
  "utf8",
);

describe("full-width shell guard (fe cleanup r1 ②)", () => {
  it("keeps the app shell fluid: fixed sidebar + fluid main, no page-level cap", () => {
    expect(STYLES).toMatch(/\.app \{[^}]*grid-template-columns: 180px minmax\(0, 1fr\)/s);
    expect(STYLES).not.toMatch(/\.app \{[^}]*max-width/s);
    expect(STYLES).not.toMatch(/\bmain \{[^}]*max-width/s);
    // 写作页双栏同样是流式比例，不设上限。
    expect(STYLES).toMatch(/\.writing-layout \{[^}]*minmax\(720px, 1\.72fr\) minmax\(360px, 0\.72fr\)/s);
  });
});

describe("cjk line-break fixes (fe cleanup r1 ④)", () => {
  it("matching-dimension label column no longer forces one-CJK-char-per-line", () => {
    // 旧：64px 固定首列。新：minmax 下限放宽到 88px 且可随内容增长，
    // 标签禁止逐字断行（word-break: keep-all）。
    expect(STYLES).toMatch(
      /\.writing-reference-validation-checks > div \{[^}]*grid-template-columns: minmax\(88px, auto\) 48px minmax\(0, 1fr\)/s,
    );
    expect(STYLES).toMatch(
      /\.writing-reference-validation-checks b \{[^}]*word-break: keep-all/s,
    );
  });

  it("structured planned-design select row has a real responsive grid", () => {
    expect(STYLES).toMatch(/\.authoring-structured-planned-grid \{/);
    expect(STYLES).toMatch(
      /\.authoring-structured-planned-grid \{[^}]*repeat\(auto-fit, minmax\(150px, 1fr\)\)/s,
    );
  });
});
