import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronRight,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";

import {
  MedicalMonitoringApiError,
  createMedicalMonitoringApi,
} from "./medicalMonitoringApi.mjs";
import { semanticQualityPresentation } from "./medicalMonitoringFieldMappingState.mjs";
import {
  MedicalMonitoringFieldMappingShapeError,
  normalizeFieldMappingRun,
  normalizeFieldMappingStatus,
  normalizeMappingDraft,
  normalizeMappingRevision,
  medicalMonitoringFieldMappingEvidenceKey,
} from "./medicalMonitoringFieldMappingView.mjs";
import { monitoringFieldMappingCopy } from "./medicalMonitoringModels.mjs";
import {
  createMedicalMonitoringProjectRequestScope,
} from "./medicalMonitoringProjectRequestScope.mjs";

const TERMINAL_JOB_STATES = new Set([
  "completed",
  "failed",
  "blocked",
  "stale_input",
  "cancelled",
]);

const FIELD_KIND_LABELS = {
  source_collected: "来源采集字段",
  source_metadata: "来源技术字段",
  standardized_coded: "标准编码字段",
  deterministic_derived: "确定性派生字段",
  unmapped: "暂不映射",
};
const LOW_CONFIDENCE_THRESHOLD = 0.85;

function requestKey(prefix) {
  const random = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`;
}

function errorText(error, fallback) {
  if (error instanceof MedicalMonitoringApiError) {
    const detail = error.detail?.detail;
    if (detail && typeof detail === "object" && detail.message) {
      return detail.message;
    }
  }
  return error?.message || fallback;
}

function confidenceLabel(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${Math.round(number * 100)}%`;
}

