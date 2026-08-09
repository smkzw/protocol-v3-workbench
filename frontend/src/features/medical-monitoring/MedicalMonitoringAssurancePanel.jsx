import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  ClipboardCheck,
  Database,
  History,
  MapPin,
  RefreshCw,
  ShieldAlert,
  UserRound,
  XCircle,
} from "lucide-react";

import {
  createMedicalMonitoringAssuranceApi,
  MedicalMonitoringAssuranceApiError,
} from "./medicalMonitoringAssuranceApi.mjs";
import {
  ASSURANCE_MODES,
  FROZEN_IDENTITY_FIELDS,
  assuranceEvidenceState,
  assuranceActionAvailability,
  assuranceAuditActionLabel,
  assuranceModeLabel,
  assuranceModeDescription,
  assuranceReadinessInput,
  assuranceReadinessPayload,
  assuranceReadinessState,
  assuranceStatusLabel,
  assuranceStatusTone,
  assuranceTaskCreationAllowed,
  assuranceTaskDisplayKey,
  assuranceTaskList,
  completeFrozenIdentity,
  missingFrozenIdentityFields,
} from "./medicalMonitoringAssurance.mjs";
import {
  assuranceRollupNumber,
  assuranceRollupRowDisplayKey,
  projectAssuranceRollup,
} from "./medicalMonitoringAssuranceRollup.mjs";
import {
  MedicalMonitoringAssuranceShapeError,
  normalizeAssuranceCreateResponse,
  normalizeAssuranceAuditPayload,
  normalizeAssuranceProofPayload,
  normalizeAssuranceReadinessPayload,
  normalizeAssuranceRollupPayload,
  normalizeAssuranceTaskList,
  normalizeAssuranceTaskPayload,
} from "./medicalMonitoringAssuranceView.mjs";
import {
  MedicalMonitoringPrincipalShapeError,
  monitoringPrincipalBlocker,
  monitoringPrincipalReady,
  monitoringPrincipalStatusLabel,
  normalizeMonitoringPrincipal,
} from "./medicalMonitoringPrincipal.mjs";
import MedicalMonitoringAssuranceRemediation from "./MedicalMonitoringAssuranceRemediation.jsx";
import {
  createMedicalMonitoringProjectRequestScope,
} from "./medicalMonitoringProjectRequestScope.mjs";
import "./MedicalMonitoringAssurancePanel.css";

