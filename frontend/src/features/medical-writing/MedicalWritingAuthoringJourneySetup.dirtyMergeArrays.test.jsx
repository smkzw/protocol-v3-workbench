// R26 自检R5第2次 P0-A 反例（红先修后）：
// 现场（proj_user_f6b25587e9b2）：编辑器新增的IP给药方案行经4轮提交均不落库
// （最终 ip_regimens 仅剩派生安慰剂1条），结构化清单在往返后回退missing。
// 根因之一：applyJourneyResponse 的脏态合并 mergeIncomingPreservingLocal 对
// 数组采用"incoming 非空即整替本地"——异步旅程写回（框架往返/门重算）带回的
// 是旧快照数组，用户在编辑器里较新的行/清单被旧数组覆盖。
// 预期契约：脏态合并时，非空本地数组（用户未保存的较新工作）优先保留；
// incoming 数组仅在本地为空时填充。
import { describe, expect, it } from "vitest";

import { mergeIncomingPreservingLocal } from "./MedicalWritingAuthoringJourneySetup";

describe("dirty-state merge preserves user-edited arrays (R26 R5#2 P0-A)", () => {
  it("keeps the local editor regimen rows when an async write-back carries the older committed arrays", () => {
    const current = {
      intervention_summary: "SMOKE-r2-2两个剂量组。",
      required_background_rules: ["稳定剂量甲氨蝶呤"],
      intervention_rules: {
        schema_version: "medical_writing_intervention_rules_v1",
        authority: "structured",
        ip_regimens: [
          { regimen_id: "reg_user_ip", product_name: "SMOKE-r2-2", product_role: "investigational_product", dose_and_frequency: "口服每日一次" },
        ],
        non_ip_treatment_rules: [],
      },
    };
    const incoming = {
      intervention_summary: "SMOKE-r2-2两个剂量组。",
      required_background_rules: ["稳定剂量甲氨蝶呤"],
      intervention_rules: {
        schema_version: "medical_writing_intervention_rules_v1",
        authority: "structured",
        ip_regimens: [
          { regimen_id: "legacy-derived-placebo-1", product_name: "安慰剂", product_role: "placebo", dose_and_frequency: "匹配安慰剂" },
        ],
        non_ip_treatment_rules: [],
      },
    };

    const merged = mergeIncomingPreservingLocal(current, incoming);

    expect(merged.intervention_rules.ip_regimens).toEqual(current.intervention_rules.ip_regimens);
  });

  it("still fills arrays the user has never touched (local empty)", () => {
    const current = { washout_rules: [], key_secondary_endpoints: undefined };
    const incoming = { washout_rules: ["既往生物制剂完成洗脱"], key_secondary_endpoints: ["第12周DAS28变化"] };

    const merged = mergeIncomingPreservingLocal(current, incoming);

    expect(merged.washout_rules).toEqual(["既往生物制剂完成洗脱"]);
    expect(merged.key_secondary_endpoints).toEqual(["第12周DAS28变化"]);
  });
});
