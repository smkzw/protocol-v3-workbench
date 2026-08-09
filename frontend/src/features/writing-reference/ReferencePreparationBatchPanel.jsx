import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Play, RefreshCw, RotateCcw } from "lucide-react";
import { WritingReferenceProgressJourney } from "./WritingReferenceProgressJourney";

const ACTIVE_BATCH_STATUSES = new Set(["accepted", "running"]);
const TERMINAL_BATCH_STATUSES = new Set([
  "completed",
  "completed_with_review_required",
  "completed_with_manual_upload_required",
  "partial_failure",
  "failed",
]);
const REFERENCE_DOCUMENT_TYPES = new Set(["protocol", "protocol_sap"]);
const FAILURE_STATUSES = new Set(["failed"]);
const REVIEW_STATUSES = new Set(["review_required", "needs_review", "mismatch"]);
const errorDetailLabels = {
  no_public_protocol_or_sap: "本次公开检索结果中未发现公开 Protocol，请手动导入已取得的研究方案原文。",
  no_public_protocol: "本次公开检索结果中未发现公开 Protocol，请手动导入已取得的研究方案原文。",
  source_artifact_invalidated: "当前来源版本已失效，请重新下载或手动导入当前版本。",
  service_restart_interrupted: "服务重启中断了本次处理，可仅重试该失败项。",
  standalone_sap_out_of_scope: "独立 SAP 不属于本批次 Protocol 语料范围。",
  public_document_content_invalid: "公开文件内容无法通过基本校验，请转入逐文件处理。",
  document_has_no_extractable_text: "文件未提取到可用文字，请核对原文件或改用可解析版本。",
  public_document_redirect_not_allowed: "公开下载地址已跳转至非授权来源，请人工核对来源。",
  registered_artifact_unavailable: "已登记的文件当前不可读取，请重新下载或手动导入。",
  validation_status_unsupported: "内容校验状态异常，请转入逐文件处理。",
};

const batchStatusLabels = {
  not_started: "待开始",
  accepted: "已受理",
  running: "批量准备中",
  completed: "批量准备完成",
  completed_with_review_required: "准备完成，待人工内容确认",
  completed_with_manual_upload_required: "准备完成，待手动导入",
  partial_failure: "部分失败",
  failed: "批次失败",
  awaiting_stage_admission: "等待下一阶段准入",
};

const stageLabels = {
  download: {
    pending: "待下载",
    running: "下载中",
    downloading: "下载中",
    succeeded: "已下载",
    review_required: "待人工处理",
    not_applicable: "不适用",
    failed: "下载失败",
    failed_retryable: "下载失败（可重试）",
    failed_terminal: "下载失败（终止）",
  },
  parse: {
    pending: "待解析",
    running: "解析中",
    extracting: "解析提取中",
    ocr_running: "OCR识别中",
    toc_planning: "目录识别中",
    succeeded: "已解析",
    review_required: "待人工处理",
    not_applicable: "不适用",
    failed: "解析失败",
    failed_retryable: "解析失败（可重试）",
    failed_terminal: "解析失败（终止）",
  },
  validation: {
    pending: "待校验",
    running: "校验中",
    translating_hy_mt2: "Hy-MT2翻译中",
    integration_qc: "衔接核对中",
    confirmed: "内容匹配",
    succeeded: "内容匹配",
    review_required: "待人工确认",
    needs_review: "待人工确认",
    mismatch: "内容不一致",
    user_overridden: "已确认沿用",
    not_applicable: "不适用",
    failed: "校验失败",
    failed_retryable: "校验失败（可重试）",
    failed_terminal: "校验失败（终止）",
  },
};

const newStageLabels = {
  extracting: "解析提取中",
  ocr_running: "OCR识别中",
  toc_planning: "目录识别中",
  translating_hy_mt2: "Hy-MT2翻译中",
  integration_qc: "衔接核对中",
  candidate_ready: "候选已就绪",
  fidelity_blocked: "忠实度阻断",
  failed_retryable: "失败（可重试）",
  failed_terminal: "失败（终止）",
};