function requestKey(prefix) {
  const random = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`;
}

function apiErrorMessage(error, fallback) {
  if (error instanceof MedicalMonitoringAssuranceApiError) return error.message;
  return error?.message || fallback;
}

function readIdentity({ currentSnapshot, sourceManifest, rawMonitoring }) {
  return currentSnapshot?.assurance_frozen_identity
    || sourceManifest?.assurance_frozen_identity
    || rawMonitoring?.assurance_frozen_identity
    || {};
}

function readPrincipal({ currentSnapshot, sourceManifest, rawMonitoring }) {
  return currentSnapshot?.monitoring_principal
    || sourceManifest?.monitoring_principal
    || rawMonitoring?.monitoring_principal
    || null;
}

function snapshotFacts(currentSnapshot = {}) {
  return [
    ["风险快照", currentSnapshot.snapshot_id || "未生成"],
    ["来源修订", currentSnapshot.source_revision || "未返回"],
    ["规则修订", currentSnapshot.rule_profile_revision || "未返回"],
    ["引擎版本", currentSnapshot.engine_version || "未返回"],
  ];
}

function EvidenceCard({ label, value, tone = "neutral" }) {
  return (
    <div className={`monitoring-assurance-evidence ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RollupStat({ label, value, tone = "neutral" }) {
  return (
    <div className={`monitoring-assurance-rollup-stat ${tone}`}>
      <span>{label}</span>
      <strong>{assuranceRollupNumber(value)}</strong>
    </div>
  );
}

function explicitArrayCount(value) {
  return Array.isArray(value) ? value.length : null;
}

function shortHash(value) {
  const text = String(value || "");
  return text ? `${text.slice(0, 10)}…${text.slice(-6)}` : "待返回";
}

function AssuranceAuditChain({ audit, loading, error, blockedReason, onRetry }) {
  if (blockedReason) {
    return (
      <section className="monitoring-assurance-audit blocked" aria-label="保障任务审计链读取阻断">
        <div className="monitoring-assurance-audit-title"><strong><ShieldAlert size={14} /> 审计链</strong><span>身份阻断</span></div>
        <div className="monitoring-assurance-audit-notice"><ShieldAlert size={15} /><div><strong>暂不能读取服务端审计链</strong><span>{blockedReason}</span></div></div>
      </section>
    );
  }
  if (loading) {
    return (
      <section className="monitoring-assurance-audit" aria-label="保障任务审计链读取中" role="status">
        <div className="monitoring-assurance-audit-title"><strong><History size={14} /> 审计链</strong><span>读取中</span></div>
        <p className="monitoring-assurance-audit-empty">正在读取服务端链证据。</p>
      </section>
    );
  }
  if (error) {
    return (
      <section className="monitoring-assurance-audit error" aria-label="保障任务审计链读取失败">
        <div className="monitoring-assurance-audit-title"><strong><History size={14} /> 审计链</strong><span>读取失败</span></div>
        <div className="monitoring-assurance-audit-notice"><ShieldAlert size={15} /><div><strong>链证据未加载</strong><span>{error}</span></div><button type="button" onClick={onRetry}>重试</button></div>
      </section>
    );
  }
  if (!audit) return null;
  if (!audit.items.length) {
    return (
      <section className="monitoring-assurance-audit empty" aria-label="保障任务审计链为空">
        <div className="monitoring-assurance-audit-title"><strong><History size={14} /> 审计链</strong><span>0 条</span></div>
        <p className="monitoring-assurance-audit-empty">当前任务尚无服务端审计事件；空链已由服务端身份授权后返回。</p>
      </section>
    );
  }
  return (
    <section className="monitoring-assurance-audit" aria-label="保障任务审计链">
      <div className="monitoring-assurance-audit-title"><strong><History size={14} /> 审计链</strong><span>{audit.items.length} 条 · 服务端已校验</span></div>
      <ol className="monitoring-assurance-audit-list">
        {audit.items.map((event, index) => (
          <li key={event.audit_id}>
            <span className="monitoring-assurance-audit-index">{index + 1}</span>
            <div><strong>{assuranceAuditActionLabel(event.action)}</strong><small>{event.occurred_at} · v{event.aggregate_version_before} → v{event.aggregate_version_after}</small></div>
            <code title={event.event_hash}>{shortHash(event.event_hash)}</code>
          </li>
        ))}
      </ol>
      <p className="monitoring-assurance-audit-footnote">验证身份：{audit.principal_id}；仅展示链摘要，不展开原始审计 payload。</p>
    </section>
  );
}

function AssuranceReadiness({ readiness, loading, error, blockedReason, input }) {
  const state = assuranceReadinessState({ readiness, input });
  if (blockedReason) {
    return (
      <section className="monitoring-assurance-readiness blocked" aria-label="保障任务 readiness 阻断">
        <div className="monitoring-assurance-readiness-title"><strong><ClipboardCheck size={14} /> 覆盖与冻结身份 readiness</strong><span>阻断</span></div>
        <div className="monitoring-assurance-readiness-notice"><ShieldAlert size={15} /><div><strong>暂不能核验完成门</strong><span>{blockedReason}</span></div></div>
      </section>
    );
  }
  if (loading) {
    return (
      <section className="monitoring-assurance-readiness" aria-label="保障任务 readiness 读取中" role="status">
        <div className="monitoring-assurance-readiness-title"><strong><ClipboardCheck size={14} /> 覆盖与冻结身份 readiness</strong><span>读取中</span></div>
        <p className="monitoring-assurance-readiness-empty">正在核验当前任务的冻结身份与项目/中心/个例覆盖。</p>
      </section>
    );
  }
  if (error) {
    return (
      <section className="monitoring-assurance-readiness error" aria-label="保障任务 readiness 读取失败">
        <div className="monitoring-assurance-readiness-title"><strong><ClipboardCheck size={14} /> 覆盖与冻结身份 readiness</strong><span>读取失败</span></div>
        <div className="monitoring-assurance-readiness-notice"><ShieldAlert size={15} /><div><strong>readiness 未加载</strong><span>{error}</span></div></div>
      </section>
    );
  }
  if (!readiness && !input?.available) return null;
  return (
    <section className={`monitoring-assurance-readiness ${state.tone}`} aria-label="保障任务 readiness">
      <div className="monitoring-assurance-readiness-title"><strong><ClipboardCheck size={14} /> 覆盖与冻结身份 readiness</strong><span>{state.label}</span></div>
      {input?.available && (
        <div className="monitoring-assurance-readiness-counts" aria-label="readiness 覆盖计数">
          <span>受试者 <b>{input.actual_subjects}</b></span>
          <span>中心 <b>{input.actual_sites}</b></span>
          <span>关键域 <b>{input.critical_domains_expected ? `${input.critical_domains_covered}/${input.critical_domains_expected}` : "未配置"}</b></span>
        </div>
      )}
      <div className="monitoring-assurance-readiness-content">
        <strong>{state.ready ? "当前任务可进入证据完成门" : "当前任务仍不能进入证据完成门"}</strong>
        <span>{state.ready ? "服务端已确认冻结身份未漂移，且已提供项目、中心与个例覆盖计数。" : state.blockingReason}</span>
      </div>
    </section>
  );
}

function AssuranceActionStatus({ availability, task, evidence }) {
  const summary = task || {};
  const evidenceReady = evidence?.ready === true;
  const reviewReady = summary.medical_review_recorded === true;
  const completed = summary.status === "completed";
  const rows = [
    {
      label: "证据生成",
      state: evidenceReady ? "已具备" : availability.canRecordEvidence ? "待受控生成" : "阻断",
      tone: evidenceReady ? "success" : availability.canRecordEvidence ? "warning" : "danger",
      detail: evidenceReady ? evidence.label : (availability.evidenceBlocker || "尚未形成可核验证据。"),
    },
    {
      label: "医学复核",
      state: reviewReady ? "已记录" : availability.canReview ? "待复核" : "阻断",
      tone: reviewReady ? "success" : availability.canReview ? "warning" : "danger",
      detail: reviewReady ? "服务端已记录医学复核。" : (availability.reviewBlocker || "证据未先完成，不能进入医学复核。"),
    },
    {
      label: "完成保障",
      state: completed ? "已完成" : availability.canComplete ? "待确认" : "阻断",
      tone: completed ? "success" : availability.canComplete ? "warning" : "danger",
      detail: completed ? "任务已由服务端完成。" : (availability.completeBlocker || "完成前仍需满足所有完成门。"),
    },
  ];
  return (
    <section className="monitoring-assurance-action-status" aria-label="保障动作完成顺序">
      <div className="monitoring-assurance-action-status-title"><strong><ClipboardCheck size={14} /> 动作完成顺序</strong><span>服务端门禁</span></div>
      <div className="monitoring-assurance-action-status-list">
        {rows.map((row) => (
          <div className={`monitoring-assurance-action-status-row ${row.tone}`} key={row.label}>
            <span className="monitoring-assurance-action-status-label">{row.label}</span>
            <strong>{row.state}</strong>
            <small>{row.detail}</small>
          </div>
        ))}
      </div>
      <p className="monitoring-assurance-action-status-note">当前仅展示服务端动作合同与阻断原因；不会在 readiness 未通过或运行时 gate 未放行时替用户提交证据、复核或签名。</p>
    </section>
  );
}

function AssuranceProvenanceDisclosure({ provenanceStatus }) {
  if (provenanceStatus !== "mixed_provenance") return null;
  return (
    <details className="monitoring-assurance-provenance">
      <summary><ShieldAlert size={14} /> 为什么当前 proof 不能作为完成证据</summary>
      <div className="monitoring-assurance-provenance-body">
        <p>当前 proof 同时包含服务端重算结果与调用方携带字段；在这些字段尚未全部绑定到可复核的服务端权威执行来源前，它只能用于只读诊断，不能通过锁库前完成门。</p>
        <div className="monitoring-assurance-provenance-grid">
          <div><strong>可以做什么</strong><span>查看返回结构、定位失败或缺口，并把问题交给正式复核。</span></div>
          <div><strong>仍缺什么</strong><span>服务端 evidence-run ledger，或签名清单的全字段服务端重验。</span></div>
        </div>
        <small>待选择并实现一种证据权威路线后，系统才会重新核验；当前状态不代表项目已完成。</small>
      </div>
    </details>
  );
}

function AssuranceRollup({ rollup, onClose, onRiskScopeChange, onSelectSubject, onOpenSubjectView }) {
  const view = projectAssuranceRollup(rollup);
  const severityEntries = view.distributions.severity.slice(0, 4);
  const maxSeverity = Math.max(1, ...severityEntries.map((entry) => entry.value));
  const subjectRows = view.subjects.slice(0, 8);
  const siteRows = view.sites.slice(0, 6);
  const openSite = (row) => {
    if (!onRiskScopeChange || row?.identityState !== "ready") return;
    onClose?.();
    onRiskScopeChange("site", { siteId: row.siteId });
  };
  const openSubject = (row, page) => {
    if (!onOpenSubjectView || row?.identityState !== "ready" || !row.subjectId) return;
    onSelectSubject?.(row.subjectId);
    onClose?.();
    onOpenSubjectView(page, "", row.subjectId);
  };
  const focusRemediation = (row) => {
    if (row.subjectId && row.subjectId !== "未标识受试者" && onOpenSubjectView) {
      onSelectSubject?.(row.subjectId);
      onClose?.();
      onOpenSubjectView("patientProfile", "", row.subjectId);
      return;
    }
    if (row.siteId && row.siteId !== "未标识中心") {
      onClose?.();
      onRiskScopeChange?.("site", { siteId: row.siteId });
    }
  };

  return (
    <section className="monitoring-assurance-rollup" aria-label="项目中心受试者三级风险总览">
      <div className="monitoring-assurance-section-title">
        <strong><BarChart3 size={15} /> 三级风险总览</strong>
        <span>{view.riskSnapshotId ? `快照 ${view.riskSnapshotId}` : "当前任务汇总"}</span>
      </div>
      <div className="monitoring-assurance-rollup-stats">
        <RollupStat label="项目风险" value={view.trial.totalRiskCount} />
        <RollupStat label="开放风险" value={view.trial.openRiskCount} tone="warning" />
        <RollupStat label="开放高风险" value={view.trial.openHighRiskCount} tone="danger" />
        <RollupStat label="已关闭" value={view.trial.closedRiskCount} tone="success" />
        <RollupStat label="缺关闭证据" value={view.trial.closedWithoutEvidenceCount} tone={view.trial.closedWithoutEvidenceCount ? "danger" : "neutral"} />
      </div>
      <div className={`monitoring-assurance-conservation ${view.conservation.ok ? "ok" : "blocked"}`} role="status">
        <strong>{view.conservation.ok ? "三级对账通过" : "三级对账阻断"}</strong>
        <span>{view.conservation.ok ? "项目、中心、个例使用同一 risk_instance_id 集合。" : "风险身份或显式计数不守恒；当前只读展示，不允许完成保障任务。"}</span>
      </div>
      {severityEntries.length > 0 && (
        <div className="monitoring-assurance-distribution" aria-label="风险严重度分布">
          <div className="monitoring-assurance-mini-title">严重度分布</div>
          {severityEntries.map((entry) => (
            <div className="monitoring-assurance-distribution-row" key={entry.label}>
              <span>{entry.label}</span>
              <i><b style={{ width: `${Math.round((entry.value / maxSeverity) * 100)}%` }} /></i>
              <strong>{entry.value}</strong>
            </div>
          ))}
        </div>
      )}
      <div className="monitoring-assurance-rollup-grid">
        <div className="monitoring-assurance-rollup-list">
          <div className="monitoring-assurance-mini-title"><MapPin size={14} /> 中心层 <span>{view.sites.length} 个</span></div>
          {!siteRows.length && <p className="monitoring-assurance-rollup-empty">暂无中心级风险引用。</p>}
          {siteRows.map((row, index) => (
            <div className="monitoring-assurance-rollup-row" key={assuranceRollupRowDisplayKey(row, "site", index)}>
              <div><strong>{row.siteId}</strong><small>{assuranceRollupNumber(row.totalRiskCount)} 项风险 · 开放 {assuranceRollupNumber(row.openRiskCount)}</small></div>
              <span className={row.openHighRiskCount ? "danger" : "neutral"}>高风险 {assuranceRollupNumber(row.openHighRiskCount)}</span>
              {row.identityState === "ready" && onRiskScopeChange
                ? <button type="button" title={`查看中心 ${row.siteId} 的风险`} onClick={() => openSite(row)}><ArrowUpRight size={14} /></button>
                : <small title={row.identityIssue}>身份待核对，仅可读</small>}
            </div>
          ))}
          {view.sites.length > siteRows.length && <small className="monitoring-assurance-rollup-more">仅显示开放风险优先的前 {siteRows.length} 个中心。</small>}
        </div>
        <div className="monitoring-assurance-rollup-list">
          <div className="monitoring-assurance-mini-title"><UserRound size={14} /> 个例层 <span>{view.subjects.length} 个</span></div>
          {!subjectRows.length && <p className="monitoring-assurance-rollup-empty">暂无个例级风险引用。</p>}
          {subjectRows.map((row, index) => (
            <div className="monitoring-assurance-rollup-row subject" key={assuranceRollupRowDisplayKey(row, "subject", index)}>
              <div><strong>{row.subjectId}</strong><small>中心 {row.siteId} · 风险 {assuranceRollupNumber(row.totalRiskCount)} · 开放 {assuranceRollupNumber(row.openRiskCount)}</small></div>
              {row.identityState === "ready" && onOpenSubjectView ? (
                <span className="monitoring-assurance-subject-actions">
                  <button type="button" title={`打开 ${row.subjectId} Patient Profile`} onClick={() => openSubject(row, "patientProfile")}>Profile</button>
                  <button type="button" title={`打开 ${row.subjectId} Subject Timeline`} onClick={() => openSubject(row, "subjectTimeline")}>Timeline</button>
                </span>
              ) : <small title={row.identityIssue}>身份待核对，仅可读</small>}
            </div>
          ))}
          {view.subjects.length > subjectRows.length && <small className="monitoring-assurance-rollup-more">仅显示开放风险优先的前 {subjectRows.length} 个个例。</small>}
        </div>
      </div>
      <MedicalMonitoringAssuranceRemediation matrix={rollup?.remediation_matrix} onFocusRow={focusRemediation} />
    </section>
  );
}

export default function MedicalMonitoringAssurancePanel(props) {
  return (
    <MedicalMonitoringAssurancePanelForProject
      key={props.projectId}
      {...props}
    />
  );
}

function MedicalMonitoringAssurancePanelForProject({
  projectId,
  open,
  onClose,
  onOpenSubjectView,
  onRiskScopeChange,
  onSelectSubject,
  currentSnapshot,
  sourceManifest,
  rawMonitoring,
}) {
  const api = useMemo(() => createMedicalMonitoringAssuranceApi(), []);
  const requestScope = useMemo(
    () => createMedicalMonitoringProjectRequestScope(projectId),
    [projectId],
  );
  const [mode, setMode] = useState("pre_lock");
  const [items, setItems] = useState([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedTask, setSelectedTask] = useState(null);
  const [proof, setProof] = useState(null);
  const [proofProvenanceStatus, setProofProvenanceStatus] = useState("");
  const [rollup, setRollup] = useState(null);
  const [audit, setAudit] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState("");
  const [auditBlockedReason, setAuditBlockedReason] = useState("");
  const [readiness, setReadiness] = useState(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [readinessError, setReadinessError] = useState("");
  const [readinessBlockedReason, setReadinessBlockedReason] = useState("");
  const [readinessInput, setReadinessInput] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [principalClock, setPrincipalClock] = useState(() => Date.now());
  const frozenIdentity = useMemo(
    () => readIdentity({ currentSnapshot, sourceManifest, rawMonitoring }),
    [currentSnapshot, rawMonitoring, sourceManifest],
  );
  const identityReady = completeFrozenIdentity(frozenIdentity);
  const missingIdentity = missingFrozenIdentityFields(frozenIdentity);
  const authorityWritePermitted = currentSnapshot?.assurance_write_permitted === true
    || sourceManifest?.assurance_write_permitted === true
    || rawMonitoring?.assurance_write_permitted === true;
  const principalState = useMemo(() => {
    const rawPrincipal = readPrincipal({ currentSnapshot, sourceManifest, rawMonitoring });
    if (!rawPrincipal) return { principal: null, error: "" };
    try {
      return {
        principal: normalizeMonitoringPrincipal(rawPrincipal, { projectId }),
        error: "",
      };
    } catch (nextError) {
      return {
        principal: null,
        error: nextError instanceof MedicalMonitoringPrincipalShapeError
          ? nextError.message
          : "服务端认证 principal 结构无法验证。",
      };
    }
  }, [currentSnapshot, projectId, rawMonitoring, sourceManifest]);
  useEffect(() => {
    const expiresAt = principalState.principal?.expiresAt;
    if (!expiresAt) return undefined;
    const remaining = new Date(expiresAt).getTime() - Date.now();
    if (!Number.isFinite(remaining) || remaining <= 0) {
      setPrincipalClock(Date.now());
      return undefined;
    }
    const timer = globalThis.setTimeout(() => setPrincipalClock(Date.now()), remaining + 1);
    return () => globalThis.clearTimeout(timer);
  }, [principalState.principal?.expiresAt]);
  const principalNow = useMemo(() => new Date(principalClock), [principalClock]);
  const principalReady = monitoringPrincipalReady(principalState.principal, { projectId, now: principalNow });
  const taskCreationAllowed = assuranceTaskCreationAllowed(frozenIdentity, authorityWritePermitted)
    && principalReady;
  const taskSummaries = useMemo(() => assuranceTaskList(items), [items]);
  const activeTask = selectedTask || taskSummaries.find((task) => task.id === selectedTaskId && task.identityState === "ready") || null;
  const evidence = assuranceEvidenceState({ task: selectedTask || activeTask || { mode }, proof, rollup });
  const visibleEvidence = proofProvenanceStatus === "mixed_provenance" && !proof
    ? {
      ...evidence,
      label: "证据来源混合",
      provenanceStatus: proofProvenanceStatus,
      ready: false,
      blockingReason: "证据来源混合，不能作为全量重算完成证明。",
    }
    : { ...evidence, blockingReason: evidence.blockingReason };
  const actionAvailability = useMemo(() => assuranceActionAvailability({
    task: selectedTask || activeTask || { mode },
    principalReady,
    authorityWritePermitted,
    evidenceReady: visibleEvidence.ready,
    evidenceRecorded: Boolean(proof || rollup),
    evidenceBlockingReason: evidence.blockingReason,
    ...(visibleEvidence.provenanceStatus === "mixed_provenance"
      ? { evidenceBlockingReason: visibleEvidence.blockingReason }
      : {}),
    readinessReady: readiness?.ready === true,
  }), [activeTask, authorityWritePermitted, mode, principalReady, proof, readiness?.ready, rollup, selectedTask, visibleEvidence.blockingReason, visibleEvidence.ready]);

  const clearLoadedState = useCallback(() => {
    setItems([]);
    setSelectedTaskId("");
    setSelectedTask(null);
    setProof(null);
    setProofProvenanceStatus("");
    setRollup(null);
    setAudit(null);
    setAuditError("");
    setAuditBlockedReason("");
    setReadiness(null);
    setReadinessError("");
    setReadinessBlockedReason("");
    setReadinessInput(null);
  }, []);

  const loadTasks = useCallback(async (nextMode = mode) => {
    if (!projectId) return;
    const request = requestScope.begin("assurance-task-list");
    setLoading(true);
    setError("");
    try {
      const payload = normalizeAssuranceTaskList(
        await api.listTasks(projectId, { mode: nextMode, signal: request.signal }),
        { projectId, mode: nextMode },
      );
      if (!requestScope.isCurrent(request)) return;
      const nextItems = Array.isArray(payload.items) ? payload.items : [];
      setItems(nextItems);
      const nextTaskSummaries = assuranceTaskList(nextItems);
      const nextId = nextTaskSummaries.find((task) => task.identityState === "ready")?.id || "";
      setSelectedTaskId((current) => current && nextTaskSummaries.some((task) => task.id === current && task.identityState === "ready") ? current : nextId);
      if (!nextId) {
        setSelectedTask(null);
        setProof(null);
        setProofProvenanceStatus("");
        setRollup(null);
      }
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      if (nextError instanceof MedicalMonitoringAssuranceShapeError || nextError?.name !== "AbortError") {
        clearLoadedState();
        setError(apiErrorMessage(nextError, "保障任务读取失败。"));
      }
    } finally {
      if (requestScope.isCurrent(request)) setLoading(false);
      requestScope.finish(request);
    }
  }, [api, clearLoadedState, mode, projectId, requestScope]);

  const loadAudit = useCallback(async (taskId = selectedTaskId) => {
    if (!projectId || !taskId) {
      setAudit(null);
      setAuditLoading(false);
      setAuditError("");
      setAuditBlockedReason("");
      return;
    }
    setAudit(null);
    setAuditError("");
    setAuditBlockedReason("");
    setAuditLoading(false);
    if (!principalReady) {
      setAuditBlockedReason(monitoringPrincipalBlocker(
        principalState.principal,
        principalState.error,
        { now: principalNow },
      ));
      return;
    }
    const request = requestScope.begin("assurance-audit");
    setAuditLoading(true);
    try {
      const payload = normalizeAssuranceAuditPayload(
        await api.getAudit(projectId, taskId, { signal: request.signal }),
        { projectId, taskId },
      );
      if (!requestScope.isCurrent(request)) return;
      setAudit(payload);
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      if (nextError?.name !== "AbortError") {
        setAuditError(apiErrorMessage(nextError, "保障任务审计链读取失败。"));
      }
    } finally {
      if (requestScope.isCurrent(request)) setAuditLoading(false);
      requestScope.finish(request);
    }
  }, [api, principalNow, principalReady, principalState.error, principalState.principal, projectId, requestScope, selectedTaskId]);

  useEffect(() => {
    requestScope.activate();
    return () => requestScope.dispose();
  }, [requestScope]);

  useEffect(() => {
    if (!open) return undefined;
    setMessage("");
    loadTasks(mode);
    return () => requestScope.cancel("assurance-task-list");
  }, [loadTasks, mode, open, requestScope]);

  useEffect(() => {
    if (!open || !selectedTaskId || !projectId) return undefined;
    const request = requestScope.begin("assurance-task-detail");
    setDetailLoading(true);
    setError("");
    setProofProvenanceStatus("");
    let rejectedProofProvenanceStatus = "";
    Promise.all([
      api.getTask(projectId, selectedTaskId, { signal: request.signal }),
      mode === "pre_lock"
        ? api.getProof(projectId, selectedTaskId, { signal: request.signal }).catch((nextError) => {
          if (nextError?.status === 404) return null;
          throw nextError;
        })
        : api.getRollups(projectId, selectedTaskId, { signal: request.signal }).catch((nextError) => {
          if (nextError?.status === 404) return null;
          throw nextError;
        }),
    ])
      .then(([rawTaskPayload, rawEvidencePayload]) => {
        if (!requestScope.isCurrent(request)) return;
        const taskPayload = normalizeAssuranceTaskPayload(rawTaskPayload, {
          projectId,
          taskId: selectedTaskId,
        });
        rejectedProofProvenanceStatus = mode === "pre_lock"
          ? String(rawEvidencePayload?.proof?.provenance_status || "").trim()
          : "";
        setSelectedTask(taskPayload.task || null);
        setProofProvenanceStatus(rejectedProofProvenanceStatus);
        if (mode === "pre_lock") {
          setProof(rawEvidencePayload
            ? normalizeAssuranceProofPayload(rawEvidencePayload, {
              projectId,
              taskId: selectedTaskId,
            }).proof
            : null);
          setRollup(null);
        } else {
          setRollup(rawEvidencePayload
            ? normalizeAssuranceRollupPayload(rawEvidencePayload, {
              projectId,
              taskId: selectedTaskId,
            }).rollup
            : null);
          setProof(null);
        }
      })
      .catch((nextError) => {
        if (!requestScope.isCurrent(request)) return;
        if (nextError?.name !== "AbortError") {
          if (rejectedProofProvenanceStatus === "mixed_provenance") {
            setProof(null);
            setRollup(null);
            setError("proof 已读取但来源混合；页面保留只读诊断并阻断完成门。");
          } else {
            setSelectedTask(null);
            setProof(null);
            setRollup(null);
            setProofProvenanceStatus("");
            setError(apiErrorMessage(nextError, "保障任务详情读取失败。"));
          }
        }
      })
      .finally(() => {
        if (requestScope.isCurrent(request)) setDetailLoading(false);
        requestScope.finish(request);
      });
    return () => requestScope.cancel("assurance-task-detail");
  }, [api, mode, open, projectId, requestScope, selectedTaskId]);

  useEffect(() => {
    if (!open || !selectedTaskId || !projectId) {
      setReadiness(null);
      setReadinessLoading(false);
      setReadinessError("");
      setReadinessBlockedReason("");
      setReadinessInput(null);
      return undefined;
    }
    const readinessTask = selectedTask || taskSummaries.find((task) => task.id === selectedTaskId) || {};
    const input = assuranceReadinessInput({
      currentSnapshot,
      sourceManifest,
      rawMonitoring,
      currentIdentity: frozenIdentity,
      task: readinessTask,
    });
    setReadiness(null);
    setReadinessInput(input);
    setReadinessError("");
    setReadinessBlockedReason("");
    if (!identityReady) {
      setReadinessBlockedReason(`冻结身份不完整，不能核验 readiness：${missingFrozenIdentityFields(frozenIdentity).join("、")}`);
      return undefined;
    }
    if (!principalReady) {
      setReadinessBlockedReason(monitoringPrincipalBlocker(
        principalState.principal,
        principalState.error,
        { now: principalNow },
      ));
      return undefined;
    }
    if (!input.available) {
      setReadinessBlockedReason(`项目覆盖计数未完整提供：${input.missingFields.join("、")}`);
      return undefined;
    }
    const request = requestScope.begin("assurance-readiness");
    setReadinessLoading(true);
    api.evaluateReadiness(projectId, selectedTaskId, assuranceReadinessPayload(input), { signal: request.signal })
      .then((payload) => {
        if (!requestScope.isCurrent(request)) return;
        setReadiness(normalizeAssuranceReadinessPayload(payload, {
          projectId,
          taskId: selectedTaskId,
          expectedVersion: input.expected_version,
        }));
      })
      .catch((nextError) => {
        if (!requestScope.isCurrent(request)) return;
        if (nextError?.name !== "AbortError") setReadinessError(apiErrorMessage(nextError, "readiness 读取失败。"));
      })
      .finally(() => {
        if (requestScope.isCurrent(request)) setReadinessLoading(false);
        requestScope.finish(request);
      });
    return () => requestScope.cancel("assurance-readiness");
  }, [api, currentSnapshot, frozenIdentity, identityReady, principalNow, principalReady, principalState.error, principalState.principal, projectId, rawMonitoring, requestScope, selectedTask, selectedTaskId, sourceManifest, taskSummaries]);

  useEffect(() => {
    if (!open || !selectedTaskId || !projectId) {
      setAudit(null);
      setAuditLoading(false);
      setAuditError("");
      setAuditBlockedReason("");
      return undefined;
    }
    loadAudit(selectedTaskId);
    return () => requestScope.cancel("assurance-audit");
  }, [loadAudit, open, projectId, requestScope, selectedTaskId]);

  const createTask = async () => {
    if (!taskCreationAllowed || creating) return;
    const request = requestScope.begin("assurance-task-create");
    setCreating(true);
    setError("");
    setMessage("");
    try {
      const payload = normalizeAssuranceCreateResponse(
        await api.createTask(projectId, {
          mode,
          frozen_identity: Object.fromEntries(FROZEN_IDENTITY_FIELDS.map((field) => [field, String(frozenIdentity[field]).trim()])),
          idempotency_key: requestKey(`assurance-${mode}`),
          owner: "医学经理",
        }, { signal: request.signal }),
        { projectId, mode },
      );
      if (!requestScope.isCurrent(request)) return;
      setMessage(payload.replayed ? "已复用同一幂等请求的保障任务。" : "保障任务已创建，等待后续证据步骤。 ");
      await loadTasks(mode);
      if (!requestScope.isCurrent(request)) return;
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      setError(apiErrorMessage(nextError, "保障任务创建失败。"));
    } finally {
      if (requestScope.isCurrent(request)) setCreating(false);
      requestScope.finish(request);
    }
  };

  if (!open) return null;
  return (
    <section className="monitoring-assurance-panel" aria-label="锁库前与核查前保障工作区">
      <header className="monitoring-assurance-head">
        <div>
          <span className="monitoring-assurance-eyebrow"><ClipboardCheck size={14} /> P8 保障工作区</span>
          <h2>锁库前 / 核查前</h2>
          <p>冻结版本、全量重算、三级对账和医学决定集中在同一任务；当前页面首次加载只读取，不会创建或修改任务。</p>
        </div>
        <button type="button" className="icon-button" title="关闭保障工作区" onClick={onClose}><XCircle size={18} /></button>
      </header>
      <div className="monitoring-assurance-mode-row" role="tablist" aria-label="保障模式">
        {ASSURANCE_MODES.map((value) => (
          <button type="button" role="tab" aria-selected={mode === value} className={mode === value ? "active" : ""} key={value} onClick={() => { setMode(value); setSelectedTask(null); setProof(null); setProofProvenanceStatus(""); setRollup(null); setAudit(null); setAuditError(""); setAuditBlockedReason(""); }}>
            <span>{assuranceModeLabel(value)}</span>
            <small>{assuranceModeDescription(value)}</small>
          </button>
        ))}
        <button type="button" className="monitoring-assurance-refresh" onClick={() => loadTasks(mode)} disabled={loading} title="重新读取当前模式的保障任务"><RefreshCw size={14} />{loading ? "读取中" : "刷新"}</button>
      </div>
      <div className="monitoring-assurance-snapshot-grid">
        {snapshotFacts(currentSnapshot).map(([label, value]) => <EvidenceCard key={label} label={label} value={value} />)}
        <EvidenceCard label="冻结身份" value={identityReady ? "完整，可创建" : `缺少 ${missingIdentity.length} 项`} tone={identityReady ? "success" : "warning"} />
        <EvidenceCard label="认证身份" value={monitoringPrincipalStatusLabel(principalState.principal, { now: principalNow })} tone={principalReady ? "success" : "warning"} />
      </div>
      {!taskCreationAllowed && (
        <div className="monitoring-assurance-blocker" role="status">
          <ShieldAlert size={17} />
          <div><strong>创建任务暂时阻断</strong><span>只有完整冻结身份、服务端认证 principal 且 authority 明确允许写入时才可创建；页面不会猜测版本或绕过 B6/风险权威门禁。</span><small>{missingIdentity.length
            ? `缺失身份：${missingIdentity.join("、")}`
            : !authorityWritePermitted
              ? "当前 authority 尚未明确允许写入（assurance_write_permitted 未为 true）"
              : monitoringPrincipalBlocker(principalState.principal, principalState.error, { now: principalNow })}</small></div>
        </div>
      )}
      {taskCreationAllowed && <div className="monitoring-assurance-create-row"><span>当前页面已取得完整冻结身份且 authority 已允许写入，可显式创建该模式任务。</span><button type="button" className="primary-button" onClick={createTask} disabled={creating}>{creating ? "创建中" : `创建${assuranceModeLabel(mode)}任务`}</button></div>}
      {error && <p className="gate-error">{error}</p>}
      {message && <p className="monitoring-assurance-message"><CheckCircle2 size={15} />{message}</p>}
      <div className="monitoring-assurance-body">
        <div className="monitoring-assurance-task-list">
          <div className="monitoring-assurance-section-title"><strong>{assuranceModeLabel(mode)}任务</strong><span>{taskSummaries.length} 条</span></div>
          {loading && <div className="empty-state">正在读取保障任务。</div>}
          {!loading && !taskSummaries.length && <div className="empty-state">当前模式尚无保障任务；完成冻结身份后才可创建。</div>}
          {!loading && taskSummaries.map((task, index) => (
            <button type="button" disabled={task.identityState !== "ready"} className={`monitoring-assurance-task ${selectedTaskId === task.id && task.identityState === "ready" ? "selected" : ""}`} key={assuranceTaskDisplayKey(task, index)} onClick={() => task.identityState === "ready" && setSelectedTaskId(task.id)}>
              <span><strong>{task.id}</strong><small>{task.owner || "未指定负责人"}</small></span>
              <span className={`monitoring-assurance-status ${task.identityState === "ready" ? assuranceStatusTone(task.status) : "danger"}`} title={task.identityIssue || undefined}>{task.identityState === "ready" ? assuranceStatusLabel(task.status) : "身份重复，仅可读"}</span>
            </button>
          ))}
        </div>
        <div className="monitoring-assurance-detail">
          {!activeTask && <div className="empty-state">选择一个任务查看冻结身份和证据状态。</div>}
        {activeTask && (
            <>
              <div className="monitoring-assurance-section-title"><strong>{assuranceModeLabel(activeTask.mode)}</strong><span className={`monitoring-assurance-status ${assuranceStatusTone(activeTask.status)}`}>{assuranceStatusLabel(activeTask.status)}</span></div>
              {detailLoading && <div className="empty-state">正在读取任务详情。</div>}
              {!detailLoading && (
                <>
                  <div className="monitoring-assurance-task-meta"><span>任务版本 <b>{activeTask.version || "-"}</b></span><span>医学复核 <b>{activeTask.medical_review_recorded ? "已记录" : "未记录"}</b></span><span>更新 <b>{activeTask.updated_at || "-"}</b></span></div>
                  <AssuranceReadiness readiness={readiness} loading={readinessLoading} error={readinessError} blockedReason={readinessBlockedReason} input={readinessInput} />
                  <div className="monitoring-assurance-evidence-banner"><Database size={16} /><div><strong>{visibleEvidence.label}</strong><span>{visibleEvidence.ready ? "完成门条件已具备，仍需后端任务状态允许下一步。" : (visibleEvidence.blockingReason || "证据尚未满足完成门；页面不提供绕过门禁的操作。")}</span></div></div>
                  <AssuranceActionStatus availability={actionAvailability} task={activeTask} evidence={visibleEvidence} />
                  <AssuranceProvenanceDisclosure provenanceStatus={visibleEvidence.provenanceStatus || proofProvenanceStatus} />
                  {activeTask.mode === "pre_lock" && proof && <div className="monitoring-assurance-counts"><span>全量重算失败 <b>{assuranceRollupNumber(proof.failures)}</b></span><span>跳过 <b>{assuranceRollupNumber(proof.skips)}</b></span><span>开放高风险 <b>{assuranceRollupNumber(proof.open_high_risk_count)}</b></span><span>缺关闭证据 <b>{assuranceRollupNumber(proof.closed_risks_lacking_evidence_count)}</b></span></div>}
                  {activeTask.mode === "pre_inspection" && rollup && <div className="monitoring-assurance-counts"><span>受试者层 <b>{assuranceRollupNumber(explicitArrayCount(rollup.subject_rollup))}</b></span><span>中心层 <b>{assuranceRollupNumber(explicitArrayCount(rollup.site_rollup))}</b></span><span>证据项 <b>{assuranceRollupNumber(explicitArrayCount(rollup.evidence_manifest))}</b></span><span>整改项 <b>{assuranceRollupNumber(explicitArrayCount(rollup.remediation_matrix))}</b></span></div>}
                  {activeTask.mode === "pre_inspection" && rollup && <AssuranceRollup rollup={rollup} onClose={onClose} onRiskScopeChange={onRiskScopeChange} onSelectSubject={onSelectSubject} onOpenSubjectView={onOpenSubjectView} />}
                  <AssuranceAuditChain audit={audit} loading={auditLoading} error={auditError} blockedReason={auditBlockedReason} onRetry={() => loadAudit(activeTask.task_id)} />
                </>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
