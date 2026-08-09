/**
 * Pure logic functions for medical writing reference progress journey.
 * These functions can be tested directly without React/JSX.
 */

// Stage progression for medical writing reference workflow
export const STAGE_SEQUENCE = [
  "searching",
  "screening",
  "downloading",
  "parsing",
  "extracting",
  "ocr_running",
  "validating",
  "prepared",
  "toc_planning",
  "translating_hy_mt2",
  "integration_qc",
  "medical_review",
  "corpus_admission",
  "chapter_mapping",
  "candidate_ready",
];

// Backward-compatible status mapping
export function normalizeStage(rawStatus) {
  const status = String(rawStatus || "").trim().toLowerCase();

  // Legacy status mapping
  const legacyMap = {
    pending: "waiting",
    accepted: "downloading",
    running: "parsing",
    download: "downloading",
    parse: "parsing",
    extract: "extracting",
    extracting: "extracting",
    validation: "validating",
    validate: "validating",
    validating: "validating",
    succeeded: "candidate_ready",
    completed: "candidate_ready",
    failed: "failed_retryable",
    failed_retryable: "failed_retryable",
    failed_terminal: "failed_terminal",
    excluded: "excluded",
    review_required: "medical_review",
    needs_review: "medical_review",
    mismatch: "fidelity_blocked",
    manual_upload_required: "failed_terminal",
    prepared: "prepared",
    candidate_ready: "candidate_ready",
    fidelity_blocked: "fidelity_blocked",
    ocr_running: "ocr_running",
    toc_planning: "toc_planning",
    translating: "translating_hy_mt2",
    translating_hy_mt2: "translating_hy_mt2",
    integration_qc: "integration_qc",
    medical_review: "medical_review",
    approved: "corpus_admission",
    corpus_admission: "corpus_admission",
    admitted: "chapter_mapping",
    chapter_mapping: "chapter_mapping",
    not_applicable: "skipped",
  };

  if (!status) return "waiting";
  return legacyMap[status] || "unknown";
}

export function getStageLabel(stage) {
  const labels = {
    searching: "检索中",
    screening: "筛选中",
    downloading: "下载中",
    parsing: "解析中",
    extracting: "文本提取中",
    ocr_running: "OCR识别中",
    validating: "内容校验中",
    prepared: "资料已准备",
    toc_planning: "目录识别中",
    translating_hy_mt2: "Hy-MT2翻译中",
    integration_qc: "衔接核对中",
    medical_review: "作者确认中",
    corpus_admission: "确认后准入中",
    chapter_mapping: "章节映射中",
    candidate_ready: "候选已就绪",
    failed_retryable: "失败（可重试）",
    failed_terminal: "失败（终止）",
    fidelity_blocked: "忠实度阻断",
    excluded: "规划后排除",
    skipped: "不适用",
    waiting: "等待开始",
    unknown: "状态待同步",
  };
  return labels[stage] || "处理中";
}

const TERMINAL_ITEM_STAGES = new Set([
  "prepared",
  "candidate_ready",
  "failed_retryable",
  "failed_terminal",
  "fidelity_blocked",
  "excluded",
  "skipped",
]);

function itemValue(item, snakeName, camelName) {
  return item?.[snakeName] ?? item?.[camelName];
}

