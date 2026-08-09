import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  deriveDocumentTranslationProgress,
  getActiveStages,
} from "./progressJourneyLogic.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

const docAComplete = {
  artifact_id: "doc-a",
  document_label: "Doc A",
  document_index: 1,
  document_total: 2,
  chapter_id: "doc-a-chapter-1",
  chapter_title: "Doc A 已完成章节",
  chapter_index: 1,
  chapter_total: 1,
  chunk_count: 5,
  chunk_completed: 5,
  generation_status: "candidate_ready",
  pipeline_stage: "candidate_ready",
  pipeline_stage_detail: "翻译完成，可核对并使用",
};

const docBRunningSpan1 = {
  artifact_id: "doc-b",
  span_id: "doc-b-span-1",
  document_label: "Doc B",
  document_index: 2,
  document_total: 2,
  chapter_id: "doc-b-chapter-2",
  chapter_title: "Doc B 当前章节",
  chapter_index: 2,
  chapter_total: 3,
  chunk_count: 4,
  chunk_completed: 1,
  chunk_running: 1,
  generation_status: "running",
  pipeline_stage: "translating_hy_mt2",
  pipeline_stage_detail: "正在按章节执行 Hy-MT2 翻译",
};

const docBRunningSpan2 = {
  ...docBRunningSpan1,
  span_id: "doc-b-span-2",
};

const multiDocumentProgress = deriveDocumentTranslationProgress([
  docAComplete,
  docBRunningSpan1,
  docBRunningSpan2,
]);
check(
  multiDocumentProgress.documentLabel === "Doc B"
    && multiDocumentProgress.documentIndex === 2,
  "uses the real busy item to locate Doc B instead of the first document",
);
check(
  multiDocumentProgress.chapterIndex === 2
    && multiDocumentProgress.chapterTitle === "Doc B 当前章节",
  "uses the busy item's current chapter",
);
check(
  multiDocumentProgress.currentChunkCompleted === 1
    && multiDocumentProgress.currentChunkTotal === 4
    && multiDocumentProgress.progressPercent === 28,
  "projects current chunk counts and weighted real-stage percentage",
);
check(
  multiDocumentProgress.chunkTotal === 9
    && multiDocumentProgress.chunkCompleted === 6
    && multiDocumentProgress.chunkRunning === 1,
  "counts each document and chapter once when sibling spans repeat chapter-level chunk totals",
);
check(
  multiDocumentProgress.activeStageDetail === "正在按章节执行 Hy-MT2 翻译",
  "preserves the active item's real pipeline stage detail",
);

const activeStages = getActiveStages([docAComplete, docBRunningSpan1]);
check(
  activeStages.get("candidate_ready") === 1
    && activeStages.get("translating_hy_mt2") === 1
    && !activeStages.has("parsing"),
  "uses the real pipeline stage instead of mapping a running item to generic parsing",
);

const stageCases = [
  {
    stage: "toc_planning",
    detail: "正在识别目录与章节",
    extra: { document_index: 2, document_total: 3 },
    expectedCompleted: 1,
    expectedTotal: 3,
    expectedPercent: 8,
  },
  {
    stage: "translating_hy_mt2",
    detail: "正在按章节执行 Hy-MT2 翻译",
    extra: { chunk_count: 4, chunk_completed: 2, chunk_running: 1 },
    expectedCompleted: 2,
    expectedTotal: 4,
    expectedPercent: 45,
  },
  {
    stage: "integration_qc",
    detail: "正在执行译文拼接 QC",
    extra: { chunk_count: 4, chunk_completed: 4 },
    expectedCompleted: 4,
    expectedTotal: 4,
    expectedPercent: 88,
  },
];

stageCases.forEach((stageCase) => {
  const progress = deriveDocumentTranslationProgress([{
    artifact_id: `doc-${stageCase.stage}`,
    document_label: "当前文档",
    document_index: 1,
    document_total: 1,
    chapter_id: "chapter-current",
    chapter_index: 1,
    chapter_total: 1,
    generation_status: "running",
    pipeline_stage: stageCase.stage,
    pipeline_stage_detail: stageCase.detail,
    ...stageCase.extra,
  }]);
  check(
    progress.activeStageDetail === stageCase.detail
      && progress.progressCompleted === stageCase.expectedCompleted
      && progress.progressTotal === stageCase.expectedTotal
      && progress.progressPercent === stageCase.expectedPercent,
    `${stageCase.stage} keeps its real detail and completed/total/percent projection`,
  );
});

const translatingProgress = deriveDocumentTranslationProgress([{
  artifact_id: "doc-progress",
  document_label: "Protocol-progress.pdf",
  generation_status: "running",
  pipeline_stage: "translating_hy_mt2",
  pipeline_stage_detail: "正在翻译第3/10个分块",
  chunk_count: 10,
  chunk_completed: 3,
  chunk_running: 1,
}]);
check(
  translatingProgress.progressCompleted === 3
    && translatingProgress.progressTotal === 10
    && translatingProgress.progressPercent === 31,
  "Hy-MT2 progress uses persisted chunk completion within the real stage range",
);

const panelSource = readFileSync(
  new URL("./ReferenceTranslationBatchPanel.jsx", import.meta.url),
  "utf8",
);
const journeySource = readFileSync(
  new URL("./WritingReferenceProgressJourney.jsx", import.meta.url),
  "utf8",
);
check(
  panelSource.includes("pipelineStageDetail: String(item.pipeline_stage_detail || \"\")")
    && panelSource.includes('row.generationStatus === "running" && row.pipelineStageDetail'),
  "translation rows retain and prioritize the real pipeline stage detail while running",
);
check(
  journeySource.includes('data-testid="writing-reference-compact-current-progress"')
    && journeySource.includes("{compactProgress.progressCompleted}/{compactProgress.progressTotal}")
    && journeySource.includes("{compactProgress.progressPercent}%")
    && journeySource.includes('data-testid="writing-reference-compact-progressbar"')
    && journeySource.includes('data-testid="writing-reference-full-progressbar"')
    && journeySource.includes('aria-valuenow={compactProgress.progressPercent}'),
  "compact progress always renders the concrete step, completed/total, and percentage",
);

console.log(`progressJourneyLogic: ${passed} passed`);
