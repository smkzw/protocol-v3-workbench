import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RegimenProposalCard } from "./RegimenProposalCard";

afterEach(() => {
  cleanup();
});

const SHA = "a".repeat(64);

function readyProposal(overrides = {}) {
  const regimen = {
    input_sha256: SHA,
    canonical_state: "proposed",
    periods: [
      { id: "period:induction", label: "诱导期", timing: "第1–4周" },
      { id: "period:maintenance", label: "维持期", timing: "第5周起" },
    ],
    arms: [
      { id: "arm:active", label: "试验组" },
      { id: "arm:placebo", label: "安慰剂组" },
    ],
    schedules: [
      {
        period_id: "period:induction",
        arm_id: "arm:active",
        steps: [{
          kind: "loading",
          timing: "第1天",
          frequency: "单次",
          route: "静脉滴注",
          products: [{
            name: "研究药A",
            dose: { value: 10, unit: "mg/kg" },
            volume: { value: 100, unit: "mL" },
          }],
          references: [{
            source_artifact_id: "source:ib",
            locator: "/word/document.xml/p[12]",
            quote: "诱导期负荷剂量为10 mg/kg，溶于100 mL溶媒。",
          }],
          source_support: "project_material",
          requires_confirmation: true,
        }],
      },
      {
        period_id: "period:induction",
        arm_id: "arm:placebo",
        steps: [{
          kind: "loading",
          timing: "第1天",
          frequency: "单次",
          route: "静脉滴注",
          products: [{ name: "匹配安慰剂", dose: { value: 0, unit: "mg/kg" } }],
          references: [{
            source_artifact_id: "source:ib",
            locator: "/word/document.xml/p[14]",
            quote: "安慰剂组接受外观匹配的溶媒。",
          }],
          source_support: "project_material",
          requires_confirmation: true,
        }],
      },
      {
        period_id: "period:maintenance",
        arm_id: "arm:active",
        steps: [{
          kind: "maintenance",
          timing: "每2周",
          frequency: "q2w",
          route: "静脉滴注",
          products: [{ name: "研究药A", dose: { value: 5, unit: "mg/kg" } }],
          references: [
            {
              source_artifact_id: "source:ib",
              locator: "/word/document.xml/p[20]",
              quote: "维持剂量5 mg/kg，每2周一次。",
            },
            {
              source_artifact_id: "source:ib",
              locator: "/word/document.xml/p[21]",
              quote: "维持治疗可持续至研究结束。",
            },
            {
              source_artifact_id: "source:history",
              locator: "/word/document.xml/p[3]",
              quote: "历史方案曾用相近维持剂量。",
            },
          ],
          source_support: "reference_only",
          requires_confirmation: true,
        }],
      },
      {
        period_id: "period:maintenance",
        arm_id: "arm:placebo",
        steps: [{
          kind: "maintenance",
          timing: "每2周",
          frequency: "q2w",
          route: "静脉滴注",
          products: [{ name: "匹配安慰剂", dose: { value: 0, unit: "mg/kg" } }],
          references: [{
            source_artifact_id: "source:ib",
            locator: "/word/document.xml/p[22]",
            quote: "安慰剂维持给药与试验组同步。",
          }],
          source_support: "ai_recommendation",
          requires_confirmation: true,
        }],
      },
    ],
    unresolved_questions: [],
  };
  const base = {
    status: "ready_for_review",
    coverage: [],
    regimen,
    questions: [],
  };
  return {
    ...base,
    ...overrides,
    regimen: Object.prototype.hasOwnProperty.call(overrides, "regimen") ? overrides.regimen : regimen,
  };
}

