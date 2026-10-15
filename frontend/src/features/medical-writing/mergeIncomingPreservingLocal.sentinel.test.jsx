// 自检r2-3红节点⑤反例（2026-10-15，proj_user_cfa0c74fd152）：product_profile
// 哨兵占位值（'unknown'）不得在旅程写回合并中覆盖本地已填真实值——现场签名
// "四字段只有数组存活、两个标量被unknown回写清掉"的机制级复现。
import { describe, expect, it } from "vitest";
import { mergeIncomingPreservingLocal } from "./MedicalWritingAuthoringJourneySetup.jsx";

describe("mergeIncomingPreservingLocal 哨兵占位值不覆盖本地真实值（r2-3红节点⑤）", () => {
  it("服务端快照带unknown/空数组回写时，本地画像四字段全部保留", () => {
    const local = {
      technology_type: "small_molecule",
      exposure_scope: "systemic",
      administration_routes: ["口服"],
      dosage_forms: ["口服固体制剂"],
    };
    const incoming = {
      technology_type: "unknown",
      exposure_scope: "unknown",
      administration_routes: [],
      dosage_forms: [],
      device_dependency: "unknown",
    };
    const merged = mergeIncomingPreservingLocal(local, incoming);
    expect(merged.technology_type).toBe("small_molecule");
    expect(merged.exposure_scope).toBe("systemic");
    expect(merged.administration_routes).toEqual(["口服"]);
    expect(merged.dosage_forms).toEqual(["口服固体制剂"]);
  });

  it("本地为空时服务端真实值照常合入（不阻碍正常同步）", () => {
    const local = { technology_type: "unknown", exposure_scope: "unknown", administration_routes: [] };
    const incoming = { technology_type: "small_molecule", exposure_scope: "systemic", administration_routes: ["口服"] };
    const merged = mergeIncomingPreservingLocal(local, incoming);
    expect(merged.technology_type).toBe("small_molecule");
    expect(merged.exposure_scope).toBe("systemic");
    expect(merged.administration_routes).toEqual(["口服"]);
  });

  it("undecided结构化设计哨兵同样不覆盖本地已确认值", () => {
    const merged = mergeIncomingPreservingLocal(
      { randomization_mode: "randomized" },
      { randomization_mode: "undecided" },
    );
    expect(merged.randomization_mode).toBe("randomized");
  });
});

describe("r2-4观察③：intervention_rules.ip_adjustment_policy 哨兵同样不回写", () => {
  it("unspecified（未指定）不覆盖本地已选的剂量调整政策", () => {
    const merged = mergeIncomingPreservingLocal(
      {
        intervention_rules: {
          authority: "structured",
          ip_adjustment_policy: "no_planned_adjustment",
          no_planned_adjustment_statement: "本研究无计划性剂量调整。",
        },
      },
      {
        // 旅程写回携带服务端旧快照：政策仍为未指定（创建默认）。
        intervention_rules: {
          authority: "legacy",
          ip_adjustment_policy: "unspecified",
          no_planned_adjustment_statement: "",
        },
      },
    );
    expect(merged.intervention_rules.ip_adjustment_policy).toBe(
      "no_planned_adjustment",
    );
    expect(merged.intervention_rules.no_planned_adjustment_statement).toBe(
      "本研究无计划性剂量调整。",
    );
  });
});
