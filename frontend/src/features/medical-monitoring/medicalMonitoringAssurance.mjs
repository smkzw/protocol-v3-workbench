import { projectAssuranceRollup } from "./medicalMonitoringAssuranceRollup.mjs";
import {
  monitoringModeDefinition,
  monitoringModeFromAssuranceMode,
} from "./medicalMonitoringModeCatalog.mjs";

export const ASSURANCE_MODES = ["pre_lock", "pre_inspection"];

export const FROZEN_IDENTITY_FIELDS = [
  "batch_id",
  "batch_revision",
  "mapping_revision",
  "protocol_version_id",
  "rule_pack_revision",
  "dictionary_revision",
  "ctcae_revision",
  "model_revision",
  "risk_snapshot_id",
];

const READINESS_COUNT_KEYS = Object.freeze({
  plannedSubjects: ["planned_subjects"],
  actualSubjects: ["actual_subjects", "subjects_evaluated", "subject_count"],
  plannedSites: ["planned_sites"],
  actualSites: ["actual_sites", "sites_evaluated", "site_count"],
  criticalDomainsCovered: ["critical_domains_covered"],
  criticalDomainsExpected: ["critical_domains_expected"],
});

const MODE_LABELS = {
  pre_lock: "锁库前保障",
  pre_inspection: "核查前保障",
};

const STATUS_LABELS = {
  draft: "草稿",
  running: "执行中",
  blocked: "已阻断",
  completed: "已完成",
  superseded: "已取代",
};

const STATUS_TONES = {
  draft: "info",
  running: "warning",
  blocked: "danger",
  completed: "success",
  superseded: "neutral",
};

const AUDIT_ACTION_LABELS = {
  create_assurance_task: "创建保障任务",
  record_assurance_evidence: "记录保障证据",
  review_assurance: "医学复核",
  complete_assurance: "完成保障任务",
  read_risk_audit: "读取风险审计",
};

export const ASSURANCE_EVIDENCE_PROVENANCE_STATUSES = Object.freeze({
  SERVER_EVIDENCE_RUN_LEDGER: "server_evidence_run_ledger",
  SIGNED_MANIFEST_SERVER_REVALIDATED: "signed_manifest_server_revalidated",
});

const ACCEPTED_EVIDENCE_PROVENANCE_STATUSES = new Set(
  Object.values(ASSURANCE_EVIDENCE_PROVENANCE_STATUSES),
);

function isExplicitZero(value) {
  if (typeof value === "number") return Number.isInteger(value) && value === 0;
  return typeof value === "string" && value.trim() === "0";
}

