// R9 P0-18 输入层门（前端预检）：样本量声明与假设不一致时，完成第二步
// 被阻断且统计页签内联警告给出复算明细；比例型正向工艺不误拦。
// 后端 commit 门（medical_writing_authoring_journey.commit_stage）为权威；
// 前端 sampleSizeDeclarationCheck 与服务端同一正则族/同一 ±20% 判据，
// 状态字面量与服务端一致（不一致/样本量要素未齐/自洽）。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import {
  sampleSizeDeclarationCheck,
  MedicalWritingAuthoringJourneySetup,
} from "./MedicalWritingAuthoringJourneySetup";

const GER601 = "两组各45例共90例；按GERD-HRQL组间差6分、SD 12、α=0.05双侧、80%把握度探索性设定。";
const F96ADB = "每组45例；按组间差4.5%、SD 6.5%、双侧α=0.05、把握度80%设定。";
const DAD0 = "40例/组；按组间差25米、SD 45米、双侧α=0.05、把握度80%估算。";
const POSITIVE = "基于外部锚点预期应答率47.4%与对照22.5%，单侧α=0.025、把握度80%，需51例/组（共102例，扩展至192例）。";
const CONSISTENT = "按组间差6分、SD 12、双侧α=0.05、把握度80%，需63例/组。";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("sampleSizeDeclarationCheck（浏览器端，与服务端同一契约）", () => {
  it.each([
    [GER601, 45, 63],
    [F96ADB, 45, 33],
    [DAD0, 40, 51],
  ])("判不一致 %j → 声明%d需%d", (text, declared, required) => {
    const check = sampleSizeDeclarationCheck(text);
    expect(check.status).toBe("不一致");
    expect(check.declaredPerGroup).toBe(declared);
    expect(check.requiredPerGroup).toBe(required);
    expect(check.detail).toContain(`${required}例/组`);
    expect(check.detail).toContain(`${declared}例/组`);
  });

  it("比例型正向工艺不误拦（要素未齐而非不一致）", () => {
    const check = sampleSizeDeclarationCheck(POSITIVE);
    expect(check.status).toBe("样本量要素未齐");
  });

  it("自洽声明放行", () => {
    expect(sampleSizeDeclarationCheck(CONSISTENT).status).toBe("自洽");
  });

  it("无声明返回 null", () => {
    expect(sampleSizeDeclarationCheck("本研究为随机双盲研究。")).toBeNull();
  });
});

describe("picosMissingFields 集成：不一致阻断完成第二步（组件级）", () => {
  it("完成第二步按钮在含不一致声明时禁用且执行页签有内联警告", async () => {
    const journey = {
      project_id: "proj_ss_gate_fe",
      revision: 3,
      entry_mode: "guided_greenfield",
      current_stage: "picos",
      framing_complete: true,
      picos_complete: false,
      framing: { protocol_id: "P1", version: "V0.1", document_title: "T", indication: "特应性皮炎", clinicaltrials_condition_term: "Atopic Dermatitis", study_phase: "III期", investigational_product: "R9-AD片" },
      picos: {
        design_archetype: "randomized_confirmatory",
        population_summary: "中重度特应性皮炎成人患者。",
        inclusion_modules: ["诊断标准符合"], exclusion_modules: ["活动性感染"],
        intervention_summary: "R9-AD两个剂量组", intervention_dose_regimen: "每日一次口服",
        comparator_summary: "匹配安慰剂", primary_endpoint: "第16周EASI-50应答率",
        safety_endpoints: ["TEAE发生率"], study_epochs: ["筛选期", "治疗期"],
        visit_strategy: "每4周访视一次", estimand_strategy: "治疗策略估计目标",
        sample_size_strategy: GER601,
        statistical_strategy: "MMRM主分析。",
      },
      synopsis_import: { status: "confirmed" },
      corpus_gate: { readiness_status: "not_ready", access_permitted: false, missing_requirements: [], covered_requirements: [], requirements: [], override: { active: false, reason: "", actor: "", recorded_at: null, acknowledged_missing_requirements: [] } },
      search_plan: null,
      prefill_package: null,
    };
    const fetchMock = vi.fn(async (url) => {
      if (String(url).endsWith("/medical-writing/authoring-journey")) {
        return { ok: true, status: 200, json: async () => journey };
      }
      return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MedicalWritingAuthoringJourneySetup projectId="proj_ss_gate_fe" projectHeader={{}} />);

    const commit = await screen.findByRole("button", { name: /完成第二步/ });
    await waitFor(() => {
      expect(commit.disabled).toBe(true);
      expect(commit.title).toContain("样本量声明与假设不一致");
    });
    const executionTab = screen.getByRole("tab", { name: "执行与统计" });
    executionTab.click();
    await waitFor(() => {
      const warning = document.querySelector('[data-testid="sample-size-warning"]');
      expect(warning).toBeTruthy();
      expect(warning.textContent).toContain("63例/组");
      expect(warning.textContent).toContain("45例/组");
    });
  });

  it("自洽声明不阻断完成第二步", async () => {
    const journey = {
      project_id: "proj_ss_gate_fe_ok",
      revision: 3,
      entry_mode: "guided_greenfield",
      current_stage: "picos",
      framing_complete: true,
      picos_complete: false,
      framing: { protocol_id: "P1", version: "V0.1", document_title: "T", indication: "特应性皮炎", clinicaltrials_condition_term: "Atopic Dermatitis", study_phase: "III期", investigational_product: "R9-AD片" },
      picos: {
        design_archetype: "randomized_confirmatory",
        population_summary: "中重度特应性皮炎成人患者。",
        inclusion_modules: ["诊断标准符合"], exclusion_modules: ["活动性感染"],
        intervention_summary: "R9-AD两个剂量组", intervention_dose_regimen: "每日一次口服",
        comparator_summary: "匹配安慰剂", primary_endpoint: "第16周EASI-50应答率",
        safety_endpoints: ["TEAE发生率"], study_epochs: ["筛选期", "治疗期"],
        visit_strategy: "每4周访视一次", estimand_strategy: "治疗策略估计目标",
        sample_size_strategy: CONSISTENT,
        statistical_strategy: "MMRM主分析。",
      },
      synopsis_import: { status: "confirmed" },
      corpus_gate: { readiness_status: "not_ready", access_permitted: false, missing_requirements: [], covered_requirements: [], requirements: [], override: { active: false, reason: "", actor: "", recorded_at: null, acknowledged_missing_requirements: [] } },
      search_plan: null,
      prefill_package: null,
    };
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      if (String(url).endsWith("/medical-writing/authoring-journey")) {
        return { ok: true, status: 200, json: async () => journey };
      }
      return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
    }));
    render(<MedicalWritingAuthoringJourneySetup projectId="proj_ss_gate_fe_ok" projectHeader={{}} />);

    const commit = await screen.findByRole("button", { name: /完成第二步/ });
    await waitFor(() => {
      expect(commit.disabled).toBe(false);
    });
    expect(document.querySelector('[data-testid="sample-size-warning"]')).toBeNull();
  });
});
