import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  FileSearch,
  FileText,
  RefreshCw,
  Search,
  Upload,
} from "lucide-react";
import { ReferencePreparationBatchPanel } from "./ReferencePreparationBatchPanel";
import { MixedOcrReviewPanel } from "./MixedOcrReviewPanel";
import { ReferenceTranslationBatchPanel } from "./ReferenceTranslationBatchPanel";
import { SharedPhase1CorpusPanel } from "./SharedPhase1CorpusPanel";
import {
  pollDurableMwJob,
  buildLocator,
  shouldClearLocator,
  shouldBlockStart,
  acknowledgeTriageDomain,
} from "../medical-writing/useDurableMwJob";
import {
  deriveTriagePresentation,
  mergeTriageSelections,
} from "./triagePresentationState.mjs";
import { alignedArtifactId } from "./referenceIdentity.mjs";

const viewDefinitions = [
  { id: "candidates", label: "候选研究" },
  { id: "documents", label: "文档与解析" },
  { id: "translations", label: "结构与译文确认" },
  { id: "approved", label: "已准入证据" },
  { id: "shared_phase1", label: "I期共享语料" },
];

function isPhase1(value) {
  const normalized = String(value || "").trim().toUpperCase().replace(/\s+/g, "").replaceAll("Ⅰ", "I");
  return ["1", "I", "1期", "I期", "PHASE1", "PHASEI", "1A", "1B", "IA", "IB", "I/II期", "I期/II期"].includes(normalized)
    || normalized.startsWith("PHASE1/")
    || normalized.startsWith("I期/")
    || normalized.startsWith("I/II");
}

const relevanceLabels = {
  pending_medical_relevance: ["待AI分类", "warning"],
  direct_competitor: ["直接竞品", "info"],
  indirect_reference: ["间接参照", "info"],
  excluded: ["已排除", "neutral"],
};

const triageClassificationLabels = {
  direct_competitor: "直接竞品",
  indirect_reference: "间接参照",
  excluded: "排除",
};

const triageDimensionLabels = {
  indication: "适应症",
  phase: "研究分期",
  population: "研究人群",
  intervention: "干预措施",
  comparator: "对照",
  endpoint: "研究终点",
  mechanism: "作用机制",
  route: "给药途径",
  design: "研究设计",
  document: "公开文档",
};

const translationStatusLabels = {
  pending_author_confirmation: ["待作者确认", "warning"],
  author_confirmed_admitted: ["作者已确认并准入", "success"],
  pending_medical_approval: ["历史状态：待迁移", "warning"],
  fidelity_blocked: ["忠实度校验未通过", "danger"],
  invalidated_source: ["来源已失效", "danger"],
  invalidated_extraction: ["结构解析已更新", "danger"],
  invalidated_review: ["作者确认已撤回", "danger"],
};

const reviewLabels = {
  approved: ["作者已确认", "success"],
  returned: ["已退回", "warning"],
  rejected: ["已拒绝", "danger"],
};

const historicalReviewLabels = {
  approved: ["历史审核已批准", "neutral"],
  returned: ["历史退回记录", "neutral"],
  rejected: ["历史拒绝记录", "neutral"],
};

const validationLabels = {
  confirmed: ["内容匹配", "success"],
  needs_review: ["需确认", "warning"],
  mismatch: ["发现不一致", "danger"],
  user_overridden: ["已确认沿用", "info"],
};

const extractionReviewLabels = {
  approved: ["结构已确认", "success"],
  returned: ["结构待修正", "warning"],
};

function ReferenceTag({ value, dictionary, fallback = "待处理" }) {
  const [label, tone] = dictionary[value] || [fallback, "neutral"];
  return <span className={`tag ${tone}`}>{label}</span>;
}

function requestKey(prefix) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}-${suffix}`;
}

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload;
  const error = new Error(typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`);
  error.status = response.status;
  throw error;
}

function currentDecision(workspace, nctId) {
  return (workspace?.decisions || [])
    .filter((item) => item.nct_id === nctId)
    .sort((left, right) => right.revision - left.revision)[0];
}

function currentReview(workspace, translation) {
  return (workspace?.medical_reviews || [])
    .filter((item) => item.translation_id === translation?.translation_id && item.translation_revision === translation?.revision)
    .sort((left, right) => right.revision - left.revision)[0];
}

function triageCandidateResults(runResponse) {
  return (runResponse?.run?.chunks || [])
    .filter((chunk) => chunk.status === "succeeded")
    .flatMap((chunk) => chunk.results || []);
}

function spanOptionLabel(span) {
  const source = String(span?.source_text || span?.section_heading || span?.ich_m11_anchor || "")
    .replace(/\s+/g, " ")
    .trim();
  const summary = source.length > 110 ? `${source.slice(0, 107)}...` : source;
  const pages = span?.source_fragments?.length > 1
    ? span.source_fragments.map((item) => `p${item.physical_page}`).join("+")
    : `p${span?.physical_page || "?"}`;
  return `${pages} · ${summary || "未识别到正文"}`;
}