const preparationProgressPhaseLabels = {
  pending: "等待开始处理",
  downloading: "正在下载公开 Protocol",
  native_extracting: "正在提取原生文本",
  ocr_rendering: "正在渲染 OCR 页面",
  ocr_completing: "正在完成 OCR 页面识别",
  extraction_persisting: "正在持久化结构提取结果",
  content_validating: "正在校验文件内容",
  completed: "文件准备完成",
  failed: "文件准备失败",
};

function stageLabel(stage, status) {
  const stageMap = stageLabels[stage];
  if (stageMap && stageMap[status]) return stageMap[status];
  if (newStageLabels[status]) return newStageLabels[status];
  return status;
}

function requestKey(prefix) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}-${suffix}`;
}

async function readJson(response, { allowNotFound = false } = {}) {
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload;
  if (allowNotFound && response.status === 404) return null;
  const error = new Error(typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`);
  error.status = response.status;
  throw error;
}

function normalizedStatus(value, fallback = "pending") {
  return String(value || fallback).trim().toLowerCase();
}

function itemProgress(item) {
  const progress = item?.progress || {};
  return {
    phase: normalizedStatus(progress.phase, "pending"),
    current_substep: progress.current_substep || "",
    completed: Number(progress.completed || 0),
    total: Number(progress.total || 0),
    percent: Math.max(0, Math.min(100, Number(progress.percent || 0))),
    unit: progress.unit || "",
    context: progress.context || {},
  };
}

function progressSubstep(progress) {
  return progress.current_substep
    || preparationProgressPhaseLabels[progress.phase]
    || "等待真实处理边界";
}

function progressCountLabel(progress) {
  if (!progress.total) return "";
  if (progress.unit === "page" && String(progress.phase || "").startsWith("ocr_")) {
    return `已完成 ${progress.completed}/${progress.total} 个需识别页面`;
  }
  return `${progress.completed}/${progress.total}${progress.unit === "page" ? " 页" : ""}`;
}

function stageStatus(item, stage) {
  const stageState = stage === "download"
    ? item.ingest
    : stage === "parse"
      ? item.extraction
      : item.validation;
  return normalizedStatus(stageState?.status);
}

function rawBatchItems(batch) {
  return Array.isArray(batch?.items) ? batch.items : [];
}

function normalizeBatchItem(item, candidateById) {
  const nctId = item.nct_id || "";
  const documentId = item.document_id || item.item_id;
  const downloadStatus = stageStatus(item, "download");
  const parseStatus = stageStatus(item, "parse");
  const validationStageStatus = stageStatus(item, "validation");
  const validationStatus = normalizedStatus(item.validation_status, "") || validationStageStatus;
  const itemStatus = normalizedStatus(item.status);
  return {
    ...item,
    nct_id: nctId,
    document_id: documentId,
    artifact_id: item.artifact_id || "",
    study_title: item.study_title || candidateById.get(nctId)?.brief_title || candidateById.get(nctId)?.official_title || "",
    document_label: item.filename || (item.item_kind === "study_manual_upload_required" ? "未发现公开 Protocol" : "公开文件待确认"),
    document_type: item.document_type || (item.item_kind === "study_manual_upload_required" ? "待补充" : "Protocol"),
    document_date: item.document_date || "",
    download_status: downloadStatus,
    parse_status: parseStatus,
    validation_status: validationStatus,
    item_status: itemStatus,
    error_detail: itemStatus === "excluded"
      ? ""
      : errorDetailLabels[item.error_code] || item.error_detail || "",
    progress: item.progress || {},
  };
}

