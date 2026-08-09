import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  FileText,
  Filter,
  Loader2,
  MessageSquareText,
  PanelRightOpen,
  RotateCcw,
  Save,
  Search,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  X,
  XCircle,
} from "lucide-react";

const CANDIDATE_TYPES = [
  { key: "all", label: "全部" },
  { key: "document", label: "原始资料" },
  { key: "trial", label: "临床试验" },
  { key: "efficacy", label: "疗效结果" },
  { key: "safety", label: "安全性结果" },
  { key: "publication", label: "公开发表" },
  { key: "regulatory", label: "监管资料" },
];

const APPRAISAL_OPTIONS = [
  { key: "high", label: "高质量" },
  { key: "moderate", label: "中等质量" },
  { key: "low", label: "低质量" },
];

function cn(...classes) {
  return classes.filter(Boolean).join(" ");
}

function Tag({ children, tone = "neutral" }) {
  return <span className={cn("tag", tone)}>{children}</span>;
}

function SectionTitle({ eyebrow, title, action }) {
  return (
    <div className="section-title">
      <div>
        {eyebrow && <small>{eyebrow}</small>}
        <h2>{title}</h2>
      </div>
      {action && <div className="section-title-action">{action}</div>}
    </div>
  );
}

function formatMaybeNumber(value) {
  return value === null || value === undefined ? "未读取" : Number(value).toLocaleString("zh-CN");
}

function apiErrorText(error) {
  return error?.message || error?.status || "network";
}

function apiDetailText(payload, fallback = "") {
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") return detail.detail || detail.message || JSON.stringify(detail);
  return fallback;
}

function readJsonOrThrow(response) {
  if (response.ok) return response.json();
  return response
    .json()
    .catch(() => ({}))
    .then((payload) => {
      throw new Error(apiDetailText(payload, `${response.status}`));
    });
}

function idempotencyKey(prefix) {
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function statusTone(status) {
  if (["已纳入", "作者已确认", "写作候选"].includes(status)) return "success";
  if (["已排除", "退回补证", "阻断", "失败"].includes(status)) return "danger";
  if (["待补证", "待医学确认", "待评价", "待筛选"].includes(status)) return "warning";
  return "info";
}

function candidateTypeLabel(value) {
  return CANDIDATE_TYPES.find((item) => item.key === value)?.label || value || "未分类";
}

function screeningStatusLabel(status) {
  return {
    待筛选: "待筛选",
    已纳入: "已纳入",
    已排除: "已排除",
    待补证: "暂缓",
    重复项: "重复",
  }[status] || status || "待筛选";
}

function appraisalStatusLabel(status) {
  return {
    待评价: "待评价",
    已评价: "已评价",
  }[status] || status || "待评价";
}

function qualityRatingLabel(value) {
  return APPRAISAL_OPTIONS.find((item) => item.key === value)?.label || value || "";
}

function qualityTone(value) {
  if (value === "high") return "success";
  if (value === "moderate") return "warning";
  if (value === "low") return "danger";
  return "neutral";
}

function picosStatusTone(status) {
  if (["作者已确认", "写作候选"].includes(status)) return "success";
  if (["待用户确认", "待医学确认", "待补医学理由"].includes(status)) return "warning";
  if (status === "退回补证") return "danger";
  return "info";
}

function picosStatusLabel(status) {
  return {
    待用户确认: "待医学确认",
  }[status] || status || "待医学确认";
}

function picosActionLabel(action) {
  return {
    select_option: "选择候选",
    save_rationale: "保存理由",
    mark_writing_candidate: "作者确认",
    return_for_evidence: "退回补证",
    reset_decision: "重置",
  }[action] || action;
}

function safeMetaValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const text = String(value);
  if (text.startsWith("/") || /^[A-Za-z]:[\\/]/.test(text)) {
    return text.split(/[\\/]/).pop();
  }
  return text;
}

function useAbortRegistry() {
  const controllersRef = useRef(new Map());
  useEffect(() => () => {
    controllersRef.current.forEach((controller) => controller.abort());
    controllersRef.current.clear();
  }, []);
  return (channel) => {
    controllersRef.current.get(channel)?.abort();
    const controller = new AbortController();
    controllersRef.current.set(channel, controller);
    return controller.signal;
  };
}

