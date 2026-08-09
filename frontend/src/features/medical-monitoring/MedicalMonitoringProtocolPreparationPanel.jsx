import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpenCheck,
  Check,
  CheckCircle2,
  CircleAlert,
  FileSearch,
  LoaderCircle,
  RefreshCw,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";

import {
  MedicalMonitoringApiError,
  createMedicalMonitoringApi,
} from "./medicalMonitoringApi.mjs";
import {
  PROTOCOL_PREPARATION_STATUS_LABELS,
  acceptedProtocolCandidateFact,
  acceptedProtocolFacts,
  applyProtocolCandidateDecision,
  buildProtocolCandidateDecisionPayload,
  candidateReferencedEvidence,
  candidateConfidenceSummary,
  candidateStructuredSections,
  confirmedProtocolVersions,
  newlyAcceptedProtocolDecisionFact,
  protocolCandidateDecisionLabel,
  protocolFactTypeOptions,
  protocolPreparationCandidateDisplayKey,
  protocolPreparationCandidateIdentityReady,
  protocolPreparationEvidenceDisplayKey,
  protocolPreparationProgress,
  protocolPreparationStartAction,
  protocolPreparationTopicDisplayKey,
  protocolPreparationTopicTone,
  protocolPreparationVersionDisplayKey,
  normalizeProtocolPreparationStatus,
  resolveProtocolCandidateInputRevision,
  shouldPollProtocolPreparation,
} from "./medicalMonitoringProtocolPreparation.mjs";
import {
  applyRuleTemplateRecommendationDecision,
  buildRuleTemplateRecommendationDecisionPayload,
  buildRuleTemplateRecommendationStartPayload,
  ruleTemplateRecommendationViewModel,
  shouldPollRuleTemplateRecommendation,
} from "./medicalMonitoringRuleTemplateRecommendation.mjs";
import {
  MedicalMonitoringRuleTemplateShapeError,
  normalizeRuleTemplateDecisionResponse,
  normalizeRuleTemplateRecommendationPayload,
} from "./medicalMonitoringRuleTemplateView.mjs";
import {
  createMedicalMonitoringProjectRequestScope,
} from "./medicalMonitoringProjectRequestScope.mjs";
import "./MedicalMonitoringProtocolPreparationPanel.css";

const POLL_INTERVAL_MS = 5000;
const DEFAULT_REJECTION_REASON = "该候选不适用于当前方案监查。";