function nonNegativeInteger(value) {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

function candidateSources({ currentSnapshot, sourceManifest, rawMonitoring }) {
  const roots = [currentSnapshot, sourceManifest, rawMonitoring];
  return roots.flatMap((root) => (
    root && typeof root === "object" && !Array.isArray(root)
      ? [root.assurance_readiness, root.readiness, root]
      : []
  )).filter((value) => value && typeof value === "object" && !Array.isArray(value));
}

function firstCount(sources, keys) {
  for (const source of sources) {
    for (const key of keys) {
      const count = nonNegativeInteger(source[key]);
      if (count !== null) return count;
    }
  }
  return null;
}

function firstArrayCount(sources, keys) {
  for (const source of sources) {
    for (const key of keys) {
      if (Array.isArray(source[key])) return source[key].length;
    }
  }
  return null;
}

/**
 * Build the read-only readiness request from explicit project-bound facts.
 * Missing coverage is preserved as a blocker; it is never guessed as zero.
 */
export function assuranceReadinessInput({
  currentSnapshot,
  sourceManifest,
  rawMonitoring,
  currentIdentity = {},
  task = {},
} = {}) {
  const sources = candidateSources({ currentSnapshot, sourceManifest, rawMonitoring });
  const rollups = sources
    .map((source) => source.rollup)
    .filter((value) => value && typeof value === "object" && !Array.isArray(value));
  const actualSubjects = firstCount(sources, READINESS_COUNT_KEYS.actualSubjects)
    ?? firstArrayCount(rollups, ["subjects", "subject_rollup"]);
  const actualSites = firstCount(sources, READINESS_COUNT_KEYS.actualSites)
    ?? firstArrayCount(rollups, ["sites", "site_rollup"]);
  const plannedSubjects = firstCount(sources, READINESS_COUNT_KEYS.plannedSubjects);
  const plannedSites = firstCount(sources, READINESS_COUNT_KEYS.plannedSites);
  const criticalDomainsCovered = firstCount(sources, READINESS_COUNT_KEYS.criticalDomainsCovered);
  const criticalDomainsExpected = firstCount(sources, READINESS_COUNT_KEYS.criticalDomainsExpected);
  const expectedVersion = nonNegativeInteger(task.version);
  const missingFields = [];
  if (expectedVersion === null || expectedVersion < 1) missingFields.push("expected_version");
  if (actualSubjects === null) missingFields.push("actual_subjects");
  if (actualSites === null) missingFields.push("actual_sites");
  return {
    available: missingFields.length === 0,
    missingFields,
    expected_version: expectedVersion || 0,
    current_identity: currentIdentity && typeof currentIdentity === "object" ? { ...currentIdentity } : {},
    planned_subjects: plannedSubjects ?? 0,
    actual_subjects: actualSubjects ?? 0,
    planned_sites: plannedSites ?? 0,
    actual_sites: actualSites ?? 0,
    critical_domains_covered: criticalDomainsCovered ?? 0,
    critical_domains_expected: criticalDomainsExpected ?? 0,
  };
}

export function assuranceReadinessState({ readiness = null, input = null } = {}) {
  if (!input?.available) {
    return {
      ready: false,
      tone: "warning",
      label: "等待覆盖计数",
      blockingReason: input?.missingFields?.length
        ? `尚未提供可核验字段：${input.missingFields.join("、")}`
        : "尚未形成可核验的 readiness 请求。",
    };
  }
  if (!readiness) {
    return {
      ready: false,
      tone: "warning",
      label: "等待 readiness 结果",
      blockingReason: "服务端尚未返回当前任务的 readiness 结果。",
    };
  }
  const ready = readiness.ready === true;
  return {
    ready,
    tone: ready ? "success" : "danger",
    label: ready ? "覆盖与冻结身份已核验" : "readiness 完成门未通过",
    blockingReason: ready
      ? ""
      : (readiness.gaps?.length ? readiness.gaps.join("；") : "服务端返回未就绪，但未提供具体缺口。"),
  };
}

/** Remove local availability metadata before sending the strict backend request. */
export function assuranceReadinessPayload(input = {}) {
  return Object.fromEntries(
    Object.entries(input).filter(([key]) => key !== "available" && key !== "missingFields"),
  );
}

export function assuranceModeLabel(mode) {
  return MODE_LABELS[mode] || "保障任务";
}

export function assuranceModeMonitoringId(mode) {
  return monitoringModeFromAssuranceMode(mode);
}

export function assuranceModeDescription(mode) {
  const definition = monitoringModeDefinition(assuranceModeMonitoringId(mode));
  return definition
    ? `${definition.label} · ${definition.baseline}`
    : "当前保障任务模式尚未绑定商业运行策略。";
}

export function assuranceStatusLabel(status) {
  return STATUS_LABELS[status] || status || "未知状态";
}

export function assuranceStatusTone(status) {
  return STATUS_TONES[status] || "neutral";
}

export function assuranceAuditActionLabel(action) {
  return AUDIT_ACTION_LABELS[action] || action || "未知审计动作";
}

export function completeFrozenIdentity(identity = {}) {
  return FROZEN_IDENTITY_FIELDS.every((field) => (
    identity[field] !== null
    && identity[field] !== undefined
    && String(identity[field]).trim().length > 0
  ));
}

export function assuranceTaskCreationAllowed(identity = {}, writePermitted = false) {
  return completeFrozenIdentity(identity) && writePermitted === true;
}

export function missingFrozenIdentityFields(identity = {}) {
  return FROZEN_IDENTITY_FIELDS.filter((field) => (
    identity[field] === null
    || identity[field] === undefined
    || !String(identity[field]).trim()
  ));
}

export function assuranceTaskSummary(task = {}) {
  const identity = task.frozen_identity || {};
  return {
    id: String(task.task_id || ""),
    mode: String(task.mode || ""),
    modeLabel: assuranceModeLabel(task.mode),
    status: String(task.status || ""),
    statusLabel: assuranceStatusLabel(task.status),
    statusTone: assuranceStatusTone(task.status),
    version: Number(task.version || 0),
    identityHash: String(task.identity_hash || ""),
    identityReady: completeFrozenIdentity(identity),
    medicalReviewRecorded: task.medical_review_recorded === true,
    proofId: String(task.full_recompute_proof_id || ""),
    owner: String(task.owner || ""),
    lockImpact: String(task.lock_impact || ""),
    updatedAt: String(task.updated_at || ""),
  };
}

function preInspectionEvidenceState(rollup) {
  const projected = projectAssuranceRollup(rollup);
  if (!projected.available) {
    return {
      label: "等待三级汇总",
      tone: "warning",
      ready: false,
      blockingReason: "尚未返回可核验的三级汇总。",
    };
  }

  const blockers = [];
  if (!projected.conservation.ok) {
    blockers.push("项目、中心、个例的风险身份或显式计数不守恒");
  }
  if (projected.trial.closedWithoutEvidenceCount !== 0) {
    blockers.push(
      projected.trial.closedWithoutEvidenceCount === null
        ? "缺少已关闭风险的关闭依据计数"
        : `有 ${projected.trial.closedWithoutEvidenceCount} 项已关闭风险缺少关闭依据`,
    );
  }

  const ready = blockers.length === 0;
  return {
    label: ready ? "三级汇总与关闭依据已核验" : "三级汇总已记录，但完成门未通过",
    tone: ready ? "success" : "danger",
    ready,
    blockingReason: ready ? "" : blockers.join("；"),
  };
}

export function assuranceEvidenceProvenanceState(proof = null) {
  const status = proof && typeof proof === "object"
    ? String(proof.provenance_status || "").trim()
    : "";
  if (ACCEPTED_EVIDENCE_PROVENANCE_STATUSES.has(status)) {
    return {
      status,
      ready: true,
      label: status === ASSURANCE_EVIDENCE_PROVENANCE_STATUSES.SERVER_EVIDENCE_RUN_LEDGER
        ? "服务端 evidence-run ledger 已声明"
        : "签名 evidence manifest 已经服务端全字段重验",
      blockingReason: "",
    };
  }
  if (status === "mixed" || status === "mixed_provenance") {
    return {
      status,
      ready: false,
      label: "证据来源混合",
      blockingReason: "证据来源混合，不能作为全量重算完成证明。",
    };
  }
  return {
    status,
    ready: false,
    label: "证据权威未确认",
    blockingReason: "服务端未声明可接受的证据权威，不能作为全量重算完成证明。",
  };
}

export function assuranceEvidenceState({ task = {}, proof = null, rollup = null } = {}) {
  const summary = assuranceTaskSummary(task);
  if (summary.mode === "pre_lock") {
    const provenance = assuranceEvidenceProvenanceState(proof);
    const ready = Boolean(proof)
      && provenance.ready
      && isExplicitZero(proof.failures)
      && isExplicitZero(proof.skips)
      && proof.subject_reconciliation_ok === true
      && proof.site_reconciliation_ok === true
      && proof.trial_reconciliation_ok === true;
    return {
      label: !proof
        ? "等待全量重算证明"
        : ready
          ? "全量重算证明已核验"
          : provenance.label === "证据权威未确认" || provenance.label === "证据来源混合"
            ? provenance.label
            : "全量重算证明已记录，但完成门未通过",
      tone: ready ? "success" : proof ? "danger" : "warning",
      ready,
      provenanceStatus: provenance.status,
      blockingReason: proof
        ? (provenance.ready ? "全量重算失败、跳过或三级对账未通过。" : provenance.blockingReason)
        : "尚未返回全量重算证明。",
    };
  }
  if (summary.mode === "pre_inspection") {
    return preInspectionEvidenceState(rollup);
  }
  return {
    label: "未识别的保障模式",
    tone: "danger",
    ready: false,
    blockingReason: "当前任务模式无法进入完成门。",
  };
}

/**
 * Describe the server-backed assurance action sequence without granting a
 * client-side bypass. Evidence must exist before medical review, and both
 * evidence plus review/readiness must exist before completion.
 */
export function assuranceActionAvailability({
  task = {},
  principalReady = false,
  authorityWritePermitted = false,
  evidenceReady = false,
  evidenceRecorded = false,
  evidenceBlockingReason = "",
  readinessReady = false,
} = {}) {
  const summary = assuranceTaskSummary({
    ...task,
    task_id: task.task_id || task.id,
  });
  const baseBlockers = [];
  if (!summary.id) baseBlockers.push("未选择保障任务");
  if (!Number.isInteger(summary.version) || summary.version < 1) baseBlockers.push("任务版本不可核验");
  if (!principalReady) baseBlockers.push("服务端认证 principal 未就绪");
  if (!authorityWritePermitted) baseBlockers.push("当前 authority 未允许保障写入");
  if (["completed", "superseded"].includes(summary.status)) baseBlockers.push("任务已结束，不能继续写入");
  const baseReady = baseBlockers.length === 0;
  const evidenceExists = evidenceRecorded === true || evidenceReady === true;
  const evidenceBlocker = evidenceReady
    ? ""
    : evidenceBlockingReason || (evidenceExists ? "已有证据但其权威尚未核验" : "尚未形成可核验的证据结果");
  const reviewBlocker = !evidenceReady
    ? evidenceBlocker
    : summary.medicalReviewRecorded
      ? "医学复核已记录"
      : "等待医学复核确认";
  const completeBlocker = !evidenceReady
    ? evidenceBlocker
    : !summary.medicalReviewRecorded
      ? "医学复核尚未记录"
      : !readinessReady
        ? "readiness 完成门尚未通过"
        : "";
  return {
    baseReady,
    baseBlockers,
    canRecordEvidence: baseReady && !evidenceExists,
    canReview: baseReady && evidenceReady && !summary.medicalReviewRecorded,
    canComplete: baseReady && evidenceReady && summary.medicalReviewRecorded && readinessReady,
    evidenceBlocker: baseReady && !evidenceReady && !evidenceExists
      ? ""
      : (baseBlockers.join("；") || evidenceBlocker),
    reviewBlocker: baseReady && evidenceReady && !summary.medicalReviewRecorded ? "" : (baseBlockers.join("；") || reviewBlocker),
    completeBlocker: baseReady && evidenceReady && summary.medicalReviewRecorded && readinessReady
      ? ""
      : (baseBlockers.join("；") || completeBlocker),
  };
}

export function assuranceTaskList(items = []) {
  const summaries = (Array.isArray(items) ? items : [])
    .map((item, sourceIndex) => ({ ...assuranceTaskSummary(item), sourceIndex }))
    .filter((task) => task.id);
  const identityCounts = new Map();
  summaries.forEach((task) => identityCounts.set(task.id, (identityCounts.get(task.id) || 0) + 1));
  return summaries
    .map((task) => {
      const duplicate = (identityCounts.get(task.id) || 0) > 1;
      return {
        ...task,
        identityState: duplicate ? "duplicate" : "ready",
        identityIssue: duplicate ? "保障任务 task_id 重复；仅可读，暂不可选择" : "",
      };
    })
    .sort((left, right) => (
      String(right.updatedAt).localeCompare(String(left.updatedAt))
      || left.mode.localeCompare(right.mode)
      || left.id.localeCompare(right.id)
    ));
}

/** UI-only key; never becomes the task ID sent to an assurance API. */
export function assuranceTaskDisplayKey(task = {}, index = 0) {
  const identity = String(task.id || task.task_id || "").trim() || "missing";
  const sourceIndex = Number.isInteger(task.sourceIndex) && task.sourceIndex >= 0
    ? task.sourceIndex
    : Number.isInteger(index) && index >= 0 ? index : 0;
  return `assurance-task:${identity}:${sourceIndex}`;
}