export default function MedicalMonitoringFieldMappingPanel({
  projectId,
  batch,
  aiStatus = {},
  onClose,
  onConfirmed,
}) {
  const api = useMemo(() => createMedicalMonitoringApi(), []);
  const requestScope = useMemo(
    () => createMedicalMonitoringProjectRequestScope(projectId),
    [projectId],
  );
  const [mappingRun, setMappingRun] = useState(null);
  const [jobDetails, setJobDetails] = useState([]);
  const [draft, setDraft] = useState(null);
  const [confirmedRevision, setConfirmedRevision] = useState(null);
  const [activeMapping, setActiveMapping] = useState(null);
  const [activeDomain, setActiveDomain] = useState("all");
  const [attentionFilter, setAttentionFilter] = useState("attention");
  const [search, setSearch] = useState("");
  const [selectedFieldKey, setSelectedFieldKey] = useState("");
  const [fieldForm, setFieldForm] = useState(null);
  const [confirmationReason, setConfirmationReason] = useState(
    "已核对本批次字段语义、试验药物与非试验用药边界，确认用于后续批次解析和医学规则运行。",
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const mappingCopy = useMemo(
    () => monitoringFieldMappingCopy(aiStatus),
    [aiStatus],
  );

  const clearMappingState = useCallback(() => {
    setMappingRun(null);
    setJobDetails([]);
    setDraft(null);
    setConfirmedRevision(null);
    setActiveMapping(null);
    setSelectedFieldKey("");
    setFieldForm(null);
  }, []);

  const applyStatus = useCallback((status) => {
    const normalized = normalizeFieldMappingStatus(status);
    setMappingRun(normalized.job_details.length
      ? {
        batch_id: normalized.batch_id,
        profile_sha256: normalized.profile_sha256,
        input_sha256: normalized.input_sha256,
        field_count: normalized.field_count,
        job_count: normalized.job_count,
        jobs: normalized.job_details.map((item) => item.job),
      }
      : null);
    setJobDetails(normalized.job_details);
    setDraft(normalized.draft
      ? {
        ...normalized.draft,
        semantic_quality: normalized.semantic_quality
          || normalized.draft.semantic_quality
          || null,
      }
      : null);
    setActiveMapping(normalized.active_mapping);
    return normalized.job_details;
  }, []);

  const refreshStatus = useCallback(async () => {
    const request = requestScope.begin("field-mapping-status");
    try {
      const status = await api.getFieldMappingStatus(
        projectId,
        batch.batch_id,
        { signal: request.signal },
      );
      if (!requestScope.isCurrent(request)) return [];
      const nextJobs = applyStatus(status);
      setError("");
      return nextJobs;
    } finally {
      requestScope.finish(request);
    }
  }, [api, applyStatus, batch.batch_id, projectId, requestScope]);

  useEffect(() => {
    requestScope.activate();
    return () => requestScope.dispose();
  }, [requestScope]);

  useEffect(() => {
    const request = requestScope.begin("field-mapping-status");
    clearMappingState();
    setError("");
    setMessage("");
    setBusy(true);
    api.getFieldMappingStatus(projectId, batch.batch_id, { signal: request.signal })
      .then(async (status) => {
        if (!requestScope.isCurrent(request)) return;
        const normalizedStatus = normalizeFieldMappingStatus(status);
        applyStatus(normalizedStatus);
        if (normalizedStatus.draft?.status === "confirmed") {
          setMessage("当前批次已存在正式字段映射。");
          return;
        }
        const mappingRevision = normalizedStatus.active_mapping?.mapping_revision;
        if (!normalizedStatus.draft && mappingRevision) {
          const revision = normalizeMappingRevision(await api.getMappingRevision(
            projectId,
            mappingRevision,
            { signal: request.signal },
          ));
          if (!requestScope.isCurrent(request)) return;
          setDraft({
            ...revision,
            draft_id: revision.draft_id,
            version: revision.draft_version,
            status: "confirmed",
            confirmed_revision_id: revision.mapping_revision,
          });
          setMessage("当前项目已启用以下正式字段映射。");
        }
      })
      .catch((nextError) => {
        if (requestScope.isCurrent(request)) {
          if (nextError?.name !== "AbortError") {
            clearMappingState();
          }
          setError(errorText(nextError, "字段映射状态读取失败"));
        }
      })
      .finally(() => {
        if (requestScope.isCurrent(request)) setBusy(false);
        requestScope.finish(request);
      });
    return () => {
      requestScope.cancel("field-mapping-status");
    };
  }, [api, applyStatus, batch.batch_id, clearMappingState, projectId, requestScope]);

  useEffect(() => {
    if (!mappingRun?.jobs?.length) return undefined;
    const allTerminal = jobDetails.length === mappingRun.jobs.length
      && jobDetails.every((item) => TERMINAL_JOB_STATES.has(item.job?.status));
    if (allTerminal) return undefined;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      refreshStatus().catch((nextError) => {
        if (!cancelled) {
          if (nextError?.name !== "AbortError") {
            clearMappingState();
          }
          setError(errorText(nextError, "字段识别进度读取失败"));
        }
      });
    }, jobDetails.length ? 3500 : 600);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [clearMappingState, jobDetails, mappingRun, refreshStatus]);

  const startMapping = async ({ retryFailed = false } = {}) => {
    requestScope.cancel("field-mapping-status");
    const request = requestScope.begin("field-mapping-start");
    setBusy(true);
    setError("");
    setMessage("");
    clearMappingState();
    setDraft(null);
    setConfirmedRevision(null);
    try {
      const run = normalizeFieldMappingRun(
        await api.startFieldMapping(projectId, batch.batch_id, {
          retryFailed,
          signal: request.signal,
        }),
      );
      if (!requestScope.isCurrent(request)) return;
      setMappingRun(run);
      setJobDetails([]);
      setMessage(
        run.jobs?.every((job) => job.status === "completed")
          ? mappingCopy.completedMessage
          : mappingCopy.runningMessage,
      );
      await refreshStatus();
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      if (nextError instanceof MedicalMonitoringFieldMappingShapeError) {
        clearMappingState();
      }
      setError(errorText(nextError, "字段识别未能启动"));
    } finally {
      if (requestScope.isCurrent(request)) setBusy(false);
      requestScope.finish(request);
    }
  };

  const allCompleted = mappingRun?.jobs?.length > 0
    && jobDetails.length === mappingRun.jobs.length
    && jobDetails.every((item) => item.job?.status === "completed");
  const terminalCount = jobDetails.filter(
    (item) => TERMINAL_JOB_STATES.has(item.job?.status),
  ).length;
  const failedJobs = jobDetails.filter(
    (item) => item.job?.status && item.job.status !== "completed"
      && TERMINAL_JOB_STATES.has(item.job.status),
  );
  const candidateMappings = useMemo(
    () => jobDetails.flatMap((item) => item.candidates.flatMap((candidate) => (
      candidate.structured_payload.field_mappings
    ))),
    [jobDetails],
  );

  const acceptAndAssemble = async () => {
    if (!allCompleted || !mappingRun?.profile_sha256) return;
    const request = requestScope.begin("field-mapping-adopt");
    setBusy(true);
    setError("");
    try {
      const nextDraft = normalizeMappingDraft(
        await api.adoptFieldMappingRun(projectId, {
          batchId: batch.batch_id,
          fullProfileSha256: mappingRun.profile_sha256,
          reason: "采用本次完整字段建议进入映射校对。",
        }, { signal: request.signal }),
      );
      if (!requestScope.isCurrent(request)) return;
      setDraft(nextDraft);
      setMessage("AI建议已汇总为可编辑草稿。请重点核对低置信度和试验药物相关字段。");
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      if (nextError instanceof MedicalMonitoringFieldMappingShapeError) {
        clearMappingState();
      }
      setError(errorText(nextError, "字段映射草稿生成失败"));
    } finally {
      if (requestScope.isCurrent(request)) setBusy(false);
      requestScope.finish(request);
    }
  };

  const domains = useMemo(
    () => [...new Set((draft?.fields || candidateMappings).map((item) => item.domain))].sort(),
    [candidateMappings, draft],
  );
  const candidateByField = useMemo(
    () => new Map(candidateMappings.map((item) => [
      `${item.domain}::${item.source_field}`,
      item,
    ])),
    [candidateMappings],
  );
  const attentionReason = useCallback((field) => {
    const role = String(field.recommended_role || "").toLowerCase();
    if (field.field_kind === "unmapped") return "暂未映射";
    if (Number(field.confidence) < LOW_CONFIDENCE_THRESHOLD) return "低置信度";
    if (/(^|_)(ip|cm|dose|dosing|adherence|compliance)(_|$)/.test(role)) {
      return "用药边界";
    }
    if (field.field_kind === "standardized_coded") return "编码依据";
    if (field.field_kind === "deterministic_derived") return "派生依据";
    return "";
  }, []);
  const displayedFields = useMemo(() => {
    const source = draft?.fields || candidateMappings;
    const needle = search.trim().toLocaleLowerCase("zh-CN");
    return source.filter((item) => (
      (activeDomain === "all" || item.domain === activeDomain)
      && (
        attentionFilter === "all"
        || (attentionFilter === "attention" && attentionReason(item))
        || (attentionFilter === "unmapped" && item.field_kind === "unmapped")
        || (
          attentionFilter === "low"
          && Number(item.confidence) < LOW_CONFIDENCE_THRESHOLD
        )
        || (
          attentionFilter === "medication"
          && attentionReason(item) === "用药边界"
        )
        || (
          attentionFilter === "lineage"
          && ["standardized_coded", "deterministic_derived"].includes(
            item.field_kind,
          )
        )
      )
      && (
        !needle
        || item.source_field.toLocaleLowerCase("zh-CN").includes(needle)
        || item.recommended_role.toLocaleLowerCase("zh-CN").includes(needle)
      )
    ));
  }, [
    activeDomain,
    attentionFilter,
    attentionReason,
    candidateMappings,
    draft,
    search,
  ]);
  const confirmedReadOnly = draft?.status === "confirmed";
  const semanticQuality = draft?.semantic_quality || null;
  const semanticQualityState = useMemo(
    () => semanticQualityPresentation(semanticQuality),
    [semanticQuality],
  );
  const changedFields = useMemo(() => {
    if (!draft) return [];
    return draft.fields.filter((field) => {
      const original = candidateByField.get(
        `${field.domain}::${field.source_field}`,
      );
      if (!original) return false;
      return [
        "recommended_role",
        "field_kind",
        "uncertainty",
        "user_action",
      ].some((key) => JSON.stringify(field[key]) !== JSON.stringify(original[key]))
        || JSON.stringify(field.standards_reference || null)
          !== JSON.stringify(original.standards_reference || null)
        || JSON.stringify(field.derivation_lineage || null)
          !== JSON.stringify(original.derivation_lineage || null);
    });
  }, [candidateByField, draft]);
  const attentionCount = useMemo(
    () => (draft?.fields || []).filter((field) => attentionReason(field)).length,
    [attentionReason, draft],
  );

  const selectField = (field) => {
    const key = `${field.domain}::${field.source_field}`;
    const original = candidateByField.get(key);
    setSelectedFieldKey(key);
    setFieldForm({
      domain: field.domain,
      source_field: field.source_field,
      recommended_role: field.recommended_role,
      field_kind: field.field_kind,
      uncertainty: field.uncertainty,
      user_action: field.user_action,
      standards_reference: field.standards_reference || null,
      derivation_lineage: field.derivation_lineage || null,
      evidence_summary: original?.evidence_summary || [],
    });
  };

  const changeFieldKind = (value) => {
    setFieldForm((current) => {
      let derivationLineage = current.derivation_lineage;
      if (value === "standardized_coded") {
        derivationLineage = {
          source_fields: derivationLineage?.source_fields || [],
          coding_system: derivationLineage?.coding_system || "",
          dictionary_version: derivationLineage?.dictionary_version || "",
        };
      } else if (value === "deterministic_derived") {
        derivationLineage = {
          source_fields: derivationLineage?.source_fields || [],
          formula: derivationLineage?.formula || "",
        };
      } else {
        derivationLineage = null;
      }
      return {
        ...current,
        field_kind: value,
        derivation_lineage: derivationLineage,
      };
    });
  };

  const updateLineage = (key, value) => {
    setFieldForm((current) => ({
      ...current,
      derivation_lineage: {
        ...(current.derivation_lineage || {}),
        [key]: value,
      },
    }));
  };

  const saveField = async () => {
    if (!draft || !fieldForm) return;
    const request = requestScope.begin("field-mapping-edit");
    setBusy(true);
    setError("");
    try {
      const nextDraft = normalizeMappingDraft(await api.editMappingDraftField(
        projectId,
        draft.draft_id,
        {
          domain: fieldForm.domain,
          source_field: fieldForm.source_field,
          patch: {
            recommended_role: fieldForm.recommended_role.trim(),
            field_kind: fieldForm.field_kind,
            uncertainty: fieldForm.uncertainty.trim(),
            user_action: fieldForm.user_action.trim(),
            standards_reference: fieldForm.standards_reference,
            derivation_lineage: fieldForm.derivation_lineage
              ? {
                ...fieldForm.derivation_lineage,
                source_fields: (
                  fieldForm.derivation_lineage.source_fields || []
                ).map((item) => item.trim()).filter(Boolean),
              }
              : null,
          },
          expected_version: draft.version,
          idempotency_key: requestKey("monitoring-mapping-field"),
        },
        { signal: request.signal },
      ));
      if (!requestScope.isCurrent(request)) return;
      setDraft(nextDraft);
      setSelectedFieldKey("");
      setFieldForm(null);
      setMessage(`已保存 ${fieldForm.domain}.${fieldForm.source_field} 的修订。`);
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      if (nextError instanceof MedicalMonitoringFieldMappingShapeError) {
        clearMappingState();
      }
      setError(errorText(nextError, "字段修订保存失败"));
    } finally {
      if (requestScope.isCurrent(request)) setBusy(false);
      requestScope.finish(request);
    }
  };

  const confirmDraft = async () => {
    if (!draft || confirmationReason.trim().length < 10) return;
    const request = requestScope.begin("field-mapping-confirm");
    setBusy(true);
    setError("");
    try {
      const revision = normalizeMappingRevision(await api.confirmMappingDraft(
        projectId,
        draft.draft_id,
        {
          expected_version: draft.version,
          confirmed_by: "medical_manager",
          confirmation_reason: confirmationReason.trim(),
          idempotency_key: requestKey("monitoring-mapping-confirm"),
          expected_project_version: activeMapping?.project_version || 0,
        },
        { signal: request.signal },
      ));
      if (!requestScope.isCurrent(request)) return;
      setConfirmedRevision(revision);
      setDraft((current) => current && {
        ...current,
        status: "confirmed",
        confirmed_revision_id: revision.mapping_revision,
      });
      setMessage("字段映射已确认，可作为后续批次与规则运行的正式映射版本。");
      setActiveMapping(revision.activation || activeMapping);
      onConfirmed?.(revision);
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      if (nextError instanceof MedicalMonitoringFieldMappingShapeError) {
        clearMappingState();
      }
      setError(errorText(nextError, "字段映射确认失败"));
    } finally {
      if (requestScope.isCurrent(request)) setBusy(false);
      requestScope.finish(request);
    }
  };

  return (
    <section className="monitoring-mapping-panel" aria-label="字段识别与映射校对">
      <header className="monitoring-mapping-head">
        <div>
          <span>{confirmedReadOnly ? "正式字段映射" : "字段识别"}</span>
          <strong>{batch.sources?.[0]?.file_name || "当前批次"}</strong>
          <small>
            {confirmedReadOnly
              ? "当前项目已启用；可查看重点字段、依据与历史确认内容。"
              : mappingCopy.headerDescription}
          </small>
        </div>
        <button className="icon-button" type="button" title="关闭" onClick={onClose}>
          <X size={16} />
        </button>
      </header>

      {!mappingRun && !draft && (
        <div className="monitoring-mapping-start">
          <Sparkles size={22} />
          <div>
            <strong>{mappingCopy.startTitle}</strong>
            <span>{mappingCopy.startDescription}</span>
          </div>
          <button
            className="primary-button"
            type="button"
            disabled={busy}
            title={mappingCopy.startDescription}
            onClick={startMapping}
          >
            {busy ? "正在启动" : mappingCopy.startAction}
          </button>
        </div>
      )}

      {mappingRun && !draft && (
        <>
          <div className="monitoring-mapping-progress">
            <div>
              {allCompleted
                ? <Check size={17} />
                : <LoaderCircle className="spin" size={17} />}
              <strong>
                {allCompleted
                  ? `${mappingRun.field_count} 个字段已识别`
                  : `${terminalCount}/${mappingRun.job_count} 个识别单元已完成`}
              </strong>
            </div>
            <span>{mappingCopy.progressDescription}</span>
            <button
              className="icon-button"
              type="button"
              title="刷新进度"
              onClick={() => refreshStatus()}
              disabled={busy}
            >
              <RefreshCw size={15} />
            </button>
          </div>
          {failedJobs.length > 0 && (
            <div className="monitoring-mapping-error">
              <span>部分字段尚未生成可用建议，不影响已完成内容或冻结原始数据。</span>
              <button
                className="text-button"
                type="button"
                disabled={busy}
                onClick={() => startMapping({ retryFailed: true })}
              >
                重试失败部分
              </button>
            </div>
          )}
          {allCompleted && (
            <div className="monitoring-mapping-review">
              <div>
                <strong>{candidateMappings.length} 个字段建议可进入校对</strong>
                <span>采用建议不会直接运行风险规则；下一步仍可逐字段修改。</span>
              </div>
              <button className="primary-button" type="button" disabled={busy} onClick={acceptAndAssemble}>
                采用建议并校对
                <ChevronRight size={15} />
              </button>
            </div>
          )}
        </>
      )}

      {draft && (
        <div className="monitoring-mapping-editor">
          <div className="monitoring-mapping-toolbar">
            <select
              value={attentionFilter}
              onChange={(event) => setAttentionFilter(event.target.value)}
            >
              <option value="attention">待关注 ({attentionCount})</option>
              <option value="unmapped">暂未映射</option>
              <option value="low">低置信度</option>
              <option value="medication">用药边界</option>
              <option value="lineage">编码与派生</option>
              <option value="all">全部字段</option>
            </select>
            <select value={activeDomain} onChange={(event) => setActiveDomain(event.target.value)}>
              <option value="all">全部数据域</option>
              {domains.map((domain) => <option value={domain} key={domain}>{domain}</option>)}
            </select>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索原始字段或建议角色"
            />
            <span>{displayedFields.length}/{draft.fields.length} 个字段</span>
          </div>

          <div className="monitoring-mapping-table" role="table" aria-label="字段映射草稿">
            <div className="monitoring-mapping-row header" role="row">
              <span>来源字段</span>
              <span>建议角色</span>
              <span>字段类型</span>
              <span>置信度</span>
              <span aria-label="操作" />
            </div>
            {displayedFields.map((field) => {
              const key = `${field.domain}::${field.source_field}`;
              return (
                <button
                  type="button"
                  role="row"
                  className={`monitoring-mapping-row ${selectedFieldKey === key ? "active" : ""}`}
                  key={key}
                  onClick={() => selectField(field)}
                >
                  <span><b>{field.domain}</b>{field.source_field}</span>
                  <span title={field.recommended_role}>{field.recommended_role}</span>
                  <span>{FIELD_KIND_LABELS[field.field_kind] || field.field_kind}</span>
                  <span
                    className={
                      Number(field.confidence) < LOW_CONFIDENCE_THRESHOLD
                        ? "low"
                        : ""
                    }
                  >
                    {confidenceLabel(field.confidence)}
                  </span>
                  <Pencil size={14} />
                </button>
              );
            })}
          </div>

          {fieldForm && (
            <div className="monitoring-mapping-field-editor">
              <div>
                <strong>{fieldForm.domain}.{fieldForm.source_field}</strong>
                <button className="icon-button" type="button" title="关闭字段编辑" onClick={() => setFieldForm(null)}>
                  <X size={14} />
                </button>
              </div>
              <label>
                建议角色
                <input
                  disabled={confirmedReadOnly}
                  value={fieldForm.recommended_role}
                  onChange={(event) => setFieldForm((current) => ({
                    ...current,
                    recommended_role: event.target.value,
                  }))}
                />
              </label>
              <label>
                字段类型
                <select
                  disabled={confirmedReadOnly}
                  value={fieldForm.field_kind}
                  onChange={(event) => changeFieldKind(event.target.value)}
                >
                  {Object.entries(FIELD_KIND_LABELS).map(([value, label]) => (
                    <option value={value} key={value}>{label}</option>
                  ))}
                </select>
              </label>
              {fieldForm.evidence_summary?.length > 0 && (
                <section className="monitoring-mapping-evidence">
                  <strong>原始画像依据</strong>
                  {fieldForm.evidence_summary.map((item, index) => (
                    <div key={medicalMonitoringFieldMappingEvidenceKey(item, index)}>
                      <span>
                        {item.profile?.non_empty_count}/{item.profile?.total_rows}
                        {" 条非空 · "}
                        {item.profile?.inferred_type || "类型待定"}
                      </span>
                      <small>{item.locator || "来源定位待核对"}</small>
                      {!item.evidence_id && !item.locator && (
                        <small>来源证据身份缺失；不可据此确认映射</small>
                      )}
                    </div>
                  ))}
                </section>
              )}
              {fieldForm.standards_reference && (
                <section className="monitoring-mapping-evidence">
                  <strong>标准参照（仅作参照）</strong>
                  <span>
                    {fieldForm.standards_reference.reference_name}
                    {" · "}
                    {fieldForm.standards_reference.reference_concept}
                  </span>
                  <small>{fieldForm.standards_reference.uncertainty}</small>
                </section>
              )}
              {fieldForm.field_kind === "standardized_coded" && (
                <fieldset className="monitoring-mapping-lineage">
                  <legend>编码血缘</legend>
                  <label>
                    来源字段
                    <input
                      disabled={confirmedReadOnly}
                      value={(fieldForm.derivation_lineage?.source_fields || []).join(", ")}
                      onChange={(event) => updateLineage(
                        "source_fields",
                        event.target.value.split(","),
                      )}
                      placeholder="如 AETERM, AEDECOD"
                    />
                  </label>
                  <label>
                    编码体系
                    <input
                      disabled={confirmedReadOnly}
                      value={fieldForm.derivation_lineage?.coding_system || ""}
                      onChange={(event) => updateLineage(
                        "coding_system",
                        event.target.value,
                      )}
                      placeholder="如 MedDRA"
                    />
                  </label>
                  <label>
                    词典版本
                    <input
                      disabled={confirmedReadOnly}
                      value={fieldForm.derivation_lineage?.dictionary_version || ""}
                      onChange={(event) => updateLineage(
                        "dictionary_version",
                        event.target.value,
                      )}
                      placeholder="填写版本或对应版本字段"
                    />
                  </label>
                </fieldset>
              )}
              {fieldForm.field_kind === "deterministic_derived" && (
                <fieldset className="monitoring-mapping-lineage">
                  <legend>派生血缘</legend>
                  <label>
                    来源字段
                    <input
                      disabled={confirmedReadOnly}
                      value={(fieldForm.derivation_lineage?.source_fields || []).join(", ")}
                      onChange={(event) => updateLineage(
                        "source_fields",
                        event.target.value.split(","),
                      )}
                      placeholder="以逗号分隔"
                    />
                  </label>
                  <label>
                    计算规则
                    <textarea
                      disabled={confirmedReadOnly}
                      rows={3}
                      value={fieldForm.derivation_lineage?.formula || ""}
                      onChange={(event) => updateLineage(
                        "formula",
                        event.target.value,
                      )}
                    />
                  </label>
                </fieldset>
              )}
              <label>
                不确定性
                <textarea
                  disabled={confirmedReadOnly}
                  rows={3}
                  value={fieldForm.uncertainty}
                  onChange={(event) => setFieldForm((current) => ({
                    ...current,
                    uncertainty: event.target.value,
                  }))}
                />
              </label>
              <label>
                建议核对
                <textarea
                  disabled={confirmedReadOnly}
                  rows={2}
                  value={fieldForm.user_action}
                  onChange={(event) => setFieldForm((current) => ({
                    ...current,
                    user_action: event.target.value,
                  }))}
                />
              </label>
              {!confirmedReadOnly && (
                <button className="primary-button" type="button" disabled={busy} onClick={saveField}>
                  保存修订
                </button>
              )}
            </div>
          )}

          <footer className="monitoring-mapping-confirm">
            {semanticQuality && (
              <div
                className={`monitoring-mapping-quality-summary ${semanticQualityState.level}`}
              >
                <strong>{semanticQualityState.title}</strong>
                {semanticQualityState.detail && (
                  <span>{semanticQualityState.detail}</span>
                )}
              </div>
            )}
            <div className="monitoring-mapping-change-summary">
              <strong>{changedFields.length} 项已修订</strong>
              <span>{attentionCount} 项属于重点校对范围</span>
            </div>
            <label>
              <span>{confirmedReadOnly ? "启用说明" : "确认说明"}</span>
              <input
                value={confirmationReason}
                onChange={(event) => setConfirmationReason(event.target.value)}
                disabled={confirmedReadOnly}
              />
            </label>
            <button
              className="primary-button"
              type="button"
              disabled={
                confirmedReadOnly
                || busy
                || semanticQualityState.blocksConfirmation
                || confirmationReason.trim().length < 10
              }
              onClick={confirmDraft}
            >
              {confirmedReadOnly ? "已启用" : "确认字段映射"}
            </button>
          </footer>
          {confirmedRevision && (
            <p className="monitoring-mapping-success">
              <Check size={15} />
              正式映射已生成，后续批次将继续保留该版本的来源与修订记录。
            </p>
          )}
        </div>
      )}

      {message && <p className="monitoring-mapping-message">{message}</p>}
      {error && <p className="monitoring-mapping-error">{error}</p>}
    </section>
  );
}
