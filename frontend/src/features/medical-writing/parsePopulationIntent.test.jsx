// R27 第1轮末修订 P2-22：人群意图结构解析的子串误勾（反例先红后绿）。
// 现场：『疾病状态：中重度』保存→重载后『重度』框被自动勾上（『中重度』
// 含『重度』子串），再保存即静默改写用户输入。
// 契约：extract 按『、』（兼容逗号/分号）切分后全等匹配，不做子串匹配。
import { describe, expect, it } from "vitest";

import { parsePopulationIntentStructure } from "./MedicalWritingAuthoringJourneySetup";

describe("population intent parsing uses exact segment matching (P2-22)", () => {
  it("中重度 does not silently check 重度", () => {
    const parsed = parsePopulationIntentStructure(
      "18至75岁成人；疾病状态：中重度；经治情况：经治疗效不佳",
    );
    expect(parsed.diseaseStates).toEqual(["中重度"]);
  });

  it("multi-value segments still parse every explicit choice", () => {
    const parsed = parsePopulationIntentStructure(
      "疾病状态：中重度、重度；年龄段：成人",
    );
    expect(parsed.diseaseStates).toEqual(["中重度", "重度"]);
  });

  it("age bands keep exact matching too", () => {
    const parsed = parsePopulationIntentStructure("年龄段：成人、青少年；疾病状态：轻中度");
    expect(parsed.ageBands).toEqual(["成人", "青少年"]);
    expect(parsed.diseaseStates).toEqual(["轻中度"]);
  });
});