it("renders all four period-arm units with loading and maintenance visible", () => {
  render(<RegimenProposalCard proposal={readyProposal()} onConfirm={vi.fn()} sourceDownloadUrl={(id) => `/dl/${id}`} />);
  expect(screen.getByText("剂量方案")).toBeTruthy();
  expect(screen.getByText("监管答辩级·需确认")).toBeTruthy();
  expect(screen.getByText("建议，尚未确认")).toBeTruthy();
  expect(screen.getAllByText("诱导期").length).toBe(2);
  expect(screen.getAllByText("维持期").length).toBe(2);
  expect(screen.getAllByText("试验组").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("安慰剂组").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("负荷").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("维持").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("10 mg/kg")).toBeTruthy();
  expect(screen.getByText("100 mL")).toBeTruthy();
  expect(screen.getByText("5 mg/kg")).toBeTruthy();
  expect(screen.queryByText(/停药|不适用/)).toBeNull();
  expect(screen.queryByText(/\bloading\b|\bmaintenance\b|\bproject_material\b|\bai_recommendation\b|\breference_only\b/)).toBeNull();
  expect(screen.queryByText(/\/word\/document\.xml/)).toBeNull();
  expect(screen.queryByText(/已批准/)).toBeNull();
});

it("does not call onConfirm before an explicit click", () => {
  const onConfirm = vi.fn();
  render(<RegimenProposalCard proposal={readyProposal()} onConfirm={onConfirm} sourceDownloadUrl={() => "/x"} />);
  expect(onConfirm).not.toHaveBeenCalled();
});

it("calls onConfirm once with the proposal and ignores a synchronous double click", async () => {
  let resolveConfirm;
  const onConfirm = vi.fn(() => new Promise((resolve) => { resolveConfirm = resolve; }));
  render(<RegimenProposalCard proposal={readyProposal()} onConfirm={onConfirm} sourceDownloadUrl={() => "/x"} />);
  const button = screen.getByRole("button", { name: "确认这套给药方案" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(onConfirm).toHaveBeenCalledTimes(1);
  expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ status: "ready_for_review" }));
  expect(button.disabled).toBe(true);
  resolveConfirm();
  await waitFor(() => expect(button.disabled).toBe(false));
  expect(screen.queryByText(/已保存|已确认/)).toBeNull();
});

it("disables confirm when unresolved items exist and surfaces those items", () => {
  const onConfirm = vi.fn();
  const proposal = readyProposal({
    status: "needs_information",
    questions: ["随机化分层尚未明确"],
    regimen: {
      ...readyProposal().regimen,
      unresolved_questions: ["维持期伴随用药是否允许"],
    },
  });
  render(<RegimenProposalCard proposal={proposal} onConfirm={onConfirm} />);
  const button = screen.getByRole("button", { name: "确认这套给药方案" });
  expect(button.disabled).toBe(true);
  expect(screen.getByText(/随机化分层尚未明确/)).toBeTruthy();
  expect(screen.getByText(/维持期伴随用药是否允许/)).toBeTruthy();
  fireEvent.click(button);
  expect(onConfirm).not.toHaveBeenCalled();
});

it("disables confirm without callback, while busy, or when regimen is empty", () => {
  const { rerender } = render(<RegimenProposalCard proposal={readyProposal()} />);
  expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(true);

  rerender(<RegimenProposalCard proposal={readyProposal()} onConfirm={vi.fn()} busy />);
  expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(true);

  rerender(<RegimenProposalCard proposal={readyProposal({ status: "ready_for_review", regimen: null })} onConfirm={vi.fn()} />);
  expect(screen.getByRole("button", { name: "确认这套给药方案" }).disabled).toBe(true);
});

it("keeps the full card after confirm failure and shows a readable error", async () => {
  const onConfirm = vi.fn(async () => {
    throw new Error("保存失败，请稍后重试");
  });
  render(<RegimenProposalCard proposal={readyProposal()} onConfirm={onConfirm} sourceDownloadUrl={() => "/x"} />);
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  await screen.findByRole("alert");
  expect(screen.getByText("保存失败，请稍后重试")).toBeTruthy();
  expect(screen.getByText("剂量方案")).toBeTruthy();
  expect(screen.getAllByText("诱导期").length).toBe(2);
  expect(screen.queryByText(/已保存/)).toBeNull();
  expect(onConfirm).toHaveBeenCalledTimes(1);
});

it("shows external error without optimistic saved state", () => {
  render(<RegimenProposalCard proposal={readyProposal()} onConfirm={vi.fn()} error="外部校验未通过" />);
  expect(screen.getByRole("alert").textContent).toContain("外部校验未通过");
  expect(screen.queryByText(/已保存|已确认/)).toBeNull();
});

