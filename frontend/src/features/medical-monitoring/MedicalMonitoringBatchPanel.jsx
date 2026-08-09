import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookOpenCheck,
  CheckCircle2,
  Database,
  RefreshCw,
  Upload,
  X,
} from "lucide-react";

import {
  MedicalMonitoringApiError,
  createMedicalMonitoringApi,
} from "./medicalMonitoringApi.mjs";
import MedicalMonitoringDailyRunPanel from "./MedicalMonitoringDailyRunPanel.jsx";
import MedicalMonitoringFieldMappingPanel from "./MedicalMonitoringFieldMappingPanel.jsx";
import MedicalMonitoringProtocolPreparationPanel from "./MedicalMonitoringProtocolPreparationPanel.jsx";
import MedicalMonitoringRuleReleasePanel from "./MedicalMonitoringRuleReleasePanel.jsx";
import {
  createMedicalMonitoringProjectRequestScope,
} from "./medicalMonitoringProjectRequestScope.mjs";
import {
  normalizeBatchDetail,
  normalizeBatchIntakeResult,
  normalizeBatchList,
  normalizeBatchMutationResult,
  normalizeClassificationConfirmationDetail,
  normalizeContentConfirmationDetail,
} from "./medicalMonitoringBatchView.mjs";
import { monitoringFieldMappingCopy } from "./medicalMonitoringModels.mjs";

const STATE_LABELS = {
  draft: "已解析",
  parsed: "待确认完整性",
  validated: "校验完成",
  confirmed: "完整性已确认",
  frozen: "不可变候选批次",
};

const SOURCE_CLASS_LABELS = {
  raw_full_snapshot: "原始全量快照",
  raw_full_snapshot_candidate: "原始全量快照（待确认）",
  verified_derived_full_snapshot: "已验证派生全量快照",
  comparison_workbook: "比较文件（不可作基线）",
  mixed_monitoring_workbook: "混合监查文件（不可作基线）",
  raw_snapshot_with_format_defect: "格式异常快照（不可作基线）",
  restored_transitional: "还原过渡文件（不可作基线）",
  processed_full_snapshot: "处理后全量快照（需B级确认）",
  unknown_blocked: "无法识别",
};

function sourceClassLabel(value) {
  return SOURCE_CLASS_LABELS[value] || value || "-";
}