export function EvidenceDesignPage({ projectId, aiGatewayStatus }) {
  const [mode, setMode] = useState("evidence"); // "evidence" | "picos"
  const [packages, setPackages] = useState([]);
  const [selectedPackageId, setSelectedPackageId] = useState("");
  const [loadingPackages, setLoadingPackages] = useState(false);
  const [packageError, setPackageError] = useState("");

  const [candidateType, setCandidateType] = useState("all");
  const [search, setSearch] = useState("");
  const [candidatePage, setCandidatePage] = useState(1);
  const [candidatePageSize] = useState(25);
  const [candidatePageData, setCandidatePageData] = useState(null);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [candidateError, setCandidateError] = useState("");
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  const [candidateDetail, setCandidateDetail] = useState(null);
  const [candidateReview, setCandidateReview] = useState(null);
  const [loadingCandidateDetail, setLoadingCandidateDetail] = useState(false);
  const [checkedCandidateIds, setCheckedCandidateIds] = useState(new Set());
  const [reviewActionBusy, setReviewActionBusy] = useState("");
  const [reviewMessage, setReviewMessage] = useState("");

  const [extractionDraft, setExtractionDraft] = useState([]);
  const [appraisalDraft, setAppraisalDraft] = useState("");
  const [reasonDraft, setReasonDraft] = useState("");

  const [picosWorkflow, setPicosWorkflow] = useState(null);
  const [loadingPicos, setLoadingPicos] = useState(false);
  const [picosError, setPicosError] = useState("");
  const [selectedPicosQuestionId, setSelectedPicosQuestionId] = useState("");
  const [picosRationales, setPicosRationales] = useState({});
  const [picosBusyAction, setPicosBusyAction] = useState("");
  const [picosMessage, setPicosMessage] = useState("");
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [handoffBusy, setHandoffBusy] = useState(false);

  const [aiThreads, setAiThreads] = useState([]);
  const [aiInstruction, setAiInstruction] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState("");
  const [rewriteDrafts, setRewriteDrafts] = useState({});

  const getAbortSignal = useAbortRegistry();

  const selectedPackage = useMemo(
    () => packages.find((item) => item.package_id === selectedPackageId) || packages[0] || null,
    [packages, selectedPackageId]
  );

  // Reset page, selected candidate, and unsaved state on project/package switch.
  useEffect(() => {
    setCandidatePage(1);
    setCandidatePageData(null);
    setSelectedCandidateId("");
    setCandidateDetail(null);
    setCandidateReview(null);
    setCheckedCandidateIds(new Set());
    setReviewMessage("");
    setExtractionDraft([]);
    setAppraisalDraft("");
    setReasonDraft("");
    setSelectedPicosQuestionId("");
    setAiThreads([]);
    setAiInstruction("");
    setAiError("");
    setRewriteDrafts({});
  }, [projectId, selectedPackageId]);

  useEffect(() => {
    setPackages([]);
    setSelectedPackageId("");
    setPackageError("");
  }, [projectId]);

  const loadPackages = async () => {
    const signal = getAbortSignal("packages");
    setLoadingPackages(true);
    setPackageError("");
    try {
      const response = await fetch(`/api/projects/${projectId}/evidence-design/packages`, { signal });
      const payload = await readJsonOrThrow(response);
      if (signal.aborted) return;
      const nextPackages = payload.packages || [];
      setPackages(nextPackages);
      const packageIds = new Set(nextPackages.map((item) => item.package_id));
      setSelectedPackageId((current) => packageIds.has(current) ? current : nextPackages[0]?.package_id || "");
    } catch (error) {
      if (signal.aborted) return;
      setPackageError(`资料包加载失败：${apiErrorText(error)}`);
    } finally {
      if (!signal.aborted) setLoadingPackages(false);
    }
  };

  useEffect(() => {
    loadPackages();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const loadCandidates = async () => {
    if (!selectedPackageId) return;
    const signal = getAbortSignal("candidates");
    setLoadingCandidates(true);
    setCandidateError("");
    try {
      const params = new URLSearchParams();
      params.set("candidate_type", candidateType);
      params.set("search", search);
      params.set("page", String(candidatePage));
      params.set("page_size", String(candidatePageSize));
      const response = await fetch(
        `/api/projects/${projectId}/evidence-design/packages/${encodeURIComponent(selectedPackageId)}/candidates?${params.toString()}`,
        { signal }
      );
      const payload = await readJsonOrThrow(response);
      if (signal.aborted) return;
      setCandidatePageData(payload);
    } catch (error) {
      if (signal.aborted) return;
      setCandidateError(`候选证据加载失败：${apiErrorText(error)}`);
    } finally {
      if (!signal.aborted) setLoadingCandidates(false);
    }
  };

  useEffect(() => {
    loadCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, selectedPackageId, candidateType, search, candidatePage, candidatePageSize]);

  const loadCandidateDetail = async () => {
    if (!selectedPackageId || !selectedCandidateId) return;
    const signal = getAbortSignal("candidate-detail");
    setLoadingCandidateDetail(true);
    setCandidateDetail(null);
    setCandidateReview(null);
    try {
      const [detail, review] = await Promise.all([
        fetch(
          `/api/projects/${projectId}/evidence-design/packages/${encodeURIComponent(selectedPackageId)}/candidates/${encodeURIComponent(selectedCandidateId)}`,
          { signal }
        ).then(readJsonOrThrow),
        fetch(
          `/api/projects/${projectId}/evidence-design/packages/${encodeURIComponent(selectedPackageId)}/candidates/${encodeURIComponent(selectedCandidateId)}/review`,
          { signal }
        ).then(readJsonOrThrow),
      ]);
      if (signal.aborted) return;
      setCandidateDetail(detail);
      setCandidateReview(review);
      setExtractionDraft(Object.entries(review.extraction || {}).map(([k, v]) => ({ key: k, value: v })));
      setAppraisalDraft(review.quality_rating || "");
      setReasonDraft(review.reason || "");
    } catch (error) {
      if (signal.aborted) return;
      setReviewMessage(`证据详情读取失败：${apiErrorText(error)}`);
    } finally {
      if (!signal.aborted) setLoadingCandidateDetail(false);
    }
  };

  useEffect(() => {
    loadCandidateDetail();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, selectedPackageId, selectedCandidateId]);

  const loadPicos = async () => {
    if (!selectedPackageId) return;
    const signal = getAbortSignal("picos");
    setLoadingPicos(true);
    setPicosError("");
    try {
      const response = await fetch(
        `/api/projects/${projectId}/evidence-design/picos-workflow?package_id=${encodeURIComponent(selectedPackageId)}`,
        { signal }
      );
      const payload = await readJsonOrThrow(response);
      if (signal.aborted) return;
      setPicosWorkflow(payload);
      const steps = payload.steps || [];
      if (!steps.some((step) => step.question_id === selectedPicosQuestionId)) {
        setSelectedPicosQuestionId(steps[0]?.question_id || "");
      }
    } catch (error) {
      if (signal.aborted) return;
      setPicosError(`PICOS方案设计加载失败：${apiErrorText(error)}`);
    } finally {
      if (!signal.aborted) setLoadingPicos(false);
    }
  };

  useEffect(() => {
    loadPicos();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, selectedPackageId]);

  const loadAiThreads = async () => {
    if (!selectedPackageId || !selectedPicosQuestionId) return;
    const signal = getAbortSignal("ai-threads");
    try {
      const response = await fetch(
        `/api/projects/${projectId}/evidence-design/picos-workflow/${encodeURIComponent(selectedPackageId)}/ai-revisions?anchor_id=${encodeURIComponent(selectedPicosQuestionId)}`,
        { signal }
      );
      const payload = await response.json();
      if (signal.aborted) return;
      setAiThreads(Array.isArray(payload) ? payload : []);
    } catch {
      if (signal.aborted) return;
      setAiThreads([]);
    }
  };

  useEffect(() => {
    loadAiThreads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, selectedPackageId, selectedPicosQuestionId]);

  const submitReviewAction = async (action, extra = {}) => {
    if (!selectedPackageId || !selectedCandidateId) return;
    setReviewActionBusy(action);
    setReviewMessage("");
    try {
      const response = await fetch(
        `/api/projects/${projectId}/evidence-design/packages/${encodeURIComponent(selectedPackageId)}/candidates/${encodeURIComponent(selectedCandidateId)}/review-actions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action,
            actor: "medical_manager",
            expected_revision: candidateReview?.revision || 0,
            idempotency_key: idempotencyKey("evidence-review"),
            ...extra,
          }),
        }
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(apiDetailText(payload, `${response.status}`));
      setCandidateReview(payload);
      setExtractionDraft(Object.entries(payload.extraction || {}).map(([k, v]) => ({ key: k, value: v })));
      setAppraisalDraft(payload.quality_rating || "");
      setReasonDraft(payload.reason || "");
      await loadCandidates();
      setReviewMessage("审阅状态已保存。");
    } catch (error) {
      setReviewMessage(`审阅失败：${error.message}；请刷新后重试。`);
    } finally {
      setReviewActionBusy("");
    }
  };

  const submitPicosAction = async (questionId, action, extra = {}) => {
    if (!selectedPackageId) return;
    const actionKey = `${questionId}:${action}`;
    setPicosBusyAction(actionKey);
    setPicosMessage("");
    try {
      const response = await fetch(
        `/api/projects/${projectId}/evidence-design/picos-workflow/${encodeURIComponent(selectedPackageId)}/questions/${encodeURIComponent(questionId)}/actions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action,
            actor: "medical_manager",
            expected_revision: picosWorkflow?.revision || 0,
            expected_evidence_package_hash: picosWorkflow?.evidence_package_hash || "",
            idempotency_key: idempotencyKey("picos"),
            ...extra,
          }),
        }
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(apiDetailText(payload, `${response.status}`));
      setPicosWorkflow(payload);
      setPicosMessage(
        action === "select_option" && extra.user_rationale?.trim()
          ? "候选与医学理由已采用，当前PICOS域已由作者确认。"
          : action === "save_rationale"
            ? "医学理由已保存并采用，当前PICOS域已由作者确认。"
            : action === "mark_writing_candidate"
              ? "当前PICOS域已按历史动作完成作者确认。"
              : "PICOS决策已保存。",
      );
    } catch (error) {
      setPicosMessage(`PICOS动作失败：${error.message}`);
    } finally {
      setPicosBusyAction("");
    }
  };

  const generateSnapshotAndHandoff = async () => {
    if (!selectedPackageId) return;
    setApprovalBusy(true);
    setHandoffBusy(true);
    setPicosMessage("");
    try {
      let snapshotId = picosWorkflow?.approved_snapshot_id || "";
      if (
        !snapshotId ||
        !["medically_approved", "locked_for_submission"].includes(
          picosWorkflow?.approval_state,
        )
      ) {
        const snapshotResponse = await fetch(
          `/api/projects/${projectId}/evidence-design/picos-workflow/${encodeURIComponent(selectedPackageId)}/approval-submissions`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              actor: "medical_manager",
              expected_revision: picosWorkflow?.revision || 0,
              expected_evidence_package_hash: picosWorkflow?.evidence_package_hash || "",
              idempotency_key: idempotencyKey("picos-version-snapshot"),
            }),
          },
        );
        const snapshotPayload = await snapshotResponse.json();
        if (!snapshotResponse.ok) {
          throw new Error(apiDetailText(snapshotPayload, `${snapshotResponse.status}`));
        }
        snapshotId = snapshotPayload.snapshot?.snapshot_id || "";
        if (!snapshotId) throw new Error("版本化技术快照未返回有效标识。");
        setPicosWorkflow(snapshotPayload.workflow);
      }
      const handoffResponse = await fetch(
        `/api/projects/${projectId}/evidence-design/picos-workflow/${encodeURIComponent(selectedPackageId)}/writing-handoffs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            actor: "medical_manager",
            snapshot_id: snapshotId,
            target_document_type: "protocol",
            idempotency_key: idempotencyKey("picos-handoff"),
          }),
        }
      );
      const handoffPayload = await handoffResponse.json();
      if (!handoffResponse.ok) {
        throw new Error(apiDetailText(handoffPayload, `${handoffResponse.status}`));
      }
      await loadPicos();
      setPicosMessage(`版本快照与撰写交接已生成：${handoffPayload.handoff_id}。`);
    } catch (error) {
      setPicosMessage(`版本快照或撰写交接生成失败：${error.message}`);
    } finally {
      setApprovalBusy(false);
      setHandoffBusy(false);
    }
  };

  const submitAiRevision = async () => {
    if (!selectedPackageId || !selectedPicosQuestionId || !aiInstruction.trim()) return;
    setAiLoading(true);
    setAiError("");
    try {
      const response = await fetch(
        `/api/projects/${projectId}/evidence-design/picos-workflow/${encodeURIComponent(selectedPackageId)}/ai-revisions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            anchor_type: "picos_question",
            anchor_id: selectedPicosQuestionId,
            user_instruction: aiInstruction.trim(),
            source_evidence_ids: Array.from(checkedCandidateIds),
            expected_picos_revision: picosWorkflow?.revision || 0,
            expected_evidence_package_hash: picosWorkflow?.evidence_package_hash || "",
            actor: "medical_manager",
            idempotency_key: idempotencyKey("ai-revision"),
          }),
        }
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(apiDetailText(payload, `${response.status}`));
      setAiInstruction("");
      await loadAiThreads();
    } catch (error) {
      setAiError(error.message);
    } finally {
      setAiLoading(false);
    }
  };

  const applyAiAction = async (thread, proposal, action) => {
    if (!selectedPackageId) return;
    setAiLoading(true);
    setAiError("");
    try {
      const rewriteDraft = rewriteDrafts[proposal.proposal_id] || "";
      const body = {
        action,
        proposal_id: proposal.proposal_id,
        expected_thread_revision: thread.revision,
        actor: "medical_manager",
        idempotency_key: idempotencyKey("ai-action"),
      };
      if (action === "request_rewrite") {
        if (!rewriteDraft.trim()) {
          setAiError("退回修改时必须填写具体修改要求。");
          setAiLoading(false);
          return;
        }
        body.rewrite_instruction = rewriteDraft.trim();
      }
      const response = await fetch(
        `/api/projects/${projectId}/evidence-design/picos-workflow/${encodeURIComponent(selectedPackageId)}/ai-revisions/${encodeURIComponent(thread.thread_id)}/actions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(apiDetailText(payload, `${response.status}`));
      setRewriteDrafts((current) => ({ ...current, [proposal.proposal_id]: "" }));
      await loadAiThreads();
    } catch (error) {
      setAiError(error.message);
    } finally {
      setAiLoading(false);
    }
  };

  const applyAcceptedToPicos = async (proposal) => {
    if (!proposal || !selectedPicosQuestionId) return;
    await submitPicosAction(selectedPicosQuestionId, "select_option", {
      option_id: proposal.proposed_option_id,
      user_rationale: proposal.rationale,
    });
  };

  const rationaleKey = (questionId) => `${projectId}:${selectedPackageId}:${questionId}`;

  const steps = picosWorkflow?.steps || [];
  const selectedStep = steps.find((step) => step.question_id === selectedPicosQuestionId) || steps[0] || null;
  const selectedOption = selectedStep?.options?.find((option) => option.option_id === selectedStep?.selected_option_id) || null;
  const rationaleValue = picosRationales[rationaleKey(selectedStep?.question_id)] ?? selectedStep?.user_rationale ?? "";
  const canSaveRationale = Boolean(selectedStep?.selected_option_id && rationaleValue.trim());
  const allDomainsConfirmed = steps.length > 0 && steps.every(
    (step) => ["作者已确认", "写作候选"].includes(step.decision_status),
  );
  const preConfirmationBlockingGates = (picosWorkflow?.quality_gates || []).filter(
    (gate) => gate.status === "blocked" &&
      !["picos:gate:author_confirmation", "picos:gate:medical_approval"].includes(gate.gate_id),
  );
  const approvalState = picosWorkflow?.approval_state || "ai_draft";
  const currentHandoffCreated = Boolean(
    picosWorkflow?.current_handoff_id &&
    picosWorkflow?.current_handoff_snapshot_id === picosWorkflow?.approved_snapshot_id &&
    picosWorkflow?.current_handoff_revision === picosWorkflow?.approved_revision &&
    picosWorkflow?.current_handoff_target_document_type === "protocol",
  );
  const canGenerateSnapshotAndHandoff = allDomainsConfirmed &&
    (picosWorkflow?.revision || 0) > 0 &&
    preConfirmationBlockingGates.length === 0 &&
    [
      "ai_draft",
      "in_medical_review",
      "returned_for_revision",
      "medically_approved",
      "locked_for_submission",
    ].includes(approvalState) &&
    !currentHandoffCreated;
  const extractionPayload = Object.fromEntries(
    extractionDraft
      .map((row) => [row.key.trim(), row.value.trim()])
      .filter(([key, value]) => key && value),
  );
  const hasExtraction = Object.keys(extractionPayload).length > 0;

  const candidateRange = useMemo(() => {
    if (!candidatePageData) return "";
    const total = candidatePageData.total || 0;
    const start = total === 0 ? 0 : (candidatePageData.page - 1) * candidatePageData.page_size + 1;
    const end = Math.min(candidatePageData.page * candidatePageData.page_size, total);
    return `${start}-${end} / ${total}`;
  }, [candidatePageData]);

  const onSelectPackage = (packageId) => {
    setSelectedPackageId(packageId);
  };

  const onSelectCandidate = (candidateId) => {
    setSelectedCandidateId(candidateId);
  };

  const toggleCandidateCheck = (candidateId) => {
    setCheckedCandidateIds((prev) => {
      const next = new Set(prev);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  };

  const onPagePrev = () => setCandidatePage((page) => Math.max(1, page - 1));
  const onPageNext = () => setCandidatePage((page) => (candidatePageData?.has_next ? page + 1 : page));

  const onAddExtractionRow = () => {
    setExtractionDraft((rows) => [...rows, { key: "", value: "" }]);
  };

  const onUpdateExtractionRow = (index, field, value) => {
    setExtractionDraft((rows) => {
      const next = [...rows];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const onRemoveExtractionRow = (index) => {
    setExtractionDraft((rows) => rows.filter((_, i) => i !== index));
  };

  const isIncluded = candidateReview?.screening_status === "已纳入";

  return (
    <main className="page evidence-workspace-page">
      <SectionTitle
        eyebrow="证据调研与方案设计"
        title="证据筛选与PICOS方案设计"
        action={
          <div className="evidence-mode-tabs">
            <button
              className={mode === "evidence" ? "active" : ""}
              onClick={() => setMode("evidence")}
              title="候选证据库与结构化审阅"
            >
              <Database size={14} />
              候选证据库
            </button>
            <button
              className={mode === "picos" ? "active" : ""}
              onClick={() => setMode("picos")}
              title="PICOS方案设计"
            >
              <PanelRightOpen size={14} />
              PICOS方案设计
            </button>
          </div>
        }
      />

      <div className="evidence-workspace-boundary">
        本工作面保留来源、质量门和版本边界；医学作者逐域选择并填写理由后，确认即形成项目写作输入，不再进入第二层医学批准。
      </div>

      <div className="evidence-workspace-grid">
        <aside className="evidence-left-rail">
          <div className="evidence-rail-block">
            <h4>资料包</h4>
            {loadingPackages ? (
              <p className="evidence-quiet"><Loader2 size={14} className="spin" /> 加载中...</p>
            ) : packageError ? (
              <p className="evidence-error">{packageError}</p>
            ) : packages.length === 0 ? (
              <p className="evidence-quiet">当前项目未配置证据资料包。</p>
            ) : (
              <div className="evidence-package-list">
                {packages.map((item) => (
                  <button
                    key={item.package_id}
                    className={cn(item.package_id === selectedPackageId && "active")}
                    onClick={() => onSelectPackage(item.package_id)}
                    title={item.package_label}
                  >
                    <strong>{item.package_label}</strong>
                    <span>{item.indication}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {mode === "evidence" && (
            <>
              <div className="evidence-rail-block">
                <h4>候选类型</h4>
                <div className="evidence-type-chips">
                  {CANDIDATE_TYPES.filter((item) => item.key === "all" || selectedPackage?.candidate_count_by_type?.[item.key] !== undefined).map((item) => {
                    const count = selectedPackage?.candidate_count_by_type?.[item.key];
                    return (
                      <button
                        key={item.key}
                        className={cn(candidateType === item.key && "active")}
                        onClick={() => {
                          setCandidateType(item.key);
                          setCandidatePage(1);
                        }}
                        title={item.label}
                      >
                        {item.label}
                        {count !== undefined && count !== null && <span>{count}</span>}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="evidence-rail-block">
                <h4>搜索</h4>
                <div className="evidence-search-row">
                  <Search size={14} />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value);
                      setCandidatePage(1);
                    }}
                    placeholder="标题 / 药物 / 试验号"
                  />
                  {search && (
                    <button onClick={() => setSearch("")} title="清空搜索">
                      <X size={14} />
                    </button>
                  )}
                </div>
              </div>
            </>
          )}

          {mode === "picos" && selectedPackage && (
            <div className="evidence-rail-block">
              <h4>PICOS状态</h4>
              <div className="evidence-picos-stats">
                <div><strong>{picosWorkflow?.decision_count ?? 0}</strong><span>已选择</span></div>
                <div><strong>{picosWorkflow?.writing_candidate_count ?? 0}</strong><span>作者已确认</span></div>
                <div><strong>{picosWorkflow?.blocking_gate_count ?? 0}</strong><span>阻断质量门</span></div>
              </div>
              <button
                className="evidence-refresh-button"
                onClick={loadPicos}
                disabled={loadingPicos}
                title={loadingPicos ? "PICOS方案设计刷新中" : "刷新PICOS方案设计"}
              >
                <RotateCcw size={14} />
                {loadingPicos ? "刷新中" : "刷新"}
              </button>
              <div className="evidence-picos-domain-list evidence-picos-domain-list-left">
                {steps.map((step) => (
                  <button
                    key={step.question_id}
                    className={cn(step.question_id === selectedStep?.question_id && "active")}
                    onClick={() => setSelectedPicosQuestionId(step.question_id)}
                    title={step.writing_target_section}
                  >
                    <span>{step.picos_domain}</span>
                    <strong>{step.writing_target_section}</strong>
                    <Tag tone={picosStatusTone(step.decision_status)}>{picosStatusLabel(step.decision_status)}</Tag>
                  </button>
                ))}
              </div>
            </div>
          )}
        </aside>

        <section className="evidence-main">
          {mode === "evidence" && (
            <div className="evidence-candidate-panel">
              <div className="evidence-synthesis-strip">
                <strong>证据综合</strong>
                <div>
                  {Object.entries(selectedPackage?.candidate_count_by_type || {}).map(([type, count]) => (
                    <span key={type}>{candidateTypeLabel(type)} {formatMaybeNumber(count)}</span>
                  ))}
                </div>
                {(selectedPackage?.diagnostics || []).map((note) => <p key={note}>{note}</p>)}
              </div>
              <div className="evidence-table-toolbar">
                <div className="evidence-table-range">
                  <Filter size={14} />
                  <span>{candidateRange || "—"}</span>
                </div>
                <div className="evidence-table-paging">
                  <button onClick={onPagePrev} disabled={candidatePage <= 1 || loadingCandidates} title="上一页">
                    <ChevronLeft size={14} />
                  </button>
                  <span>第 {candidatePage} 页</span>
                  <button onClick={onPageNext} disabled={!candidatePageData?.has_next || loadingCandidates} title="下一页">
                    <ChevronRight size={14} />
                  </button>
                </div>
                <button
                  className="evidence-refresh-button"
                  onClick={loadCandidates}
                  disabled={loadingCandidates}
                  title={loadingCandidates ? "候选证据加载中" : "刷新候选证据"}
                >
                  <RotateCcw size={14} />
                  {loadingCandidates ? "加载中" : "刷新"}
                </button>
              </div>

              {candidateError && <div className="evidence-error-message">{candidateError}</div>}
              {!candidateError && candidatePageData?.items?.length === 0 && !loadingCandidates && (
                <div className="evidence-empty-state">当前筛选无候选证据。</div>
              )}
              {loadingCandidates && candidatePageData === null && (
                <div className="evidence-empty-state"><Loader2 size={16} className="spin" /> 候选证据加载中...</div>
              )}
              {candidatePageData?.items?.length > 0 && (
                <div className="evidence-table-scroll">
                  <table className="evidence-candidate-table">
                    <thead>
                      <tr>
                        <th className="evidence-col-check"></th>
                        <th>标题</th>
                        <th>来源标识</th>
                        <th>药物/试验</th>
                        <th>分期</th>
                        <th>筛选状态</th>
                        <th>证据质量</th>
                        <th>修订</th>
                      </tr>
                    </thead>
                    <tbody>
                      {candidatePageData.items.map((item) => (
                        <tr
                          key={item.evidence_id}
                          className={cn(selectedCandidateId === item.evidence_id && "selected")}
                          onClick={() => onSelectCandidate(item.evidence_id)}
                        >
                          <td onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={checkedCandidateIds.has(item.evidence_id)}
                              onChange={() => toggleCandidateCheck(item.evidence_id)}
                              title="作为AI建议来源锚点"
                            />
                          </td>
                          <td>
                            <strong>{item.title}</strong>
                            <span className="evidence-subtype">{candidateTypeLabel(item.evidence_type)}</span>
                          </td>
                          <td>{item.primary_source_id}</td>
                          <td>{item.drug_name || "—"}<span>{item.trial_identifier || ""}</span></td>
                          <td>{item.phase || "—"}</td>
                          <td>
                            <Tag tone={statusTone(item.screening_status)}>
                              {screeningStatusLabel(item.screening_status)}
                            </Tag>
                          </td>
                          <td>
                            <Tag tone={qualityTone(item.appraisal_status === "已评价" ? "moderate" : "")}>
                              {appraisalStatusLabel(item.appraisal_status)}
                            </Tag>
                          </td>
                          <td>{item.review_revision}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {mode === "picos" && (
            <div className="evidence-picos-panel">
              {picosError && <div className="evidence-error-message">{picosError}</div>}
              {loadingPicos && !picosWorkflow && (
                <div className="evidence-empty-state"><Loader2 size={16} className="spin" /> PICOS方案设计加载中...</div>
              )}
              {!loadingPicos && !picosWorkflow && !picosError && (
                <div className="evidence-empty-state">尚未生成PICOS方案设计。</div>
              )}
              {picosWorkflow && selectedStep && (
                <div className="evidence-picos-editor">
                  <div className="evidence-picos-question">
                    <Tag tone={picosStatusTone(selectedStep.decision_status)}>{picosStatusLabel(selectedStep.decision_status)}</Tag>
                    <h3>{selectedStep.question}</h3>
                    <p>{selectedStep.current_evidence_summary}</p>
                    <div className="evidence-picos-sources">
                      {(selectedStep.source_refs || []).map((ref) => (
                        <span key={ref}>{safeMetaValue(ref)}</span>
                      ))}
                    </div>
                  </div>
                  <div className="evidence-picos-options">
                    {selectedStep.options.map((option) => (
                      <button
                        key={option.option_id}
                        className={cn(option.option_id === selectedStep.selected_option_id && "selected")}
                        onClick={() => submitPicosAction(selectedStep.question_id, "select_option", {
                          option_id: option.option_id,
                          user_rationale: rationaleValue,
                        })}
                        disabled={Boolean(picosBusyAction)}
                        title={option.label}
                      >
                        <strong>{option.label}</strong>
                        <span>{option.design_summary}</span>
                        <em>{option.medical_rationale_prompt}</em>
                      </button>
                    ))}
                  </div>
                  <label className="evidence-picos-rationale">
                    <span>医学理由与项目口径</span>
                    <textarea
                      value={rationaleValue}
                      onChange={(e) => setPicosRationales((current) => ({
                        ...current,
                        [rationaleKey(selectedStep.question_id)]: e.target.value,
                      }))}
                      placeholder="填写选择理由、适用人群/终点/设计边界、需跨部门确认的事项"
                    />
                  </label>
                  <div className="evidence-picos-actions">
                    <button
                      className="primary-button"
                      disabled={!canSaveRationale || Boolean(picosBusyAction)}
                      onClick={() => submitPicosAction(selectedStep.question_id, "save_rationale", {
                        user_rationale: rationaleValue,
                      })}
                      title="保存医学理由并采用当前候选"
                    >
                      <Save size={14} />
                      保存修订并采用
                    </button>
                    <button
                      disabled={Boolean(picosBusyAction)}
                      onClick={() => submitPicosAction(selectedStep.question_id, "return_for_evidence", {
                        comment: "退回补充来源或跨部门确认。",
                      })}
                      title="退回补证"
                    >
                      <XCircle size={14} />
                      退回补证
                    </button>
                    <button
                      disabled={Boolean(picosBusyAction)}
                      onClick={() => submitPicosAction(selectedStep.question_id, "reset_decision", {
                        comment: "重置当前PICOS决策。",
                      })}
                      title="重置"
                    >
                      <RotateCcw size={14} />
                      重置
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        <aside className="evidence-right-rail">
          {mode === "evidence" && selectedCandidateId && (
            <div className="evidence-detail-panel">
              <h4>证据详情与审阅</h4>
              {loadingCandidateDetail && (
                <p className="evidence-quiet"><Loader2 size={14} className="spin" /> 加载中...</p>
              )}
              {!loadingCandidateDetail && candidateDetail && (
                <>
                  <div className="evidence-detail-head">
                    <Tag tone={statusTone(candidateReview?.screening_status)}>
                      {screeningStatusLabel(candidateReview?.screening_status)}
                    </Tag>
                    <strong>{candidateDetail.title}</strong>
                    <span>{candidateTypeLabel(candidateDetail.evidence_type)} · {candidateDetail.primary_source_id}</span>
                  </div>
                  <div className="evidence-detail-meta">
                    <div><span>药物</span><strong>{candidateDetail.drug_name || "—"}</strong></div>
                    <div><span>试验/登记</span><strong>{candidateDetail.trial_identifier || "—"}</strong></div>
                    <div><span>分期</span><strong>{candidateDetail.phase || "—"}</strong></div>
                    <div><span>来源状态</span><strong>{candidateDetail.source_status || "—"}</strong></div>
                    <div><span>来源日期</span><strong>{candidateDetail.source_date || "—"}</strong></div>
                    <div><span>证据等级</span><strong>{candidateDetail.evidence_level || "—"}</strong></div>
                  </div>
                  <div className="evidence-detail-refs">
                    <span>来源依据</span>
                    <div>
                      {(candidateDetail.source_refs || []).length ? (candidateDetail.source_refs || []).map((ref, idx) => (
                        <span key={idx}>{safeMetaValue(ref)}</span>
                      )) : <span>待补充</span>}
                    </div>
                  </div>
                  {candidateDetail.provenance && Object.keys(candidateDetail.provenance).length > 0 && (
                    <div className="evidence-detail-metadata">
                      <span>来源追溯</span>
                      {Object.entries(candidateDetail.provenance).map(([key, value]) => {
                        const safe = safeMetaValue(value);
                        return safe ? <div key={key}><span>{key}</span><strong>{safe}</strong></div> : null;
                      })}
                    </div>
                  )}
                  {candidateDetail.metadata && Object.keys(candidateDetail.metadata).length > 0 && (
                    <div className="evidence-detail-metadata">
                      <span>元数据</span>
                      {Object.entries(candidateDetail.metadata).map(([k, v]) => {
                        const safe = safeMetaValue(v);
                        return safe ? (
                          <div key={k}>
                            <span>{k}</span>
                            <strong>{safe}</strong>
                          </div>
                        ) : null;
                      })}
                    </div>
                  )}

                  <div className="evidence-detail-actions">
                    <button
                      className="primary-button"
                      disabled={Boolean(reviewActionBusy) || isIncluded}
                      onClick={() => submitReviewAction("include")}
                      title="纳入该证据"
                    >
                      <CheckCircle2 size={14} /> 纳入
                    </button>
                    <button
                      disabled={Boolean(reviewActionBusy) || !reasonDraft.trim()}
                      onClick={() => submitReviewAction("exclude", { reason: reasonDraft })}
                      title="排除该证据，需填写理由"
                    >
                      <XCircle size={14} /> 排除
                    </button>
                    <button
                      disabled={Boolean(reviewActionBusy) || !reasonDraft.trim()}
                      onClick={() => submitReviewAction("defer", { reason: reasonDraft })}
                      title="暂缓，需填写理由"
                    >
                      <AlertTriangle size={14} /> 暂缓
                    </button>
                    <button
                      disabled={Boolean(reviewActionBusy) || !reasonDraft.trim()}
                      onClick={() => submitReviewAction("mark_duplicate", { reason: reasonDraft })}
                      title="标记重复，需填写理由"
                    >
                      <MessageSquareText size={14} /> 重复
                    </button>
                    <button
                      disabled={Boolean(reviewActionBusy) || !candidateReview?.revision}
                      onClick={() => submitReviewAction("reset_review")}
                      title="重置审阅"
                    >
                      <RotateCcw size={14} /> 重置
                    </button>
                  </div>

                  <label className="evidence-detail-reason">
                    <span>理由/备注</span>
                    <textarea
                      value={reasonDraft}
                      onChange={(e) => setReasonDraft(e.target.value)}
                      placeholder="排除、暂缓、重复时必须填写具体理由"
                    />
                  </label>

                  <div className="evidence-detail-section">
                    <h5>结构化提取</h5>
                    {extractionDraft.map((row, index) => (
                      <div className="evidence-extraction-row" key={index}>
                        <input
                          type="text"
                          value={row.key}
                          onChange={(e) => onUpdateExtractionRow(index, "key", e.target.value)}
                          placeholder="字段"
                          disabled={!isIncluded}
                        />
                        <input
                          type="text"
                          value={row.value}
                          onChange={(e) => onUpdateExtractionRow(index, "value", e.target.value)}
                          placeholder="值"
                          disabled={!isIncluded}
                        />
                        <button onClick={() => onRemoveExtractionRow(index)} disabled={!isIncluded} title="删除行">
                          <X size={14} />
                        </button>
                      </div>
                    ))}
                    <button
                      className="evidence-add-row"
                      onClick={onAddExtractionRow}
                      disabled={!isIncluded}
                      title={isIncluded ? "添加结构化提取字段" : "纳入后才可编辑结构化提取"}
                    >
                      + 添加字段
                    </button>
                    <button
                      className="evidence-save-extraction"
                      disabled={!isIncluded || !hasExtraction || Boolean(reviewActionBusy)}
                      onClick={() => submitReviewAction("save_extraction", { extraction: extractionPayload })}
                      title="保存结构化提取"
                    >
                      <Save size={14} /> 保存结构化提取
                    </button>
                  </div>

                  <div className="evidence-detail-section">
                    <h5>证据质量评价</h5>
                    <div className="evidence-appraisal-options">
                      {APPRAISAL_OPTIONS.map((option) => (
                        <button
                          key={option.key}
                          className={cn(appraisalDraft === option.key && "selected")}
                          onClick={() => setAppraisalDraft(option.key)}
                          disabled={!isIncluded}
                          title={option.label}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                    <button
                      className="evidence-save-appraisal"
                      disabled={!isIncluded || !appraisalDraft || Boolean(reviewActionBusy)}
                      onClick={() => submitReviewAction("save_appraisal", { quality_rating: appraisalDraft })}
                      title="保存证据质量评价"
                    >
                      <Save size={14} /> 保存评价
                    </button>
                  </div>

                  {reviewMessage && <div className="evidence-review-message">{reviewMessage}</div>}
                </>
              )}
              {!selectedCandidateId && (
                <p className="evidence-quiet">在候选表中选择一项以查看详情与审阅。</p>
              )}
            </div>
          )}

          {mode === "picos" && selectedStep && (
            <div className="evidence-picos-right">
              <div className="evidence-picos-summary">
                <h4>当前候选</h4>
                <div><span>目标章节</span><strong>{selectedStep.writing_target_section}</strong></div>
                <div><span>当前候选</span><strong>{selectedOption?.label || "尚未选择"}</strong></div>
                <div>
                  <span>流转状态</span>
                  <Tag tone={selectedStep.author_confirmation_status === "confirmed" ? "success" : "warning"}>
                    {selectedStep.writing_handoff_status}
                  </Tag>
                </div>
              </div>
              <div className="evidence-picos-handoff">
                <h4>版本快照与撰写交接</h4>
                <p className="evidence-picos-handoff-note">
                  全部PICOS域均已采用且质量门通过后，一键生成绑定当前来源哈希与revision的技术快照和撰写交接。
                </p>
                <button
                  className={currentHandoffCreated ? "evidence-complete-button" : "primary-button"}
                  disabled={!canGenerateSnapshotAndHandoff || approvalBusy || handoffBusy}
                  onClick={generateSnapshotAndHandoff}
                  title={
                    currentHandoffCreated
                      ? "当前版本的技术快照与撰写交接已生成"
                      : canGenerateSnapshotAndHandoff
                        ? "生成当前版本技术快照并创建撰写交接"
                        : "需先采用全部PICOS域并通过质量门"
                  }
                >
                  {approvalBusy || handoffBusy
                    ? "生成中"
                    : currentHandoffCreated
                      ? "版本快照与撰写交接已生成"
                      : "生成版本快照与撰写交接"}
                </button>
                {picosMessage && <div className="evidence-picos-message">{picosMessage}</div>}
              </div>
            </div>
          )}

          {mode === "picos" && selectedStep && (
            <div className="evidence-ai-panel">
              <h4>AI建议修订</h4>
              <div className="evidence-ai-boundary">
                AI仅提供建议；采纳后需通过“应用到PICOS”才能修改当前决策。
              </div>
              {aiGatewayStatus?.semantic_ai_tasks_enabled === true ? (
                <>
                  <label className="evidence-ai-instruction">
                    <span>修订指令</span>
                    <textarea
                      value={aiInstruction}
                      onChange={(e) => setAiInstruction(e.target.value)}
                      placeholder="输入具体修订要求，例如：目标人群增加既往补体抑制剂经治分层"
                      disabled={aiLoading}
                    />
                  </label>
                  <div className="evidence-ai-anchors">
                    <span>已选证据锚点 ({checkedCandidateIds.size})</span>
                    <div>
                      {Array.from(checkedCandidateIds).map((id) => (
                        <span key={id} title={id}>{id.split(":").pop()}</span>
                      ))}
                    </div>
                  </div>
                  <button
                    className="primary-button"
                    disabled={!aiInstruction.trim() || aiLoading || checkedCandidateIds.size === 0}
                    onClick={submitAiRevision}
                    title={checkedCandidateIds.size === 0 ? "请先在候选证据表中勾选锚点" : "提交AI建议"}
                  >
                    <Sparkles size={14} />
                    {aiLoading ? "AI思考中" : "获取AI建议"}
                  </button>
                </>
              ) : (
                <div className="evidence-ai-disabled">
                  <AlertTriangle size={14} />
                  <span>
                    独立AI未配置或未获私有化执行许可；当前不会生成替代建议。
                  </span>
                </div>
              )}
              {aiError && <div className="evidence-error-message">{aiError}</div>}
              {aiThreads.length > 0 && (
                <div className="evidence-ai-threads">
                  {aiThreads.map((thread) => (
                    <div key={thread.thread_id} className="evidence-ai-thread">
                      <div className="evidence-ai-thread-head">
                        <span>指令：{thread.user_instruction}</span>
                        <span>修订 {thread.revision}</span>
                      </div>
                      {thread.proposals.map((proposal) => (
                        <div key={proposal.proposal_id} className="evidence-ai-proposal">
                          <div><span>建议</span><strong>{proposal.proposal_text}</strong></div>
                          <div><span>理由</span><p>{proposal.rationale}</p></div>
                          <div><span>不确定性</span><p>{proposal.uncertainty || "未说明"}</p></div>
                          <div><span>AI run</span><p>{proposal.ai_run_id}</p></div>
                          <div><span>证据锚点</span><p>{(proposal.evidence_span_ids || []).map(safeMetaValue).join("；") || "未提供"}</p></div>
                          <div><span>状态</span><Tag tone={proposal.user_decision === "accepted" ? "success" : proposal.user_decision === "pending" ? "warning" : "neutral"}>{proposal.user_decision || "pending"}</Tag></div>
                          {proposal.user_decision === "pending" && (
                            <div className="evidence-ai-proposal-actions">
                              <button
                                onClick={() => applyAiAction(thread, proposal, "accept")}
                                disabled={aiLoading}
                                title="采纳建议"
                              >
                                <ThumbsUp size={14} /> 采纳建议
                              </button>
                              <button
                                onClick={() => applyAiAction(thread, proposal, "reject")}
                                disabled={aiLoading}
                                title="拒绝建议"
                              >
                                <ThumbsDown size={14} /> 拒绝建议
                              </button>
                              <button
                                onClick={() => applyAiAction(thread, proposal, "request_rewrite")}
                                disabled={aiLoading || !(rewriteDrafts[proposal.proposal_id] || "").trim()}
                                title="退回修改，需填写修改要求"
                              >
                                <RotateCcw size={14} /> 退回修改
                              </button>
                            </div>
                          )}
                          {proposal.user_decision === "pending" && (
                            <label className="evidence-ai-rewrite">
                              <span>修改要求</span>
                              <textarea
                                value={rewriteDrafts[proposal.proposal_id] || ""}
                                onChange={(e) => setRewriteDrafts((current) => ({ ...current, [proposal.proposal_id]: e.target.value }))}
                                placeholder="填写退回修改的具体要求"
                              />
                            </label>
                          )}
                          {proposal.user_decision === "accepted" && (
                            <div className="evidence-ai-apply">
                              <button
                                className="primary-button"
                                onClick={() => applyAcceptedToPicos(proposal)}
                                title="将已采纳的建议应用到当前PICOS决策"
                              >
                                应用到PICOS
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}

export default EvidenceDesignPage;