it("shows quotes verbatim, dedupes download links per source, and skips missing urls", () => {
  const sourceDownloadUrl = vi.fn((id) => (id === "source:ib" ? `/files/${id}` : ""));
  render(<RegimenProposalCard proposal={readyProposal()} onConfirm={vi.fn()} sourceDownloadUrl={sourceDownloadUrl} />);
  const maintenanceActive = screen.getByText("维持剂量5 mg/kg，每2周一次。").closest("details");
  expect(maintenanceActive).toBeTruthy();
  fireEvent.click(within(maintenanceActive).getByText("查看原文依据"));
  expect(within(maintenanceActive).getByText("维持剂量5 mg/kg，每2周一次。")).toBeTruthy();
  expect(within(maintenanceActive).getByText("维持治疗可持续至研究结束。")).toBeTruthy();
  expect(within(maintenanceActive).getByText("历史方案曾用相近维持剂量。")).toBeTruthy();
  const links = screen.getAllByRole("link", { name: "下载对应原文件" });
  expect(links).toHaveLength(1);
  expect(links[0].getAttribute("href")).toBe("/files/source:ib");
  expect(within(maintenanceActive).queryByText(/\/word\/document\.xml/)).toBeNull();
  expect(screen.getAllByText("参考资料中的信息").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("来自所提供的方案资料").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("AI建议，仍需结合研究确认").length).toBeGreaterThanOrEqual(1);
});

it("does not apply a stale confirm failure after the proposal is replaced", async () => {
  let rejectFirst;
  const firstConfirm = vi.fn(() => new Promise((_, reject) => { rejectFirst = reject; }));
  const secondConfirm = vi.fn(async () => {});
  const first = readyProposal();
  const second = readyProposal({
    regimen: {
      ...readyProposal().regimen,
      input_sha256: "b".repeat(64),
      periods: [{ id: "period:only", label: "单期", timing: "全程" }],
      arms: [{ id: "arm:only", label: "单组" }],
      schedules: [{
        period_id: "period:only",
        arm_id: "arm:only",
        steps: [{
          kind: "single",
          timing: "第1天",
          frequency: "单次",
          route: "口服",
          products: [{ name: "研究药B", dose: { value: 100, unit: "mg" } }],
          references: [],
          source_support: "project_material",
          requires_confirmation: true,
        }],
      }],
    },
  });
  const { rerender } = render(
    <RegimenProposalCard proposal={first} onConfirm={firstConfirm} sourceDownloadUrl={() => "/x"} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "确认这套给药方案" }));
  rerender(<RegimenProposalCard proposal={second} onConfirm={secondConfirm} sourceDownloadUrl={() => "/x"} />);
  expect(screen.getByText("单期")).toBeTruthy();
  expect(screen.getByText("研究药B")).toBeTruthy();
  rejectFirst(new Error("旧请求失败"));
  await waitFor(() => expect(firstConfirm).toHaveBeenCalledTimes(1));
  expect(screen.queryByText("旧请求失败")).toBeNull();
  expect(screen.queryByText("诱导期")).toBeNull();
});


it("keeps confirmation pending when an equivalent proposal object is received", async () => {
  let finish;
  const onConfirm = vi.fn(() => new Promise(resolve => { finish = resolve; }));
  const proposal = readyProposal();
  const view = render(<RegimenProposalCard proposal={proposal} onConfirm={onConfirm} />);
  fireEvent.click(screen.getByRole("button", {name: "确认这套给药方案"}));
  view.rerender(<RegimenProposalCard proposal={JSON.parse(JSON.stringify(proposal))} onConfirm={onConfirm} />);
  expect(screen.getByRole("button", {name: "确认这套给药方案"}).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", {name: "确认这套给药方案"}));
  expect(onConfirm).toHaveBeenCalledTimes(1);
  finish();
  await waitFor(() => expect(screen.getByRole("button", {name: "确认这套给药方案"}).disabled).toBe(false));
});
