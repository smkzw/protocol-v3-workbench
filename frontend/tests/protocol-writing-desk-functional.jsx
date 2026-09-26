import React from "react";
import { createRoot } from "react-dom/client";
import { ProtocolWritingDesk } from "../src/features/medical-writing/protocol-workbench/ProtocolWritingDesk.jsx";
import "../src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.css";
import "../src/styles.css";

// 0927V1 G7 组件验收环境（0926V1 A703/A704）：挂载真实 ProtocolWritingDesk
// 与真实 GenOfficeFrame。全部数据为合成fixture，不写任何后端；Office iframe
// 的文档内容由 vite dev 的 g7-fixture-docx 中间件提供（public/genoffice-fixture）。
const HEX = (ch) => ch.repeat(64);
const savedDocument = {
  revision: 3,
  document: { revision: 3, study_definition_sha256: HEX("f") },
  document_sha256: HEX("a"),
};

const snapshot = {
  operation_id: "g7-fixture-snapshot",
  artifact_revision: 7,
  study_revision_sha256: HEX("e"),
  document_sha256: HEX("a"),
  document_revision: 3,
  saved_at: "2026-09-27T00:00:00Z",
};

const api = {
  getSavedManuscriptDocument: async () => savedDocument,
  latestOfficeSnapshot: async () => snapshot,
  officeSnapshotHistory: async () => ({ snapshots: [snapshot] }),
  getOfficeSnapshotReconciliation: async () => ({
    status: "not_checked",
    located: [],
    semantic_review: [],
    uncovered: [],
    coverage_note: "合成验收样例：无关键事实核对项。",
    study_matches_opened_baseline: true,
  }),
};

// ?bridge=0 → 非bridge档位（带研究比较面板）；任何未列出的API调用回落null，
// 面板显示各自的空态。
const bridgeMode = new URLSearchParams(location.search).get("bridge") !== "0";
const stubApi = new Proxy(api, {
  get: (target, key) => target[key] ?? (async () => null),
});

function Harness() {
  return <>
    <aside style={{ padding: "10px 24px", background: "#fff3d6", fontSize: 14 }}>
      G7组件验收环境 · 全部内容为合成资料 · Office样例文档为仓库内合成fixture · 不写入任何后端
    </aside>
    <main style={{ padding: "0 12px" }}>
      <ProtocolWritingDesk bridgeMode={bridgeMode} projectId="g7-fixture" studyDefinitionId="g7-study"
        seedRunId="g7-fixture-run" proposal={null}
        actorId="medical_manager" api={stubApi} onNavigationGuardChange={() => {}} />
    </main>
  </>;
}

createRoot(document.getElementById("root")).render(<React.StrictMode><Harness /></React.StrictMode>);
