import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { RegimenDesignWorkspace } from "../../../../../frontend/src/features/medical-writing/protocol-workbench/RegimenDesignWorkspace.jsx";

const done = {
  workflow_run_id: "design:one", status: "needs_information", can_resume: false,
  validation: { valid: true, proposal: { regimen: null, questions: ["请补充研究给药途径。"], coverage: [] } },
};
afterEach(() => { cleanup(); localStorage.clear(); });

it("study-bound pending without intent recovers with seed-only body (mix-up surface)", async () => {
  const key = "protocol-v3:regimen:" + JSON.stringify(["one", "seed:one", "study:a"]);
  localStorage.setItem(key, JSON.stringify({ pending: true }));
  const api = {
    recoverRegimenDesign: vi.fn(async (_p, intent) => {
      if (intent === "seed:one") return done;
      throw Object.assign(new Error("unexpected intent"), { status: 409 });
    }),
    getRegimenDesign: vi.fn(async () => done),
    prepareRegimenDesign: vi.fn(),
    startRegimenDesign: vi.fn(),
  };
  render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:a" actorId="user:a" api={api} />);
  await screen.findByText("请补充研究给药途径。");
  expect(api.recoverRegimenDesign.mock.calls[0][1]).toBe("seed:one");
  expect(api.prepareRegimenDesign).not.toHaveBeenCalled();
});

it("does not re-prepare on StrictMode remount after prepare+start saved pending", async () => {
  const intent = { seed_run_id: "seed:one", study_definition_id: "study:a", expected_workflow_run_id: "design:one" };
  const api = {
    prepareRegimenDesign: vi.fn(async () => intent),
    startRegimenDesign: vi.fn(async () => { throw new Error("连接中断，记录待核对。"); }),
    recoverRegimenDesign: vi.fn(async () => done),
    getRegimenDesign: vi.fn(async () => done),
  };
  const view = render(<StrictMode>
    <RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:a" actorId="user:a" api={api} />
  </StrictMode>);
  fireEvent.click(screen.getByRole("button", { name: "整理完整给药建议" }));
  await screen.findByText("连接中断，记录待核对。");
  view.unmount();
  render(<StrictMode>
    <RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:a" actorId="user:a" api={api} />
  </StrictMode>);
  await screen.findByText("请补充研究给药途径。");
  expect(api.prepareRegimenDesign).toHaveBeenCalledTimes(1);
  expect(api.startRegimenDesign).toHaveBeenCalledTimes(1);
  expect(api.recoverRegimenDesign.mock.calls[0][1]).toEqual(intent);
});

it("keeps legacy source-only record when opening a different study", async () => {
  const legacyKey = "protocol-v3:regimen:" + JSON.stringify(["one", "seed:one"]);
  localStorage.setItem(legacyKey, JSON.stringify({ runId: "design:legacy", intent: { study_definition_id: "study:a" } }));
  const api = {
    prepareRegimenDesign: vi.fn(async (_p, seed, study) => ({
      seed_run_id: seed, study_definition_id: study, expected_workflow_run_id: "design:b",
    })),
    startRegimenDesign: vi.fn(),
    getRegimenDesign: vi.fn(),
  };
  render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:b" actorId="user:a" api={api} />);
  expect(screen.getByRole("button", { name: "整理完整给药建议" })).toBeTruthy();
  expect(JSON.parse(localStorage.getItem(legacyKey)).runId).toBe("design:legacy");
  expect(api.getRegimenDesign).not.toHaveBeenCalled();
});

it("aborts start when localStorage cannot save the prepared identity", async () => {
  const intent = { seed_run_id: "seed:one", study_definition_id: "study:a", expected_workflow_run_id: "design:one" };
  const api = {
    prepareRegimenDesign: vi.fn(async () => intent),
    startRegimenDesign: vi.fn(),
  };
  const setItem = localStorage.setItem.bind(localStorage);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation((key, value) => {
    if (String(value).includes("pending")) throw new Error("quota");
    return setItem(key, value);
  });
  render(<RegimenDesignWorkspace projectId="one" seedRunId="seed:one" studyDefinitionId="study:a" actorId="user:a" api={api} />);
  fireEvent.click(screen.getByRole("button", { name: "整理完整给药建议" }));
  await waitFor(() => expect(api.prepareRegimenDesign).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  expect(api.startRegimenDesign).not.toHaveBeenCalled();
});