function requestKey(prefix) {
  const random = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`;
}

function detailFromError(error) {
  if (!(error instanceof MedicalMonitoringApiError)) return null;
  const detail = error.detail?.detail;
  return detail && typeof detail === "object" ? detail : null;
}

function stateTone(state) {
  if (state === "frozen") return "success";
  if (state === "draft" || state === "parsed") return "warning";
  return "info";
}

function BatchState({ state }) {
  return (
    <span className={`monitoring-batch-state ${stateTone(state)}`}>
      {STATE_LABELS[state] || state}
    </span>
  );
}

export default function MedicalMonitoringBatchPanel(props) {
  return (
    <MedicalMonitoringBatchPanelForProject
      key={props.projectId}
      {...props}
    />
  );
}

function MedicalMonitoringBatchPanelForProject({
  projectId,
  onClose,
  aiStatus = {},
}) {
  const api = useMemo(() => createMedicalMonitoringApi(), []);
  const requestScope = useMemo(
    () => createMedicalMonitoringProjectRequestScope(projectId),
    [projectId],
  );
  const fileInputRef = useRef(null);
  const [batches, setBatches] = useState([]);
  const [activeBatch, setActiveBatch] = useState(null);
  const [file, setFile] = useState(null);
  const [intakeKey, setIntakeKey] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [pendingConfirmation, setPendingConfirmation] = useState(null);
  const [acknowledgedCodes, setAcknowledgedCodes] = useState([]);
  const [fullSnapshotConfirmed, setFullSnapshotConfirmed] = useState(false);
  const [fieldMappingOpen, setFieldMappingOpen] = useState(false);
  const [protocolPreparationOpen, setProtocolPreparationOpen] = useState(false);
  const [ruleReleaseOpen, setRuleReleaseOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const mappingCopy = useMemo(
    () => monitoringFieldMappingCopy(aiStatus),
    [aiStatus],
  );

  const clearBatchState = useCallback(() => {
    setBatches([]);
    setActiveBatch(null);
    setPendingConfirmation(null);
    setAcknowledgedCodes([]);
    setFullSnapshotConfirmed(false);
  }, []);

  const loadBatches = useCallback(async (focusBatchId = "") => {
    const request = requestScope.begin("batch-view");
    try {
      const payload = normalizeBatchList(await api.listBatches(
        projectId,
        { signal: request.signal },
      ));
      if (!requestScope.isCurrent(request)) return null;
      const nextBatches = payload.batches;
      setBatches(nextBatches);
      const focusedBatches = focusBatchId
        ? nextBatches.filter((batch) => batch.batch_id === focusBatchId && batch.displayIdentityState === "ready")
        : [];
      if (focusBatchId && focusedBatches.length !== 1) {
        setActiveBatch(null);
        return null;
      }
      const batchId = focusedBatches[0]?.batch_id
        || nextBatches.find((batch) => batch.displayIdentityState === "ready")?.batch_id;
      if (!batchId) {
        setActiveBatch(null);
        return null;
      }
      const nextBatch = normalizeBatchDetail(await api.getBatch(
        projectId,
        batchId,
        { signal: request.signal },
      ));
      if (!requestScope.isCurrent(request)) return null;
      setActiveBatch(nextBatch);
      setFullSnapshotConfirmed(false);
      return nextBatch;
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return null;
      throw nextError;
    } finally {
      requestScope.finish(request);
    }
  }, [api, projectId, requestScope]);

  const refreshBatches = useCallback(async (focusBatchId = "") => {
    setBusy(true);
    setError("");
    try {
      return await loadBatches(focusBatchId);
    } catch (nextError) {
      if (nextError?.name !== "AbortError") {
        clearBatchState();
      }
      setError(nextError.message || "批次读取失败");
      return null;
    } finally {
      setBusy(false);
    }
  }, [clearBatchState, loadBatches]);

  useEffect(() => {
    requestScope.activate();
    return () => requestScope.dispose();
  }, [requestScope]);

  useEffect(() => {
    let mounted = true;
    setBusy(true);
    setError("");
    loadBatches()
      .catch((nextError) => {
        if (mounted) {
          if (nextError?.name !== "AbortError") {
            clearBatchState();
          }
          setError(nextError.message || "批次读取失败");
        }
      })
      .finally(() => {
        if (mounted) setBusy(false);
      });
    return () => {
      mounted = false;
      requestScope.cancel("batch-view");
    };
  }, [clearBatchState, loadBatches, requestScope]);

  const retryIntake = async (classificationReason = overrideReason) => {
    if (!file) return;
    const request = requestScope.begin("batch-intake");
    const currentKey = intakeKey || requestKey("monitoring-intake");
    if (!intakeKey) setIntakeKey(currentKey);
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = normalizeBatchIntakeResult(await api.intakeBatchFile(projectId, file, {
        signal: request.signal,
        idempotencyKey: currentKey,
        classificationOverrideReason: classificationReason,
      }));
      if (!requestScope.isCurrent(request)) return;
      const batchId = result.batch.batch.batch_id;
      setPendingConfirmation(null);
      setAcknowledgedCodes([]);
      setMessage("批次已解析并保存，尚未运行医学风险规则。");
      await loadBatches(batchId);
      if (!requestScope.isCurrent(request)) return;
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      const detail = detailFromError(nextError);
      if (detail?.code === "source_content_confirmation_required") {
        try {
          const contentDetail = normalizeContentConfirmationDetail(detail);
          const unresolved = contentDetail.validation.checks
            .filter((check) => ["warning", "mismatch"].includes(check.outcome))
            .map((check) => check.check_code);
          setAcknowledgedCodes([]);
          setPendingConfirmation({
            kind: "content",
            sourceEntryId: contentDetail.source_entry_id,
            validation: contentDetail.validation,
            unresolved,
          });
        } catch (shapeError) {
          clearBatchState();
          setError(shapeError.message || "来源内容校验回执字段异常");
        }
        return;
      }
      if (detail?.code === "listing_classification_confirmation_required") {
        try {
          const classificationDetail = normalizeClassificationConfirmationDetail(detail);
          setPendingConfirmation({
            kind: "classification",
            classification: classificationDetail.classification,
            sourceEntryId: classificationDetail.source_entry_id,
          });
        } catch (shapeError) {
          clearBatchState();
          setError(shapeError.message || "来源分类回执字段异常");
        }
        return;
      }
      if (nextError?.name !== "AbortError") {
        clearBatchState();
      }
      setError(nextError.message || "批次导入失败");
    } finally {
      if (requestScope.isCurrent(request)) setBusy(false);
      requestScope.finish(request);
    }
  };

  const confirmContent = async () => {
    const pending = pendingConfirmation;
    if (pending?.kind !== "content") return;
    const request = requestScope.begin("content-confirmation");
    setBusy(true);
    setError("");
    try {
      await api.confirmSourceContent(projectId, pending.sourceEntryId, {
        reason: overrideReason.trim(),
        acknowledged_check_codes: acknowledgedCodes,
        expected_revision: pending.validation.revision,
        idempotency_key: requestKey("monitoring-content-confirmation"),
      }, { signal: request.signal });
      if (!requestScope.isCurrent(request)) return;
      setPendingConfirmation(null);
      await retryIntake();
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      setError(nextError.message || "内容确认失败");
      setBusy(false);
    } finally {
      requestScope.finish(request);
    }
  };

  const confirmClassification = async () => {
    setPendingConfirmation(null);
    await retryIntake(overrideReason.trim());
  };

  const transitionToParsed = async () => {
    if (!activeBatch) return;
    const request = requestScope.begin("batch-transition");
    setBusy(true);
    setError("");
    try {
      const result = normalizeBatchMutationResult(await api.transitionBatch(projectId, activeBatch.batch_id, {
        target_state: "parsed",
        expected_version: activeBatch.version,
        idempotency_key: requestKey("monitoring-parsed"),
      }, { signal: request.signal }));
      if (!requestScope.isCurrent(request)) return;
      await loadBatches(result.batch.batch_id);
      if (!requestScope.isCurrent(request)) return;
      setMessage("解析结果已确认。请核对数据域及本次是否为完整全量导出。");
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      if (nextError?.name !== "AbortError") {
        clearBatchState();
      }
      setError(nextError.message || "解析确认失败");
    } finally {
      if (requestScope.isCurrent(request)) setBusy(false);
      requestScope.finish(request);
    }
  };

  const freezeBatch = async () => {
    if (!activeBatch || !fullSnapshotConfirmed) return;
    const request = requestScope.begin("batch-freeze");
    const activeSource = activeBatch.sources?.[0];
    const isProcessedSource = activeSource?.source_class === "processed_full_snapshot";
    setBusy(true);
    setError("");
    try {
      const frozen = normalizeBatchMutationResult(await api.confirmBatchFullSnapshot(
        projectId,
        activeBatch.batch_id,
        {
          full_snapshot_proof: {
            confirmed: true,
            basis: isProcessedSource
              ? `医学经理确认 ${activeSource?.file_name || "该文件"} 为完整项目级处理后快照，可用于增量比较；不作为原始EDC权威证据。`
              : `医学经理确认 ${activeSource?.file_name || "该文件"} 为本次完整全量EDC导出。`,
            confirmed_by: "medical_manager",
            ...(isProcessedSource ? {
              source_authority_grade: "B",
              processed_source_acknowledged: true,
            } : {}),
          },
          expected_version: activeBatch.version,
          idempotency_key: requestKey("monitoring-full-snapshot"),
        },
        { signal: request.signal },
      ));
      if (!requestScope.isCurrent(request)) return;
      await loadBatches(frozen.batch.batch_id);
      if (!requestScope.isCurrent(request)) return;
      setMessage("批次已冻结为不可变候选；完成差异分析、风险复核和医学确认后才会成为下一批比较基线。");
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      const detail = detailFromError(nextError);
      if ([
        "monitoring_mapping_required",
        "monitoring_mapping_difference_review_required",
      ].includes(detail?.code)) {
        setFieldMappingOpen(true);
        setMessage(
          detail.code === "monitoring_mapping_required"
            ? "请先完成字段识别与校对，再确认本批次。"
            : "检测到字段结构变化，请先校对差异字段。",
        );
      } else {
        if (nextError?.name !== "AbortError") {
          clearBatchState();
        }
        setError(nextError.message || "批次确认失败");
      }
    } finally {
      if (requestScope.isCurrent(request)) setBusy(false);
      requestScope.finish(request);
    }
  };

  const selectBatch = async (batchId) => {
    const matchingBatches = batches.filter((batch) => batch.batch_id === batchId);
    if (matchingBatches.length !== 1 || matchingBatches[0].displayIdentityState !== "ready") {
      setError("该批次身份重复或待核对，暂不能打开。");
      return;
    }
    const request = requestScope.begin("batch-view");
    setBusy(true);
    setError("");
    try {
      const nextBatch = normalizeBatchDetail(await api.getBatch(
        projectId,
        batchId,
        { signal: request.signal },
      ));
      if (!requestScope.isCurrent(request)) return;
      setActiveBatch(nextBatch);
      setFullSnapshotConfirmed(false);
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      if (nextError?.name !== "AbortError") {
        clearBatchState();
      }
      setError(nextError.message || "批次读取失败");
    } finally {
      if (requestScope.isCurrent(request)) setBusy(false);
      requestScope.finish(request);
    }
  };

  const source = activeBatch?.sources?.[0];
  const processedBaselineEligible = source?.source_class === "processed_full_snapshot"
    && Boolean(source?.medical_override_reason?.trim());
  const baselineEligible = source?.source_class === "raw_full_snapshot"
    || source?.source_class === "raw_full_snapshot_candidate"
    || source?.source_class === "verified_derived_full_snapshot"
    || processedBaselineEligible;
  const unresolvedCount = pendingConfirmation?.unresolved?.length || 0;
  const allContentChecksAcknowledged = unresolvedCount > 0
    && acknowledgedCodes.length === unresolvedCount;

  return (
    <section className="panel monitoring-batch-panel" aria-label="医学监查批次管理">
      <div className="monitoring-batch-panel-head">
        <div>
          <span>数据批次</span>
          <strong>导入定期 EDC data listing</strong>
        </div>
        <div className="button-row">
          <button
            className="monitoring-protocol-prep-entry"
            type="button"
            onClick={() => setProtocolPreparationOpen(true)}
          >
            <BookOpenCheck size={15} />
            准备方案规则
          </button>
          <button
            className="monitoring-protocol-prep-entry"
            type="button"
            onClick={() => setRuleReleaseOpen(true)}
          >
            <CheckCircle2 size={15} />
            规则发布
          </button>
          <button
            className="icon-button"
            type="button"
            title="刷新批次"
            onClick={() => refreshBatches(activeBatch?.batch_id)}
            disabled={busy}
          >
            <RefreshCw size={15} />
          </button>
          <button className="icon-button" type="button" title="关闭" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="monitoring-batch-workspace">
        <div className="monitoring-batch-upload">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xls,.xlsx,.xlsm"
            onChange={(event) => {
              const nextFile = event.target.files?.[0] || null;
              setFile(nextFile);
              setIntakeKey(nextFile ? requestKey("monitoring-intake") : "");
              setPendingConfirmation(null);
              setOverrideReason("");
              setAcknowledgedCodes([]);
              setError("");
              setMessage("");
            }}
          />
          <button
            type="button"
            onClick={() => {
              if (!fileInputRef.current) return;
              // Selecting the same file again must still create a fresh intake request.
              fileInputRef.current.value = "";
              fileInputRef.current.click();
            }}
          >
            <Upload size={16} />
            {file ? "更换文件" : "选择 listing"}
          </button>
          <div>
            <strong>{file?.name || "尚未选择文件"}</strong>
            <span>支持 CSV、XLS、XLSX、XLSM；导入后保留原文件。</span>
          </div>
          <button
            className="primary-button"
            type="button"
            disabled={!file || busy}
            onClick={() => retryIntake()}
          >
            {busy ? "处理中" : "导入并解析"}
          </button>
        </div>

        <div className="monitoring-batch-list" aria-label="历史批次">
          {batches.length ? batches.map((batch) => {
            const ambiguous = batch.displayIdentityState !== "ready";
            return (
              <button
                type="button"
                className={!ambiguous && activeBatch?.batch_id === batch.batch_id ? "active" : ""}
                key={batch.displayKey}
                disabled={ambiguous}
                aria-disabled={ambiguous ? "true" : undefined}
                title={ambiguous ? batch.displayIdentityIssue : undefined}
                onClick={() => {
                  if (!ambiguous) selectBatch(batch.batch_id);
                }}
              >
                <Database size={15} />
                <span>{new Date(batch.created_at).toLocaleString("zh-CN")}</span>
                <BatchState state={batch.state} />
                {ambiguous && <span className="monitoring-batch-state warning">身份待核对</span>}
              </button>
            );
          }) : <span className="monitoring-batch-empty">当前项目尚无导入批次</span>}
        </div>

        {activeBatch && (
          <div className="monitoring-batch-summary">
            <div>
              <span>文件</span>
              <strong>{source?.file_name || "-"}</strong>
            </div>
            <div>
              <span>记录</span>
              <strong>{activeBatch.row_count?.toLocaleString?.("zh-CN") || activeBatch.row_count || "-"}</strong>
            </div>
            <div>
              <span>数据域</span>
              <strong>{activeBatch.expected_domains?.length || 0}</strong>
            </div>
            <div>
              <span>来源类型</span>
              <strong title={source?.source_class || ""}>
                {source?.source_class === "raw_full_snapshot_candidate" && activeBatch.state === "frozen"
                  ? "原始全量快照（已确认）"
                  : sourceClassLabel(source?.source_class)}
              </strong>
            </div>
            <BatchState state={activeBatch.state} />
          </div>
        )}

        {activeBatch?.expected_domains?.length > 0 && (
          <div className="monitoring-domain-strip">
            {activeBatch.expected_domains.map((domain) => (
              <span key={domain}>{domain}</span>
            ))}
          </div>
        )}

        {activeBatch?.state === "draft" && (
          <div className="monitoring-batch-action">
            <div>
              <strong>解析已完成</strong>
              <span>确认记录数和数据域后进入完整性核对；此操作不会运行风险规则。</span>
            </div>
            <button className="primary-button" type="button" disabled={busy} onClick={transitionToParsed}>
              确认解析结果
            </button>
          </div>
        )}

        {activeBatch?.state === "parsed" && (
          <div className="monitoring-batch-action">
            <label>
              <input
                type="checkbox"
                checked={fullSnapshotConfirmed}
                disabled={!baselineEligible}
                onChange={(event) => setFullSnapshotConfirmed(event.target.checked)}
              />
              <span>
                <strong>
                  {source?.source_class === "processed_full_snapshot"
                    ? "确认这是完整项目级 EDC 快照（B级处理后来源）"
                    : "确认这是本次完整全量 EDC 导出"}
                </strong>
                <small>
                  {source?.source_class === "processed_full_snapshot"
                    ? "可用于增量比较；不改变处理后来源身份，也不能作为原始 EDC 权威证据。"
                    : "缺失记录将只有在前后两批均完成此确认后才可解释为删除。"}
                </small>
              </span>
            </label>
            <button
              className="primary-button"
              type="button"
              disabled={!fullSnapshotConfirmed || !baselineEligible || busy}
              onClick={freezeBatch}
            >
              冻结候选批次
            </button>
          </div>
        )}

        {activeBatch?.state === "parsed" && source?.source_class === "processed_full_snapshot"
          && !processedBaselineEligible && (
          <p className="monitoring-batch-inline-note">
            处理后快照只有在文件基本信息已由医学经理确认并记录理由后，才可按 B 级来源用于
            增量比较；其来源身份不会被改写。
          </p>
        )}

        {activeBatch?.state === "parsed" && !baselineEligible
          && source?.source_class !== "processed_full_snapshot" && (
          <p className="monitoring-batch-inline-note">
            当前来源类型不能作为全量比较基线；文件仍可保留用于人工复核，但不会被改写为原始快照。
          </p>
        )}

        {["parsed", "frozen"].includes(activeBatch?.state) && !fieldMappingOpen && (
          <div className="monitoring-batch-action monitoring-batch-mapping-entry">
            <div>
              <strong>{mappingCopy.entryTitle}</strong>
              <span>{mappingCopy.entryDescription}</span>
            </div>
            <button
              className="primary-button"
              type="button"
              title={mappingCopy.entryDescription}
              onClick={() => setFieldMappingOpen(true)}
            >
              {mappingCopy.entryAction}
            </button>
          </div>
        )}

        {["parsed", "frozen"].includes(activeBatch?.state) && fieldMappingOpen && (
          <MedicalMonitoringFieldMappingPanel
            projectId={projectId}
            batch={activeBatch}
            aiStatus={aiStatus}
            onClose={() => setFieldMappingOpen(false)}
            onConfirmed={() => {
              setFieldMappingOpen(false);
              setMessage("项目字段映射已启用，可继续确认本批次。");
              refreshBatches(activeBatch.batch_id);
            }}
          />
        )}

        {activeBatch?.state === "frozen" && !fieldMappingOpen && (
          <MedicalMonitoringDailyRunPanel
            projectId={projectId}
            batch={activeBatch}
            api={api}
            onMappingRequired={() => setFieldMappingOpen(true)}
            onRulePackRequired={() => setRuleReleaseOpen(true)}
            onBaselineConfirmed={() => {
              setMessage("本次医学监查已确认，该批次已成为下一次比较基线。");
              refreshBatches(activeBatch.batch_id);
            }}
          />
        )}

        {pendingConfirmation?.kind === "content" && (
          <div className="monitoring-batch-confirmation">
            <div>
              <AlertTriangle size={17} />
              <strong>请核对文件基本信息</strong>
            </div>
            <p>{pendingConfirmation.validation?.summary}</p>
            {pendingConfirmation.validation.checks
              .filter((check) => ["warning", "mismatch"].includes(check.outcome))
              .map((check) => (
                <label key={check.check_code}>
                  <input
                    type="checkbox"
                    checked={acknowledgedCodes.includes(check.check_code)}
                    onChange={(event) => setAcknowledgedCodes((current) => (
                      event.target.checked
                        ? [...current, check.check_code]
                        : current.filter((code) => code !== check.check_code)
                    ))}
                  />
                  <span>
                    <strong>{check.label}</strong>
                    <small>{check.observed_value || "未识别到可核对信息"}</small>
                  </span>
                </label>
              ))}
            <textarea
              value={overrideReason}
              onChange={(event) => setOverrideReason(event.target.value)}
              placeholder="说明为何确认该文件属于当前项目和本次数据批次。"
            />
            <button
              className="primary-button"
              type="button"
              disabled={!allContentChecksAcknowledged || overrideReason.trim().length < 10 || busy}
              onClick={confirmContent}
            >
              确认并继续
            </button>
          </div>
        )}

        {pendingConfirmation?.kind === "classification" && (
          <div className="monitoring-batch-confirmation">
            <div>
              <AlertTriangle size={17} />
              <strong>确认来源类型</strong>
            </div>
            <p>
              系统识别为{sourceClassLabel(pendingConfirmation.classification?.source_class)}。
              {pendingConfirmation.classification.content_warnings.join(" ")}
            </p>
            <textarea
              value={overrideReason}
              onChange={(event) => setOverrideReason(event.target.value)}
              placeholder="说明继续导入该文件的医学用途；确认不会改变来源分类。"
            />
            <button
              className="primary-button"
              type="button"
              disabled={overrideReason.trim().length < 10 || busy}
              onClick={confirmClassification}
            >
              保留原分类并继续
            </button>
          </div>
        )}

        {message && (
          <p className="monitoring-batch-message">
            <CheckCircle2 size={15} />
            {message}
          </p>
        )}
        {error && <p className="monitoring-batch-error">{error}</p>}
      </div>
      {protocolPreparationOpen && (
        <MedicalMonitoringProtocolPreparationPanel
          projectId={projectId}
          aiStatus={aiStatus}
          onClose={() => setProtocolPreparationOpen(false)}
          onOpenRuleRelease={() => {
            setProtocolPreparationOpen(false);
            setRuleReleaseOpen(true);
          }}
        />
      )}
      {ruleReleaseOpen && (
        <MedicalMonitoringRuleReleasePanel
          projectId={projectId}
          onClose={() => setRuleReleaseOpen(false)}
          onOpenProtocolPreparation={() => {
            setRuleReleaseOpen(false);
            setProtocolPreparationOpen(true);
          }}
          onOpenMapping={() => {
            setRuleReleaseOpen(false);
            setFieldMappingOpen(true);
          }}
          onPublished={() => refreshBatches(activeBatch?.batch_id)}
        />
      )}
    </section>
  );
}
