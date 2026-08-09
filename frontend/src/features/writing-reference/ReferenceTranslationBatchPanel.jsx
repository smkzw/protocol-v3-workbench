import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpDown, CheckCheck, Eye, Languages, Play, RefreshCw, RotateCcw } from "lucide-react";
import { WritingReferenceProgressJourney } from "./WritingReferenceProgressJourney";
import {
  pollDurableMwJob,
  buildLocator,
  extractArtifactBatchId,
  resolveRetryJobId,
  mergeRetryLocator,
  acknowledgeTranslationDomain,
} from "../medical-writing/useDurableMwJob";
import {
  deriveDocumentTranslationProgress,
  formatDocumentTranslationProgressSummary,
} from "./progressJourneyLogic.mjs";

const ACTIVE_BATCH_STATUSES = new Set(["accepted", "running"]);
const TERMINAL_BATCH_STATUSES = new Set([
  "completed",
  "completed_with_blocked",
  "partial_failure",
  "failed",
]);
const FAILED_ITEM_STATUSES = new Set(["failed_retryable", "failed_terminal"]);
const EXCLUSION_EXAMPLE_LIMIT = 4;
// The server's translation contract currently exposes only these six M11
// anchors.  Other mapped anchors remain visible for transparency, but are
// disabled instead of being submitted as an invalid batch scope.
const SUPPORTED_TRANSLATION_ANCHORS = new Set([
  "eligibility",
  "objectives_endpoints",
  "safety",
  "schedule",
  "statistics",
  "synopsis",
]);

const batchStatusLabels = {
  not_started: "尚未生成",
  accepted: "已受理",
  running: "生成中",
  completed: "已完成",
  completed_with_blocked: "完成，有忠实度阻断",
  partial_failure: "部分失败",
  failed: "批次失败",
};

const generationLabels = {
  pending: ["待生成", "warning"],
  running: ["生成中", "info"],
  excluded: ["规划后排除", "neutral"],
  candidate_ready: ["候选已就绪", "success"],
  fidelity_blocked: ["忠实度阻断", "danger"],
  failed_retryable: ["失败，可重试", "danger"],
  failed_terminal: ["终止失败", "danger"],
};

const fidelityLabels = {
  not_checked: ["待机器检查", "warning"],
  passed: ["机器检查通过", "success"],
  blocked: ["忠实度阻断", "danger"],
};

const reviewLabels = {
  not_confirmed: ["待作者确认", "warning"],
  confirmed: ["作者已确认", "success"],
  returned: ["已退回", "warning"],
  rejected: ["已拒绝", "danger"],
};

const admissionLabels = {
  not_admitted: ["未准入", "neutral"],
  admitted: ["已准入", "success"],
  invalidated: ["准入已失效", "danger"],
};

const exclusionReasonLabels = {
  no_current_artifact: "没有当前有效的已登记文件",
  validation_missing: "文件内容核验尚未建立",
  validation_not_confirmed: "文件内容核验尚未确认",
  validation_document_hash_mismatch: "文件版本与核验记录不一致",
  validation_state_stale: "文件核验状态已过期",
  validation_extraction_stale: "文件内容核验未绑定当前结构解析版本",
  latest_extraction_missing: "没有当前结构解析版本",
  latest_extraction_has_no_spans: "当前解析版本没有片段",
  structure_review_missing: "结构医学审核尚未建立",
  structure_review_not_approved: "结构医学审核尚未通过",
  source_text_hash_mismatch: "片段原文版本不一致",
  semantic_fragment_incomplete: "原文为跨块或跨页的不完整语义片段",
  unmapped: "未映射到 M11 结构",
  standalone_sap_not_corpus_input: "独立SAP不进入竞品方案语料库",
  combined_protocol_boundary_unresolved: "合并文件未能可靠定位Protocol与SAP边界",
  sap_section_excluded_from_protocol_corpus: "合并文件中的SAP章节已排除",
  anchor_filtered: "不在本次所选 M11 结构范围",
};

