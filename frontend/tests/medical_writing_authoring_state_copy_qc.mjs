import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(
  testDir,
  "../src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx",
);
const source = await readFile(sourcePath, "utf8");

const expectedWorkingCopyMessage =
  "研究设计变更提交后，返回编辑器完成受影响章节的重绑定、重新核对与审阅。";
const expectedAssemblyPlanCopy = [
  "语料已就绪 · 仍需核对方案结构",
  "系统正在自动核对方案结构完整性，您无需填写技术表单。",
  "查看待确认项",
  "完成核对后进入写作",
  "语料准入完成",
];
const expectedWritingWorkspaceResearchGuard = [
  'journey.current_stage === "writing"',
  'journey.status === "document_created"',
];
const forbiddenEntryStatusCopy = "journey.status === \"writing_allowed\") return journey.corpus_gate?.readiness_status === \"ready\" ? \"可进入写作\"";
const forbiddenWorkingCopyPhrases = [
  "正文调和和重新医学批准",
  "正文调和和重新审阅",
  "返回编辑器完成受影响章节的重新医学批准",
];

if (!source.includes(expectedWorkingCopyMessage)) {
  throw new Error("章节/工作稿变更提示未使用已锁定的重新核对与审阅状态域");
}

for (const phrase of forbiddenWorkingCopyPhrases) {
  if (source.includes(phrase)) {
    throw new Error(`章节/工作稿变更提示仍混入不适用状态语义：${phrase}`);
  }
}

for (const phrase of expectedAssemblyPlanCopy) {
  if (!source.includes(phrase)) {
    throw new Error(`写作入口未保留统一方案结构门禁文案：${phrase}`);
  }
}
for (const phrase of expectedWritingWorkspaceResearchGuard) {
  const occurrences = source.split(phrase).length - 1;
  if (occurrences < 2) {
    throw new Error(`写作工作区重新挂载缺少自动研究守卫：${phrase}`);
  }
}
if (source.includes(forbiddenEntryStatusCopy)) {
  throw new Error("项目状态仍把语料准入误报为可进入写作");
}

console.log(JSON.stringify({
  passed: true,
  source: sourcePath,
  expectedWorkingCopyMessage,
  expectedAssemblyPlanCopy,
  expectedWritingWorkspaceResearchGuard,
  verifiedBoundary: "仅约束医学写作章节/工作稿变更提示；不扫描或改写正式放行与审批中心。",
}, null, 2));