export function WritingReferencePanel({
  projectId,
  selectedBriefIds = [],
  onSelectedBriefIdsChange = () => {},
  onUseEvidence = () => {},
  variant = "editor",
  snapshotId = "",
  lockedIndication = "",
  lockedPhase = "",
  journey = null,
  onJourneyChange = () => {},
  onTriagePipelineChange = () => {},
  embedded = false,
  compact = false,
  requestedView = "",
  requestedArtifactId = "",
  focusRequestKey = "",
  refreshSignal = 0,
}) {
  const authoringMode = variant === "authoring";
  const presentationClass = [
    "writing-reference-panel",
    authoringMode ? "authoring-mode" : "",
    embedded ? "is-embedded" : "",
    compact ? "is-compact" : "",
  ].filter(Boolean).join(" ");
  const activeProjectRef = useRef(projectId);
  const activeSnapshotRef = useRef(snapshotId);
  const refreshGenerationRef = useRef(0);
  const manualFileInputRef = useRef(null);
  const manualUploadKeyRef = useRef("");
  const aiTriageCreateKeyRef = useRef("");
  const legacyIssueToolsRef = useRef(null);
  const translationReviewRef = useRef(null);
  const [workspace, setWorkspace] = useState(null);
  const [activeView, setActiveView] = useState(authoringMode ? "candidates" : "approved");
  const [loading, setLoading] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [message, setMessage] = useState("");
  const [indication, setIndication] = useState(lockedIndication);
  const [phase, setPhase] = useState(lockedPhase || "PHASE2");
  const phase1SharedAvailable = authoringMode && isPhase1(
    lockedPhase || journey?.framing?.study_phase || phase,
  );
  const [selectedNctId, setSelectedNctId] = useState("");
  const [selectedArtifactId, setSelectedArtifactId] = useState("");
  const [selectedSpanId, setSelectedSpanId] = useState("");
  const [reason, setReason] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [showReviewWithdrawal, setShowReviewWithdrawal] = useState(false);
  const [structureReviewComment, setStructureReviewComment] = useState("");
  const [structureIssues, setStructureIssues] = useState("");
  const [validationOverrideReason, setValidationOverrideReason] = useState("");
  const [acknowledgedValidationCodes, setAcknowledgedValidationCodes] = useState([]);
  const [spans, setSpans] = useState([]);
  const [spanMeta, setSpanMeta] = useState({ extractionRevision: "", anchorCounts: {}, total: 0, filteredTotal: 0 });
  const [spanAnchorFilter, setSpanAnchorFilter] = useState("all");
  const [spanOffset, setSpanOffset] = useState(0);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [candidateStatus, setCandidateStatus] = useState("retained");
  const [candidatePage, setCandidatePage] = useState(1);
  const [triageReason, setTriageReason] = useState("");
  const [noSuitableCompetitorReason, setNoSuitableCompetitorReason] = useState("");
  const [aiTriageJobId, setAiTriageJobId] = useState("");
  const [aiTriageStatus, setAiTriageStatus] = useState("");
  const [aiTriageError, setAiTriageError] = useState("");
  const [aiTriageRun, setAiTriageRun] = useState(null);
  const [aiTriagePipeline, setAiTriagePipeline] = useState(null);
  const [aiTriageSelections, setAiTriageSelections] = useState({});
  const [aiTriageDetailsOpen, setAiTriageDetailsOpen] = useState(false);
  const [aiTriageRecovering, setAiTriageRecovering] = useState(false);
  const aiTriageSelectionRunRef = useRef("");
  const [alignmentStatus, setAlignmentStatus] = useState("no_conflicts");
  const [alignmentConflictCount, setAlignmentConflictCount] = useState(0);
  const [alignmentSummary, setAlignmentSummary] = useState("");
  const [manualFile, setManualFile] = useState(null);
  const [manualDocumentType, setManualDocumentType] = useState("protocol");
  const [manualDocumentDate, setManualDocumentDate] = useState("");
  const [legacyIssueOpen, setLegacyIssueOpen] = useState(false);

  const refreshWorkspace = async ({ preserveMessage = false } = {}) => {
    const requestedProjectId = projectId;
    const generation = ++refreshGenerationRef.current;
    setLoading(true);
    if (!preserveMessage) setMessage("");
    try {
      const query = authoringMode && snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
      const payload = await fetch(`/api/projects/${projectId}/medical-writing/references/workspace${query}`).then(readJson);
      if (generation !== refreshGenerationRef.current || activeProjectRef.current !== requestedProjectId) return;
      if (authoringMode && snapshotId && payload.snapshot?.snapshot_id !== snapshotId) {
        throw new Error("语料工作区返回了非当前建项快照，请刷新后重试");
      }
      setWorkspace(payload);
      if (payload.snapshot?.request) {
        setIndication(payload.snapshot.request.indication || "");
        setPhase(payload.snapshot.request.phases?.[0] || "PHASE2");
      }
      const candidateIds = (payload.snapshot?.candidates || []).map((item) => item.nct_id);
      setSelectedNctId((current) => candidateIds.includes(current) ? current : candidateIds[0] || "");
      const artifactIds = (payload.artifacts || []).map((item) => item.artifact_id);
      setSelectedArtifactId((current) => artifactIds.includes(current) ? current : artifactIds[0] || "");
    } catch (error) {
      if (generation === refreshGenerationRef.current && activeProjectRef.current === requestedProjectId) {
        setMessage(`竞品方案参照读取失败：${error.message}`);
      }
    } finally {
      if (generation === refreshGenerationRef.current && activeProjectRef.current === requestedProjectId) setLoading(false);
    }
  };

  // Batch medical-review/admission changes the evidence rows in the parent
  // workspace but may leave the journey revision unchanged. Reconcile the
  // corpus gate explicitly before handing the journey back to the authoring
  // surface; otherwise a successful batch confirmation remains displayed as
  // an old, missing-gate state until an unrelated reference action occurs.
  const refreshAuthoringAfterBatchSettled = async () => {
    await refreshWorkspace({ preserveMessage: true });
    if (!authoringMode || !projectId) return;
    const recalculated = await fetch(
      `/api/projects/${projectId}/medical-writing/authoring-journey/corpus-gate/recalculate`,
      { method: "POST" },
    ).then(readJson);
    const authoritative = await fetch(
      `/api/projects/${projectId}/medical-writing/authoring-journey?allow_missing=true`,
    ).then(readJson);
    onJourneyChange(authoritative.available === false ? recalculated : authoritative);
  };

  const adoptTriageRun = (payload) => {
    const run = payload?.run;
    if (!run || !activeSnapshotRef.current || run.snapshot_id !== activeSnapshotRef.current) {
      throw new Error("AI分诊结果不属于当前建项快照，已阻止载入");
    }
    setAiTriageRun(payload);
    // A terminal durable-job state is more specific than the business run
    // when a parent pipeline times out before the run can persist its own end state.
    setAiTriageStatus((current) => (
      ["failed", "cancelled"].includes(current) ? current : run.status || current
    ));
    setAiTriageError("");
    const isNewRun = aiTriageSelectionRunRef.current !== run.run_id;
    const latestResults = triageCandidateResults(payload);
    const reconfirmationSelections = payload?.reconfirmation?.required
      ? payload.reconfirmation.final_classifications || {}
      : null;
    setAiTriageSelections((current) => (
      reconfirmationSelections
        ? { ...reconfirmationSelections }
        : mergeTriageSelections(current, latestResults, { reset: isNewRun })
    ));
    if (isNewRun) {
      setAiTriageDetailsOpen(false);
      aiTriageSelectionRunRef.current = run.run_id;
    }
    return payload;
  };

  const recoverLatestTriageRun = async ({ silentNotFound = true, background = false } = {}) => {
    if (!authoringMode || !projectId || !snapshotId) return null;
    const requestedProjectId = projectId;
    const requestedSnapshotId = snapshotId;
    if (!background) setAiTriageRecovering(true);
    try {
      const pipelineRequest = fetch(
        `/api/projects/${projectId}/medical-writing/research-pipeline/status`,
      ).catch(() => null);
      const response = await fetch(
        `/api/projects/${projectId}/medical-writing/authoring-journey/competitor-triage/latest?snapshot_id=${encodeURIComponent(snapshotId)}`,
      );
      const pipelineResponse = await pipelineRequest;
      if (pipelineResponse?.ok) {
        const pipelinePayload = await pipelineResponse.json().catch(() => ({}));
        if (
          activeProjectRef.current === requestedProjectId
          && activeSnapshotRef.current === requestedSnapshotId
        ) {
          setAiTriagePipeline(pipelinePayload?.pipeline || null);
          // Propagate the latest parent research-pipeline payload to the outer
          // authoring page so its compact toolbar and banner converge to the
          // same terminal state the drawer already observes.
          onTriagePipelineChange(pipelinePayload?.pipeline || null);
        }
      } else if (
        pipelineResponse?.status === 404
        && activeProjectRef.current === requestedProjectId
        && activeSnapshotRef.current === requestedSnapshotId
      ) {
        setAiTriagePipeline(null);
        onTriagePipelineChange(null);
      }
      if (response.status === 404 && silentNotFound) return null;
      const payload = await readJson(response);
      if (
        activeProjectRef.current !== requestedProjectId
        || activeSnapshotRef.current !== requestedSnapshotId
      ) return null;
      return adoptTriageRun(payload);
    } catch (error) {
      setAiTriageError(`AI分诊结果恢复失败：${error.message}`);
      return null;
    } finally {
      if (
        activeProjectRef.current === requestedProjectId
        && activeSnapshotRef.current === requestedSnapshotId
      && !background) setAiTriageRecovering(false);
    }
  };

  useEffect(() => {
    activeProjectRef.current = projectId;
    activeSnapshotRef.current = snapshotId;
    refreshGenerationRef.current += 1;
    setWorkspace(null);
    setSelectedNctId("");
    setSelectedArtifactId("");
    setSelectedSpanId("");
    setSpans([]);
    setSpanMeta({ extractionRevision: "", anchorCounts: {}, total: 0, filteredTotal: 0 });
    setSpanAnchorFilter("all");
    setSpanOffset(0);
    setValidationOverrideReason("");
    setAcknowledgedValidationCodes([]);
    setStructureReviewComment("");
    setStructureIssues("");
    setCandidateQuery("");
    setCandidateStatus("retained");
    setCandidatePage(1);
    setAiTriageJobId("");
    setAiTriageStatus("");
    setAiTriageError("");
    setAiTriageRun(null);
    setAiTriagePipeline(null);
    setAiTriageSelections({});
    setAiTriageRecovering(false);
    aiTriageSelectionRunRef.current = "";
    setManualFile(null);
    setManualDocumentType("protocol");
    setManualDocumentDate("");
    setLegacyIssueOpen(false);
    manualUploadKeyRef.current = "";
    if (manualFileInputRef.current) manualFileInputRef.current.value = "";
    refreshWorkspace();
  }, [projectId, snapshotId]);

  useEffect(() => {
    setIndication(lockedIndication);
    setPhase(lockedPhase || "PHASE2");
  }, [lockedIndication, lockedPhase]);

  useEffect(() => {
    if (refreshSignal > 0) {
      refreshWorkspace();
      recoverLatestTriageRun({ silentNotFound: true, background: true });
    }
  // refreshSignal is an external open-transition trigger; both views use current props.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  useEffect(() => {
    if (!focusRequestKey) return;
    if (viewDefinitions.some((view) => view.id === requestedView)) {
      setActiveView(requestedView);
    }
    if (requestedArtifactId) {
      setSelectedArtifactId(requestedArtifactId);
    }
    globalThis.requestAnimationFrame?.(() => {
      translationReviewRef.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    });
  }, [focusRequestKey, requestedArtifactId, requestedView]);

  useEffect(() => {
    if (!selectedArtifactId) {
      setSpans([]);
      setSpanMeta({ extractionRevision: "", anchorCounts: {}, total: 0, filteredTotal: 0 });
      setSelectedSpanId("");
      return;
    }
    const controller = new AbortController();
    const anchorQuery = spanAnchorFilter === "all"
      ? ""
      : `&ich_m11_anchor=${encodeURIComponent(spanAnchorFilter)}`;
    fetch(`/api/projects/${projectId}/medical-writing/references/documents/${selectedArtifactId}/spans?limit=500&offset=${spanOffset}${anchorQuery}`, { signal: controller.signal })
      .then(readJson)
      .then((payload) => {
        setSpans(payload.items || []);
        setSpanMeta({
          extractionRevision: payload.extraction_revision || "",
          anchorCounts: payload.anchor_counts || {},
          total: Object.values(payload.anchor_counts || {}).reduce((sum, value) => sum + Number(value || 0), 0),
          filteredTotal: payload.total || 0,
        });
        setSelectedSpanId((current) => (payload.items || []).some((item) => item.span_id === current) ? current : payload.items?.[0]?.span_id || "");
      })
      .catch((error) => {
        if (error.name !== "AbortError") setMessage(`结构化片段读取失败：${error.message}`);
      });
    return () => controller.abort();
  }, [
    projectId,
    selectedArtifactId,
    spanAnchorFilter,
    spanOffset,
    workspace?.document_validations?.find((item) => item.artifact_id === selectedArtifactId)?.revision,
    workspace?.artifact_span_counts?.[selectedArtifactId],
  ]);

  useEffect(() => {
    setSpanAnchorFilter("all");
    setSpanOffset(0);
  }, [selectedArtifactId]);

  const snapshot = workspace?.snapshot;
  const candidates = snapshot?.candidates || [];
  const aiTriageResults = useMemo(
    () => triageCandidateResults(aiTriageRun),
    [aiTriageRun],
  );
  const triageReconfirmationRequired = Boolean(
    aiTriageRun?.reconfirmation?.required,
  );
  const aiTriagePresentation = useMemo(() => deriveTriagePresentation({
    run: aiTriageRun?.run,
    reconfirmationRequired: triageReconfirmationRequired,
    jobStatus: aiTriageStatus,
    hasActiveJob: Boolean(aiTriageJobId) && ["starting", "queued", "running", "resuming"].includes(aiTriageStatus),
    pipeline: aiTriagePipeline,
    snapshotId,
    candidateCount: candidates.length,
  }), [aiTriageJobId, aiTriagePipeline, aiTriageRun, aiTriageStatus, candidates.length, snapshotId, triageReconfirmationRequired]);
  const aiTriageCoverageComplete = Boolean(candidates.length)
    && aiTriageResults.length === candidates.length
    && candidates.every((candidate) => aiTriageSelections[candidate.nct_id]);
  const aiTriageRetainedCount = candidates.filter((candidate) => (
    ["direct_competitor", "indirect_reference"].includes(
      aiTriageSelections[candidate.nct_id],
    )
  )).length;
  const aiTriageAllExcluded = aiTriageCoverageComplete && aiTriageRetainedCount === 0;
  const candidateDisplayStatus = useCallback((candidate) => (
    aiTriageRun?.run?.status === "review_ready" || triageReconfirmationRequired
      ? aiTriageSelections[candidate.nct_id] || candidate.relevance_status
      : currentDecision(workspace, candidate.nct_id)?.relevance_status || candidate.relevance_status
  ), [aiTriageRun?.run?.status, aiTriageSelections, triageReconfirmationRequired, workspace]);
  const candidatePageSize = 50;
  const filteredCandidates = useMemo(() => {
    const query = candidateQuery.trim().toLowerCase();
    return candidates.filter((candidate) => {
      const status = candidateDisplayStatus(candidate);
      if (
        candidateStatus === "retained"
          ? !["direct_competitor", "indirect_reference"].includes(status)
          : candidateStatus !== "all" && status !== candidateStatus
      ) return false;
      if (!query) return true;
      return [candidate.nct_id, candidate.brief_title, candidate.official_title, candidate.lead_sponsor]
        .some((value) => String(value || "").toLowerCase().includes(query));
    });
  }, [
    candidateDisplayStatus,
    candidates,
    candidateQuery,
    candidateStatus,
  ]);
  const candidatePageCount = Math.max(1, Math.ceil(filteredCandidates.length / candidatePageSize));
  const visibleCandidates = filteredCandidates.slice(
    (candidatePage - 1) * candidatePageSize,
    candidatePage * candidatePageSize,
  );
  const selectedCandidate = filteredCandidates.find(
    (item) => item.nct_id === selectedNctId,
  ) || filteredCandidates[0] || candidates.find(
    (item) => item.nct_id === selectedNctId,
  ) || candidates[0];
  const selectedCandidateDecision = currentDecision(workspace, selectedCandidate?.nct_id);
  const triageFinalized = authoringMode
    && journey?.corpus_triage?.status === "finalized"
    && journey?.corpus_triage?.snapshot_id === snapshotId;
  const triageReviewLocked = triageFinalized || (
    authoringMode
      && aiTriageRun?.run?.status === "confirmed"
      && !triageReconfirmationRequired
  );
  const retainedCandidateIds = journey?.corpus_triage?.retained_candidate_ids || [];
  const retainedCandidateIdSet = useMemo(
    () => new Set(retainedCandidateIds),
    [retainedCandidateIds],
  );
  const documentCandidates = triageFinalized
    ? candidates.filter((item) => retainedCandidateIdSet.has(item.nct_id))
    : candidates;
  const selectedDocumentCandidate = documentCandidates.find((item) => item.nct_id === selectedNctId)
    || documentCandidates[0];
  const selectedDocumentCandidateDecision = currentDecision(workspace, selectedDocumentCandidate?.nct_id);
  const selectedCandidateCanIngest = ["direct_competitor", "indirect_reference"].includes(
    selectedDocumentCandidateDecision?.relevance_status,
  );
  const selectedArtifact = (workspace?.artifacts || []).find((item) => item.artifact_id === selectedArtifactId);
  const selectedValidation = (workspace?.document_validations || []).find((item) => item.artifact_id === selectedArtifactId);
  const validationWarnings = (selectedValidation?.checks || []).filter((check) => ["warning", "mismatch"].includes(check.outcome));
  const selectedSpan = spans.find((item) => item.span_id === selectedSpanId) || spans[0];
  const selectedExtractionRevision = spanMeta.extractionRevision || selectedSpan?.extraction_revision || "";
  const selectedExtractionAnchors = Object.keys(spanMeta.anchorCounts)
    .filter((item) => item && item !== "unmapped")
    .sort();
  const selectedExtractionReview = (workspace?.extraction_reviews || [])
    .filter((item) => item.artifact_id === selectedArtifactId && item.extraction_revision === selectedExtractionRevision)
    .sort((left, right) => right.revision - left.revision)[0];
  const selectedTranslation = (workspace?.translations || []).find((item) => item.span_id === selectedSpan?.span_id);
  const selectedReview = currentReview(workspace, selectedTranslation);
  const selectedBrief = (workspace?.evidence_brief_history || []).find(
    (item) => item.translation_id === selectedTranslation?.translation_id
      && item.translation_revision === selectedTranslation?.revision
      && item.status === "approved_current",
  );
  const selectedTranslationInvalidated = Boolean(
    selectedTranslation?.status?.startsWith("invalidated_"),
  );
  const selectedReviewIsCurrentConfirmation = Boolean(
    selectedReview?.decision === "approved"
      && selectedReview?.decision_type === "author_confirmation"
      && selectedReview?.admission_status === "admitted"
      && selectedTranslation?.status === "author_confirmed_admitted"
      && selectedBrief,
  );
  const legacyApprovedAwaitingAuthorConfirmation = Boolean(
    selectedReview?.decision === "approved"
      && !selectedBrief
      && !selectedTranslationInvalidated
      && (
        selectedReview?.decision_type !== "author_confirmation"
        || selectedReview?.admission_status !== "admitted"
      ),
  );
  const currentBriefs = workspace?.approved_evidence_briefs || [];
  const currentBriefIdSet = new Set(currentBriefs.map((item) => item.brief_id));
  const displayedBriefHistory = [...(workspace?.evidence_brief_history || [])].sort((left, right) => {
    const currentDelta = Number(currentBriefIdSet.has(right.brief_id)) - Number(currentBriefIdSet.has(left.brief_id));
    if (currentDelta) return currentDelta;
    return String(right.recorded_at || right.created_at || "").localeCompare(
      String(left.recorded_at || left.created_at || ""),
    );
  });
  const alignmentSubmitDisabledReason = !journey?.picos_sha256
    ? "当前PICOS尚未形成可核对版本"
    : alignmentSummary.trim().length < 10
      ? "请填写至少10个字的核对与处置说明"
      : alignmentStatus === "resolved" && Number(alignmentConflictCount) < 1
        ? "请填写已处置冲突数"
        : busyAction
          ? "前一项操作尚未完成"
          : "";
  const artifactBySourceDocument = useMemo(
    () => new Map((workspace?.artifacts || []).map((item) => [item.source_document_id, item])),
    [workspace?.artifacts],
  );
  const selectedManualArtifacts = (workspace?.artifacts || []).filter(
    (item) => item.nct_id === selectedDocumentCandidate?.nct_id && item.source_status === "user_uploaded",
  );
  const selectCandidateForReview = (nctId) => {
    setSelectedNctId(nctId);
    setSelectedArtifactId((currentArtifactId) => alignedArtifactId(
      workspace?.artifacts,
      currentArtifactId,
      nctId,
    ));
  };

  useEffect(() => {
    setValidationOverrideReason("");
    setAcknowledgedValidationCodes([]);
    setStructureReviewComment("");
    setStructureIssues("");
  }, [selectedArtifactId, selectedValidation?.revision, selectedExtractionReview?.revision]);

  useEffect(() => {
    setShowReviewWithdrawal(false);
    setReviewComment("");
  }, [selectedSpan?.span_id, selectedTranslation?.revision]);

  useEffect(() => {
    setCandidatePage((current) => Math.min(current, candidatePageCount));
  }, [candidatePageCount]);

  useEffect(() => {
    if (activeView !== "documents" || !documentCandidates.length) return;
    if (!documentCandidates.some((item) => item.nct_id === selectedNctId)) {
      setSelectedNctId(documentCandidates[0].nct_id);
    }
  }, [activeView, documentCandidates, selectedNctId]);

  const runAction = async (key, action, successMessage) => {
    setBusyAction(key);
    setMessage("");
    try {
      await action();
      await refreshWorkspace({ preserveMessage: true });
      if (authoringMode) {
        const recalculated = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/corpus-gate/recalculate`, {
          method: "POST",
        }).then(readJson);
        // The recalculation endpoint returns the persisted journey model, while
        // the read endpoint adds derived hashes (notably picos_sha256) that the
        // PICOS alignment contract needs.  Keep the parent state on that
        // authoritative read shape after every reference action; otherwise a
        // successful refresh silently makes the visible alignment button look
        // as if PICOS had never been completed.
        const authoritative = await fetch(
          `/api/projects/${projectId}/medical-writing/authoring-journey?allow_missing=true`,
        ).then(readJson);
        onJourneyChange(authoritative.available === false ? recalculated : authoritative);
      }
      setMessage(successMessage);
    } catch (error) {
      setMessage(`操作未完成：${error.message}`);
    } finally {
      setBusyAction("");
    }
  };

  const submitSearch = () => runAction(
    "search",
    () => fetch(`/api/projects/${projectId}/medical-writing/references/search-snapshots`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        search: { indication: indication.trim(), phases: phase ? [phase] : [], study_type: "INTERVENTIONAL", page_size: 100 },
        actor: "medical_manager",
        idempotency_key: requestKey("reference-search"),
      }),
    }).then(readJson),
    "公开研究检索已完成；候选研究仍需医学分类。",
  );

  const relatedDecisionIds = (workspace?.decisions || [])
    .filter((item) => ["direct_competitor", "indirect_reference"].includes(item.relevance_status))
    .map((item) => item.nct_id);

  const finalizeTriage = () => runAction(
    "finalize-triage",
    async () => {
      const updated = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/corpus-triage/finalize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: journey.revision,
          snapshot_id: snapshotId,
          retained_candidate_ids: relatedDecisionIds,
          reason: triageReason.trim(),
          actor: "medical_manager",
          idempotency_key: requestKey("reference-triage-finalize"),
        }),
      }).then(readJson);
      onJourneyChange(updated);
    },
    `已锁定${relatedDecisionIds.length}项直接竞品/间接参照进入深度语料处理。`,
  );

  const startAiTriage = async () => {
    if (
      (shouldBlockStart(aiTriageStatus) && aiTriageRun?.run?.status !== "stale")
      || busyAction
    ) return; // dedupe
    setAiTriageError("");
    setAiTriageStatus("starting");
    const storageKey = `mw_triage_job_${projectId}`;
    if (!aiTriageCreateKeyRef.current) {
      aiTriageCreateKeyRef.current = requestKey("competitor-triage");
    }
    try {
      const resp = await fetch(
        `/api/projects/${projectId}/medical-writing/authoring-journey/competitor-triage`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            snapshot_id: snapshotId,
            expected_journey_revision: journey?.revision || 0,
            actor: "medical_manager",
            idempotency_key: aiTriageCreateKeyRef.current,
          }),
        },
      );
      const body = await readJson(resp);
      if (!resp.ok) {
        aiTriageCreateKeyRef.current = "";
        setAiTriageError(`AI分诊启动失败：${typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body)}`);
        setAiTriageStatus("");
        return;
      }
      const jobId = body.job_id;
      const runId = body.run_id || "";
      if (!jobId) {
        setAiTriageError("AI分诊启动失败：后端未返回作业标识。");
        setAiTriageStatus("");
        return;
      }
      setAiTriageJobId(jobId);
      setAiTriageStatus("queued");
      const locator = buildLocator({
        projectId,
        jobId,
        operation: "competitor_triage",
        jobType: "competitor_triage",
        runId,
        snapshotId,
      });
      try { localStorage.setItem(storageKey, JSON.stringify(locator)); } catch { /* ignore */ }
      const { status, result, error, transportResultOk } = await pollDurableMwJob(projectId, jobId, {
        intervalMs: 2000, maxLoops: 150,
        onUpdate: (st) => setAiTriageStatus(st.status),
      });
      setAiTriageStatus(status);
      const ack = acknowledgeTriageDomain({
        status,
        resultBody: transportResultOk ? result : null,
        locator,
        expectedRunId: runId,
        expectedSnapshotId: snapshotId,
      });
      if (ack.outcome === "success") {
        setMessage("AI分诊已完成。请整体浏览AI建议，必要时展开修改，再一次确认并锁定。");
        await recoverLatestTriageRun({ silentNotFound: false });
      } else if (ack.outcome === "terminal_failure") {
        setAiTriageError(status === "cancelled"
          ? "AI分诊已取消。"
          : `AI分诊失败：${error || "请检查生产AI配置后重试。"}`);
        await recoverLatestTriageRun();
      } else {
        setAiTriageError(
          ack.outcome === "reconcile_failed"
            ? "AI分诊已结束，但结果核对失败。定位器已保留，请重试核对。"
            : "AI分诊仍在后台进行，请稍后查看或刷新页面恢复。",
        );
      }
      if (ack.shouldClear) {
        try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
        setAiTriageJobId("");
        aiTriageCreateKeyRef.current = "";
      }
    } catch (err) {
      setAiTriageError(`AI分诊请求异常：${err.message || err}`);
      setAiTriageStatus("");
    }
  };

  const cancelAiTriage = async () => {
    if (!aiTriageJobId) return;
    try {
      await fetch(`/api/projects/${projectId}/medical-writing/jobs/${aiTriageJobId}/cancel`, { method: "POST" });
      // Do not clear locator without domain recon (no cancelled override).
      const { status, result, transportResultOk } = await pollDurableMwJob(projectId, aiTriageJobId, {
        intervalMs: 1000, maxLoops: 30, onUpdate: (st) => setAiTriageStatus(st.status),
      });
      setAiTriageStatus(status);
      let locator = null;
      try { locator = JSON.parse(localStorage.getItem(`mw_triage_job_${projectId}`) || "null"); } catch { /* ignore */ }
      const ack = acknowledgeTriageDomain({
        status,
        resultBody: transportResultOk ? result : null,
        locator,
      });
      setAiTriageError(
        ack.domainReconciled
          ? "AI分诊已取消。"
          : "取消请求已发送，结果核对未完成。定位器已保留，请重试核对。",
      );
      if (ack.shouldClear) {
        try { localStorage.removeItem(`mw_triage_job_${projectId}`); } catch { /* ignore */ }
        setAiTriageJobId("");
      }
    } catch { /* best-effort */ }
  };

  const retryAiTriageRun = async () => {
    const run = aiTriageRun?.run;
    if (!run) {
      setAiTriageError("未找到当前分诊运行，无法安全重试；请刷新当前候选结果后再启动分诊。");
      return;
    }
    if (run.status === "stale") {
      setAiTriageRun(null);
      setAiTriageSelections({});
      aiTriageSelectionRunRef.current = "";
      await startAiTriage();
      return;
    }
    if (busyAction) return;
    setBusyAction("retry-ai-triage");
    setAiTriageError("");
    setAiTriageStatus("starting");
    const storageKey = `mw_triage_job_${projectId}`;
    try {
      const incompleteChunkIds = (run.chunks || [])
        .filter((chunk) => chunk.status !== "succeeded")
        .map((chunk) => chunk.chunk_id);
      const retryKey = requestKey("competitor-triage-retry");
      const recoverParentPipeline = aiTriagePipeline?.stage === "failed"
        && aiTriagePipeline?.triage_run_id === run.run_id
        && (!aiTriagePipeline?.snapshot_id || aiTriagePipeline.snapshot_id === snapshotId);
      const body = await fetch(
        recoverParentPipeline
          ? `/api/projects/${projectId}/medical-writing/research-pipeline/retry-triage`
          : `/api/projects/${projectId}/medical-writing/authoring-journey/competitor-triage/${run.run_id}/retry`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(recoverParentPipeline ? {
            actor: "medical_manager",
            idempotency_key: retryKey,
            expected_pipeline_id: aiTriagePipeline.pipeline_id,
            expected_triage_run_id: run.run_id,
          } : {
            actor: "medical_manager",
            idempotency_key: retryKey,
            chunk_ids: incompleteChunkIds,
          }),
        },
      ).then(readJson);
      const retryJobId = body.triage_job_id || body.job_id;
      if (!retryJobId) throw new Error("后端未返回重试作业标识");
      if (body.pipeline) setAiTriagePipeline(body.pipeline);
      const locator = buildLocator({
        projectId,
        jobId: retryJobId,
        operation: "competitor_triage",
        jobType: "competitor_triage",
        runId: body.run_id || run.run_id,
        snapshotId,
      });
      try { localStorage.setItem(storageKey, JSON.stringify(locator)); } catch { /* ignore */ }
      setAiTriageJobId(retryJobId);
      setAiTriageStatus("queued");
      await recoverLatestTriageRun({ silentNotFound: false, background: true });
      const polled = await pollDurableMwJob(projectId, retryJobId, {
        intervalMs: 2000,
        maxLoops: 150,
        onUpdate: (state) => setAiTriageStatus(state.status),
      });
      const ack = acknowledgeTriageDomain({
        status: polled.status,
        resultBody: polled.transportResultOk ? polled.result : null,
        locator,
        expectedRunId: locator.run_id,
        expectedSnapshotId: snapshotId,
      });
      if (ack.outcome === "success") {
        setMessage("AI分诊重试已完成，请整体浏览后一次确认并锁定。");
      } else if (ack.outcome === "terminal_failure") {
        setAiTriageError(`AI分诊重试失败：${polled.error || "请查看失败分块后再次重试。"}`);
      } else {
        setAiTriageError("AI分诊重试已结束，但结果尚未完成核对，请刷新状态。");
      }
      await recoverLatestTriageRun({ silentNotFound: false });
      if (ack.shouldClear) {
        try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
        setAiTriageJobId("");
      }
    } catch (error) {
      setAiTriageStatus(run.status);
      setAiTriageError(`AI分诊重试未完成：${error.message}`);
    } finally {
      setBusyAction("");
    }
  };

  const confirmAiTriageRun = async () => {
    const run = aiTriageRun?.run;
    if (
      !run
      || (!triageReconfirmationRequired && run.status !== "review_ready")
      || !aiTriageCoverageComplete
    ) return;
    const allCandidateIds = candidates.map((candidate) => candidate.nct_id);
    const retainedNctIds = allCandidateIds.filter((nctId) => (
      ["direct_competitor", "indirect_reference"].includes(aiTriageSelections[nctId])
    ));
    const excludedNctIds = allCandidateIds.filter((nctId) => aiTriageSelections[nctId] === "excluded");
    if (retainedNctIds.length + excludedNctIds.length !== allCandidateIds.length) {
      setAiTriageError("仍有候选研究未完成分类，无法确认。");
      return;
    }
    const finalClassifications = Object.fromEntries(
      allCandidateIds.map((nctId) => [nctId, aiTriageSelections[nctId]]),
    );
    setBusyAction("confirm-ai-triage");
    setAiTriageError("");
    try {
      const endpoint = triageReconfirmationRequired ? "reconfirm" : "confirm";
      const basePayload = {
        retained_nct_ids: retainedNctIds,
        excluded_nct_ids: excludedNctIds,
        final_classifications: finalClassifications,
        no_suitable_competitor_reason: retainedNctIds.length
          ? ""
          : noSuitableCompetitorReason.trim(),
        actor: "medical_manager",
        reason: triageReason.trim() || (
          triageReconfirmationRequired
            ? "医学经理已按当前研究信息重新核对既有竞品篮子。"
            : "医学经理已整体核对AI分诊结果并确认锁定当前竞品篮子。"
        ),
        idempotency_key: requestKey(
          triageReconfirmationRequired
            ? "competitor-triage-reconfirm"
            : "competitor-triage-confirm",
        ),
        expected_journey_revision: journey?.revision || 0,
      };
      const confirmation = await fetch(
        `/api/projects/${projectId}/medical-writing/authoring-journey/competitor-triage/${run.run_id}/${endpoint}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...basePayload,
            ...(triageReconfirmationRequired
              ? { source_confirmation_id: aiTriageRun.reconfirmation.source_confirmation_id }
              : { expected_run_revision: run.canonical_input_hash }),
          }),
        },
      ).then(readJson);
      await refreshWorkspace({ preserveMessage: true });
      const latestJourney = await fetch(
        `/api/projects/${projectId}/medical-writing/authoring-journey`,
      ).then(readJson);
      onJourneyChange(latestJourney);
      await recoverLatestTriageRun({ silentNotFound: false });
      const pipeline = confirmation?.pipeline || null;
      const pipelineStage = String(pipeline?.stage || "").trim();
      const pipelineAdvanced = confirmation?.pipeline_advanced === true;
      if (
        triageReconfirmationRequired
        && ["failed", "deferred_until_picos"].includes(
          confirmation?.projection_status,
        )
      ) {
        setMessage("分类复核记录已保存，但尚未同步到写作旅程；请点击“重试同步”，无需再次审核。");
      } else if (triageReconfirmationRequired) {
        setMessage(`已按当前研究信息确认${allCandidateIds.length}项分类，并沿用原检索快照；未重复运行AI或原文处理。`);
      } else if (!retainedNctIds.length) {
        setMessage("已确认本次公开检索结果中无合适竞品；可继续手工上传方案或使用通用语料库。");
      } else if (pipelineAdvanced) {
        setMessage(`已按本次审核结果确认并锁定全部${allCandidateIds.length}项候选研究。研究流水线已开始继续处理原文。`);
      } else if (pipelineStage) {
        setMessage(
          `已按本次审核结果确认并锁定全部${allCandidateIds.length}项候选研究；研究流水线当前为“${pipelineStage}”，尚未确认进入原文处理。请刷新状态后再继续。`,
        );
      } else {
        const pipelineError = String(confirmation?.pipeline_error || "").trim();
        setMessage(
          pipelineError
            ? `已确认并锁定全部${allCandidateIds.length}项候选研究，但原文处理未启动：${pipelineError}。系统未将其显示为已开始，请先处理该问题后重试。`
            : `已确认并锁定全部${allCandidateIds.length}项候选研究，但研究流水线尚未建立；系统未开始下载原文。请刷新检索状态后重试。`,
        );
      }
    } catch (error) {
      setAiTriageError(`确认并锁定未完成：${error.message}`);
    } finally {
      setBusyAction("");
    }
  };

  const retryAiTriageProjection = async () => {
    const run = aiTriageRun?.run;
    if (!run || run.status !== "projection_pending") return;
    setBusyAction("retry-ai-triage-projection");
    setAiTriageError("");
    try {
      await fetch(
        `/api/projects/${projectId}/medical-writing/authoring-journey/competitor-triage/${run.run_id}/projection-retry`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            actor: "medical_manager",
            idempotency_key: requestKey("competitor-triage-projection-retry"),
          }),
        },
      ).then(readJson);
      await refreshWorkspace({ preserveMessage: true });
      const latestJourney = await fetch(
        `/api/projects/${projectId}/medical-writing/authoring-journey`,
      ).then(readJson);
      onJourneyChange(latestJourney);
      await recoverLatestTriageRun({ silentNotFound: false });
      setMessage("已恢复确认结果与写作旅程的同步，无需再次审核。");
    } catch (error) {
      setAiTriageError(`确认结果同步仍未完成：${error.message}`);
    } finally {
      setBusyAction("");
    }
  };

  // Resume a durable job when its locator exists; otherwise recover the
  // latest run strictly within the current project snapshot.
  useEffect(() => {
    if (!authoringMode || !projectId || !snapshotId) return undefined;
    let cancelled = false;
    try {
      const storageKey = `mw_triage_job_${projectId}`;
      const stored = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (stored?.job_id && stored.snapshot_id === snapshotId && !aiTriageJobId) {
        setAiTriageJobId(stored.job_id);
        setAiTriageStatus("resuming");
        pollDurableMwJob(projectId, stored.job_id, {
          intervalMs: 2000, maxLoops: 150, onUpdate: (st) => setAiTriageStatus(st.status),
        }).then(async ({ status, result, transportResultOk, error }) => {
          if (cancelled) return;
          setAiTriageStatus(status);
          const ack = acknowledgeTriageDomain({
            status,
            resultBody: transportResultOk ? result : null,
            locator: stored,
            expectedRunId: stored.run_id || "",
            expectedSnapshotId: stored.snapshot_id || "",
          });
          if (ack.outcome === "success") {
            setMessage("AI分诊已完成。请整体浏览AI建议，必要时展开修改，再一次确认并锁定。");
          } else if (ack.outcome === "terminal_failure") {
            setAiTriageError(status === "cancelled" ? "AI分诊已取消。" : `AI分诊失败：${error || ""}`);
          } else if (ack.outcome === "reconcile_failed") {
            setAiTriageError("AI分诊已结束，但结果核对失败。定位器已保留。");
          }
          await recoverLatestTriageRun();
          if (ack.shouldClear) {
            try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
            setAiTriageJobId("");
          }
        });
      } else {
        if (stored?.job_id && stored.snapshot_id !== snapshotId) {
          try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
        }
        recoverLatestTriageRun();
      }
    } catch { /* ignore */ }
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, snapshotId]);

  // The durable job poll owns its own lifecycle. This lightweight business-state
  // refresh keeps an already-restored drawer current and lets a parent-pipeline
  // terminal state surface without manufacturing a local timeout.
  useEffect(() => {
    const runStatus = aiTriageRun?.run?.status || "";
    const pipelineStage = aiTriagePipeline?.stage || "";
    const shouldPoll = authoringMode
      && projectId
      && snapshotId
      && aiTriagePresentation.kind !== "failed"
      && aiTriagePresentation.kind !== "stale"
      && (
        ["starting", "queued", "running", "resuming"].includes(aiTriageStatus)
        || ["queued", "running"].includes(runStatus)
        || ["queued", "triaging"].includes(pipelineStage)
      );
    if (!shouldPoll) return undefined;

    let cancelled = false;
    let timer = null;
    const refresh = async () => {
      await recoverLatestTriageRun({ silentNotFound: true, background: true });
      if (!cancelled) timer = globalThis.setTimeout(refresh, 5000);
    };
    refresh();
    return () => {
      cancelled = true;
      if (timer) globalThis.clearTimeout(timer);
    };
  // recoverLatestTriageRun is render-local; status values are the intended trigger surface.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authoringMode, projectId, snapshotId, aiTriagePresentation.kind, aiTriageStatus, aiTriageRun?.run?.status, aiTriagePipeline?.stage]);

  const recordPicosAlignment = () => runAction(
    "record-picos-alignment",
    async () => {
      const currentBriefIds = (workspace?.approved_evidence_briefs || []).map((item) => item.brief_id);
      const updated = await fetch(`/api/projects/${projectId}/medical-writing/authoring-journey/picos-corpus-alignment`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: journey.revision,
          source_picos_sha256: journey.picos_sha256,
          status: alignmentStatus,
          conflict_count: alignmentStatus === "no_conflicts" ? 0 : Number(alignmentConflictCount || 0),
          disposition_summary: alignmentSummary.trim(),
          evidence_brief_ids: selectedBriefIds.length ? selectedBriefIds : currentBriefIds,
          actor: "medical_manager",
          idempotency_key: requestKey("reference-picos-alignment"),
        }),
      }).then(readJson);
      onJourneyChange(updated);
    },
    "PICOS与当前准入语料的核对结论已记录。",
  );

  const recordRelevance = (status) => {
    const decision = currentDecision(workspace, selectedCandidate?.nct_id);
    return runAction(
      `relevance-${status}`,
      () => fetch(`/api/projects/${projectId}/medical-writing/references/search-snapshots/${snapshot.snapshot_id}/relevance-decisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          nct_id: selectedCandidate.nct_id,
          relevance_status: status,
          reason: reason.trim(),
          actor: "medical_manager",
          expected_revision: decision?.revision || 0,
          idempotency_key: requestKey("reference-relevance"),
        }),
      }).then(readJson),
      "医学相关性已记录。",
    );
  };

  const extractArtifact = (artifact) => fetch(`/api/projects/${projectId}/medical-writing/references/documents/${artifact.artifact_id}/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      actor: "medical_manager",
      extraction_idempotency_key: requestKey("reference-extraction"),
    }),
  }).then(readJson);

  const ingestDocument = (document) => runAction(
    `ingest-${document.document_id}`,
    async () => {
      const artifact = await fetch(`/api/projects/${projectId}/medical-writing/references/documents/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          snapshot_id: snapshot.snapshot_id,
          nct_id: selectedDocumentCandidate.nct_id,
          document_id: document.document_id,
          actor: "medical_manager",
          idempotency_key: requestKey("reference-ingest"),
        }),
      }).then(readJson);
      return extractArtifact(artifact);
    },
    "公开文档已下载并完成结构化解析，片段可直接进入后续审核。",
  );

  const selectManualFile = (event) => {
    const file = event.target.files?.[0] || null;
    setManualFile(file);
    manualUploadKeyRef.current = file ? requestKey("reference-manual-upload") : "";
  };

  const uploadManualDocument = () => runAction(
    "manual-upload",
    async () => {
      if (!manualFile || !selectedDocumentCandidate || !selectedCandidateCanIngest) {
        throw new Error("请先选择已标记为直接竞品或间接参照的候选研究及PDF/DOCX文件");
      }
      const requestedProjectId = projectId;
      const form = new FormData();
      form.append("file", manualFile, manualFile.name);
      form.append("snapshot_id", snapshot.snapshot_id);
      form.append("nct_id", selectedDocumentCandidate.nct_id);
      form.append("document_type", manualDocumentType);
      form.append("document_date", manualDocumentDate);
      form.append("actor", "medical_manager");
      form.append("idempotency_key", manualUploadKeyRef.current);
      const artifact = await fetch(`/api/projects/${projectId}/medical-writing/references/documents/upload`, {
        method: "POST",
        body: form,
      }).then(readJson);
      await extractArtifact(artifact);
      if (activeProjectRef.current !== requestedProjectId) return;
      setSelectedArtifactId(artifact.artifact_id);
      setManualFile(null);
      setManualDocumentDate("");
      manualUploadKeyRef.current = "";
      if (manualFileInputRef.current) manualFileInputRef.current.value = "";
    },
    "手动导入文件已登记并完成解析；请进入译文审核核对内容、文件角色和结构。",
  );

  const extractDocument = (artifact) => runAction(
    `extract-${artifact.artifact_id}`,
    () => extractArtifact(artifact),
    "结构化解析已完成，片段可直接进入后续审核。",
  );

  const overrideDocumentValidation = () => {
    return runAction(
      `validation-override-${selectedArtifactId}`,
      () => fetch(`/api/projects/${projectId}/medical-writing/references/documents/${selectedArtifactId}/content-validation/override`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason: validationOverrideReason.trim(),
          acknowledged_warning_codes: acknowledgedValidationCodes,
          actor: "medical_manager",
          expected_revision: selectedValidation.revision,
          idempotency_key: requestKey("reference-validation-override"),
        }),
      }).then(readJson),
      "已记录医学用户确认；原核验提示和确认理由均保留在审计记录中。",
    ).then(() => {
      setValidationOverrideReason("");
      setAcknowledgedValidationCodes([]);
    });
  };

  const reviewExtraction = (decision) => runAction(
    `structure-review-${decision}`,
    () => fetch(`/api/projects/${projectId}/medical-writing/references/documents/${selectedArtifactId}/extraction-reviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        extraction_revision: selectedExtractionRevision,
        decision,
        confirmed_anchor_coverage: selectedExtractionAnchors,
        unresolved_structure_issues: decision === "returned"
          ? structureIssues.split(/\n+/).map((item) => item.trim()).filter(Boolean)
          : [],
        comment: structureReviewComment.trim(),
        actor: "medical_manager",
        expected_revision: selectedExtractionReview?.revision || 0,
        idempotency_key: requestKey("reference-structure-review"),
      }),
    }).then(readJson),
    decision === "approved"
      ? "抽取章节与M11结构映射已完成医学确认，可进入逐段翻译。"
      : "结构问题已退回记录，当前抽取版本不能进入语料准入。",
  );

  const createTranslation = () => runAction(
    `translate-${selectedSpan?.span_id}`,
    () => fetch(`/api/projects/${projectId}/medical-writing/references/translations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        span_id: selectedSpan.span_id,
        glossary_version: "cms_regulatory_zh_v1",
        actor: "medical_manager",
        idempotency_key: requestKey("reference-translation"),
      }),
    }).then(readJson),
    "监管中文候选已生成；忠实度通过后仍需医学作者对照原文确认。",
  );

  const reviewTranslation = (decision) => runAction(
    `review-${decision}`,
    () => fetch(`/api/projects/${projectId}/medical-writing/references/translations/${selectedTranslation.translation_id}/medical-review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        translation_revision: selectedTranslation.revision,
        decision,
        comment: reviewComment.trim(),
        actor: "medical_manager",
        expected_revision: selectedReview?.revision || 0,
        idempotency_key: requestKey("reference-review"),
      }),
    }).then(readJson),
    decision === "approved" ? "医学作者已确认译文，已直接纳入写作参考库。" : "译文作者处置已记录。",
  );

  const reviseTranslation = () => runAction(
    `revise-${selectedTranslation?.translation_id}`,
    () => fetch(`/api/projects/${projectId}/medical-writing/references/translations/${selectedTranslation.translation_id}/revisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_translation_revision: selectedTranslation.revision,
        medical_review_id: selectedReview.review_id,
        actor: "medical_manager",
        idempotency_key: requestKey("reference-translation-revision"),
      }),
    }).then(readJson),
    "已按作者退回意见生成新译文版本，仍需重新核对与确认。",
  );

  const toggleBrief = (briefId) => {
    onSelectedBriefIdsChange(
      selectedBriefIds.includes(briefId)
        ? selectedBriefIds.filter((item) => item !== briefId)
        : [...selectedBriefIds, briefId],
    );
  };

  const openBatchIssue = async (item) => {
    await refreshWorkspace({ preserveMessage: true });
    setSelectedNctId(item.nct_id);
    if (item.issue_kind === "content_validation" && item.artifact_id) {
      setSelectedArtifactId(item.artifact_id);
      setActiveView("translations");
      setMessage("已打开该文件的内容核验；请对照原文后人工处置。批次不会自动确认沿用。");
      return;
    }
    setLegacyIssueOpen(true);
    setActiveView("documents");
    setMessage("已定位到该研究的逐文件问题处理入口；可手动下载、导入或重新解析。");
    globalThis.setTimeout(() => legacyIssueToolsRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }), 0);
  };

  const openTranslationBatchSpan = (item) => {
    const anchor = item.ich_m11_anchor && item.ich_m11_anchor !== "unmapped"
      ? item.ich_m11_anchor
      : "all";
    const artifact = (workspace?.artifacts || []).find(
      (candidate) => candidate.artifact_id === item.artifact_id,
    );
    if (item.nct_id || artifact?.nct_id) {
      setSelectedNctId(item.nct_id || artifact.nct_id);
    }
    setSelectedArtifactId(item.artifact_id);
    setSpanAnchorFilter(anchor);
    setSpanOffset(Math.max(0, Number(item.span_offset || 0)));
    setSelectedSpanId(item.span_id);
    setActiveView("translations");
    setMessage("已定位到具体片段；请在现有单片段区对照原文完成作者确认。");
    globalThis.setTimeout(() => translationReviewRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }), 0);
  };

  return (
    <div className={presentationClass} data-embedded={embedded ? "true" : "false"} data-compact={compact ? "true" : "false"}>
      {!embedded && (
        <div className="writing-reference-header">
          <div><span>{authoringMode ? "建稿前语料准备" : "当前章节"}</span><strong>{authoringMode ? "竞品方案参照" : "可用证据"}</strong></div>
          <button className="icon-button" onClick={refreshWorkspace} disabled={loading} title="刷新来源、审核与版本状态"><RefreshCw size={15} /></button>
        </div>
      )}
      {embedded ? (
        <div className="writing-reference-boundary is-embedded">
          <span>优先处理候选研究、原文与分诊结论；运行标识与定位信息默认折叠。</span>
          <button type="button" className="icon-button" onClick={refreshWorkspace} disabled={loading} title="刷新来源、审核与版本状态" aria-label="刷新来源、审核与版本状态">
            <RefreshCw size={15} />
          </button>
        </div>
      ) : (
        <div className="writing-reference-boundary">
          {authoringMode
            ? `当前工作区已保存本次公开检索快照${snapshotId ? `（${snapshotId}）` : ""}；候选分诊、原文处理、译文审核和准入将沿用同一来源链。检索快照本身不等于医学确认。`
            : "仅显示作者已确认、已准入且来源当前有效的证据；检索、下载、解析与核对在独立语料准备流程中完成。"}
        </div>
      )}
      <div className="writing-reference-views" role="tablist" aria-label="竞品方案参照工作步骤">
        {(authoringMode
          ? viewDefinitions.filter((view) => view.id !== "shared_phase1" || phase1SharedAvailable)
          : viewDefinitions.filter((view) => view.id === "approved")).map((view) => (
          <button key={view.id} role="tab" aria-selected={activeView === view.id} className={activeView === view.id ? "active" : ""} onClick={() => setActiveView(view.id)}>{view.label}</button>
        ))}
      </div>
      {message && <div className={`writing-reference-message ${message.includes("失败") || message.includes("未完成") ? "danger" : ""}`}>{message}</div>}

      {activeView === "candidates" && (
        <div className="writing-reference-view">
          {!authoringMode && <div className="writing-reference-search">
            <label>适应症<input value={indication} onChange={(event) => setIndication(event.target.value)} /></label>
            <label>研究分期<select value={phase} onChange={(event) => setPhase(event.target.value)}><option value="PHASE1">I期</option><option value="PHASE2">II期</option><option value="PHASE3">III期</option><option value="PHASE4">IV期</option></select></label>
            <button className="primary-button" onClick={submitSearch} disabled={!indication.trim() || busyAction === "search"}><Search size={14} />{busyAction === "search" ? "检索中" : "检索公开方案"}</button>
          </div>}
          {snapshot && (embedded ? (
            <details className="writing-reference-snapshot-details">
              <summary>本次公开检索结果与运行信息</summary>
              <p className="writing-reference-snapshot" title={snapshotId || undefined}>API {snapshot.api_version || "待记录"} · 数据时间 {snapshot.data_timestamp || "待记录"} · 返回 {snapshot.returned_count}/{snapshot.total_count}{snapshotId ? ` · 结果编号 ${snapshotId}` : ""}</p>
            </details>
          ) : (
            <p className="writing-reference-snapshot">API {snapshot.api_version || "待记录"} · 数据时间 {snapshot.data_timestamp || "待记录"} · 返回 {snapshot.returned_count}/{snapshot.total_count}</p>
          ))}
          {authoringMode && <div className="writing-reference-candidate-filters">
            <label><Search size={14} /><input value={candidateQuery} onChange={(event) => { setCandidateQuery(event.target.value); setCandidatePage(1); }} placeholder="检索NCT号、标题或申办方" /></label>
            <select value={candidateStatus} onChange={(event) => { setCandidateStatus(event.target.value); setCandidatePage(1); }}>
              <option value="retained">已保留参照</option>
              <option value="all">全部状态</option>
              <option value="pending_medical_relevance">待AI分类</option>
              <option value="direct_competitor">直接竞品</option>
              <option value="indirect_reference">间接参照</option>
              <option value="excluded">已排除</option>
            </select>
            <span data-testid="candidate-count">{loading && !workspace ? "加载中…" : `${filteredCandidates.length}项`}</span>
          </div>}
          <div className="writing-reference-list" data-state={loading && !workspace ? "loading" : workspace ? "loaded" : "idle"}>
            {(authoringMode ? visibleCandidates : candidates).map((candidate) => {
              const displayStatus = candidateDisplayStatus(candidate);
              return (
                <button key={candidate.nct_id} className={candidate.nct_id === selectedCandidate?.nct_id ? "active" : ""} onClick={() => selectCandidateForReview(candidate.nct_id)}>
                  <span><b>{candidate.nct_id}</b><ReferenceTag value={displayStatus} dictionary={relevanceLabels} /></span>
                  <strong>{candidate.brief_title || candidate.official_title || "未提供研究标题"}</strong>
                  <small>{candidate.lead_sponsor || "申办方待核验"} · {(candidate.phases || []).join("/") || "分期待核验"}</small>
                </button>
              );
            })}
            {loading && !workspace && <div className="writing-reference-empty" role="status">正在加载候选研究…</div>}
            {!loading && workspace && !candidates.length && <div className="writing-reference-empty" data-state="loaded-empty">尚未检索公开竞品研究。</div>}
          </div>
          {authoringMode && candidatePageCount > 1 && <div className="writing-reference-pagination">
            <button onClick={() => setCandidatePage((current) => Math.max(1, current - 1))} disabled={candidatePage === 1}>上一页</button>
            <span>{candidatePage}/{candidatePageCount}</span>
            <button onClick={() => setCandidatePage((current) => Math.min(candidatePageCount, current + 1))} disabled={candidatePage === candidatePageCount}>下一页</button>
          </div>}
          {selectedCandidate
            && !triageReviewLocked
            && !(authoringMode && aiTriageRun?.run?.status === "review_ready") && (
            <div className="writing-reference-actions">
              <label>医学分类理由<textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明适应症、分期、机制、设计或人群的参照关系。" /></label>
              <div className="button-row">
                <button onClick={() => recordRelevance("direct_competitor")} disabled={!reason.trim() || Boolean(busyAction)}>标记为直接竞品</button>
                <button onClick={() => recordRelevance("indirect_reference")} disabled={!reason.trim() || Boolean(busyAction)}>标记为间接参照</button>
                <button onClick={() => recordRelevance("excluded")} disabled={!reason.trim() || Boolean(busyAction)}>排除</button>
              </div>
            </div>
          )}
          {authoringMode && <div className="writing-reference-ai-triage">
            <div><strong>AI辅助分诊</strong><span>AI先完成全量分类；您整体浏览，必要时展开修改，再一次确认锁定。</span></div>
            <div className="writing-reference-ai-triage-controls">
              {aiTriagePresentation.kind === "idle" && <button className="primary-button" data-action="start-ai-triage" onClick={startAiTriage} disabled={Boolean(aiTriageJobId) || Boolean(busyAction) || triageFinalized || aiTriageRecovering || Boolean(aiTriageRun?.run)}>
                {aiTriageRecovering ? "恢复分诊结果…" : aiTriageStatus === "starting" || aiTriageStatus === "queued" || aiTriageStatus === "running" || aiTriageStatus === "resuming" ? "AI分诊中…" : aiTriageRun?.run?.status === "review_ready" ? "AI建议待确认" : aiTriageRun?.run?.status === "confirmed" ? "已确认锁定" : aiTriageRun?.run?.status === "projection_pending" ? "已确认，待同步" : "启动AI分诊"}
              </button>
              }
              {aiTriageJobId && !["completed", "failed", "cancelled"].includes(aiTriageStatus) && (
                <button data-action="cancel-ai-triage" onClick={cancelAiTriage}>取消</button>
              )}
              {aiTriagePresentation.retryable && (
                <button className="primary-button" data-action="retry-ai-triage" onClick={retryAiTriageRun} disabled={Boolean(busyAction) || aiTriageRecovering}>重试当前分诊</button>
              )}
              {aiTriageRun?.run?.status === "stale" && <button data-action="restart-stale-ai-triage" onClick={retryAiTriageRun}>按当前信息重新分诊</button>}
              {aiTriagePresentation.kind === "running" && <button data-action="refresh-ai-triage" onClick={() => recoverLatestTriageRun({ silentNotFound: false })}>刷新</button>}
              {aiTriageRun?.run?.status === "projection_pending" && <button data-action="retry-ai-triage-projection" onClick={retryAiTriageProjection}>重试同步</button>}
            </div>
            {aiTriagePresentation.kind !== "idle" && <p className={`writing-reference-message ${aiTriagePresentation.kind === "failed" || aiTriagePresentation.kind === "stale" ? "danger" : ""}`} role={aiTriagePresentation.kind === "failed" ? "alert" : undefined}>
              {aiTriageRun?.run?.status === "partial_failed" && <strong>部分分块失败：</strong>}
              {aiTriagePresentation.message}
              {aiTriagePresentation.kind === "stale" && " 旧结果仅保留审计，不会进入当前竞品篮子。"}
            </p>}
            {aiTriageError && aiTriagePresentation.kind === "idle" && <p className="writing-reference-message danger" role="alert">{aiTriageError}</p>}
          </div>}
          {authoringMode && (aiTriageRun?.run?.status === "review_ready" || triageReconfirmationRequired) && (
            <section className="writing-reference-validation" data-section="ai-triage-review">
              <div>
                <div>
                  <strong>{triageReconfirmationRequired ? "按当前研究信息重新核对" : "批量确认AI分诊建议"}</strong>
                  <p>
                    {triageReconfirmationRequired ? "既有人工确认结果已全部预选" : `AI已预设 ${aiTriageResults.length}/${candidates.length} 项分类`}：
                    保留 {aiTriageRetainedCount} 项，排除 {Math.max(0, candidates.length - aiTriageRetainedCount)} 项。
                    只需核对变化影响；需要调整时再展开明细。
                  </p>
                  {triageReconfirmationRequired && (
                    <ul className="writing-reference-criteria-list">
                      {(aiTriageRun?.reconfirmation?.current_triage_criteria || []).map((criterion) => (
                        <li key={criterion.criterion_id}>
                          <b>{criterion.label}</b>：{criterion.value}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setAiTriageDetailsOpen((current) => !current)}
                >
                  {aiTriageDetailsOpen ? "收起明细" : "展开明细修订"}
                </button>
              </div>
              {aiTriageDetailsOpen && <div className="writing-reference-list" style={{ maxHeight: 560, paddingRight: 6 }}>
                {aiTriageResults.map((result) => {
                  const candidate = candidates.find((item) => item.nct_id === result.nct_id);
                  return (
                    <article className="writing-reference-document-row" key={result.nct_id} data-nct-id={result.nct_id}>
                      <div>
                        <span><strong>{result.nct_id}</strong> · {candidate?.brief_title || candidate?.official_title || "研究标题待核验"}</span>
                        <span className="tag info">置信度 {Math.round(Number(result.confidence || 0) * 100)}%</span>
                      </div>
                      <label className="writing-reference-select">
                        本次最终分类
                        <select
                          aria-label={`${result.nct_id}最终分类`}
                          value={aiTriageSelections[result.nct_id] || result.classification}
                          onChange={(event) => setAiTriageSelections((current) => ({
                            ...current,
                            [result.nct_id]: event.target.value,
                          }))}
                        >
                          {Object.entries(triageClassificationLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                        </select>
                      </label>
                      <div className="writing-reference-validation">
                        <strong>AI中文理由</strong>
                        <p>{result.reason || "AI未提供可审核理由。"}</p>
                        <strong>匹配维度</strong>
                        <div className="writing-reference-validation-checks">
                          {(result.matching_dimensions || []).map((dimension) => (
                            <div key={`${result.nct_id}-${dimension.dimension}`}>
                              <b>{triageDimensionLabels[dimension.dimension] || dimension.dimension}</b>
                              <span>{dimension.match === "match" ? "匹配" : dimension.match === "partial" ? "部分匹配" : dimension.match === "mismatch" ? "不匹配" : "未知"}</span>
                              <small>{dimension.detail || "未提供具体说明"}</small>
                            </div>
                          ))}
                          {!result.matching_dimensions?.length && <p>AI未返回匹配维度。</p>}
                        </div>
                        <strong>证据缺口</strong>
                        <p>{result.evidence_gaps?.length ? result.evidence_gaps.join("；") : "未识别到需要补充的关键证据。"}</p>
                      </div>
                    </article>
                  );
                })}
              </div>}
              {!aiTriageCoverageComplete && <p className="writing-reference-message danger">AI结果未完整覆盖当前公开检索结果全部候选，不能确认；请重试或刷新结果。</p>}
              {aiTriageAllExcluded && <p className="writing-reference-message">当前选择将排除全部候选。确认后仍可继续手工上传方案或使用通用语料库；说明可按需补充。</p>}
              <label className="writing-reference-select">
                本次审核说明（可选）
                <textarea value={triageReason} onChange={(event) => setTriageReason(event.target.value)} placeholder="可记录调整分类或锁定篮子的总体考虑；不填写时系统记录标准确认说明。" />
              </label>
              {aiTriageAllExcluded && <label className="writing-reference-select">
                无合适竞品理由（可选）
                <textarea value={noSuitableCompetitorReason} onChange={(event) => setNoSuitableCompetitorReason(event.target.value)} placeholder="如需留痕，可简要说明候选与当前适应症、分期、人群或设计不匹配之处。" />
              </label>}
              <button className="primary-button" data-action="confirm-ai-triage" onClick={confirmAiTriageRun} disabled={!aiTriageCoverageComplete || Boolean(busyAction)}>
                {busyAction === "confirm-ai-triage" ? "确认中…" : triageReconfirmationRequired ? `确认当前${candidates.length}项分类` : aiTriageAllExcluded ? "确认全部排除并继续" : `确认并锁定全部${candidates.length}项`}
              </button>
            </section>
          )}
          {authoringMode && !triageFinalized && aiTriageRun?.run?.status !== "review_ready" && aiTriageRun?.run?.status !== "confirmed" && !triageReconfirmationRequired && <div className="writing-reference-triage-finalize">
            <div><strong>锁定深度处理篮子</strong><span>当前已有 {relatedDecisionIds.length} 项直接竞品/间接参照；锁定后仍保留所有候选和分诊审计。</span></div>
            <label>分诊定稿理由<textarea value={triageReason} onChange={(event) => setTriageReason(event.target.value)} placeholder="说明为何当前篮子足以进入Protocol深度处理。" /></label>
            <button className="primary-button" onClick={finalizeTriage} disabled={!relatedDecisionIds.length || triageReason.trim().length < 10 || Boolean(busyAction)}>{busyAction === "finalize-triage" ? "锁定中" : "锁定竞品篮子"}</button>
          </div>}
        </div>
      )}

      {activeView === "documents" && (
        <div className="writing-reference-view">
          {authoringMode && triageFinalized && (
            <ReferencePreparationBatchPanel
              projectId={projectId}
              snapshotId={snapshotId}
              candidates={documentCandidates}
              artifacts={workspace?.artifacts || []}
              documentValidations={workspace?.document_validations || []}
              artifactSpanCounts={workspace?.artifact_span_counts || {}}
              onOpenIssue={openBatchIssue}
              onBatchSettled={refreshAuthoringAfterBatchSettled}
            />
          )}
          {authoringMode && triageFinalized && (
            <MixedOcrReviewPanel
              projectId={projectId}
              reviews={workspace?.ocr_consistency_reviews || []}
              artifacts={workspace?.artifacts || []}
              onSettled={() => refreshWorkspace({ preserveMessage: true })}
            />
          )}
          {triageFinalized && (
            <div className="writing-reference-single-document-entry">
              <button type="button" data-action="toggle-single-document-tools" onClick={() => setLegacyIssueOpen((current) => !current)}>
                <FileSearch size={14} />逐文件问题处理
              </button>
              <span>用于批次失败、缺失公开文件或待人工确认项；保留原下载、导入、解析与核验流程。</span>
            </div>
          )}
          {(!triageFinalized || legacyIssueOpen) && (
          <div className="writing-reference-single-document-tools" ref={legacyIssueToolsRef}>
          <label className="writing-reference-select">候选研究<select value={selectedNctId} onChange={(event) => selectCandidateForReview(event.target.value)}>{documentCandidates.map((item) => <option value={item.nct_id} key={item.nct_id}>{item.nct_id}</option>)}</select></label>
          <div className="writing-reference-manual-upload">
            <div className="writing-reference-manual-upload-head">
              <span><Upload size={15} /></span>
              <div><strong>手动导入 Protocol</strong><small>适用于已自行取得的PDF或DOCX；组合文件仅使用其中的Protocol部分。</small></div>
            </div>
            <label>选择文件<input ref={manualFileInputRef} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={selectManualFile} /></label>
            <label>文件角色<select value={manualDocumentType} onChange={(event) => setManualDocumentType(event.target.value)}><option value="protocol">Protocol</option><option value="protocol_sap">Protocol + SAP（仅使用Protocol部分）</option></select></label>
            <label>文件日期（选填）<input type="date" value={manualDocumentDate} onChange={(event) => setManualDocumentDate(event.target.value)} /></label>
            <button className="primary-button" onClick={uploadManualDocument} disabled={!manualFile || !selectedCandidateCanIngest || Boolean(busyAction)}><Upload size={14} />{busyAction === "manual-upload" ? "导入解析中" : "导入并解析"}</button>
            <small className="writing-reference-manual-upload-state">
              {manualFile
                ? `${manualFile.name} · ${(manualFile.size / 1024 / 1024).toFixed(2)} MB`
                : selectedCandidateCanIngest
                ? "尚未选择文件"
                : "当前候选研究需先完成直接竞品或间接参照分类"}
            </small>
          </div>
          <div className="writing-reference-list">
            {selectedManualArtifacts.map((artifact) => {
              const artifactParsed = Number(workspace?.artifact_span_counts?.[artifact.artifact_id] || 0) > 0;
              const extractionReview = (workspace?.extraction_reviews || [])
                .filter((item) => item.artifact_id === artifact.artifact_id)
                .sort((left, right) => right.revision - left.revision)[0];
              const validation = (workspace?.document_validations || []).find((item) => item.artifact_id === artifact.artifact_id);
              return (
                <div className="writing-reference-document-row manual" key={artifact.artifact_id}>
                  <div><FileText size={15} /><strong>{artifact.filename}</strong><span className="tag info">手动导入</span></div>
                  <p>{artifact.document_type} · {artifact.document_date || "日期未填写"}</p>
                  <ReferenceTag value={extractionReview?.decision || (artifactParsed ? "parsed" : "pending")} dictionary={{ ...extractionReviewLabels, parsed: ["已解析待结构审核", "warning"], pending: ["待解析", "warning"] }} />
                  {validation && <ReferenceTag value={validation.status} dictionary={validationLabels} />}
                  <code title={artifact.content_sha256}>{artifact.content_sha256.slice(0, 12)}…</code>
                  <button onClick={() => { setSelectedArtifactId(artifact.artifact_id); setActiveView("translations"); }} title="查看文件检查、解析片段与译文审核状态"><FileSearch size={14} />查看处理状态</button>
                  {!artifactParsed && <button onClick={() => extractDocument(artifact)} disabled={Boolean(busyAction)}><FileSearch size={14} />重新解析</button>}
                </div>
              );
            })}
            {(selectedDocumentCandidate?.public_documents || []).map((document) => {
              const artifact = artifactBySourceDocument.get(document.document_id);
              const artifactParsed = artifact && Number(workspace?.artifact_span_counts?.[artifact.artifact_id] || 0) > 0;
              const extractionReview = artifact && (workspace?.extraction_reviews || [])
                .filter((item) => item.artifact_id === artifact.artifact_id)
                .sort((left, right) => right.revision - left.revision)[0];
              const validation = artifact && (workspace?.document_validations || []).find((item) => item.artifact_id === artifact.artifact_id);
              return (
                <div className="writing-reference-document-row" key={document.document_id}>
                  <div><FileText size={15} /><strong>{document.label || document.filename}</strong></div>
                  <p>{document.document_type} · {document.document_date || "日期待核验"}</p>
                  {artifact ? (
                    <>
                      <ReferenceTag
                        value={extractionReview?.decision || (artifactParsed ? "parsed" : "pending")}
                        dictionary={{ ...extractionReviewLabels, parsed: ["已解析待结构审核", "warning"], pending: ["待解析", "warning"] }}
                      />
                      {validation && <ReferenceTag value={validation.status} dictionary={validationLabels} />}
                      <code title={artifact.content_sha256}>{artifact.content_sha256.slice(0, 12)}…</code>
                      <button onClick={() => { setSelectedArtifactId(artifact.artifact_id); setActiveView("translations"); }} title="查看文件检查、解析片段与译文审核状态"><FileSearch size={14} />查看处理状态</button>
                      {!artifactParsed && <button onClick={() => extractDocument(artifact)} disabled={Boolean(busyAction)}><FileSearch size={14} />解析文档</button>}
                    </>
                  ) : (
                    <button onClick={() => ingestDocument(document)} disabled={Boolean(busyAction)}><Download size={14} />下载并解析</button>
                  )}
                  <a href={document.download_url} target="_blank" rel="noreferrer" title="在新窗口查看 ClinicalTrials.gov 公开原文"><ExternalLink size={14} />公开原文</a>
                </div>
              );
            })}
            {!selectedDocumentCandidate?.public_documents?.length && !selectedManualArtifacts.length && <div className="writing-reference-empty">该候选研究未发现公开 Protocol，可在上方导入已取得的研究方案原文。</div>}
          </div>
          </div>
          )}
        </div>
      )}

      {activeView === "shared_phase1" && phase1SharedAvailable && <SharedPhase1CorpusPanel />}

      {activeView === "translations" && (
        <div className="writing-reference-view">
          {authoringMode && (
            <ReferenceTranslationBatchPanel
              projectId={projectId}
              snapshotId={snapshotId}
              glossaryVersion="cms_regulatory_zh_v1"
              onOpenSpan={openTranslationBatchSpan}
              onBatchSettled={refreshAuthoringAfterBatchSettled}
            />
          )}
          <label ref={translationReviewRef} className="writing-reference-select writing-reference-translation-review-anchor">已登记文档<select value={selectedArtifactId} onChange={(event) => setSelectedArtifactId(event.target.value)}>{(workspace?.artifacts || []).map((item) => <option value={item.artifact_id} key={item.artifact_id}>{item.nct_id} · {item.filename}</option>)}</select></label>
          {selectedArtifact && !selectedArtifact.source_current && <div className="writing-reference-invalid"><AlertTriangle size={15} />该来源版本已失效，对应译文和批准引用已退出写作参考库。</div>}
          {selectedValidation && (
            <div className={`writing-reference-validation ${["mismatch", "needs_review"].includes(selectedValidation.status) ? "requires-review" : ""}`}>
              <div><strong>文件内容核验</strong><ReferenceTag value={selectedValidation.status} dictionary={validationLabels} /></div>
              <p>{selectedValidation.summary}</p>
              <div className="writing-reference-validation-checks">
                {selectedValidation.checks.map((check) => (
                  <div key={check.check_code}><span>{check.label}</span><b>{check.outcome === "match" ? "匹配" : check.outcome === "mismatch" ? "不一致" : "需确认"}</b><small title={check.observed_value}>{check.observed_value}</small></div>
                ))}
              </div>
              {["mismatch", "needs_review"].includes(selectedValidation.status) && (
                <div className="writing-reference-override">
                  <div className="writing-reference-override-warning"><AlertTriangle size={15} /><span>以下信息尚未通过自动核验。请逐项对照原文；确认沿用不代表系统判定已转为匹配。</span></div>
                  <fieldset>
                    <legend>逐项确认</legend>
                    {validationWarnings.map((check) => (
                      <label className="writing-reference-override-check" key={check.check_code}>
                        <input
                          type="checkbox"
                          checked={acknowledgedValidationCodes.includes(check.check_code)}
                          onChange={(event) => setAcknowledgedValidationCodes((current) => (
                            event.target.checked
                              ? [...new Set([...current, check.check_code])]
                              : current.filter((code) => code !== check.check_code)
                          ))}
                        />
                        <span><strong>我已核对：{check.label}</strong><small>{check.observed_value || "未识别到可核对内容"}</small></span>
                      </label>
                    ))}
                  </fieldset>
                  <label>确认理由<textarea value={validationOverrideReason} onChange={(event) => setValidationOverrideReason(event.target.value)} placeholder="说明为何确认该文件属于当前适应症、研究和预期文件类型。" /></label>
                  <button
                    onClick={overrideDocumentValidation}
                    disabled={validationOverrideReason.trim().length < 10 || acknowledgedValidationCodes.length !== validationWarnings.length || Boolean(busyAction)}
                  >确认沿用当前文件</button>
                  <small>确认后，原提示、确认理由、操作者及版本信息将纳入审计记录。</small>
                </div>
              )}
              {selectedValidation.status === "user_overridden" && (
                <div className="writing-reference-override-record">
                  <ReferenceTag value={selectedValidation.status} dictionary={validationLabels} />
                  <p><strong>医学确认理由</strong>{selectedValidation.override_reason}</p>
                </div>
              )}
            </div>
          )}
          {selectedExtractionRevision && (
            <div className={`writing-reference-structure-review ${selectedExtractionReview?.decision || "pending"}`}>
              <div>
                <strong>抽取结构医学审核</strong>
                {selectedExtractionReview
                  ? <ReferenceTag value={selectedExtractionReview.decision} dictionary={extractionReviewLabels} />
                  : <ReferenceTag value="pending" dictionary={{ pending: ["待医学确认", "warning"] }} />}
              </div>
              <p>抽取版本 <code>{selectedExtractionRevision}</code> · {spanMeta.total} 个片段 · M11映射 {selectedExtractionAnchors.length} 类</p>
              <div className="writing-reference-anchor-list">
                {selectedExtractionAnchors.map((anchor) => <span key={anchor}>{anchor}</span>)}
              </div>
              {selectedExtractionReview && <small>{selectedExtractionReview.comment}</small>}
              <label>结构审核说明<textarea value={structureReviewComment} onChange={(event) => setStructureReviewComment(event.target.value)} placeholder="说明已核对页码、章节标题、片段边界及M11结构映射。" /></label>
              <label>需修正问题（每行一项）<textarea value={structureIssues} onChange={(event) => setStructureIssues(event.target.value)} placeholder="仅在退回时填写，例如：第8章被错误映射为安全性章节。" /></label>
              <div className="button-row">
                <button className="primary-button" onClick={() => reviewExtraction("approved")} disabled={structureReviewComment.trim().length < 10 || !selectedExtractionAnchors.length || Boolean(busyAction)}>确认结构完整</button>
                <button onClick={() => reviewExtraction("returned")} disabled={structureReviewComment.trim().length < 10 || !structureIssues.trim() || Boolean(busyAction)}>退回重新解析</button>
              </div>
            </div>
          )}
          <div className="writing-reference-span-controls">
            <label className="writing-reference-select">M11结构筛选
              <select value={spanAnchorFilter} onChange={(event) => { setSpanAnchorFilter(event.target.value); setSpanOffset(0); }}>
                <option value="all">全部结构（{spanMeta.total}）</option>
                {Object.entries(spanMeta.anchorCounts).map(([anchor, count]) => (
                  <option value={anchor} key={anchor}>{anchor}（{count}）</option>
                ))}
              </select>
            </label>
            <label className="writing-reference-select">结构化片段
              <select value={selectedSpanId} onChange={(event) => setSelectedSpanId(event.target.value)}>
                {spans.map((item) => <option value={item.span_id} key={item.span_id}>{spanOptionLabel(item)}</option>)}
              </select>
            </label>
            <div className="writing-reference-span-pager">
              <span>当前 {spanMeta.filteredTotal ? spanOffset + 1 : 0}-{Math.min(spanOffset + spans.length, spanMeta.filteredTotal)} / {spanMeta.filteredTotal}</span>
              <button title="上一页片段" aria-label="上一页片段" onClick={() => setSpanOffset((current) => Math.max(0, current - 500))} disabled={spanOffset === 0}><ChevronLeft size={15} /></button>
              <button title="下一页片段" aria-label="下一页片段" onClick={() => setSpanOffset((current) => current + 500)} disabled={spanOffset + spans.length >= spanMeta.filteredTotal}><ChevronRight size={15} /></button>
            </div>
          </div>
          {selectedSpan ? (
            <div className="writing-reference-review">
              <div className="writing-reference-source">
                <span>原始方案内容</span>
                <p>{selectedSpan.source_text}</p>
                {embedded ? (
                  <details className="writing-reference-provenance-details">
                    <summary>定位与溯源</summary>
                    <code>{selectedSpan.source_locator}</code>
                  </details>
                ) : (
                  <code>{selectedSpan.source_locator}</code>
                )}
                {selectedSpan.source_fragments?.length > 1 && (
                  <details className="writing-reference-cross-page-source">
                    <summary>
                      跨页原始片段 · {selectedSpan.source_fragments.map((item) => `p${item.physical_page}`).join(" + ")}
                    </summary>
                    <div>
                      {selectedSpan.source_fragments.map((item) => (
                        <section key={item.source_locator}>
                          <code>p{item.physical_page}:b{item.block_index}</code>
                          <p>{item.source_text}</p>
                        </section>
                      ))}
                      {selectedSpan.skipped_interstitials?.length > 0 && (
                        <small>
                          已跳过{selectedSpan.skipped_interstitials.map((item) => (
                            item.reason_code === "repeated_margin_header" ? "重复页眉" : "重复页脚"
                          )).join("、")}；定位信息保留在来源记录中。
                        </small>
                      )}
                    </div>
                  </details>
                )}
              </div>
              {selectedTranslation ? (
                <>
                  <div className="writing-reference-translation"><span>监管中文候选 · v{selectedTranslation.revision}</span><ReferenceTag value={selectedReviewIsCurrentConfirmation ? selectedReview.decision : selectedTranslation.status} dictionary={selectedReviewIsCurrentConfirmation ? reviewLabels : translationStatusLabels} /><p>{selectedTranslation.translated_text}</p>{selectedTranslation.fidelity_failure_codes?.length > 0 && <small>{selectedTranslation.fidelity_failure_codes.join("、")}</small>}</div>
                  {selectedReview && <div className="writing-reference-review-state"><ReferenceTag value={selectedReview.decision} dictionary={selectedReviewIsCurrentConfirmation ? reviewLabels : historicalReviewLabels} /><span>{selectedReview.comment}{!selectedReviewIsCurrentConfirmation && "（仅保留为历史记录，不构成当前作者确认）"}</span></div>}
                  {selectedTranslationInvalidated && <div className="writing-reference-review-state"><ReferenceTag value={selectedTranslation.status} dictionary={translationStatusLabels} /><span>请基于当前来源和结构解析重新生成译文后再确认。</span></div>}
                  {!selectedTranslationInvalidated && selectedReview?.decision === "returned" && <button className="primary-button" onClick={reviseTranslation} disabled={Boolean(busyAction)}>按审核意见重新生成</button>}
                  {selectedReviewIsCurrentConfirmation && !showReviewWithdrawal && <button onClick={() => setShowReviewWithdrawal(true)} disabled={Boolean(busyAction)}>发现问题，撤回译文</button>}
                  {selectedReviewIsCurrentConfirmation && showReviewWithdrawal && <>
                    <label>撤回理由<textarea value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} placeholder="说明复核发现的具体问题；撤回后旧准入证据立即失效。" /></label>
                    <div className="button-row">
                      <button onClick={() => reviewTranslation("returned")} disabled={!reviewComment.trim() || Boolean(busyAction)}>确认撤回</button>
                      <button onClick={() => { setShowReviewWithdrawal(false); setReviewComment(""); }} disabled={Boolean(busyAction)}>取消</button>
                    </div>
                  </>}
                  {legacyApprovedAwaitingAuthorConfirmation && <>
                    <label>当前作者确认意见<textarea value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} placeholder="历史记录未完成当前准入；请对照当前原文、来源版本和译文后确认。" /></label>
                    <div className="button-row">
                      <button className="primary-button" onClick={() => reviewTranslation("approved")} disabled={!reviewComment.trim() || selectedTranslation.fidelity_status !== "passed" || Boolean(busyAction)}>确认当前译文并准入</button>
                      <button onClick={() => reviewTranslation("returned")} disabled={!reviewComment.trim() || Boolean(busyAction)}>退回修改</button>
                      <button onClick={() => reviewTranslation("rejected")} disabled={!reviewComment.trim() || Boolean(busyAction)}>拒绝</button>
                    </div>
                  </>}
                  {!selectedReview && !selectedTranslationInvalidated && <>
                    <label>作者核对意见<textarea value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} placeholder="对照原文记录医学含义、数字、时间窗及否定关系的核对结论。" /></label>
                    <div className="button-row">
                      <button className="primary-button" onClick={() => reviewTranslation("approved")} disabled={!reviewComment.trim() || selectedTranslation.fidelity_status !== "passed" || Boolean(busyAction)}>确认译文并准入</button>
                      <button onClick={() => reviewTranslation("returned")} disabled={!reviewComment.trim() || Boolean(busyAction)}>退回修改</button>
                      <button onClick={() => reviewTranslation("rejected")} disabled={!reviewComment.trim() || Boolean(busyAction)}>拒绝</button>
                    </div>
                  </>}
                  {selectedBrief && <div className="writing-reference-admitted"><CheckCircle2 size={15} />已纳入写作参考库：{selectedBrief.status === "approved_current" ? "来源当前有效" : "来源已失效"}</div>}
                </>
              ) : (
                <button className="primary-button" onClick={createTranslation} disabled={selectedExtractionReview?.decision !== "approved" || Boolean(busyAction)}>生成监管中文候选</button>
              )}
            </div>
          ) : <div className="writing-reference-empty">当前文档尚无可审核的结构化片段。</div>}
        </div>
      )}

      {activeView === "approved" && (
        <div className="writing-reference-view approved-reference-view">
          <div className="writing-reference-selection-head">
            <strong>{authoringMode ? "已准入证据" : "本次AI证据包"}</strong>
            <span>{authoringMode ? `${currentBriefs.length} 条 · 已选 ${selectedBriefIds.length} 条` : `${selectedBriefIds.length} 条`}</span>
          </div>
          <div className="writing-reference-list">
            {displayedBriefHistory.map((brief) => {
              const current = brief.status === "approved_current" && currentBriefs.some((item) => item.brief_id === brief.brief_id);
              return (
                <label className={`writing-reference-brief ${current ? "" : "invalid"}`} key={brief.brief_id}>
                  <input type="checkbox" checked={selectedBriefIds.includes(brief.brief_id)} disabled={!current} onChange={() => toggleBrief(brief.brief_id)} />
                  <span><strong>{brief.nct_id} · {brief.ich_m11_anchor}</strong><ReferenceTag value={current ? "approved" : "invalidated_source"} dictionary={{ approved: ["作者已确认并准入", "success"], invalidated_source: ["来源已失效", "danger"] }} /><small>{brief.approved_zh_text}</small><code>{brief.source_locator}</code></span>
                </label>
              );
            })}
            {!displayedBriefHistory.length && <div className="writing-reference-empty">尚无作者已确认、已准入且可追溯的竞品方案证据。</div>}
          </div>
          {authoringMode ? <div className="writing-reference-alignment">
            <div><strong>PICOS与语料核对</strong><span>结论绑定当前PICOS哈希和当前有效证据；上游变更后必须重新核对。</span></div>
            <label>核对结论<select value={alignmentStatus} onChange={(event) => setAlignmentStatus(event.target.value)}><option value="no_conflicts">未发现冲突</option><option value="resolved">发现冲突且已处置</option></select></label>
            {alignmentStatus === "resolved" && <label>已处置冲突数<input type="number" min="1" value={alignmentConflictCount} onChange={(event) => setAlignmentConflictCount(event.target.value)} /></label>}
            <label>核对与处置说明<textarea value={alignmentSummary} onChange={(event) => setAlignmentSummary(event.target.value)} placeholder="逐项说明研究人群、干预、对照、终点和时间点与语料的一致性或处置结果。" /></label>
            <button className="primary-button" title={alignmentSubmitDisabledReason} onClick={recordPicosAlignment} disabled={Boolean(alignmentSubmitDisabledReason)}>{busyAction === "record-picos-alignment" ? "记录中" : "记录PICOS核对结论"}</button>
          </div> : <button className="primary-button" onClick={onUseEvidence} disabled={!selectedBriefIds.length}>返回AI修订并使用所选证据</button>}
        </div>
      )}
    </div>
  );
}