function normalizeStatusOrThrow(payload) {
  const normalized = normalizeProtocolPreparationStatus(payload);
  if (!normalized.ok) throw new Error(normalized.error);
  return normalized.value;
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

function versionOptionLabel(version) {
  return [
    version.source_title,
    version.version_label,
    version.version_date,
  ].filter(Boolean).join(" · ");
}

function TopicStateIcon({ status }) {
  if (status === "running" || status === "queued") {
    return <LoaderCircle className="monitoring-protocol-prep-spinner" size={15} />;
  }
  if (status === "reviewed") return <CheckCircle2 size={15} />;
  if (["failed", "blocked", "stale_input", "cancelled"].includes(status)) {
    return <CircleAlert size={15} />;
  }
  return <BookOpenCheck size={15} />;
}

function RuleTemplateRecommendation({
  state,
  onStart,
  onDecision,
  onOpenRuleRelease,
  aiAvailable = false,
}) {
  const [confirmationReasons, setConfirmationReasons] = useState({});
  const view = ruleTemplateRecommendationViewModel({
    payload: state?.payload,
    loading: state?.loading,
    busy: state?.busy,
    error: state?.error,
  });

  if (view.mode === "loading" || view.mode === "progress") {
    return (
      <div className="monitoring-rule-template-compact" aria-live="polite">
        <LoaderCircle size={14} />
        <span>
          {view.mode === "loading" ? "正在读取规则建议" : view.label}
        </span>
      </div>
    );
  }

  if (view.mode === "ready") {
    return (
      <div className="monitoring-rule-template-ready">
        <span>
          {aiAvailable
            ? "方案事实已确认，可生成与当前字段映射匹配的确定性规则建议。"
            : "方案事实已确认；独立AI当前不可运行，配置后再生成规则建议。"}
        </span>
        <button type="button" disabled={!view.canStart || !aiAvailable} onClick={onStart}>
          <Sparkles size={14} />
          {aiAvailable ? "生成规则建议" : "等待独立AI"}
        </button>
      </div>
    );
  }

  if (view.mode === "manual_review") {
    return (
      <div className="monitoring-rule-template-manual">
        <CircleAlert size={14} />
        <span>{view.message || "该条款暂不适合转换为确定性规则，请人工处理。"}</span>
      </div>
    );
  }

  if (view.mode === "compiled") {
    return (
      <div className="monitoring-rule-template-compiled">
        <CheckCircle2 size={15} />
        <div>
          <strong>采用已完成，规则为医学已确认状态</strong>
          <span>请在「规则发布」中组建规则包，完成影子样本核对、确认与发布。</span>
        </div>
        {onOpenRuleRelease && (
          <button type="button" onClick={onOpenRuleRelease}>
            前往规则发布
          </button>
        )}
      </div>
    );
  }

  if (view.mode === "error") {
    return (
      <div className="monitoring-rule-template-error">
        <CircleAlert size={14} />
        <span>{view.message || "规则建议暂不可用，请刷新当前方案状态后重试。"}</span>
      </div>
    );
  }

  if (view.mode === "reviewed") {
    return (
      <div className="monitoring-rule-template-manual">
        <span>本组规则建议均未采用，可保留为人工核对项。</span>
      </div>
    );
  }

  if (view.mode !== "candidate_review") return null;

  return (
    <section className="monitoring-rule-template-review">
      <header>
        <strong>选择规则建议</strong>
        <span>采用即完成确定性编译</span>
      </header>
      <div className="monitoring-rule-template-list">
        {view.candidates.map((candidate, index) => {
          const decision = state?.candidateDecisions?.[candidate.candidateId];
          const proposed = candidate.status === "proposed";
          const confidenceSummary = candidate.confidenceSummary;
          const lowConfidence = confidenceSummary?.requires_additional_evidence;
          const confirmationReason = confirmationReasons[candidate.candidateId] || "";
          return (
            <article
              key={candidate.candidateId}
              className="monitoring-rule-template-candidate"
            >
              <header>
                <span>建议 {index + 1}</span>
                <strong>{candidate.title}</strong>
              </header>
              <div className={`monitoring-rule-template-confidence${lowConfidence ? " low" : ""}`}>
                <strong>{confidenceSummary?.label || "需人工确认来源"}</strong>
                {confidenceSummary?.confidence_floor !== null
                  && confidenceSummary?.confidence_floor !== undefined && (
                    <span>
                      最低 {Math.round(confidenceSummary.confidence_floor * 100)}%
                      （阈值 {Math.round((confidenceSummary.threshold || 0.70) * 100)}%）
                    </span>
                  )}
                {lowConfidence && (
                  <p>采用前请补充来源核对、数据缺口或医学确认理由；系统不会自动采用。</p>
                )}
              </div>
              {candidate.summary && <p>{candidate.summary}</p>}
              <dl>
                {candidate.rationale && (
                  <div>
                    <dt>推荐理由</dt>
                    <dd>{candidate.rationale}</dd>
                  </div>
                )}
                {candidate.tradeoffs.length > 0 && (
                  <div>
                    <dt>取舍</dt>
                    <dd>
                      <ul className="monitoring-rule-template-tradeoffs">
                        {candidate.tradeoffs.map((tradeoff) => (
                          <li key={tradeoff}>{tradeoff}</li>
                        ))}
                      </ul>
                    </dd>
                  </div>
                )}
                {candidate.requiredDomains.length > 0 && (
                  <div>
                    <dt>所需数据域</dt>
                    <dd>{candidate.requiredDomains.join("、")}</dd>
                  </div>
                )}
                {candidate.mappingFields.length > 0 && (
                  <div>
                    <dt>所需字段</dt>
                    <dd className="monitoring-rule-template-fields">
                      {candidate.mappingFields.map((field) => (
                        <span key={`${field.role}-${field.domain}-${field.field}`}>
                          {field.domain}.{field.field}
                          {field.role && <small>{field.role}</small>}
                        </span>
                      ))}
                    </dd>
                  </div>
                )}
              </dl>
              {candidate.sourceText && (
                <blockquote>
                  <strong>方案原文</strong>
                  <p>{candidate.sourceText}</p>
                  {candidate.sourceLocator && <small>{candidate.sourceLocator}</small>}
                </blockquote>
              )}
              {proposed && (
                <div className="monitoring-rule-template-actions-wrap">
                  {lowConfidence && (
                    <label className="monitoring-rule-template-confirmation">
                      <span>低置信度确认说明（必填）</span>
                      <textarea
                        value={confirmationReason}
                        disabled={Boolean(decision?.busy)}
                        maxLength={2000}
                        rows={2}
                        placeholder="写明已核对的来源、数据缺口或医学确认依据"
                        onChange={(event) => setConfirmationReasons((current) => ({
                          ...current,
                          [candidate.candidateId]: event.target.value,
                        }))}
                      />
                    </label>
                  )}
                  <div className="monitoring-rule-template-actions">
                  <button
                    className="monitoring-rule-template-adopt"
                    type="button"
                    disabled={Boolean(decision?.busy) || (lowConfidence && !confirmationReason.trim())}
                    onClick={() => onDecision(candidate, "accepted", confirmationReason.trim())}
                  >
                    {decision?.busy
                      ? <LoaderCircle size={14} />
                      : <Check size={14} />}
                    采用
                  </button>
                  <button
                    type="button"
                    disabled={Boolean(decision?.busy)}
                    onClick={() => onDecision(candidate, "rejected")}
                  >
                    <XCircle size={14} />
                    不采用
                  </button>
                  </div>
                </div>
              )}
              {decision?.error && (
                <p className="monitoring-rule-template-inline-error">
                  {decision.error}
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function CandidateDetail({
  candidate,
  topic,
  decisionState,
  onDecision,
  ruleTemplateState,
  onStartRuleTemplate,
  onRuleTemplateDecision,
  onOpenRuleRelease,
  aiAvailable,
}) {
  const sections = candidateStructuredSections(candidate);
  const referencedEvidence = candidateReferencedEvidence(candidate);
  const factTypeOptions = protocolFactTypeOptions(topic);
  const [factType, setFactType] = useState(
    factTypeOptions.length === 1 ? factTypeOptions[0].value : "",
  );
  const [rejecting, setRejecting] = useState(false);
  const [rejectionReason, setRejectionReason] = useState(
    DEFAULT_REJECTION_REASON,
  );
  const [confirmationReason, setConfirmationReason] = useState("");
  const pending = candidate.status === "proposed";
  const deciding = Boolean(decisionState?.busy);
  const requiresFactType = factTypeOptions.length > 1;
  const confidenceSummary = candidateConfidenceSummary(candidate);
  const lowConfidence = confidenceSummary.requires_additional_evidence;
  const candidateIdentityReady = protocolPreparationCandidateIdentityReady(candidate);
  const acceptDisabled = deciding
    || !candidateIdentityReady
    || (requiresFactType && !factType)
    || (lowConfidence && !confirmationReason.trim());
  const acceptedFact = acceptedProtocolCandidateFact(candidate);

  return (
    <section className="monitoring-protocol-candidate">
      <header>
        <div>
          <strong>{candidate.title || "结构化条款候选"}</strong>
          <span className={candidate.status || "proposed"}>
            {protocolCandidateDecisionLabel(candidate)}
          </span>
        </div>
      </header>

      <div className={`monitoring-protocol-confidence${lowConfidence ? " low" : ""}`}>
        <strong>{confidenceSummary.label}</strong>
        {confidenceSummary.confidence_floor !== null && (
          <span>
            最低 {Math.round(confidenceSummary.confidence_floor * 100)}%
            （阈值 {Math.round(confidenceSummary.threshold * 100)}%）
          </span>
        )}
        {lowConfidence && (
          <p>接受前请补充原文核对、数据缺口或医学确认理由；系统不会自动采用。</p>
        )}
      </div>

      {candidate.text && (
        <div className="monitoring-protocol-candidate-text">
          <span>条款正文</span>
          <p>{candidate.text}</p>
        </div>
      )}

      {sections.length > 0 && (
        <dl className="monitoring-protocol-structured-fields">
          {sections.map((section) => (
            <div key={section.key}>
              <dt>{section.label}</dt>
              <dd>
                {section.values.map((value) => <p key={value}>{value}</p>)}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {referencedEvidence.length > 0 && (
        <div className="monitoring-protocol-evidence">
          <strong>方案原文</strong>
          {referencedEvidence.map((evidence, index) => (
            <blockquote key={protocolPreparationEvidenceDisplayKey(evidence, index)}>
              <p>{evidence.quote || "未返回可展示的方案原文。"}</p>
              {evidence.locator && <small>{evidence.locator}</small>}
            </blockquote>
          ))}
        </div>
      )}

      {pending && (
        <div className="monitoring-protocol-candidate-decision">
          {!candidateIdentityReady && (
            <p className="monitoring-protocol-candidate-error">
              候选身份缺失或重复，暂不能提交接受/驳回；请回到方案准备状态核对原始候选。
            </p>
          )}
          {requiresFactType && (
            <label>
              <span>归入</span>
              <select
                value={factType}
                disabled={deciding}
                onChange={(event) => setFactType(event.target.value)}
              >
                <option value="">选择条款类型</option>
                {factTypeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          {lowConfidence && (
            <label className="monitoring-protocol-confidence-confirmation">
              <span>低置信度确认说明（必填）</span>
              <textarea
                value={confirmationReason}
                disabled={deciding}
                maxLength={2000}
                rows={2}
                placeholder="写明已核对的方案原文、数据缺口或医学确认依据"
                onChange={(event) => setConfirmationReason(event.target.value)}
              />
            </label>
          )}

          {!rejecting ? (
            <div className="monitoring-protocol-candidate-actions">
              <button
                className="monitoring-protocol-candidate-accept"
                type="button"
                disabled={acceptDisabled}
                onClick={() => onDecision({
                  decision: "accepted",
                  factType,
                  reason: lowConfidence ? confirmationReason.trim() : "",
                })}
              >
                {deciding ? <LoaderCircle size={14} /> : <Check size={14} />}
                接受
              </button>
              <button
                className="monitoring-protocol-candidate-reject"
                type="button"
                disabled={deciding || !candidateIdentityReady}
                onClick={() => setRejecting(true)}
              >
                <XCircle size={14} />
                驳回
              </button>
            </div>
          ) : (
            <div className="monitoring-protocol-rejection">
              <label>
                <span>驳回理由</span>
                <input
                  value={rejectionReason}
                  disabled={deciding}
                  maxLength={2000}
                  onChange={(event) => setRejectionReason(event.target.value)}
                />
              </label>
              <div>
                <button
                  type="button"
                  disabled={deciding || !candidateIdentityReady}
                  onClick={() => setRejecting(false)}
                >
                  取消
                </button>
                <button
                  className="monitoring-protocol-candidate-reject"
                  type="button"
                  disabled={deciding || !candidateIdentityReady}
                  onClick={() => onDecision({
                    decision: "rejected",
                    reason: rejectionReason || DEFAULT_REJECTION_REASON,
                  })}
                >
                  {deciding
                    ? <LoaderCircle size={14} />
                    : <XCircle size={14} />}
                  确认驳回
                </button>
              </div>
            </div>
          )}

          {decisionState?.error && (
            <p className="monitoring-protocol-candidate-error">
              {decisionState.error}
            </p>
          )}
        </div>
      )}

      {acceptedFact && (
        <RuleTemplateRecommendation
          state={ruleTemplateState}
          onStart={() => onStartRuleTemplate(acceptedFact)}
          onDecision={(ruleCandidate, decision, reason) => (
          onRuleTemplateDecision(acceptedFact, ruleCandidate, decision, reason)
          )}
          onOpenRuleRelease={onOpenRuleRelease}
          aiAvailable={aiAvailable}
        />
      )}
    </section>
  );
}

export default function MedicalMonitoringProtocolPreparationPanel(props) {
  return (
    <MedicalMonitoringProtocolPreparationPanelForProject
      key={props.projectId}
      {...props}
    />
  );
}

function MedicalMonitoringProtocolPreparationPanelForProject({
  projectId,
  aiStatus = {},
  onClose,
  onOpenRuleRelease,
}) {
  const api = useMemo(() => createMedicalMonitoringApi(), []);
  const requestScope = useMemo(
    () => createMedicalMonitoringProjectRequestScope(projectId),
    [projectId],
  );
  const [versions, setVersions] = useState([]);
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [status, setStatus] = useState(null);
  const [loadingVersions, setLoadingVersions] = useState(true);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [starting, setStarting] = useState(false);
  const [pollStopped, setPollStopped] = useState(false);
  const [error, setError] = useState("");
  const [candidateDecisions, setCandidateDecisions] = useState({});
  const [ruleTemplateStates, setRuleTemplateStates] = useState({});
  const independentAiReady = aiStatus?.semantic_ai_tasks_enabled === true;

  useEffect(() => {
    requestScope.activate();
    return () => requestScope.dispose();
  }, [requestScope]);

  useEffect(() => {
    const request = requestScope.begin("protocol-versions");
    setVersions([]);
    setSelectedVersionId("");
    setStatus(null);
    setCandidateDecisions({});
    setRuleTemplateStates({});
    setLoadingVersions(true);
    setError("");
    api.listProtocolVersions(projectId, { signal: request.signal })
      .then((payload) => {
        if (!requestScope.isCurrent(request)) return;
        const confirmed = confirmedProtocolVersions(payload);
        setVersions(confirmed);
        setSelectedVersionId((current) => confirmed.some(
          (version) => version.protocol_version_id === current && version.displayIdentityState === "ready",
        ) ? current : confirmed.find((version) => version.displayIdentityState === "ready")?.protocol_version_id || "");
      })
      .catch((nextError) => {
        if (requestScope.isCurrent(request)) {
          setVersions([]);
          setSelectedVersionId("");
          setStatus(null);
          setCandidateDecisions({});
          setRuleTemplateStates({});
          setError(errorText(nextError, "已确认方案版本读取失败"));
        }
      })
      .finally(() => {
        if (requestScope.isCurrent(request)) setLoadingVersions(false);
        requestScope.finish(request);
      });
    return () => requestScope.cancel("protocol-versions");
  }, [api, projectId, requestScope]);

  const readStatus = useCallback(async ({ resumePolling = false } = {}) => {
    if (!selectedVersionId) return null;
    const request = requestScope.begin("protocol-status");
    setLoadingStatus(true);
    setError("");
    if (resumePolling) setPollStopped(false);
    try {
      const payload = await api.getProtocolPreparationStatus(
        projectId,
        selectedVersionId,
        { signal: request.signal },
      );
      if (!requestScope.isCurrent(request)) return null;
      const normalized = normalizeStatusOrThrow(payload);
      setStatus(normalized);
      return normalized;
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return null;
      setStatus(null);
      setCandidateDecisions({});
      setRuleTemplateStates({});
      setPollStopped(true);
      setError(errorText(nextError, "方案规则准备状态读取失败"));
      return null;
    } finally {
      if (requestScope.isCurrent(request)) setLoadingStatus(false);
      requestScope.finish(request);
    }
  }, [api, projectId, requestScope, selectedVersionId]);

  useEffect(() => {
    if (!selectedVersionId) {
      requestScope.cancel("protocol-status");
      setStatus(null);
      setLoadingStatus(false);
      return undefined;
    }
    setStatus(null);
    setCandidateDecisions({});
    setRuleTemplateStates({});
    setPollStopped(false);
    readStatus().catch(() => {});
    return () => requestScope.cancel("protocol-status");
  }, [readStatus, requestScope, selectedVersionId]);

  useEffect(() => {
    if (
      !selectedVersionId
      || !status
      || pollStopped
      || !shouldPollProtocolPreparation(status)
    ) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      readStatus().catch(() => {});
    }, POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [pollStopped, readStatus, selectedVersionId, status]);

  const progress = protocolPreparationProgress(status);
  const acceptedFactItems = useMemo(
    () => acceptedProtocolFacts(status),
    [status],
  );
  const acceptedFactKey = acceptedFactItems
    .map(({ fact }) => `${fact.fact_revision_id}:v${fact.state_version}`)
    .join("|");
  const hasReadyTopic = (status?.topics || [])
    .some((topic) => topic.status === "ready");
  const startAction = protocolPreparationStartAction(status);
  const canStart = Boolean(
    selectedVersionId
    && status
    && (hasReadyTopic || startAction.available)
    && independentAiReady
    && !starting,
  );

  const startAllTopics = async () => {
    if (!canStart) return;
    const request = requestScope.begin("protocol-start");
    setStarting(true);
    setError("");
    try {
      const payload = await api.startProtocolPreparation(
        projectId,
        selectedVersionId,
        { signal: request.signal },
      );
      if (!requestScope.isCurrent(request)) return;
      setStatus(normalizeStatusOrThrow(payload));
      setPollStopped(false);
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      setError(errorText(nextError, "方案规则准备未能启动"));
    } finally {
      if (requestScope.isCurrent(request)) setStarting(false);
      requestScope.finish(request);
    }
  };

  const updateRuleTemplateState = useCallback((factRevisionId, updater) => {
    setRuleTemplateStates((current) => {
      const previous = current[factRevisionId] || {};
      const next = typeof updater === "function"
        ? updater(previous)
        : { ...previous, ...updater };
      return {
        ...current,
        [factRevisionId]: next,
      };
    });
  }, []);

  const readRuleTemplateStatus = useCallback(async (
    fact,
    { showLoading = false } = {},
  ) => {
    const factRevisionId = fact.fact_revision_id;
    const request = requestScope.begin(
      `rule-template:${factRevisionId}`,
    );
    updateRuleTemplateState(factRevisionId, (current) => ({
      ...current,
      loading: showLoading,
      error: "",
    }));
    try {
      const payload = normalizeRuleTemplateRecommendationPayload(
        await api.getRuleTemplateRecommendationStatus(
        projectId,
        factRevisionId,
        {
          expectedFactStateVersion: fact.state_version,
          signal: request.signal,
        },
        ),
        projectId,
        factRevisionId,
      );
      if (!requestScope.isCurrent(request)) return null;
      updateRuleTemplateState(factRevisionId, (current) => ({
        ...current,
        payload,
        loading: false,
        error: "",
      }));
      return payload;
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return null;
      updateRuleTemplateState(factRevisionId, (current) => ({
        ...current,
        payload: null,
        loading: false,
        error: errorText(nextError, "规则建议状态读取失败"),
      }));
      return null;
    } finally {
      requestScope.finish(request);
    }
  }, [api, projectId, requestScope, updateRuleTemplateState]);

  const startRuleTemplateRecommendation = useCallback(async (fact) => {
    const factRevisionId = fact.fact_revision_id;
    const request = requestScope.begin(
      `rule-template:${factRevisionId}`,
    );
    updateRuleTemplateState(factRevisionId, (current) => ({
      ...current,
      busy: true,
      loading: false,
      error: "",
    }));
    try {
      const payload = normalizeRuleTemplateRecommendationPayload(
        await api.startRuleTemplateRecommendation(
        projectId,
        factRevisionId,
        buildRuleTemplateRecommendationStartPayload(fact),
        { signal: request.signal },
        ),
        projectId,
        factRevisionId,
      );
      if (!requestScope.isCurrent(request)) return null;
      updateRuleTemplateState(factRevisionId, (current) => ({
        ...current,
        payload,
        busy: false,
        error: "",
      }));
      return payload;
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return null;
      updateRuleTemplateState(factRevisionId, (current) => ({
        ...current,
        payload: null,
        busy: false,
        error: errorText(nextError, "规则建议未能启动"),
      }));
      return null;
    } finally {
      requestScope.finish(request);
    }
  }, [api, projectId, requestScope, updateRuleTemplateState]);

  useEffect(() => {
    acceptedFactItems.forEach(({ fact }) => {
      if (ruleTemplateStates[fact.fact_revision_id]) return;
      readRuleTemplateStatus(fact, { showLoading: true });
    });
    // acceptedFactKey is the stable restore boundary; state updates must not
    // repeatedly re-read facts that are already present in this drawer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [acceptedFactKey, readRuleTemplateStatus]);

  useEffect(() => {
    const pollingFacts = acceptedFactItems
      .map(({ fact }) => fact)
      .filter((fact) => shouldPollRuleTemplateRecommendation(
        ruleTemplateStates[fact.fact_revision_id]?.payload,
      ));
    if (pollingFacts.length === 0) return undefined;
    const timer = window.setTimeout(() => {
      pollingFacts.forEach((fact) => {
        readRuleTemplateStatus(fact).catch(() => {});
      });
    }, POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [
    acceptedFactItems,
    readRuleTemplateStatus,
    ruleTemplateStates,
  ]);

  const decideRuleTemplateRecommendation = async (
    fact,
    candidate,
    decision,
    confirmationReason = "",
  ) => {
    const factRevisionId = fact.fact_revision_id;
    const currentState = ruleTemplateStates[factRevisionId] || {};
    if (currentState.candidateDecisions?.[candidate.candidateId]?.busy) return;
    const request = requestScope.begin(
      `rule-template-decision:${factRevisionId}:${candidate.candidateId}`,
    );
    updateRuleTemplateState(factRevisionId, (current) => ({
      ...current,
      candidateDecisions: {
        ...(current.candidateDecisions || {}),
        [candidate.candidateId]: { busy: true, error: "" },
      },
    }));
    try {
      const { candidateId, payload } =
        buildRuleTemplateRecommendationDecisionPayload({
          decision,
          statusPayload: currentState.payload,
          candidate: {
            candidate_id: candidate.candidateId,
            status: candidate.status,
          },
          fact,
          reason: decision === "rejected"
            ? "当前建议不适用于本项目的医学监查。"
            : confirmationReason,
        });
      const response = normalizeRuleTemplateDecisionResponse(
        await api.decideRuleTemplateRecommendation(
          projectId,
          factRevisionId,
          candidateId,
          payload,
          { signal: request.signal },
        ),
        projectId,
        candidateId,
      );
      if (!requestScope.isCurrent(request)) return;
      updateRuleTemplateState(factRevisionId, (current) => ({
        ...current,
        payload: applyRuleTemplateRecommendationDecision(
          current.payload,
          candidateId,
          response,
        ),
        candidateDecisions: {
          ...(current.candidateDecisions || {}),
          [candidateId]: { busy: false, error: "" },
        },
      }));
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      updateRuleTemplateState(factRevisionId, (current) => ({
        ...current,
        payload: nextError instanceof MedicalMonitoringRuleTemplateShapeError
          ? null
          : current.payload,
        candidateDecisions: {
          ...(current.candidateDecisions || {}),
          [candidate.candidateId]: {
            busy: false,
            error: errorText(nextError, "规则建议决定未能保存"),
          },
        },
      }));
    } finally {
      requestScope.finish(request);
    }
  };

  const decideCandidate = async (
    topic,
    candidate,
    { decision, factType = "", reason = "" },
  ) => {
    if (
      !selectedVersionId
      || candidate?.status !== "proposed"
      || !protocolPreparationCandidateIdentityReady(candidate)
      || candidateDecisions[candidate.candidate_id]?.busy
    ) {
      return;
    }
    const candidateId = candidate.candidate_id;
    const request = requestScope.begin(
      `protocol-candidate-decision:${candidateId}`,
    );
    setCandidateDecisions((current) => ({
      ...current,
      [candidateId]: { busy: true, error: "" },
    }));
    try {
      let jobPayload = null;
      if (!resolveProtocolCandidateInputRevision(topic, candidate, null)) {
        if (!topic.job?.job_id) {
          throw new Error("候选运行信息不可用，请刷新后重试。");
        }
        jobPayload = await api.getMonitoringAiJob(
          projectId,
          topic.job.job_id,
          { signal: request.signal },
        );
        if (!requestScope.isCurrent(request)) return;
        const currentCandidate = (jobPayload?.candidates || [])
          .find((item) => item?.candidate_id === candidateId);
        if (currentCandidate && currentCandidate.status !== "proposed") {
          throw new Error("候选状态已变化，请刷新后查看当前决定。");
        }
      }
      const payload = buildProtocolCandidateDecisionPayload({
        decision,
        topic,
        candidate,
        jobPayload,
        factType,
        reason,
      });
      const response = await api.decideProtocolPreparationCandidate(
        projectId,
        selectedVersionId,
        candidateId,
        payload,
        { signal: request.signal },
      );
      if (!requestScope.isCurrent(request)) return;
      setStatus((current) => applyProtocolCandidateDecision(
        current,
        candidateId,
        response,
      ));
      setCandidateDecisions((current) => ({
        ...current,
        [candidateId]: { busy: false, error: "" },
      }));
      const newlyAcceptedFact = newlyAcceptedProtocolDecisionFact(response);
      if (newlyAcceptedFact) {
        await startRuleTemplateRecommendation(newlyAcceptedFact);
      }
      await readStatus();
    } catch (nextError) {
      if (!requestScope.isCurrent(request)) return;
      setCandidateDecisions((current) => ({
        ...current,
        [candidateId]: {
          busy: false,
          error: errorText(nextError, "候选决定未能保存"),
        },
      }));
    } finally {
      requestScope.finish(request);
    }
  };

  return (
    <div className="monitoring-protocol-prep-host">
      <button
        className="monitoring-protocol-prep-backdrop"
        type="button"
        aria-label="关闭方案监查准备"
        onClick={onClose}
      />
      <aside
        className="monitoring-protocol-prep-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="方案监查准备"
      >
        <header className="monitoring-protocol-prep-head">
          <div>
            <span>项目资料</span>
            <strong>准备方案规则</strong>
            <small>从已确认方案提取监查候选；关闭后任务仍在后台继续。</small>
          </div>
          <button
            className="icon-button"
            type="button"
            title="关闭"
            onClick={onClose}
          >
            <X size={17} />
          </button>
        </header>

        <div className="monitoring-protocol-prep-body">
          <section className="monitoring-protocol-version-row">
            <label htmlFor="monitoring-protocol-version">方案版本</label>
            {loadingVersions ? (
              <span className="monitoring-protocol-loading">
                <LoaderCircle size={15} />
                正在读取
              </span>
            ) : versions.length === 0 ? (
              <p>当前项目尚无已确认且可解析的方案版本。</p>
            ) : versions.length === 1 && versions[0].displayIdentityState === "ready" ? (
              <strong>{versionOptionLabel(versions[0])}</strong>
            ) : versions.length === 1 ? (
              <span className="monitoring-protocol-version-warning" title={versions[0].displayIdentityIssue}>
                {versionOptionLabel(versions[0])} · 身份待核对
              </span>
            ) : (
              <select
                id="monitoring-protocol-version"
                value={selectedVersionId}
                onChange={(event) => {
                  setSelectedVersionId(event.target.value);
                  setError("");
                }}
              >
                <option value="">选择本次监查适用的方案版本</option>
                {versions.map((version, index) => {
                  const ambiguous = version.displayIdentityState !== "ready";
                  return (
                    <option
                      key={version.displayKey || protocolPreparationVersionDisplayKey(version, index)}
                      value={version.protocol_version_id || ""}
                      disabled={ambiguous}
                    >
                      {versionOptionLabel(version)}{ambiguous ? " · 身份待核对" : ""}
                    </option>
                  );
                })}
              </select>
            )}
          </section>

          {selectedVersionId && (
            <section className="monitoring-protocol-prep-summary">
              <div>
                <span>准备进度</span>
                <strong>
                  {progress.submitted
                    ? `${progress.completed}/${progress.total} 个主题已完成`
                    : "方案原文已就绪，可一键准备"}
                </strong>
              </div>
              <div className="monitoring-protocol-prep-actions">
                <button
                  className="icon-button"
                  type="button"
                  title="刷新状态"
                  disabled={loadingStatus}
                  onClick={() => readStatus({ resumePolling: true })}
                >
                  <RefreshCw size={15} />
                </button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={!canStart}
                  onClick={startAllTopics}
                >
                  {starting ? (
                    <LoaderCircle size={15} />
                  ) : (
                    <Sparkles size={15} />
                  )}
                  {starting ? "正在提交" : startAction.label}
                </button>
              </div>
              <div
                className="monitoring-protocol-progress"
                role="progressbar"
                aria-valuemin="0"
                aria-valuemax={progress.total || 8}
                aria-valuenow={progress.completed}
              >
                <i style={{ width: `${progress.percent}%` }} />
              </div>
              {progress.candidateCount > 0 && (
                <small>{progress.candidateCount} 条候选等待用户确认</small>
              )}
            </section>
          )}

          {loadingStatus && !status && (
            <p className="monitoring-protocol-loading">
              <LoaderCircle size={15} />
              正在核对方案原文和准备状态
            </p>
          )}

          {error && (
            <div className="monitoring-protocol-prep-error">
              <CircleAlert size={16} />
              <span>{error}</span>
              {selectedVersionId && (
                <button
                  type="button"
                  onClick={() => readStatus({ resumePolling: true })}
                >
                  重新读取
                </button>
              )}
            </div>
          )}

              {status?.topics?.length > 0 && (
                <section className="monitoring-protocol-topic-list" aria-label="方案监查主题">
              {status.topics.map((topic, topicIndex) => (
                <details key={protocolPreparationTopicDisplayKey(topic, topicIndex)}>
                  <summary>
                    <TopicStateIcon status={topic.status} />
                    <strong>{topic.label}</strong>
                    {topic.candidates?.length > 0 && (
                      <span>{topic.candidates.length} 条候选</span>
                    )}
                    <em className={protocolPreparationTopicTone(topic.status)}>
                      {PROTOCOL_PREPARATION_STATUS_LABELS[topic.status]
                        || topic.status}
                    </em>
                  </summary>
                  <div className="monitoring-protocol-topic-detail">
                    {topic.data_gap && <p>{topic.data_gap}</p>}
                    {topic.status === "ready" && (
                      <p>
                        {independentAiReady
                          ? "已找到相关方案原文，启动后将生成结构化监查候选。"
                          : "已找到相关方案原文；独立AI当前不可运行，配置后再生成语义候选。"}
                      </p>
                    )}
                    {["queued", "running"].includes(topic.status) && (
                      <p>
                        {independentAiReady
                          ? "独立AI正在分析相关方案原文，无需停留在当前页面。"
                          : "独立AI当前不可运行；队列/运行状态不等于已生成语义候选，请配置后再确认。"}
                      </p>
                    )}
                    {(topic.candidates || []).map((candidate, candidateIndex) => (
                      <CandidateDetail
                        key={protocolPreparationCandidateDisplayKey(candidate, candidateIndex)}
                        candidate={candidate}
                        topic={topic}
                        decisionState={
                          candidateDecisions[candidate.candidate_id]
                        }
                        onDecision={(nextDecision) => decideCandidate(
                          topic,
                          candidate,
                          nextDecision,
                        )}
                        ruleTemplateState={
                          acceptedProtocolCandidateFact(candidate)
                            ? ruleTemplateStates[
                              candidate.fact.fact_revision_id
                            ]
                            : null
                        }
                        onStartRuleTemplate={startRuleTemplateRecommendation}
                        onRuleTemplateDecision={
                          decideRuleTemplateRecommendation
                        }
                        onOpenRuleRelease={onOpenRuleRelease}
                        aiAvailable={independentAiReady}
                      />
                    ))}
                    {["failed", "blocked", "stale_input", "cancelled"].includes(topic.status)
                      && (
                        <p>
                          {topic.job?.failure_message
                            || "该主题需要重新核对方案来源或运行状态。"}
                        </p>
                      )}
                  </div>
                </details>
              ))}
            </section>
          )}

          {!selectedVersionId && versions.length > 1 && (
            <div className="monitoring-protocol-prep-empty">
              <FileSearch size={22} />
              <p>请选择本次医学监查适用的已确认方案版本。</p>
            </div>
          )}
        </div>

        <footer className="monitoring-protocol-prep-foot">
          <span>
            采用规则建议即为医学决定；后续在「规则发布」抽屉完成影子样本核对、确认与发布。
          </span>
        </footer>
      </aside>
    </div>
  );
}