function progressNumber(item, snakeName, camelName) {
  const value = Number(itemValue(item, snakeName, camelName));
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

function getItemStage(item) {
  const generationStage = normalizeStage(
    item?.status || item?.generation_status || item?.generationStatus,
  );
  if (TERMINAL_ITEM_STAGES.has(generationStage)) return generationStage;

  const rawPipelineStage = itemValue(item, "pipeline_stage", "pipelineStage");
  const pipelineStage = normalizeStage(rawPipelineStage);
  if (rawPipelineStage && pipelineStage !== "waiting" && pipelineStage !== "unknown") {
    return pipelineStage;
  }
  return generationStage;
}

function derivePipelineItemPercent(item) {
  const stage = getItemStage(item);
  if (TERMINAL_ITEM_STAGES.has(stage)) return 100;
  if (stage === "toc_planning") return 8;
  if (stage === "translating_hy_mt2") {
    const chunkTotal = progressNumber(item, "chunk_count", "chunkCount");
    const chunkCompleted = Math.min(
      chunkTotal,
      progressNumber(item, "chunk_completed", "chunkCompleted"),
    );
    return chunkTotal
      ? Math.round(10 + ((chunkCompleted / chunkTotal) * 70))
      : 10;
  }
  if (stage === "integration_qc") return 88;
  if (stage === "medical_review") return 94;
  if (stage === "corpus_admission") return 97;
  if (stage === "chapter_mapping") return 99;
  if (stage === "extracting") return 3;
  if (stage === "ocr_running") return 5;
  if (stage === "validating") return 7;
  return 0;
}

export function getActiveStages(items) {
  const stageCounts = new Map();
  items.forEach((item) => {
    const stage = getItemStage(item);
    stageCounts.set(stage, (stageCounts.get(stage) || 0) + 1);
  });
  return stageCounts;
}

export function getNextAction(item) {
  const stage = normalizeStage(item.status || item.generation_status);
  const actions = {
    searching: "等待检索启动",
    screening: "等待筛选完成",
    downloading: "等待下载完成",
    parsing: "等待解析完成",
    extracting: "等待文本提取完成",
    ocr_running: "等待OCR识别完成",
    validating: "等待内容校验完成",
    prepared: "可进入翻译与语料审核",
    toc_planning: "等待目录识别完成",
    translating_hy_mt2: "等待翻译完成",
    integration_qc: "等待衔接核对完成",
    medical_review: "等待作者确认",
    corpus_admission: "等待确认后准入",
    chapter_mapping: "等待章节映射",
    candidate_ready: "可进入下一步",
    failed_retryable: "可重试失败项",
    failed_terminal: "需人工处理",
    fidelity_blocked: "需核对原文",
    excluded: "不在所选章节范围，无需生成",
    skipped: "不适用",
    waiting: "等待启动",
    unknown: "刷新状态或查看任务详情",
  };
  return actions[stage] || "处理中";
}

const BUSY_STAGES = new Set([
  "searching",
  "screening",
  "downloading",
  "parsing",
  "extracting",
  "ocr_running",
  "validating",
  "toc_planning",
  "translating_hy_mt2",
  "integration_qc",
  "medical_review",
  "corpus_admission",
  "chapter_mapping",
]);

export function isBusyStage(stage) {
  return BUSY_STAGES.has(normalizeStage(stage));
}

/**
 * Derive medical-user-facing document/chapter/chunk progress from batch items.
 * Does not expose hashes, model names, internal IDs, or raw logs.
 */
export function deriveDocumentTranslationProgress(items = []) {
  const list = Array.isArray(items) ? items : [];
  const byDocument = new Map();
  const byChapter = new Map();
  let blockerKind = "";
  let blockerMessage = "";

  const itemDocumentKey = (item, index) => String(
    itemValue(item, "artifact_id", "artifactId")
      || itemValue(item, "document_label", "documentLabel")
      || item?.filename
      || `document:${index}`,
  );
  const itemChapterKey = (item, index) => {
    const chapterId = itemValue(item, "chapter_id", "chapterId");
    const chapterIndex = progressNumber(item, "chapter_index", "chapterIndex");
    const chapterTitle = itemValue(item, "chapter_title", "chapterTitle");
    const chapterIdentity = chapterId || (chapterIndex || chapterTitle
      ? `${chapterIndex}:${chapterTitle || ""}`
      : `item:${index}`);
    return `${itemDocumentKey(item, index)}:${chapterIdentity}`;
  };

  list.forEach((item, index) => {
    const documentKey = itemDocumentKey(item, index);
    const label = itemValue(item, "document_label", "documentLabel")
      || item.filename
      || itemValue(item, "artifact_id", "artifactId")
      || "文档";
    const existingDocument = byDocument.get(documentKey);
    const document = {
      key: documentKey,
      label,
      index: progressNumber(item, "document_index", "documentIndex"),
      total: progressNumber(item, "document_total", "documentTotal"),
    };
    if (!existingDocument) {
      byDocument.set(documentKey, document);
    } else {
      byDocument.set(documentKey, {
        ...existingDocument,
        label: existingDocument.label || document.label,
        index: Math.max(existingDocument.index, document.index),
        total: Math.max(existingDocument.total, document.total),
      });
    }

    const chapterKey = itemChapterKey(item, index);
    const chapterProgress = {
      chunkTotal: progressNumber(item, "chunk_count", "chunkCount"),
      chunkCompleted: progressNumber(item, "chunk_completed", "chunkCompleted"),
      chunkRunning: progressNumber(item, "chunk_running", "chunkRunning"),
      chunkFailed: progressNumber(item, "chunk_failed", "chunkFailed"),
      chunkReused: progressNumber(item, "chunk_reused", "chunkReused"),
    };
    const existingChapter = byChapter.get(chapterKey);
    if (!existingChapter) {
      byChapter.set(chapterKey, chapterProgress);
    } else {
      byChapter.set(chapterKey, {
        chunkTotal: Math.max(existingChapter.chunkTotal, chapterProgress.chunkTotal),
        chunkCompleted: Math.max(existingChapter.chunkCompleted, chapterProgress.chunkCompleted),
        chunkRunning: Math.max(existingChapter.chunkRunning, chapterProgress.chunkRunning),
        chunkFailed: Math.max(existingChapter.chunkFailed, chapterProgress.chunkFailed),
        chunkReused: Math.max(existingChapter.chunkReused, chapterProgress.chunkReused),
      });
    }

    const stage = getItemStage(item);
    if (!blockerKind && item.blocker_kind) {
      blockerKind = String(item.blocker_kind);
      blockerMessage = String(item.blocker_message || "");
    } else if (!blockerKind && (stage === "failed_retryable" || stage === "failed_terminal" || stage === "fidelity_blocked")) {
      blockerKind = stage === "failed_retryable" ? "retryable" : "terminal";
      blockerMessage = getNextAction({ generation_status: stage });
    }
  });

  const busyItemIndex = list.findIndex((item) => isBusyStage(getItemStage(item)));
  const currentItemIndex = busyItemIndex >= 0
    ? busyItemIndex
    : list.reduce((selectedIndex, item, index) => {
      if (selectedIndex < 0) return index;
      const selectedDocumentIndex = progressNumber(
        list[selectedIndex],
        "document_index",
        "documentIndex",
      );
      const candidateDocumentIndex = progressNumber(item, "document_index", "documentIndex");
      return candidateDocumentIndex >= selectedDocumentIndex ? index : selectedIndex;
    }, -1);
  const currentItem = currentItemIndex >= 0 ? list[currentItemIndex] : null;
  const activeStage = currentItem ? getItemStage(currentItem) : "waiting";
  const activeStageDetail = String(
    itemValue(currentItem, "pipeline_stage_detail", "pipelineStageDetail")
      || getStageLabel(activeStage),
  );

  const documents = Array.from(byDocument.values()).sort(
    (a, b) => (a.index || 0) - (b.index || 0),
  );
  const currentDocumentKey = currentItem
    ? itemDocumentKey(currentItem, currentItemIndex)
    : "";
  const currentDocument = byDocument.get(currentDocumentKey) || null;
  const documentTotal = Math.max(
    documents.length,
    ...documents.map((document) => document.total || 0),
  );
  const chapterProgress = Array.from(byChapter.values()).reduce(
    (total, chapter) => ({
      chunkTotal: total.chunkTotal + chapter.chunkTotal,
      chunkCompleted: total.chunkCompleted + chapter.chunkCompleted,
      chunkRunning: total.chunkRunning + chapter.chunkRunning,
      chunkFailed: total.chunkFailed + chapter.chunkFailed,
      chunkReused: total.chunkReused + chapter.chunkReused,
    }),
    {
      chunkTotal: 0,
      chunkCompleted: 0,
      chunkRunning: 0,
      chunkFailed: 0,
      chunkReused: 0,
    },
  );
  const currentChunkTotal = progressNumber(currentItem, "chunk_count", "chunkCount");
  const currentChunkCompleted = Math.min(
    currentChunkTotal,
    progressNumber(currentItem, "chunk_completed", "chunkCompleted"),
  );
  const currentPipelineStage = currentItem
    ? itemValue(currentItem, "pipeline_stage", "pipelineStage")
    : "";
  let progressCompleted = currentChunkCompleted;
  let progressTotal = currentChunkTotal;
  if (!progressTotal && currentDocument?.total) {
    progressTotal = currentDocument.total;
    progressCompleted = Math.max(0, (currentDocument.index || 1) - 1);
  }
  if (!progressTotal && list.length) {
    progressTotal = list.length;
    progressCompleted = list.filter((item) => TERMINAL_ITEM_STAGES.has(getItemStage(item))).length;
  }
  const progressPercent = currentPipelineStage
    ? derivePipelineItemPercent(currentItem)
    : (
      progressTotal
        ? Math.round((Math.min(progressCompleted, progressTotal) / progressTotal) * 100)
        : 0
    );

  return {
    documentTotal,
    documentIndex: currentDocument?.index || (documents.length ? 1 : 0),
    documentLabel: currentDocument?.label || "",
    chapterTotal: progressNumber(currentItem, "chapter_total", "chapterTotal"),
    chapterIndex: progressNumber(currentItem, "chapter_index", "chapterIndex"),
    chapterTitle: itemValue(currentItem, "chapter_title", "chapterTitle") || "",
    ...chapterProgress,
    currentChunkTotal,
    currentChunkCompleted,
    currentChunkRunning: progressNumber(currentItem, "chunk_running", "chunkRunning"),
    currentChunkFailed: progressNumber(currentItem, "chunk_failed", "chunkFailed"),
    currentChunkReused: progressNumber(currentItem, "chunk_reused", "chunkReused"),
    activeStage,
    activeStageDetail,
    progressCompleted,
    progressTotal,
    progressPercent,
    blockerKind,
    blockerMessage,
  };
}

export function formatDocumentTranslationProgressSummary(progress) {
  if (!progress) return "";
  const parts = [];
  if (progress.documentTotal) {
    parts.push(
      `文档 ${progress.documentIndex || 0}/${progress.documentTotal}`
        + (progress.documentLabel ? `（${progress.documentLabel}）` : ""),
    );
  }
  if (progress.chapterTotal) {
    parts.push(
      `章节 ${progress.chapterIndex || 0}/${progress.chapterTotal}`
        + (progress.chapterTitle ? `（${progress.chapterTitle}）` : ""),
    );
  }
  if (progress.chunkTotal) {
    parts.push(
      `分块 完成${progress.chunkCompleted || 0}/运行${progress.chunkRunning || 0}/失败${progress.chunkFailed || 0}/复用${progress.chunkReused || 0}/共${progress.chunkTotal}`,
    );
  }
  if (progress.blockerKind) {
    const kindLabel = progress.blockerKind === "retryable" ? "可重试" : "需处理";
    parts.push(`阻断（${kindLabel}）${progress.blockerMessage ? `：${progress.blockerMessage}` : ""}`);
  }
  return parts.join(" · ");
}