function preparationProgressStatus(item) {
  const statuses = [
    normalizedStatus(item.download_status, ""),
    normalizedStatus(item.parse_status, ""),
    normalizedStatus(item.validation_status, ""),
    normalizedStatus(item.item_status, ""),
  ];
  if (statuses.includes("excluded")) return "excluded";
  const terminalFailure = statuses.find((status) => ["failed_terminal", "manual_upload_required"].includes(status));
  if (terminalFailure) return "failed_terminal";
  const retryableFailure = statuses.find((status) => ["failed", "failed_retryable"].includes(status));
  if (retryableFailure) return "failed_retryable";
  if (statuses.some((status) => ["mismatch", "review_required", "needs_review"].includes(status))) {
    return "fidelity_blocked";
  }
  if (["confirmed", "succeeded", "user_overridden"].includes(normalizedStatus(item.validation_status, ""))) {
    return "prepared";
  }
  if (["prepared", "completed"].includes(normalizedStatus(item.item_status, ""))) return "prepared";
  if (["running", "validating"].includes(normalizedStatus(item.validation_status, ""))) return "validating";
  const parseStatus = normalizedStatus(item.parse_status, "");
  if (["extracting", "ocr_running", "toc_planning"].includes(parseStatus)) return parseStatus;
  if (parseStatus === "running") return "parsing";
  const downloadStatus = normalizedStatus(item.download_status, "");
  if (["running", "downloading", "accepted"].includes(downloadStatus)) return "downloading";
  return "waiting";
}

function buildPreviewItems(candidates, artifacts, validations, artifactSpanCounts) {
  const artifactByDocument = new Map(
    artifacts.filter((item) => item.source_status !== "user_uploaded")
      .map((item) => [item.source_document_id, item]),
  );
  const validationByArtifact = new Map(validations.map((item) => [item.artifact_id, item]));
  return candidates.flatMap((candidate) => {
    const documents = (candidate.public_documents || []).filter((document) => (
      REFERENCE_DOCUMENT_TYPES.has(String(document.document_type || "").toLowerCase())
    ));
    if (!documents.length) {
      return [{
        nct_id: candidate.nct_id,
        document_id: `missing-${candidate.nct_id}`,
        artifact_id: "",
        item_kind: "study_manual_upload_required",
        study_title: candidate.brief_title || candidate.official_title || "",
        document_label: "未发现公开 Protocol",
        document_type: "待补充",
        document_date: "",
        download_status: "not_applicable",
        parse_status: "not_applicable",
        validation_status: "not_applicable",
        item_status: "manual_upload_required",
        error_detail: "可在逐文件问题处理中手动导入已取得的原始文件。",
      }];
    }
    return documents.map((document) => {
      const artifact = artifactByDocument.get(document.document_id);
      const validation = artifact ? validationByArtifact.get(artifact.artifact_id) : null;
      const parsed = artifact && Number(artifactSpanCounts?.[artifact.artifact_id] || 0) > 0;
      const sourceInvalid = artifact && !artifact.source_current;
      return {
        nct_id: candidate.nct_id,
        document_id: document.document_id,
        artifact_id: artifact?.artifact_id || "",
        study_title: candidate.brief_title || candidate.official_title || "",
        document_label: document.label || document.filename || "公开文件",
        document_type: document.document_type || "Protocol",
        document_date: document.document_date || "",
        download_status: sourceInvalid ? "failed" : artifact ? "succeeded" : "pending",
        parse_status: sourceInvalid ? "pending" : parsed ? "succeeded" : "pending",
        validation_status: sourceInvalid ? "pending" : validation?.status || "pending",
        item_status: sourceInvalid
          ? "failed"
          : validation?.status === "confirmed" || validation?.status === "user_overridden"
            ? "prepared"
            : REVIEW_STATUSES.has(validation?.status)
              ? "review_required"
              : "pending",
        error_detail: sourceInvalid ? "来源版本已失效，不能在批次中自动重用。" : "",
      };
    });
  });
}

function stageTone(status) {
  if (status === "failed" || status === "mismatch") return "danger";
  if (["succeeded", "confirmed", "user_overridden"].includes(status)) return "success";
  if (status === "running") return "info";
  return "warning";
}

