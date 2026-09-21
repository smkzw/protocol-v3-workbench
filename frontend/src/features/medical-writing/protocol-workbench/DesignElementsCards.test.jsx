import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { DesignElementsCards } from "./DesignElementsCards";

const props = {
  projectId: "project:one",
  studyDefinitionId: "study:one",
  seedRunId: "seed:one",
  actorId: "user:one",
};
const storageKey = "protocol-v3:design-elements:" + JSON.stringify([
  props.projectId, props.studyDefinitionId, props.seedRunId,
]);
const proposal = {
  status: "ready_for_review",
  objectives: {
    primary: [
      { text: "第一个主要目的", basis: "recommendation", reason: "目的一依据" },
      { text: "第二个主要目的", basis: "source", reason: "目的二依据" },
    ],
    secondary: [],
  },
  endpoint: {
    primary_endpoint: { text: "主要终点", basis: "source", reason: "终点依据" },
    key_secondary: [],
  },
  estimand: {
    treatment: { text: "治疗", basis: "recommendation", reason: "治疗依据" },
    population: { text: "人群", basis: "recommendation", reason: "人群依据" },
    variable: { text: "变量", basis: "recommendation", reason: "变量依据" },
    ice_strategy: { text: "伴发事件策略", basis: "recommendation", reason: "策略依据" },
    summary_measure: { text: "汇总量", basis: "recommendation", reason: "汇总依据" },
  },
  sample_size: {
    assumptions: ["效应量假设"], alpha: "0.05", power: "0.8", model: "二项模型",
    planned_n: "100例", attrition: "10%", justification: "样本量依据",
  },
};
const state = {
  status: "ready_for_review",
  expected_revision: 1,
  snapshot_sha256: "a".repeat(64),
  validation: { valid: true, proposal },
};
const receipt = {
  project_id: props.projectId,
  study_definition_id: props.studyDefinitionId,
  revision: 2,
  revision_sha256: "b".repeat(64),
  effective_decision: { decision_record_id: "decision:one" },
  definition: {
    project_id: props.projectId,
    study_definition_id: props.studyDefinitionId,
    revision: 2,
  },
};

function missingReceipt() {
  return Object.assign(new Error("尚未查到保存回执"), { status: 404 });
}
function readyApi(overrides = {}) {
  return {
    getDesignElements: vi.fn(async () => state),
    recoverDesignCard: vi.fn(async () => { throw missingReceipt(); }),
    adoptDesignCard: vi.fn(async () => receipt),
    ...overrides,
  };
}
function renderWithRun(api, run = "run:one") {
  localStorage.setItem(storageKey, JSON.stringify(run));
  return render(<DesignElementsCards {...props} api={api} />);
}

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("DesignElementsCards choices and recovery", () => {
  it("sends the selected second primary objective as index 1", async () => {
    const api = readyApi();
    renderWithRun(api);
    const card = await screen.findByRole("region", { name: "研究目的与主要终点" });
    const radios = within(card).getAllByRole("radio");
    expect(radios[0].checked).toBe(true);
    fireEvent.click(radios[1]);
    fireEvent.click(within(card).getByRole("button", { name: "确认本卡片内容" }));
    await within(card).findByText("已确认主要研究目的：第二个主要目的");
    expect(api.adoptDesignCard).toHaveBeenCalledTimes(1);
    expect(api.adoptDesignCard.mock.calls[0][3].selections.primary_objective).toBe(1);
  });

  it("reuses a pending original intent after remount without adopting twice", async () => {
    const intent = {
      study_definition_id: props.studyDefinitionId,
      operation_id: "design-card:original",
      card: "objectives-endpoint",
      expected_revision: 1,
      snapshot_sha256: "a".repeat(64),
      actor_id: props.actorId,
      decided_at: "2026-09-21T00:00:00.000Z",
      reason: "确认研究目的与主要终点",
      seed_run_id: props.seedRunId,
      selections: { primary_objective: 1, primary_endpoint_confirmed: true },
    };
    localStorage.setItem(storageKey, JSON.stringify("run:one"));
    localStorage.setItem(`${storageKey}:intent:objectives-endpoint`, JSON.stringify(intent));
    const api = readyApi({
      recoverDesignCard: vi.fn()
        .mockRejectedValueOnce(missingReceipt())
        .mockResolvedValueOnce(receipt),
      adoptDesignCard: vi.fn(),
    });
    const view = render(<DesignElementsCards {...props} api={api} />);
    await screen.findByRole("button", { name: "核对本次确认" });
    expect(JSON.parse(localStorage.getItem(`${storageKey}:intent:objectives-endpoint`))).toEqual(intent);
    view.unmount();
    render(<DesignElementsCards {...props} api={api} />);
    await screen.findByText("已确认主要研究目的：第二个主要目的");
    expect(api.adoptDesignCard).not.toHaveBeenCalled();
    expect(api.recoverDesignCard).toHaveBeenCalledTimes(2);
    expect(api.recoverDesignCard.mock.calls[1][3]).toEqual(intent);
  });

  it("shows the confirmed objective rather than the proposal default", async () => {
    localStorage.setItem(storageKey, JSON.stringify("run:one"));
    localStorage.setItem(`${storageKey}:confirmed`, JSON.stringify({
      "objectives-endpoint": {
        operation_id: "design-card:confirmed",
        revision: 2,
        selections: { primary_objective: 1, primary_endpoint_confirmed: true },
      },
    }));
    const api = readyApi({ recoverDesignCard: vi.fn(), adoptDesignCard: vi.fn() });
    render(<DesignElementsCards {...props} api={api} />);
    const card = await screen.findByRole("region", { name: "研究目的与主要终点" });
    await within(card).findByText("已确认主要研究目的：第二个主要目的");
    expect(within(card).queryByText("已确认主要研究目的：第一个主要目的")).toBeNull();
    expect(within(card).getAllByRole("radio")[1].checked).toBe(true);
    expect(api.adoptDesignCard).not.toHaveBeenCalled();
  });
});