function requestKey(prefix) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}-${suffix}`;
}

async function readJson(response, { allowNotFound = false } = {}) {
  if (allowNotFound && response.status === 404) return null;
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload;
  const detail = typeof payload.detail === "string"
    ? payload.detail
    : payload.detail?.message || payload.message || `HTTP ${response.status}`;
  const error = new Error(detail);
  error.status = response.status;
  throw error;
}

function normalizedStatus(value, fallback) {
  return String(value || fallback || "").trim().toLowerCase();
}

function safeCount(value, fallback = 0) {
  const count = Number(value);
  return Number.isFinite(count) && count >= 0 ? count : fallback;
}

function selectedScopeMatchesPreview(preview, selectedAnchors) {
  if (!preview) return false;
  const returned = [...(preview.anchor_filter || [])].sort();
  const selected = [...selectedAnchors].sort();
  return returned.length === selected.length
    && returned.every((anchor, index) => anchor === selected[index]);
}

function optionsFromPreview(preview) {
  return (preview?.anchor_summaries || [])
    .map((summary) => ({
      value: String(summary.ich_m11_anchor || "").trim(),
      eligibleNew: safeCount(summary.eligible_new),
      existingCandidate: safeCount(summary.existing_candidate),
      fidelityBlocked: safeCount(summary.fidelity_blocked),
    }))
    .map((option) => ({
      ...option,
      count: option.eligibleNew + option.existingCandidate + option.fidelityBlocked,
    }))
    .filter((option) => option.value && option.value.toLowerCase() !== "unmapped" && option.count > 0)
    .sort((left, right) => left.value.localeCompare(right.value, "zh-CN"));
}

function supportedAnchors(anchors) {
  return [...new Set((anchors || []).filter((anchor) => SUPPORTED_TRANSLATION_ANCHORS.has(anchor)))];
}

function normalizeItem(item, index) {
  const generationStatus = normalizedStatus(item.generation_status, "pending");
  const hasPipelineLineage = Boolean(
    item.pipeline_fingerprint
    || item.hy_mt2_model
    || item.flash_plan_model
    || item.flash_qc_model
    || (item.pipeline_stage && item.pipeline_stage !== "extracting"),
  );
  const fidelityStatus = generationStatus === "fidelity_blocked"
    ? "blocked"
    : normalizedStatus(item.fidelity_status, "not_checked");
  return {
    rowKey: item.item_id || `${item.artifact_id || "item"}:${item.span_id || index}`,
    nctId: item.nct_id || "",
    artifactId: item.artifact_id || "",
    spanId: item.span_id || "",
    filename: item.filename || "",
    documentType: item.document_type || "",
    documentLabel: item.document_label || item.filename || "",
    documentTotal: Number(item.document_total) || 0,
    documentIndex: Number(item.document_index) || 0,
    chapterId: item.chapter_id || "",
    chapterTitle: item.chapter_title || "",
    chapterTotal: Number(item.chapter_total) || 0,
    chapterIndex: Number(item.chapter_index) || 0,
    chunkCount: Number(item.chunk_count) || 0,
    chunkCompleted: Number(item.chunk_completed) || 0,
    chunkRunning: Number(item.chunk_running) || 0,
    chunkFailed: Number(item.chunk_failed) || 0,
    chunkReused: Number(item.chunk_reused) || 0,
    blockerKind: item.blocker_kind || "",
    blockerMessage: item.blocker_message || "",
    anchor: item.ich_m11_anchor || "",
    sourceLocator: item.source_locator || "来源定位待返回",
    origin: item.origin || "new",
    generationStatus,
    translationId: item.translation_id || "",
    translationRevision: Number(item.translation_revision) || 0,
    pipelineStage: hasPipelineLineage ? normalizedStatus(item.pipeline_stage, "") : "",
    pipelineStageDetail: String(item.pipeline_stage_detail || ""),
    fidelityStatus,
    authorConfirmationStatus: normalizedStatus(
      item.author_confirmation_status,
      item.medical_review_status === "approved"
        ? "confirmed"
        : item.medical_review_status || "not_confirmed",
    ),
    admissionStatus: normalizedStatus(item.admission_status, "not_admitted"),
    fidelityFailureCodes: Array.isArray(item.fidelity_failure_codes) ? item.fidelity_failure_codes : [],
  };
}

function statusTag(status, dictionary, fallback = "状态待确认") {
  const [label, tone] = dictionary[status] || [fallback, "neutral"];
  return <span className={`tag ${tone}`}>{label}</span>;
}

function nextStep(row) {
  if (row.generationStatus === "pending") return "等待候选生成";
  if (row.generationStatus === "running") return row.pipelineStageDetail || "候选生成中";
  if (row.generationStatus === "excluded") return "不在所选章节范围，无需生成";
  if (row.generationStatus === "fidelity_blocked") return "核对原文与忠实度问题";
  if (row.generationStatus === "failed_retryable") return "可仅重试失败项";
  if (row.generationStatus === "failed_terminal") return "转逐片段问题处理";
  if (row.generationStatus !== "candidate_ready") return "等待状态确认";
  if (row.authorConfirmationStatus === "returned") return "按作者意见修订";
  if (row.authorConfirmationStatus === "rejected") return "作者已拒绝";
  if (row.authorConfirmationStatus !== "confirmed") return "逐片段核对并确认";
  if (row.admissionStatus === "admitted") return "已完成当前准入链";
  if (row.admissionStatus === "invalidated") return "复核失效准入记录";
  return "核对确认状态";
}

function batchReviewEligibleRow(row) {
  return row.generationStatus === "candidate_ready"
    && row.fidelityStatus === "passed"
    && row.authorConfirmationStatus === "not_confirmed"
    && row.admissionStatus !== "invalidated"
    && Boolean(row.translationId)
    && row.translationRevision >= 1;
}

function sortValue(row, key) {
  if (key === "study") return `${row.nctId} ${row.filename} ${row.documentType}`;
  if (key === "anchor") return `${row.anchor} ${row.sourceLocator}`;
  if (key === "generation") return row.generationStatus;
  if (key === "fidelity") return row.fidelityStatus;
  if (key === "review") return row.authorConfirmationStatus;
  if (key === "admission") return row.admissionStatus;
  return nextStep(row);
}

function SortHeader({ label, column, sort, onSort }) {
  const active = sort.key === column;
  return (
    <button
      type="button"
      className={active ? "active" : ""}
      onClick={() => onSort(column)}
      aria-label={`按${label}${active && sort.direction === "asc" ? "降序" : "升序"}排列`}
    >
      {label}<ArrowUpDown size={12} />
    </button>
  );
}

export function ReferenceTranslationBatchPanel({
  projectId,
  snapshotId,
  glossaryVersion = "cms_regulatory_zh_v1",
  onOpenSpan = () => {},
  onBatchSettled = () => {},
}) {
  const previewGenerationRef = useRef(0);
  const batchGenerationRef = useRef(0);
  const batchRequestInFlightRef = useRef(false);
  const createKeyRef = useRef("");
  const retryKeyRef = useRef({ batchId: "", key: "" });
  const batchReviewKeyRef = useRef({ batchId: "", key: "" });
  const selectionKeyRef = useRef("");
  const settledMarkerRef = useRef("");
  const [preview, setPreview] = useState(null);
  const [batch, setBatch] = useState(null);
  const [availableAnchors, setAvailableAnchors] = useState([]);
  const [selectedAnchors, setSelectedAnchors] = useState([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [tableAnchorFilter, setTableAnchorFilter] = useState("all");
  const [sort, setSort] = useState({ key: "study", direction: "asc" });
  const [previewLoading, setPreviewLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [action, setAction] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [batchError, setBatchError] = useState("");
  const [notice, setNotice] = useState("");
  const [pollSuspended, setPollSuspended] = useState(false);
  const [durableJobId, setDurableJobId] = useState("");

  const scopeKey = `${projectId}:${snapshotId}:${glossaryVersion}`;
  const selectedAnchorKey = useMemo(
    () => [...selectedAnchors].sort().join("|"),
    [selectedAnchors],
  );

  const loadPreview = useCallback(async (anchors, { silent = false } = {}) => {
    if (!snapshotId) return;
    const generation = ++previewGenerationRef.current;
    if (!silent) setPreviewLoading(true);
    const params = new URLSearchParams({ snapshot_id: snapshotId, glossary_version: glossaryVersion });
    anchors.forEach((anchor) => params.append("anchor_filter", anchor));
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/translation-batches/preview?${params.toString()}`);
      const payload = await readJson(response);
      if (generation !== previewGenerationRef.current) return;
      const returnedAnchors = optionsFromPreview(payload);
      setPreview(payload);
      setAvailableAnchors((current) => {
        const merged = new Map(current.map((item) => [item.value, item]));
        returnedAnchors.forEach((item) => merged.set(item.value, item));
        return [...merged.values()].sort((left, right) => left.value.localeCompare(right.value, "zh-CN"));
      });
      if (selectionKeyRef.current !== scopeKey) {
        selectionKeyRef.current = scopeKey;
        setSelectedAnchors(supportedAnchors(returnedAnchors.map((item) => item.value)));
      }
      setPreviewError("");
    } catch (error) {
      if (generation === previewGenerationRef.current) setPreviewError(`候选范围预览失败：${error.message}`);
    } finally {
      if (!silent && generation === previewGenerationRef.current) setPreviewLoading(false);
    }
  }, [glossaryVersion, projectId, scopeKey, snapshotId]);

  const loadBatch = useCallback(async (batchId, { polling = false } = {}) => {
    if (!batchId || batchRequestInFlightRef.current) return;
    batchRequestInFlightRef.current = true;
    const generation = ++batchGenerationRef.current;
    if (!polling) setBatchLoading(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/translation-batches/${encodeURIComponent(batchId)}`);
      const payload = await readJson(response);
      if (generation !== batchGenerationRef.current) return;
      setBatch(payload);
      setBatchError("");
      setPollSuspended(false);
    } catch (error) {
      if (generation !== batchGenerationRef.current) return;
      setBatchError(`${polling ? "批次状态轮询" : "批次刷新"}失败：${error.message}`);
      if (polling) setPollSuspended(true);
    } finally {
      batchRequestInFlightRef.current = false;
      if (!polling && generation === batchGenerationRef.current) setBatchLoading(false);
    }
  }, [projectId]);

  const loadLatest = useCallback(async () => {
    if (!snapshotId || batchRequestInFlightRef.current) return;
    batchRequestInFlightRef.current = true;
    const generation = ++batchGenerationRef.current;
    setBatchLoading(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/translation-batches/latest?snapshot_id=${encodeURIComponent(snapshotId)}`);
      const payload = await readJson(response, { allowNotFound: true });
      if (generation !== batchGenerationRef.current) return;
      setBatch(payload);
      if (payload?.anchor_filter?.length) {
        selectionKeyRef.current = scopeKey;
        setSelectedAnchors(supportedAnchors(payload.anchor_filter));
      }
      setBatchError("");
      setPollSuspended(false);
    } catch (error) {
      if (generation === batchGenerationRef.current) setBatchError(`当前批次读取失败：${error.message}`);
    } finally {
      batchRequestInFlightRef.current = false;
      if (generation === batchGenerationRef.current) setBatchLoading(false);
    }
  }, [projectId, scopeKey, snapshotId]);

  useEffect(() => {
    previewGenerationRef.current += 1;
    batchGenerationRef.current += 1;
    batchRequestInFlightRef.current = false;
    createKeyRef.current = "";
    retryKeyRef.current = { batchId: "", key: "" };
    batchReviewKeyRef.current = { batchId: "", key: "" };
    selectionKeyRef.current = "";
    settledMarkerRef.current = "";
    setPreview(null);
    setBatch(null);
    setAvailableAnchors([]);
    setSelectedAnchors([]);
    setStatusFilter("all");
    setTableAnchorFilter("all");
    setPreviewError("");
    setBatchError("");
    setNotice("");
    setPollSuspended(false);
    loadLatest();
    // Resume durable translation job after reload.
    try {
      const stored = JSON.parse(localStorage.getItem(`mw_translation_job_${projectId}`) || "null");
      if (stored?.job_id) {
        setDurableJobId(stored.job_id);
        pollDurableMwJob(projectId, stored.job_id, { intervalMs: 2500, maxLoops: 240 })
          .then(({ status, result, transportResultOk }) => {
            const ack = acknowledgeTranslationDomain({
              status,
              resultBody: transportResultOk ? result : null,
              locator: stored,
              expectedBatchId: stored.batch_id || "",
              expectedSnapshotId: stored.snapshot_id || "",
            });
            if (ack.outcome === "success") {
              const targetBatch = ack.batchId || stored.batch_id || "";
              if (targetBatch) loadBatch(targetBatch, { polling: false });
            } else if (ack.outcome === "reconcile_failed") {
              setBatchError("翻译作业已结束，但批次/快照核对失败。定位器已保留。");
            }
            if (ack.shouldClear) {
              try { localStorage.removeItem(`mw_translation_job_${projectId}`); } catch { /* ignore */ }
              setDurableJobId("");
            }
          });
      }
    } catch { /* ignore */ }
    return () => {
      previewGenerationRef.current += 1;
      batchGenerationRef.current += 1;
      batchRequestInFlightRef.current = false;
    };
  }, [loadLatest, scopeKey]);

  useEffect(() => {
    if (!snapshotId) return undefined;
    const timer = globalThis.setTimeout(() => loadPreview(selectedAnchors), selectedAnchors.length ? 80 : 0);
    return () => globalThis.clearTimeout(timer);
  }, [loadPreview, selectedAnchorKey, snapshotId]);

  useEffect(() => {
    createKeyRef.current = "";
  }, [selectedAnchorKey]);

  const batchStatus = normalizedStatus(batch?.status, "not_started");
  const batchId = batch?.batch_id || "";
  const batchRevision = batch?.updated_at || batchStatus;
  const active = ACTIVE_BATCH_STATUSES.has(batchStatus);

  useEffect(() => {
    if (!batchId || !active || pollSuspended) return undefined;
    const timer = globalThis.setInterval(() => loadBatch(batchId, { polling: true }), 2500);
    return () => globalThis.clearInterval(timer);
  }, [active, batchId, loadBatch, pollSuspended]);

  useEffect(() => {
    if (!batchId || !TERMINAL_BATCH_STATUSES.has(batchStatus)) return;
    const marker = `${batchId}:${batchRevision}`;
    if (settledMarkerRef.current === marker) return;
    settledMarkerRef.current = marker;
    onBatchSettled(batch);
  }, [batch, batchId, batchRevision, batchStatus, onBatchSettled]);

  const previewMatchesSelection = selectedScopeMatchesPreview(preview, selectedAnchors);
  const previewEligibleCount = previewMatchesSelection ? safeCount(preview?.eligible_count) : 0;
  const batchMatchesSelection = Boolean(batch)
    && batch.snapshot_id === snapshotId
    && batch.glossary_version === glossaryVersion
    && selectedScopeMatchesPreview(batch, selectedAnchors);
  const visibleBatch = batchMatchesSelection ? batch : null;
  const visibleBatchStatus = normalizedStatus(visibleBatch?.status, "not_started");
  const rows = useMemo(
    () => (visibleBatch?.items || []).map(normalizeItem),
    [visibleBatch?.items],
  );
  const documentProgress = useMemo(
    () => deriveDocumentTranslationProgress(visibleBatch?.items || []),
    [visibleBatch?.items],
  );
  const documentProgressSummary = useMemo(
    () => formatDocumentTranslationProgressSummary(documentProgress),
    [documentProgress],
  );
  const counts = visibleBatch?.counts || {};
  const candidateReadyCount = visibleBatch
    ? safeCount(counts.candidate_ready_count, rows.filter((row) => row.generationStatus === "candidate_ready").length)
    : previewMatchesSelection ? safeCount(preview?.existing_candidate_count) : 0;
  const fidelityBlockedCount = visibleBatch
    ? safeCount(counts.fidelity_blocked_count, rows.filter((row) => row.generationStatus === "fidelity_blocked").length)
    : previewMatchesSelection ? safeCount(preview?.fidelity_blocked_count) : 0;
  const failedCount = safeCount(counts.failed_count, rows.filter((row) => FAILED_ITEM_STATUSES.has(row.generationStatus)).length);
  const pendingReviewCount = safeCount(counts.pending_author_confirmation_count, rows.filter((row) => row.generationStatus === "candidate_ready" && ["not_confirmed", "returned"].includes(row.authorConfirmationStatus)).length);
  const approvedCount = safeCount(counts.author_confirmed_count, rows.filter((row) => row.authorConfirmationStatus === "confirmed").length);
  const admittedCount = safeCount(counts.admitted_count, rows.filter((row) => row.admissionStatus === "admitted").length);
  const batchReusedCount = safeCount(counts.reused_count, rows.filter((row) => row.origin === "existing").length);
  const expectedNewCount = previewMatchesSelection ? safeCount(preview?.eligible_new_count) : 0;
  const reuseCount = previewMatchesSelection ? safeCount(preview?.existing_candidate_count) : 0;

  const exclusionGroups = useMemo(() => {
    const reasonCounts = new Map();
    for (const countsByReason of [
      preview?.document_exclusion_reason_counts || {},
      preview?.span_exclusion_reason_counts || {},
    ]) {
      Object.entries(countsByReason).forEach(([reason, count]) => {
        reasonCounts.set(reason, safeCount(reasonCounts.get(reason)) + safeCount(count));
      });
    }
    const examples = new Map();
    (preview?.exclusions || []).forEach((item) => {
      const reason = item.reason_code || "other";
      const current = examples.get(reason) || [];
      if ((item.nct_id || item.artifact_id) && current.length < EXCLUSION_EXAMPLE_LIMIT) current.push(item);
      examples.set(reason, current);
    });
    return [...reasonCounts.entries()]
      .map(([reason, count]) => ({
        reason,
        label: exclusionReasonLabels[reason] || "其他不符合批量条件的原因",
        count,
        examples: examples.get(reason) || [],
      }))
      .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label, "zh-CN"));
  }, [preview]);
  const previewExcludedCount = exclusionGroups.reduce((sum, group) => sum + group.count, 0);
  const excludedCount = visibleBatch
    ? safeCount(counts.excluded_count, previewExcludedCount)
    : previewExcludedCount;

  const visibleRows = useMemo(() => {
    const filtered = rows.filter((row) => {
      if (tableAnchorFilter !== "all" && row.anchor !== tableAnchorFilter) return false;
      if (statusFilter === "pending" && row.generationStatus !== "pending") return false;
      if (statusFilter === "running" && row.generationStatus !== "running") return false;
      if (statusFilter === "excluded" && row.generationStatus !== "excluded") return false;
      if (statusFilter === "candidate_ready" && row.generationStatus !== "candidate_ready") return false;
      if (statusFilter === "fidelity_blocked" && row.generationStatus !== "fidelity_blocked") return false;
      if (statusFilter === "failed_retryable" && row.generationStatus !== "failed_retryable") return false;
      if (statusFilter === "failed_terminal" && row.generationStatus !== "failed_terminal") return false;
      if (statusFilter === "pending_author_confirmation" && !(row.generationStatus === "candidate_ready" && ["not_confirmed", "returned"].includes(row.authorConfirmationStatus))) return false;
      if (statusFilter === "author_confirmed" && row.authorConfirmationStatus !== "confirmed") return false;
      if (statusFilter === "admitted" && row.admissionStatus !== "admitted") return false;
      return true;
    });
    const direction = sort.direction === "asc" ? 1 : -1;
    return [...filtered].sort((left, right) => sortValue(left, sort.key).localeCompare(sortValue(right, sort.key), "zh-CN") * direction);
  }, [rows, sort, statusFilter, tableAnchorFilter]);

  const batchReviewEligibleRows = useMemo(
    () => visibleRows.filter(batchReviewEligibleRow),
    [visibleRows],
  );

  const toggleAnchor = (anchor, checked) => {
    if (!SUPPORTED_TRANSLATION_ANCHORS.has(anchor)) return;
    createKeyRef.current = "";
    setNotice("");
    setSelectedAnchors((current) => {
      if (!checked && current.length === 1 && current[0] === anchor) return current;
      return checked
        ? [...new Set([...current, anchor])]
        : current.filter((item) => item !== anchor);
    });
  };

  const updateSort = (key) => {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  };

  const startBatch = async () => {
    if (!selectedAnchors.length || !previewMatchesSelection || previewEligibleCount === 0) return;
    setAction("start");
    setBatchError("");
    setNotice("");
    if (!createKeyRef.current) createKeyRef.current = requestKey("reference-translation-batch");
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/translation-batches`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          snapshot_id: snapshotId,
          glossary_version: glossaryVersion,
          anchor_filter: selectedAnchors,
          actor: "medical_manager",
          idempotency_key: createKeyRef.current,
        }),
      });
      const payload = await readJson(response);
      setBatch(payload);
      if (payload.durable_job_id) {
        setDurableJobId(payload.durable_job_id);
        const locator = buildLocator({
          projectId,
          jobId: payload.durable_job_id,
          operation: "reference_translation",
          jobType: "reference_translation",
          batchId: payload.batch_id || "",
          snapshotId,
        });
        try { localStorage.setItem(`mw_translation_job_${projectId}`, JSON.stringify(locator)); } catch { /* ignore */ }
        // Poll the durable job in background for cancel/retry lifecycle.
        pollDurableMwJob(projectId, payload.durable_job_id, { intervalMs: 2500, maxLoops: 240 })
          .then(({ status, result, transportResultOk }) => {
            const ack = acknowledgeTranslationDomain({
              status,
              resultBody: transportResultOk ? result : null,
              locator,
              expectedBatchId: payload.batch_id || "",
              expectedSnapshotId: snapshotId,
            });
            if (ack.outcome === "success") {
              const targetBatch = ack.batchId || payload.batch_id || batchId;
              if (targetBatch) loadBatch(targetBatch, { polling: false });
            }
            if (ack.shouldClear) {
              try { localStorage.removeItem(`mw_translation_job_${projectId}`); } catch { /* ignore */ }
              setDurableJobId("");
            }
          });
      }
      setPollSuspended(false);
      setNotice("候选生成批次已受理；页面刷新后仍可恢复当前批次状态。");
      createKeyRef.current = "";
    } catch (error) {
      setBatchError(`候选生成未启动：${error.message}`);
    } finally {
      setAction("");
    }
  };

  const retryFailed = async () => {
    if (!batchId) return;
    setAction("retry");
    setBatchError("");
    setNotice("");
    if (retryKeyRef.current.batchId !== batchId || !retryKeyRef.current.key) {
      retryKeyRef.current = { batchId, key: requestKey("reference-translation-retry") };
    }
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/translation-batches/${encodeURIComponent(batchId)}/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: "medical_manager", idempotency_key: retryKeyRef.current.key }),
      });
      const payload = await readJson(response);
      setBatch(payload);
      const nextDurableId = resolveRetryJobId(durableJobId, payload)
        || payload.durable_job_id
        || durableJobId;
      if (nextDurableId) {
        setDurableJobId(nextDurableId);
        let previousLocator = null;
        try {
          previousLocator = JSON.parse(localStorage.getItem(`mw_translation_job_${projectId}`) || "null");
        } catch { /* ignore */ }
        const locator = mergeRetryLocator(
          previousLocator || {
            operation: "reference_translation",
            job_type: "reference_translation",
            batch_id: payload.batch_id || batchId,
            snapshot_id: snapshotId,
          },
          nextDurableId,
          projectId,
        );
        // Preserve batch/snapshot operation context across replacement job ids.
        locator.batch_id = payload.batch_id || batchId || locator.batch_id || "";
        locator.snapshot_id = snapshotId || locator.snapshot_id || "";
        try { localStorage.setItem(`mw_translation_job_${projectId}`, JSON.stringify(locator)); } catch { /* ignore */ }
        pollDurableMwJob(projectId, nextDurableId, { intervalMs: 2500, maxLoops: 240 })
          .then(({ status, result, transportResultOk }) => {
            const ack = acknowledgeTranslationDomain({
              status,
              resultBody: transportResultOk ? result : null,
              locator,
              expectedBatchId: locator.batch_id || batchId,
              expectedSnapshotId: snapshotId,
            });
            if (ack.outcome === "success") {
              const targetBatch = ack.batchId || payload.batch_id || batchId;
              if (targetBatch) loadBatch(targetBatch, { polling: false });
            }
            if (ack.shouldClear) {
              try { localStorage.removeItem(`mw_translation_job_${projectId}`); } catch { /* ignore */ }
              setDurableJobId("");
            }
          });
      }
      setPollSuspended(false);
      setNotice("已仅重新提交可重试失败项；成功项、忠实度阻断项和终止失败项不会重复生成。");
      retryKeyRef.current = { batchId: "", key: "" };
    } catch (error) {
      setBatchError(`失败项重试未启动：${error.message}`);
    } finally {
      setAction("");
    }
  };

  const batchConfirmEligible = async () => {
    if (!batchId || !batchReviewEligibleRows.length) return;
    setAction("batch-confirm");
    setBatchError("");
    setNotice("");
    if (batchReviewKeyRef.current.batchId !== batchId || !batchReviewKeyRef.current.key) {
      batchReviewKeyRef.current = { batchId, key: requestKey("reference-translation-batch-review") };
    }
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/translation-batches/${encodeURIComponent(batchId)}/medical-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targets: batchReviewEligibleRows.map((row) => ({
            translation_id: row.translationId,
            translation_revision: row.translationRevision,
          })),
          actor: "medical_manager",
          idempotency_key: batchReviewKeyRef.current.key,
        }),
      });
      const payload = await readJson(response);
      const approvedCount = safeCount(payload.approved_count);
      const skippedCount = safeCount(payload.skipped_count);
      const staleCount = safeCount(payload.stale_count);
      const failedCount = safeCount(payload.failed_count);
      setNotice(`一键确认完成：已确认 ${approvedCount} 项${skippedCount ? `，跳过 ${skippedCount} 项（忠实度阻断、已退回、已拒绝或已确认项仍需逐项核对）` : ""}${staleCount ? `，${staleCount} 项版本已变化，请刷新后逐项核对` : ""}${failedCount ? `，${failedCount} 项确认失败` : ""}。`);
      batchReviewKeyRef.current = { batchId: "", key: "" };
      await loadBatch(batchId);
      // Medical-review creates/updates approved evidence briefs in the parent
      // workspace, but does not necessarily change the batch revision marker.
      // Refresh the parent explicitly so the adjacent "已准入证据" tab cannot
      // remain at a stale zero-count after a successful one-click confirmation.
      await onBatchSettled();
    } catch (error) {
      setBatchError(`一键确认未完成：${error.message}`);
    } finally {
      setAction("");
    }
  };

  const cancelTranslationJob = async () => {
    if (!durableJobId) return;
    try {
      await fetch(`/api/projects/${projectId}/medical-writing/jobs/${durableJobId}/cancel`, { method: "POST" });
      // Do NOT clear locator or jobId here.  The background poll will detect
      // the cancelled status and reconcile before cleanup.
    } catch { /* best-effort */ }
  };

  const refreshAll = async () => {
    setAction("refresh");
    setNotice("");
    setPollSuspended(false);
    await Promise.all([
      loadPreview(selectedAnchors),
      batchId ? loadBatch(batchId) : loadLatest(),
    ]);
    setAction("");
  };

  return (
    <section className="writing-reference-translation-batch" data-testid="reference-translation-batch" data-batch-status={batchStatus} data-batch-id={batchId || undefined}>
      <header className="writing-reference-translation-batch-head">
        <div>
          <span><Languages size={14} />监管中文候选批次</span>
          <strong>按 M11 结构范围生成</strong>
          <small>机器忠实度检查只验证候选与原文的一致性；通过后由医学作者一键确认合格候选或逐片段核对，确认即直接准入。</small>
        </div>
        <code title="当前监管术语契约">{glossaryVersion}</code>
      </header>

      <div className="writing-reference-translation-summary" role="status" aria-live="polite" data-testid="translation-batch-counts">
          <span><small>当前范围批次</small><b className={visibleBatchStatus}>{batchStatusLabels[visibleBatchStatus] || "状态待确认"}</b></span>
        <span><small>符合条件</small><b>{previewEligibleCount}</b></span>
        <span><small>已生成候选</small><b>{candidateReadyCount}</b></span>
        <span className={fidelityBlockedCount ? "danger" : ""}><small>忠实度阻断</small><b>{fidelityBlockedCount}</b></span>
        <span className={failedCount ? "danger" : ""}><small>失败</small><b>{failedCount}</b></span>
        <span className={pendingReviewCount ? "warning" : ""}><small>待作者确认</small><b>{pendingReviewCount}</b></span>
        <span><small>作者已确认</small><b>{approvedCount}</b></span>
        <span><small>已准入</small><b>{admittedCount}</b></span>
      </div>

      {rows.length > 0 && (
        <>
          <WritingReferenceProgressJourney
            items={rows.map((row) => ({
              status: ["excluded", "candidate_ready", "fidelity_blocked", "failed_retryable", "failed_terminal"].includes(row.generationStatus)
                ? row.generationStatus
                : row.pipelineStage || row.generationStatus,
              pipeline_stage: row.pipelineStage,
              pipeline_stage_detail: row.pipelineStageDetail,
              artifact_id: row.artifactId,
              span_id: row.spanId,
              document_total: row.documentTotal,
              document_index: row.documentIndex,
              document_label: row.documentLabel,
              chapter_id: row.chapterId,
              chapter_title: row.chapterTitle,
              chapter_total: row.chapterTotal,
              chapter_index: row.chapterIndex,
              chunk_count: row.chunkCount,
              chunk_completed: row.chunkCompleted,
              chunk_running: row.chunkRunning,
              chunk_failed: row.chunkFailed,
              chunk_reused: row.chunkReused,
            }))}
            compact={true}
          />
          {documentProgressSummary ? (
            <p
              className="writing-reference-translation-document-progress"
              role="status"
              aria-live="polite"
              data-testid="translation-document-chapter-chunk-progress"
            >
              {documentProgressSummary}
            </p>
          ) : null}
        </>
      )}

      <div className="writing-reference-translation-scope">
        <fieldset>
          <legend>M11 结构范围（已选 {selectedAnchors.length}/{availableAnchors.filter((anchor) => SUPPORTED_TRANSLATION_ANCHORS.has(anchor.value)).length}）</legend>
          <div className="writing-reference-translation-anchor-options" data-testid="translation-anchor-filter">
            {availableAnchors.map((anchor) => (
              <label key={anchor.value}>
                <input type="checkbox" checked={selectedAnchors.includes(anchor.value)} disabled={!SUPPORTED_TRANSLATION_ANCHORS.has(anchor.value)} onChange={(event) => toggleAnchor(anchor.value, event.target.checked)} />
                <span>{anchor.value}（{anchor.count}）{SUPPORTED_TRANSLATION_ANCHORS.has(anchor.value) ? "" : " · 当前批量翻译合同暂不支持"}</span>
              </label>
            ))}
            {!availableAnchors.length && <span>当前预览没有返回可选择的已映射 M11 结构。</span>}
          </div>
        </fieldset>
        <div className="writing-reference-translation-preview" data-testid="translation-batch-preview-counts">
          <span><b>{expectedNewCount}</b>预计新生成</span>
          <span title={visibleBatch ? `当前批次实际复用 ${batchReusedCount}` : undefined}><b>{reuseCount}</b>复用当前契约候选</span>
          <span><b>{excludedCount}</b>排除</span>
        </div>
        <div className="writing-reference-translation-actions">
          <button className="primary-button" type="button" data-action="start-translation-batch" onClick={startBatch} disabled={!snapshotId || !previewMatchesSelection || previewEligibleCount === 0 || !selectedAnchors.length || active || Boolean(action) || previewLoading || batchLoading} title={!selectedAnchors.length ? "至少选择一个有资格的 M11 结构" : "按当前结构范围生成监管中文候选"}>
            <Play size={14} />{action === "start" ? "提交中" : "生成候选"}
          </button>
          <button type="button" data-action="refresh-translation-batch" onClick={refreshAll} disabled={Boolean(action) || previewLoading || batchLoading}>
            <RefreshCw size={14} className={previewLoading || batchLoading ? "spin" : ""} />刷新
          </button>
          <button type="button" data-action="retry-translation-failed" onClick={retryFailed} disabled={!batchMatchesSelection || !batchId || !failedCount || active || Boolean(action) || batchLoading}>
            <RotateCcw size={14} />{action === "retry" ? "重试中" : "仅重试失败项"}
          </button>
          <button type="button" data-action="batch-confirm-eligible-translations" onClick={batchConfirmEligible} disabled={!batchMatchesSelection || !batchId || !batchReviewEligibleRows.length || active || Boolean(action) || batchLoading} title="一键确认当前筛选中机器忠实度通过且尚未确认的候选；忠实度阻断、已退回、已拒绝或版本已变化项仍需逐项核对">
            <CheckCheck size={14} />{action === "batch-confirm" ? "确认中" : `一键确认合格候选（${batchReviewEligibleRows.length}）`}
          </button>
          {durableJobId && active && (
            <button type="button" data-action="cancel-translation-job" onClick={cancelTranslationJob}>取消生成</button>
          )}
        </div>
      </div>

      {batch && !batchMatchesSelection && previewMatchesSelection && (
        <p className="writing-reference-translation-message" role="status">
          当前选择与最近批次的冻结范围不同；本页先显示本次范围预览，生成后建立新的可恢复批次。
        </p>
      )}

      {previewError && <p className="writing-reference-translation-message danger" role="alert">{previewError}</p>}
      {batchError && <p className="writing-reference-translation-message danger" role="alert">{batchError}</p>}
      {notice && <p className="writing-reference-translation-message" role="status">{notice}</p>}

      {previewMatchesSelection && previewEligibleCount === 0 ? (
        <div className="writing-reference-translation-empty" data-testid="translation-batch-zero-eligible">
          <strong>当前范围没有可批量生成的合格片段</strong>
          <span>零 eligible 是合法结果，通常表示当前研究没有可用公开Protocol，或文件内容核验与结构医学审核双门禁尚未完成。可到“文档与解析”手动导入已取得的Protocol，或先完成阶段一处理。</span>
        </div>
      ) : (
        <>
          <div className="writing-reference-translation-table-tools">
            <label>状态筛选
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="all">全部状态</option>
                <option value="pending">待生成</option>
                <option value="running">生成中</option>
                <option value="excluded">规划后排除</option>
                <option value="candidate_ready">候选已就绪</option>
                <option value="fidelity_blocked">忠实度阻断</option>
                <option value="failed_retryable">失败，可重试</option>
                <option value="failed_terminal">终止失败</option>
                <option value="pending_author_confirmation">待作者确认</option>
                <option value="author_confirmed">作者已确认</option>
                <option value="admitted">已准入</option>
              </select>
            </label>
            <label>Anchor 筛选
              <select value={tableAnchorFilter} onChange={(event) => setTableAnchorFilter(event.target.value)}>
                <option value="all">全部 M11 结构</option>
                {availableAnchors.map((anchor) => <option value={anchor.value} key={anchor.value}>{anchor.value}</option>)}
              </select>
            </label>
            <span>{visibleRows.length}/{rows.length} 条</span>
          </div>

          <div className="writing-reference-translation-table-wrap" data-testid="translation-batch-table">
            <table className="writing-reference-translation-table">
              <thead><tr>
                <th><SortHeader label="研究 / 文件" column="study" sort={sort} onSort={updateSort} /></th>
                <th><SortHeader label="M11 结构与来源定位" column="anchor" sort={sort} onSort={updateSort} /></th>
                <th><SortHeader label="生成状态" column="generation" sort={sort} onSort={updateSort} /></th>
                <th><SortHeader label="忠实度" column="fidelity" sort={sort} onSort={updateSort} /></th>
                <th><SortHeader label="作者确认" column="review" sort={sort} onSort={updateSort} /></th>
                <th><SortHeader label="准入" column="admission" sort={sort} onSort={updateSort} /></th>
                <th><SortHeader label="下一步" column="next" sort={sort} onSort={updateSort} /></th>
              </tr></thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr key={row.rowKey} data-anchor={row.anchor} data-generation-status={row.generationStatus} data-review-status={row.authorConfirmationStatus} data-admission-status={row.admissionStatus}>
                    <td><strong>{row.nctId || "研究待确认"}</strong><small>{row.filename || "文件名待后端补充"}{row.documentType ? ` · ${row.documentType}` : ""}</small></td>
                    <td><strong>{row.anchor || "结构待确认"}</strong><small>{row.sourceLocator}</small></td>
                    <td>
                      {statusTag(row.generationStatus, generationLabels)}
                      {row.generationStatus === "running" && row.pipelineStageDetail && (
                        <small>{row.pipelineStageDetail}</small>
                      )}
                    </td>
                    <td>{statusTag(row.fidelityStatus, fidelityLabels)}{row.fidelityFailureCodes.length > 0 && <small>{row.fidelityFailureCodes.join("、")}</small>}</td>
                    <td>{statusTag(row.authorConfirmationStatus, reviewLabels, "待作者确认")}</td>
                    <td>{statusTag(row.admissionStatus, admissionLabels, "未准入")}</td>
                    <td>
                      <span>{nextStep(row)}</span>
                      <button type="button" data-action="open-translation-span" onClick={() => onOpenSpan({ artifact_id: row.artifactId, span_id: row.spanId, ich_m11_anchor: row.anchor })} disabled={row.generationStatus === "excluded" || !row.artifactId || !row.spanId} title={row.generationStatus === "excluded" ? "该章节不在本次所选范围，无需核对译文" : "在下方单片段区对照原文并确认译文"}><Eye size={13} />核对译文</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!visibleRows.length && <div className="writing-reference-translation-table-empty">{batch ? "当前筛选条件下没有片段。" : "生成批次后将在此显示具体片段。"}</div>}
          </div>
        </>
      )}

      <details className="writing-reference-translation-exclusions">
        <summary>排除项（{excludedCount}）</summary>
        {exclusionGroups.map((group) => (
          <div key={group.reason}>
            <strong>{group.label}<span>{group.count} 项</span></strong>
            {group.examples.map((item, index) => (
              <p key={`${group.reason}:${item.artifact_id || "document"}:${index}`}>
                <b>{item.nct_id || "研究待确认"}</b>
                <span>{item.artifact_id || "未登记文件"}{item.ich_m11_anchor ? ` · ${item.ich_m11_anchor}` : ""}</span>
              </p>
            ))}
            {group.count > group.examples.length && <p><b>其余项目</b><span>另有 {group.count - group.examples.length} 项未展开</span></p>}
          </div>
        ))}
        {!exclusionGroups.length && <p>当前预览没有排除项。</p>}
      </details>
    </section>
  );
}