function itemNeedsAttention(item) {
  return item.item_status === "failed"
    || item.item_status === "review_required"
    || item.item_status === "manual_upload_required"
    || item.download_status === "failed"
    || item.parse_status === "failed"
    || item.validation_status === "failed"
    || REVIEW_STATUSES.has(item.validation_status)
    || REVIEW_STATUSES.has(item.item_status);
}

function nextStepLabel(item) {
  if (item.item_status === "excluded") return "无需处理";
  if (item.item_status === "manual_upload_required") return "手动导入 Protocol";
  if (item.item_status === "review_required") return "人工确认文件内容";
  if (item.item_status === "failed") return "重试失败项或逐文件处理";
  if (item.item_status === "prepared") return "待结构审核";
  if (item.item_status === "running") return "批次处理中";
  return "等待批次执行";
}

export function ReferencePreparationBatchPanel({
  projectId,
  snapshotId,
  candidates = [],
  artifacts = [],
  documentValidations = [],
  artifactSpanCounts = {},
  onOpenIssue = () => {},
  onBatchSettled = () => {},
}) {
  const generationRef = useRef(0);
  const createKeyRef = useRef("");
  const retryKeyRef = useRef({ batchId: "", key: "" });
  const advanceKeyRef = useRef({ batchId: "", key: "" });
  const settledMarkerRef = useRef("");
  const [batch, setBatch] = useState(null);
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState("");
  const [message, setMessage] = useState("");
  const [pollSuspended, setPollSuspended] = useState(false);

  const candidateById = useMemo(
    () => new Map(candidates.map((candidate) => [candidate.nct_id, candidate])),
    [candidates],
  );
  const previewItems = useMemo(
    () => buildPreviewItems(candidates, artifacts, documentValidations, artifactSpanCounts),
    [candidates, artifacts, documentValidations, artifactSpanCounts],
  );

  const loadLatest = useCallback(async ({ silent = false } = {}) => {
    if (!snapshotId) return;
    const generation = ++generationRef.current;
    if (!silent) setLoading(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/preparation-batches/latest?snapshot_id=${encodeURIComponent(snapshotId)}`);
      const payload = await readJson(response, { allowNotFound: true });
      if (generation !== generationRef.current) return;
      setBatch(payload);
      setMessage("");
      setPollSuspended(false);
    } catch (error) {
      if (generation === generationRef.current) setMessage(`批次状态读取失败：${error.message}`);
    } finally {
      if (!silent && generation === generationRef.current) setLoading(false);
    }
  }, [projectId, snapshotId]);

  const loadBatch = useCallback(async (batchId, { polling = false } = {}) => {
    if (!batchId) return;
    const generation = ++generationRef.current;
    if (!polling) setLoading(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/preparation-batches/${encodeURIComponent(batchId)}`);
      const payload = await readJson(response);
      if (generation !== generationRef.current) return;
      setBatch(payload);
      setMessage("");
      setPollSuspended(false);
    } catch (error) {
      if (generation !== generationRef.current) return;
      setMessage(`${polling ? "批次轮询" : "批次刷新"}失败：${error.message}`);
      if (polling) setPollSuspended(true);
    } finally {
      if (!polling && generation === generationRef.current) setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    generationRef.current += 1;
    setBatch(null);
    setMessage("");
    setPollSuspended(false);
    createKeyRef.current = "";
    retryKeyRef.current = { batchId: "", key: "" };
    advanceKeyRef.current = { batchId: "", key: "" };
    settledMarkerRef.current = "";
    loadLatest();
    return () => { generationRef.current += 1; };
  }, [loadLatest]);

  const batchStatus = normalizedStatus(batch?.status, "not_started");
  const batchId = batch?.batch_id || "";
  const batchRevision = batch?.updated_at || batchStatus;

  useEffect(() => {
    if (!batchId || !ACTIVE_BATCH_STATUSES.has(batchStatus) || pollSuspended) return undefined;
    const timer = globalThis.setTimeout(() => loadBatch(batchId, { polling: true }), 2000);
    return () => globalThis.clearTimeout(timer);
  }, [batchId, batchStatus, batchRevision, loadBatch, pollSuspended]);

  useEffect(() => {
    if (!batchId || !TERMINAL_BATCH_STATUSES.has(batchStatus)) return;
    const marker = `${batchId}:${batchRevision}`;
    if (settledMarkerRef.current === marker) return;
    settledMarkerRef.current = marker;
    onBatchSettled(batch);
  }, [batch, batchId, batchRevision, batchStatus, onBatchSettled]);

  const batchItems = useMemo(
    () => rawBatchItems(batch).map((item) => normalizeBatchItem(item, candidateById)),
    [batch, candidateById],
  );
  const rows = batchItems.length ? batchItems : previewItems;
  const currentProgressItem = batchItems.find((item) => item.item_status === "running")
    || batchItems.find((item) => item.item_status === "pending")
    || batchItems.find((item) => item.item_status === "failed");
  const projectedProgress = batch?.progress || (currentProgressItem ? itemProgress(currentProgressItem) : null);
  const progress = {
    ...itemProgress(currentProgressItem),
    ...projectedProgress,
    completed: Number(projectedProgress?.completed ?? itemProgress(currentProgressItem).completed ?? 0),
    total: Number(projectedProgress?.total ?? itemProgress(currentProgressItem).total ?? 0),
    percent: Math.max(0, Math.min(100, Number(projectedProgress?.percent ?? itemProgress(currentProgressItem).percent ?? 0))),
  };
  const currentNctId = progress.context?.nct_id || batch?.current_nct_id || currentProgressItem?.nct_id || "";
  const currentDocumentLabel = progress.context?.document_label || batch?.current_document_label
    || currentProgressItem?.document_label
    || "";
  const studyCount = new Set(rows.map((item) => item.nct_id).filter(Boolean)).size;
  const fileCount = rows.filter((item) => item.item_kind !== "study_manual_upload_required").length;
  const failedCount = rows.filter((item) => (
    FAILURE_STATUSES.has(item.item_status)
    || FAILURE_STATUSES.has(item.download_status)
    || FAILURE_STATUSES.has(item.parse_status)
    || FAILURE_STATUSES.has(item.validation_status)
  )).length;
  const reviewCount = rows.filter((item) => REVIEW_STATUSES.has(item.validation_status) || REVIEW_STATUSES.has(item.item_status)).length;
  const manualUploadCount = rows.filter((item) => item.item_status === "manual_upload_required").length;
  const finishedCount = Number(batch?.prepared_count || 0)
    + Number(batch?.review_required_count || 0)
    + Number(batch?.manual_upload_required_count || 0)
    + Number(batch?.failed_count || 0)
    + Number(batch?.excluded_count || 0);
  const active = ACTIVE_BATCH_STATUSES.has(batchStatus);

  const startBatch = async () => {
    setAction("start");
    setMessage("");
    if (!createKeyRef.current) createKeyRef.current = requestKey("reference-preparation-batch");
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/preparation-batches`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          snapshot_id: snapshotId,
          actor: "medical_manager",
          idempotency_key: createKeyRef.current,
        }),
      });
      const payload = await readJson(response);
      setBatch(payload);
      setPollSuspended(false);
      setMessage("批量准备已启动；刷新页面后仍可恢复当前进度。");
      createKeyRef.current = "";
    } catch (error) {
      setMessage(`批量准备未启动：${error.message}`);
    } finally {
      setAction("");
    }
  };

  const retryFailed = async () => {
    if (!batchId) return;
    setAction("retry");
    setMessage("");
    if (retryKeyRef.current.batchId !== batchId || !retryKeyRef.current.key) {
      retryKeyRef.current = { batchId, key: requestKey("reference-preparation-retry") };
    }
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/preparation-batches/${encodeURIComponent(batchId)}/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: "medical_manager", idempotency_key: retryKeyRef.current.key }),
      });
      const payload = await readJson(response);
      setBatch(payload);
      setPollSuspended(false);
      setMessage("已仅重新提交失败项；成功项和待人工确认项不会重复处理。");
      retryKeyRef.current = { batchId: "", key: "" };
    } catch (error) {
      setMessage(`失败项重试未启动：${error.message}`);
    } finally {
      setAction("");
    }
  };

  const advanceStage = async () => {
    if (!batchId || batchStatus !== "awaiting_stage_admission") return;
    setAction("advance");
    setMessage("");
    if (advanceKeyRef.current.batchId !== batchId || !advanceKeyRef.current.key) {
      advanceKeyRef.current = { batchId, key: requestKey("reference-preparation-stage") };
    }
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/references/preparation-batches/${encodeURIComponent(batchId)}/advance-stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          actor: "medical_manager",
          idempotency_key: advanceKeyRef.current.key,
        }),
      });
      const payload = await readJson(response);
      setBatch(payload);
      setPollSuspended(false);
      setMessage("已准入下一阶段原文；成功项不会重复下载或 OCR。批次将继续处理。");
      advanceKeyRef.current = { batchId: "", key: "" };
    } catch (error) {
      setMessage(`下一阶段准入未启动：${error.message}`);
    } finally {
      setAction("");
    }
  };

  const refreshBatch = () => {
    setPollSuspended(false);
    return batchId ? loadBatch(batchId) : loadLatest();
  };

  return (
    <section
      className="writing-reference-preparation-batch"
      data-testid="reference-preparation-batch"
      data-batch-status={batchStatus}
      data-batch-id={batchId || undefined}
    >
      <header className="writing-reference-batch-head">
        <div>
          <span>已锁定竞品篮子</span>
          <strong>本批次 Protocol 准备</strong>
          <small>本批次只执行公开文件下载、结构解析和内容校验；结构确认、监管中文审核与语料准入在后续审核工作区完成。</small>
        </div>
        <span className={`writing-reference-batch-status ${batchStatus}`}>{batchStatusLabels[batchStatus] || batchStatus}</span>
      </header>

      <div className="writing-reference-batch-summary" data-testid="reference-batch-summary" role="status" aria-live="polite">
        <span><b>{studyCount}</b>项研究</span>
        <span><b>{fileCount}</b>份公开文件</span>
        <span className={failedCount ? "danger" : ""}><b>{failedCount}</b>项失败</span>
        <span className={reviewCount ? "warning" : ""}><b>{reviewCount}</b>项待人工确认</span>
        <span className={manualUploadCount ? "warning" : ""}><b>{manualUploadCount}</b>项待手动导入</span>
      </div>

      {batchItems.length > 0 && (
        <>
          <WritingReferenceProgressJourney
            items={batchItems.map((item) => ({ status: preparationProgressStatus(item) }))}
            compact={true}
          />
          <div
            className="writing-reference-preparation-progress"
            data-testid="reference-preparation-progress"
            data-progress-phase={progress.phase}
            data-progress-percent={progress.percent}
            role="status"
            aria-live="polite"
            aria-busy={active}
          >
            <div className="writing-reference-preparation-progress-main">
              <strong>{progressSubstep(progress)}</strong>
              {currentNctId && currentDocumentLabel && (
                <span>{currentNctId} / {currentDocumentLabel}</span>
              )}
            </div>
            <div className="writing-reference-preparation-progress-meta">
              {progress.total > 0 && <span>{progressCountLabel(progress)}</span>}
              <b>{progress.percent}%</b>
            </div>
            <progress max="100" value={progress.percent} aria-label="公开 Protocol 准备进度" />
          </div>
        </>
      )}

      <div className="writing-reference-batch-actions">
        {!batchId && (
          <button className="primary-button" type="button" data-action="start-batch" onClick={startBatch} disabled={!snapshotId || !candidates.length || Boolean(action) || loading}>
            <Play size={14} /> {action === "start" ? "启动中" : "开始批量准备"}
          </button>
        )}
        <button type="button" data-action="refresh-batch" onClick={refreshBatch} disabled={Boolean(action) || loading}>
          <RefreshCw size={14} className={loading ? "spin" : ""} /> 刷新
        </button>
        {batchId && (
          <button type="button" data-action="retry-failed" onClick={retryFailed} disabled={!failedCount || active || Boolean(action) || loading}>
            <RotateCcw size={14} /> {action === "retry" ? "重试中" : "仅重试失败项"}
          </button>
        )}
        {batchId && batchStatus === "awaiting_stage_admission" && Number(batch?.deferred_item_count || 0) > 0 && (
          <button className="primary-button" type="button" data-action="advance-stage" onClick={advanceStage} disabled={Boolean(action) || loading} title="仅准入下一阶段延后原文；已完成项不会重复处理">
            <Play size={14} /> {action === "advance" ? "准入中" : `准入下一阶段（${batch.deferred_item_count}）`}
          </button>
        )}
        {active && <span>批次处理中，完成 {finishedCount}/{Number(batch?.item_count || rows.length)}</span>}
      </div>

      {message && <p className={`writing-reference-batch-message ${message.includes("失败") || message.includes("未启动") ? "danger" : ""}`} role="alert">{message}</p>}

      <div className="writing-reference-batch-table-wrap" data-testid="reference-batch-scope">
        <table className="writing-reference-batch-table">
          <thead><tr><th>研究</th><th>公开文件</th><th>下载</th><th>结构解析</th><th>内容校验</th><th>下一步</th></tr></thead>
          <tbody>
            {rows.map((item) => {
              const needsAttention = itemNeedsAttention(item);
              const validationIssue = item.item_status === "review_required" && Boolean(item.artifact_id);
              return (
                <tr
                  key={`${item.nct_id}:${item.document_id}`}
                  data-testid="reference-preparation-row"
                  data-nct-id={item.nct_id}
                  data-document-id={item.document_id}
                  data-item-status={item.item_status}
                  data-download-status={item.download_status}
                  data-parse-status={item.parse_status}
                  data-validation-status={item.validation_status}
                  className={needsAttention ? "requires-attention" : ""}
                >
                  <td><strong>{item.nct_id || "研究待确认"}</strong><small>{item.study_title || "标题待核验"}</small></td>
                  <td><strong>{item.document_label}</strong><small>{item.document_type}{item.document_date ? ` · ${item.document_date}` : ""}</small>{item.progress?.current_substep && item.item_status === "running" && <small data-testid="reference-preparation-item-progress">{item.progress.current_substep}{item.progress.total ? ` · ${progressCountLabel(item.progress)}` : ""}</small>}{item.error_detail && <em><AlertTriangle size={12} />{item.error_detail}</em>}</td>
                  <td><span className={`writing-reference-stage ${stageTone(item.download_status)}`} data-stage="download" data-status={item.download_status}>{stageLabel('download', item.download_status)}</span></td>
                  <td><span className={`writing-reference-stage ${stageTone(item.parse_status)}`} data-stage="parse" data-status={item.parse_status}>{stageLabel('parse', item.parse_status)}</span></td>
                  <td><span className={`writing-reference-stage ${stageTone(item.validation_status)}`} data-stage="validation" data-status={item.validation_status}>{stageLabel('validation', item.validation_status)}</span></td>
                  <td>
                    <div className="writing-reference-next-step-cell">
                      <span className="writing-reference-next-step">{!needsAttention && <CheckCircle2 size={13} />}{nextStepLabel(item)}</span>
                      {needsAttention && <button type="button" data-action="open-issue" onClick={() => onOpenIssue({ ...item, issue_kind: validationIssue ? "content_validation" : "single_document" })}>处理问题</button>}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && <div className="writing-reference-batch-empty">锁定篮子中没有可准备的公开 Protocol。</div>}
      </div>
    </section>
  );
}
