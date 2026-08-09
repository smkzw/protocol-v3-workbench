import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  Circle,
  CircleAlert,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";

import { createMedicalMonitoringApi } from "./medicalMonitoringApi.mjs";
import {
  canStartMonitoringDailyRun,
  monitoringDailyRunRemediation,
} from "./medicalMonitoringDailyRunStartGate.mjs";
import { normalizeBatchList } from "./medicalMonitoringBatchView.mjs";
import {
  acceptedProtocolFacts,
  confirmedProtocolVersions,
} from "./medicalMonitoringProtocolPreparation.mjs";
import {
  createMedicalMonitoringProjectRequestScope,
} from "./medicalMonitoringProjectRequestScope.mjs";
import {
  PROVISIONAL_INSPECTION_NOTE,
  SHADOW_CONFIRMATION_NOTE,
  buildAutomaticShadowRunPayload,
  buildRulePackDraftPayload,
  buildRulePackPublishPayload,
  buildShadowConfirmationPayload,
  confirmedShadowRunView,
  frozenShadowBatches,
  latestPublishedRulePack,
  normalizedRulePack,
  provisionalInspectionViewModel,
  rulePackDiffView,
  rulePackDisplayKey,
  rulePackRules,
  ruleReleaseChainSteps,
  ruleReleaseErrorText,
  ruleReleaseNextAction,
  shadowBatchOptionLabel,
  shadowLineageEvidenceViewModel,
  sortedRulePacks,
} from "./medicalMonitoringRuleRelease.mjs";
import {
  normalizeAutomaticShadowResult,
  normalizeRulePackDetail,
  normalizeRulePackDiff,
  normalizeRulePackDraftResult,
  normalizeRulePackList,
  normalizeRulePackMutationResult,
  normalizeRuleReleaseReadiness,
  normalizeShadowConfirmationResult,
  normalizeShadowLineageEvidence,
  normalizeShadowRunList,
  normalizeShadowSampleSetList,
  ruleReleaseSampleDisplayKey,
} from "./medicalMonitoringRuleReleaseView.mjs";
import "./MedicalMonitoringRuleReleasePanel.css";

function confirmedAtLabel(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? text : date.toLocaleString("zh-CN");
}

function StepIcon({ state }) {
  if (state === "done") return <CheckCircle2 size={15} />;
  return <Circle size={15} />;
}

function ReleaseSamples({ samples }) {
  return (
    <table className="monitoring-rule-release-samples">
      <thead>
        <tr>
          <th>规则</th>
          <th>样本</th>
          <th>实际判定</th>
          <th>来源依据</th>
        </tr>
      </thead>
      <tbody>
        {samples.map((sample, index) => (
          <tr key={ruleReleaseSampleDisplayKey(sample, index)}>
            <td>
              <strong>{sample.ruleKey}</strong>
              <span>{sample.bucketLabel}{sample.displayIdentityState !== "ready" ? " · 身份待核对" : ""}</span>
            </td>
            <td>
              <strong>{sample.caseLabel || sample.businessKey}</strong>
              {sample.caseLabel && sample.businessKey && (
                <span>{sample.businessKey}</span>
              )}
            </td>
            <td>
              <span className={`monitoring-rule-release-outcome ${sample.outcomeTone}`}>
                {sample.outcomeLabel}
              </span>
            </td>
            <td>
              <p>{sample.evidenceSummary || "未返回可展示的来源依据。"}</p>
              {sample.diagnosticCode && <small>{sample.diagnosticCode}</small>}
              {sample.displayIdentityIssue && <small title={sample.displayIdentityIssue}>样本身份待核对</small>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function MedicalMonitoringRuleReleasePanel(props) {
  return (
    <MedicalMonitoringRuleReleasePanelForProject
      key={props.projectId}
      {...props}
    />
  );
}

function MedicalMonitoringRuleReleasePanelForProject({
  projectId,
  onClose,
  onOpenProtocolPreparation,
  onOpenMapping,
  onPublished,
}) {
  const api = useMemo(() => createMedicalMonitoringApi(), []);
  const requestScope = useMemo(
    () => createMedicalMonitoringProjectRequestScope(projectId),
    [projectId],
  );
  const [versions, setVersions] = useState([]);
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [facts, setFacts] = useState([]);
  const [packs, setPacks] = useState([]);
  const [selectedPackId, setSelectedPackId] = useState("");
  const [packDetail, setPackDetail] = useState(null);
  const [inspection, setInspection] = useState(null);
  const [shadowRun, setShadowRun] = useState(null);
  const [confirmation, setConfirmation] = useState(null);
  const [diff, setDiff] = useState(null);
  const [batches, setBatches] = useState([]);
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [readiness, setReadiness] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState("");
  const [auxiliaryReadError, setAuxiliaryReadError] = useState("");
  const [message, setMessage] = useState("");
  // Stage transitions mint a successor pack id while sample sets stay bound to
  // the shadow-stage pack id; this ref only covers same-session immediacy,
  // while fresh loads restore the snapshot from the lineage evidence endpoint.
  const confirmedSamplesRef = useRef(null);
  const selectedPackIdRef = useRef("");

  const clearLoadedState = useCallback(() => {
    setVersions([]);
    setSelectedVersionId("");
    setFacts([]);
    setPacks([]);
    setSelectedPackId("");
    setPackDetail(null);
    setInspection(null);
    setShadowRun(null);
    setConfirmation(null);
    setDiff(null);
    setBatches([]);
    setSelectedBatchId("");
    setReadiness(null);
    setAuxiliaryReadError("");
    setMessage("");
    confirmedSamplesRef.current = null;
    selectedPackIdRef.current = "";
  }, []);

  useEffect(() => {
    requestScope.activate();
    return () => requestScope.dispose();
  }, [requestScope]);

  const load = useCallback(async ({ focusPackId = "", quiet = false } = {}) => {
    const request = requestScope.begin("rule-release-state");
    if (!quiet) setLoading(true);
    setError("");
    setAuxiliaryReadError("");
    try {
      const versionPayload = await api.listProtocolVersions(
        projectId,
        { signal: request.signal },
      );
      if (!requestScope.isCurrent(request)) return;
      const confirmed = confirmedProtocolVersions(versionPayload);
      setVersions(confirmed);
      const versionId = confirmed.some(
        (version) => version.protocol_version_id === selectedVersionId,
      )
        ? selectedVersionId
        : confirmed[0]?.protocol_version_id || "";
      setSelectedVersionId(versionId);

      let nextFacts = [];
      if (versionId) {
        const status = await api.getProtocolPreparationStatus(
          projectId,
          versionId,
          { signal: request.signal },
        );
        if (!requestScope.isCurrent(request)) return;
        nextFacts = acceptedProtocolFacts(status).map(({ fact }) => fact);
      }
      setFacts(nextFacts);

      const packPayload = normalizeRulePackList(await api.listRulePacks(
        projectId,
        { signal: request.signal },
      ), projectId);
      if (!requestScope.isCurrent(request)) return;
      const nextPacks = sortedRulePacks(packPayload.items);
      setPacks(nextPacks);
      const preferredPackId = focusPackId || selectedPackIdRef.current;
      const selectablePacks = nextPacks.filter((pack) => pack.displayIdentityState === "ready");
      const packId = selectablePacks.some((pack) => pack.rulePackId === preferredPackId)
        ? preferredPackId
        : selectablePacks[0]?.rulePackId || "";
      selectedPackIdRef.current = packId;
      setSelectedPackId(packId);

      let nextInspection = null;
      let nextShadowRun = null;
      let nextConfirmation = null;
      let nextDiff = null;
      let nextDetail = null;
      if (packId) {
        nextDetail = normalizeRulePackDetail(await api.getRulePack(
          projectId,
          packId,
          { signal: request.signal },
        ), projectId);
        if (!requestScope.isCurrent(request)) return;
        setPackDetail(nextDetail);
        const sampleSets = normalizeShadowSampleSetList(await api.listShadowSampleSets(
          projectId,
          packId,
          { signal: request.signal },
        ), projectId);
        if (!requestScope.isCurrent(request)) return;
        const sampleSetItems = sampleSets.items;
        nextInspection = provisionalInspectionViewModel(
          sampleSetItems[sampleSetItems.length - 1] || null,
        );
        const runs = normalizeShadowRunList(await api.listShadowRuns(
          projectId,
          packId,
          { signal: request.signal },
        ), projectId, packId);
        if (!requestScope.isCurrent(request)) return;
        const runItems = runs.items;
        nextShadowRun = confirmedShadowRunView(runItems[runItems.length - 1] || null);
        const published = latestPublishedRulePack(packPayload.items);
        if (published && published.rulePackId !== packId) {
          try {
            const diffPayload = normalizeRulePackDiff(await api.getRulePackDiff(
              projectId,
              published.rulePackId,
              packId,
              { signal: request.signal },
            ), projectId);
            if (!requestScope.isCurrent(request)) return;
            nextDiff = rulePackDiffView(diffPayload.impact);
          } catch (nextError) {
            if (requestScope.isCurrent(request)) {
              setAuxiliaryReadError(ruleReleaseErrorText(nextError, "规则包差异读取失败，当前不显示差异。"));
            }
            nextDiff = null;
          }
        }
      } else {
        setPackDetail(null);
      }
      const nextPackStatus = normalizedRulePack(nextDetail?.pack)?.status || "";
      if (nextInspection) {
        confirmedSamplesRef.current = {
          packId,
          inspection: nextInspection,
          shadowRun: nextShadowRun,
        };
      } else if (["confirmed", "published"].includes(nextPackStatus)) {
        if (confirmedSamplesRef.current?.packId === packId) {
          // Same-session immediacy: the just-reviewed snapshot stays visible.
          nextInspection = confirmedSamplesRef.current.inspection;
          nextShadowRun = nextShadowRun || confirmedSamplesRef.current.shadowRun;
        } else {
          // Fresh load of a confirmed/published pack: restore the exact
          // reviewed sample set from the lineage evidence endpoint, never
          // from memory, and hide the sample section when the lineage has
          // no shadow-stage ancestor.
          try {
            const evidencePayload = normalizeShadowLineageEvidence(
              await api.getRulePackShadowLineageEvidence(
                projectId,
                packId,
                { signal: request.signal },
              ),
              projectId,
              packId,
            );
            if (!requestScope.isCurrent(request)) return;
            const evidence = shadowLineageEvidenceViewModel(evidencePayload);
            if (evidence?.shadowRulePackId && evidence.sampleSet) {
              nextInspection = evidence.sampleSet;
              nextConfirmation = evidence.confirmation;
              confirmedSamplesRef.current = {
                packId,
                inspection: nextInspection,
                shadowRun: null,
              };
              if (!nextShadowRun) {
                try {
                  const lineageRuns = normalizeShadowRunList(await api.listShadowRuns(
                    projectId,
                    evidence.shadowRulePackId,
                    { signal: request.signal },
                  ), projectId, evidence.shadowRulePackId);
                  if (!requestScope.isCurrent(request)) return;
                  const lineageRunItems = lineageRuns.items;
                  nextShadowRun = confirmedShadowRunView(
                    lineageRunItems[lineageRunItems.length - 1] || null,
                  );
                  confirmedSamplesRef.current.shadowRun = nextShadowRun;
                } catch (nextError) {
                  if (requestScope.isCurrent(request)) {
                    setAuxiliaryReadError(ruleReleaseErrorText(nextError, "已确认影子运行记录读取失败，当前不显示运行标签。"));
                  }
                }
              }
            }
          } catch (lineageError) {
            if (!requestScope.isCurrent(request)) return;
            setAuxiliaryReadError(ruleReleaseErrorText(
              lineageError,
              lineageError?.status === 404
                ? "规则包不存在或已被移除。"
                : "规则包影子谱系读取失败，当前不显示已确认样本。",
            ));
            // Other lineage failures fail closed: the sample section stays hidden.
          }
        }
      }
      setInspection(nextInspection);
      setShadowRun(nextShadowRun);
      setConfirmation(nextConfirmation);
      setDiff(nextDiff);

      const batchPayload = normalizeBatchList(await api.listBatches(
        projectId,
        { signal: request.signal },
      ), projectId);
      if (!requestScope.isCurrent(request)) return;
      const frozen = frozenShadowBatches(batchPayload.batches);
      setBatches(frozen);
      const selectableFrozen = frozen.filter((batch) => batch.displayIdentityState === "ready");
      const batchId = selectableFrozen.some((batch) => batch.batchId === selectedBatchId)
        ? selectedBatchId
        : selectableFrozen[0]?.batchId || "";
      setSelectedBatchId(batchId);
      if (batchId) {
        try {
          const nextReadiness = normalizeRuleReleaseReadiness(
            await api.getDailyRunReadiness(
              projectId,
              batchId,
              { signal: request.signal },
            ),
            projectId,
            batchId,
          );
          if (!requestScope.isCurrent(request)) return;
          setReadiness(nextReadiness);
        } catch (nextError) {
          if (requestScope.isCurrent(request)) {
            setReadiness(null);
            setAuxiliaryReadError(ruleReleaseErrorText(nextError, "日常监查就绪状态读取失败，当前批次不能判定为可启动。"));
          }
        }
      } else {
        setReadiness(null);
      }
    } catch (nextError) {
      if (requestScope.isCurrent(request)) {
        clearLoadedState();
        setError(ruleReleaseErrorText(nextError, "规则发布状态读取失败，请重试。"));
      }
    } finally {
      if (requestScope.isCurrent(request) && !quiet) setLoading(false);
      requestScope.finish(request);
    }
  }, [api, clearLoadedState, projectId, requestScope, selectedBatchId, selectedVersionId]);

  useEffect(() => {
    load().catch(() => {});
    return () => requestScope.cancel("rule-release-state");
  }, [load, requestScope]);

  const pack = packDetail?.pack ? normalizedRulePack(packDetail.pack) : null;
  const rules = rulePackRules(packDetail);
  // Low noise: intermediate lifecycle stages of the same lineage are not
  // separate user choices; only the latest stage and published history list.
  const pickerPacks = useMemo(() => {
    const visible = [];
    const seen = new Map();
    const candidates = [packs[0], ...packs.filter((item) => item.status === "published")].filter(Boolean);
    candidates.forEach((item) => {
      const previous = seen.get(item.rulePackId);
      if (!previous) {
        seen.set(item.rulePackId, item);
        visible.push(item);
      } else if (previous.displayIdentityState !== "ready" || item.displayIdentityState !== "ready") {
        visible.push(item);
      }
    });
    return visible.sort(
      (left, right) => (right.packRevision || 0) - (left.packRevision || 0),
    );
  }, [packs]);
  const steps = ruleReleaseChainSteps({ pack, inspection, readiness });
  const nextAction = ruleReleaseNextAction({ pack, inspection, readiness });
  const remediation = monitoringDailyRunRemediation(readiness);
  const ready = canStartMonitoringDailyRun(readiness);

  const runAction = async (key, operation) => {
    if (busyAction) return;
    const request = requestScope.begin(`rule-release-action:${key}`);
    setBusyAction(key);
    setError("");
    setMessage("");
    try {
      const focusPackId = await operation(request.signal);
      if (!requestScope.isCurrent(request)) return;
      await load({ focusPackId: focusPackId || "", quiet: true });
    } catch (nextError) {
      if (requestScope.isCurrent(request)) {
        setError(ruleReleaseErrorText(nextError));
      }
    } finally {
      if (requestScope.isCurrent(request)) setBusyAction("");
      requestScope.finish(request);
    }
  };

  const createDraft = () => runAction("draft", async (signal) => {
    const result = normalizeRulePackDraftResult(await api.createRulePackDraft(
      projectId,
      buildRulePackDraftPayload({
        protocolVersionId: selectedVersionId,
        factRevisionIds: facts.map((fact) => fact.fact_revision_id),
      }),
      { signal },
    ), projectId);
    setMessage(
      result.reused
        ? "已恢复内容一致的既有规则包草稿，未产生重复版本。"
        : "规则包草稿已组建，规则均为采用时已确认的医学决定。",
    );
    return result.pack.rule_pack_id;
  });

  const runAutomaticShadow = () => runAction("shadow", async (signal) => {
    let currentPackId = pack.rulePackId;
    let currentRevision = pack.packRevision;
    if (pack.status === "draft") {
      const started = normalizeRulePackMutationResult(await api.startRulePackShadow(
        projectId,
        currentPackId,
        {},
        { signal },
      ), projectId, "rule_pack_shadow_start");
      currentPackId = started.pack.rule_pack_id;
      currentRevision = started.pack.pack_revision;
    }
    const result = normalizeAutomaticShadowResult(await api.runAutomaticShadow(
      projectId,
      currentPackId,
      buildAutomaticShadowRunPayload({
        batchId: selectedBatchId,
        expectedPackRevision: currentRevision,
      }),
      { signal },
    ), projectId);
    const nextInspection = provisionalInspectionViewModel(result.inspection);
    if (nextInspection) setInspection(nextInspection);
    setMessage(
      result.reused
        ? "已恢复该批次的既有影子样本，内容未重复生成。"
        : `已从所选冻结批次抽取 ${nextInspection?.sampleCount || 0} 条真实样本，请逐条核对实际判定。`,
    );
    return result.pack.rule_pack_id;
  });

  const confirmShadow = () => runAction("confirm", async (signal) => {
    const result = normalizeShadowConfirmationResult(await api.confirmRulePackShadow(
      projectId,
      pack.rulePackId,
      buildShadowConfirmationPayload({
        sampleSetId: inspection.sampleSetId,
        expectedPackRevision: pack.packRevision,
      }),
      { signal },
    ), projectId);
    const successorPackId = result.pack.rule_pack_id;
    if (successorPackId && inspection) {
      confirmedSamplesRef.current = {
        packId: successorPackId,
        inspection,
        shadowRun: confirmedShadowRunView({
          shadow_run_id: result.shadow_run_id,
          case_count: inspection.sampleCount,
          passed_count: inspection.sampleCount,
          diagnostic_case_count: 0,
          diagnostic_passed_count: 0,
        }),
      };
    }
    setMessage("影子样本结果已确认。发布前规则包内容不会再变化。");
    return successorPackId;
  });

  const publish = () => runAction("publish", async (signal) => {
    const result = normalizeRulePackMutationResult(await api.publishRulePack(
      projectId,
      pack.rulePackId,
      buildRulePackPublishPayload({ expectedPackRevision: pack.packRevision }),
      { signal },
    ), projectId, "rule_pack_publish");
    const successorPackId = result.pack.rule_pack_id;
    if (successorPackId && confirmedSamplesRef.current?.inspection) {
      confirmedSamplesRef.current = {
        ...confirmedSamplesRef.current,
        packId: successorPackId,
      };
    }
    setMessage("规则包已发布。日常医学监查将以该版本规则运行。");
    onPublished?.();
    return successorPackId;
  });

  const busy = Boolean(busyAction);
  const legacyCandidateRules = rules.filter((rule) => rule.status === "candidate");
  const selectedBatchMatches = batches.filter((batch) => batch.batchId === selectedBatchId);
  const selectedBatchReady = selectedBatchMatches.length === 1
    && selectedBatchMatches[0].displayIdentityState === "ready";
  const canRunShadow = Boolean(
    pack
    && ["draft", "shadow"].includes(pack.status)
    && selectedBatchId
    && selectedBatchReady
    && !busy,
  );
  const canConfirm = Boolean(
    pack?.status === "shadow" && inspection && !busy,
  );
  const canPublish = Boolean(pack?.status === "confirmed" && !busy);
  const showSampleSection = Boolean(
    inspection && ["shadow", "confirmed", "published"].includes(pack?.status || ""),
  );
  const inspectionConfirmed = ["confirmed", "published"].includes(pack?.status || "");

  return (
    <div className="monitoring-protocol-prep-host">
      <button
        className="monitoring-protocol-prep-backdrop"
        type="button"
        aria-label="关闭规则发布"
        onClick={onClose}
      />
      <aside
        className="monitoring-protocol-prep-drawer monitoring-rule-release-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="规则发布与启用"
      >
        <header className="monitoring-protocol-prep-head">
          <div>
            <span>医学监查</span>
            <strong>规则发布与启用</strong>
            <small>组建规则包，核对真实批次影子样本，确认并发布后用于日常医学监查。</small>
          </div>
          <div className="monitoring-rule-release-head-actions">
            <button
              className="icon-button"
              type="button"
              title="刷新状态"
              disabled={loading || busy}
              onClick={() => load({ focusPackId: selectedPackId })}
            >
              <RefreshCw size={15} />
            </button>
            <button className="icon-button" type="button" title="关闭" onClick={onClose}>
              <X size={17} />
            </button>
          </div>
        </header>

        <div className="monitoring-protocol-prep-body monitoring-rule-release-body">
          <ol className="monitoring-rule-release-steps" aria-label="规则发布步骤">
            {steps.map((step) => (
              <li key={step.key} className={step.state}>
                <StepIcon state={step.state} />
                <span>{step.label}</span>
              </li>
            ))}
          </ol>

          {loading && !packs.length && (
            <p className="monitoring-rule-release-empty">
              <LoaderCircle size={15} className="monitoring-rule-release-spin" />
              正在读取规则包与批次状态
            </p>
          )}

          {!loading && versions.length === 0 && (
            <p className="monitoring-rule-release-empty">
              当前项目尚无已确认方案版本，请先完成方案版本登记。
            </p>
          )}

          {versions.length > 0 && (
            <section className="monitoring-rule-release-section" aria-label="规则包">
              <header>
                <strong>规则包</strong>
                {pack && (
                  <span className={`monitoring-rule-release-pack-status ${pack.status}`}>
                    {pack.statusLabel} · 第 {pack.packRevision} 版 · {rules.length} 条规则
                  </span>
                )}
              </header>

              {pickerPacks.length > 1 && (
                <label className="monitoring-rule-release-pack-picker">
                  <span>查看版本</span>
                  <select
                    value={selectedPackId}
                    disabled={busy}
                    onChange={(event) => {
                      load({ focusPackId: event.target.value, quiet: true });
                    }}
                  >
                    {pickerPacks.map((item, index) => (
                      <option
                        key={rulePackDisplayKey(item, index)}
                        value={item.rulePackId}
                        disabled={item.displayIdentityState !== "ready"}
                      >
                        第 {item.packRevision} 版 · {item.statusLabel}
                        {item.displayIdentityState !== "ready" ? " · 身份待核对" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {packs.some((item) => item.displayIdentityState !== "ready") && (
                <p className="monitoring-rule-release-note warning">
                  部分规则包身份重复，仅可读；默认读取与发布路径只接受唯一规则包。
                </p>
              )}

              {pack && rules.length > 0 && (
                <ul className="monitoring-rule-release-rules">
                  {rules.map((rule) => (
                    <li key={rule.ruleRevisionId || rule.ruleKey}>
                      <div>
                        <strong>{rule.title}</strong>
                        {rule.sourceLocator && <small>{rule.sourceLocator}</small>}
                      </div>
                      <span className={`monitoring-rule-release-rule-status ${rule.status}`}>
                        {rule.statusLabel}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {legacyCandidateRules.length > 0 && pack?.status === "draft" && (
                <p className="monitoring-rule-release-note warning">
                  {legacyCandidateRules.length}
                  条规则为旧版候选，缺少当前字段映射身份，无法进入影子检查；请通过规则建议重新采用后组建新草稿。
                </p>
              )}

              {diff && pack?.status !== "published" && (
                <p className="monitoring-rule-release-diff">{diff.summary}</p>
              )}

              {!pack && facts.length > 0 && (
                <p className="monitoring-rule-release-note">
                  已有 {facts.length} 条已确认方案事实，规则在采用时均已完成医学决定。
                </p>
              )}
              {!pack && facts.length === 0 && !loading && (
                <div className="monitoring-rule-release-note">
                  <span>尚无已确认方案事实。请先在「准备方案规则」中完成条款确认并采用规则建议。</span>
                  {onOpenProtocolPreparation && (
                    <button type="button" onClick={onOpenProtocolPreparation}>
                      前往准备方案规则
                    </button>
                  )}
                </div>
              )}

              {!pack && facts.length > 0 && (
                <div className="monitoring-rule-release-action">
                  <button
                    className="primary-button"
                    type="button"
                    disabled={busy || !selectedVersionId}
                    onClick={createDraft}
                  >
                    {busyAction === "draft" ? <LoaderCircle size={15} /> : null}
                    组建规则包草稿
                  </button>
                </div>
              )}
            </section>
          )}

          {pack && ["draft", "shadow"].includes(pack.status) && (
            <section className="monitoring-rule-release-section" aria-label="自动影子检查">
              <header>
                <strong>自动影子检查</strong>
                <span>服务器从冻结批次抽取样本并实际运行规则</span>
              </header>
              {batches.length === 0 ? (
                <p className="monitoring-rule-release-note warning">
                  尚无已冻结批次。请先完成批次冻结与字段映射，再运行自动影子检查。
                </p>
              ) : (
                <label className="monitoring-rule-release-pack-picker">
                  <span>冻结批次</span>
                  <select
                    value={selectedBatchId}
                    disabled={busy}
                    onChange={(event) => {
                      // Readiness is batch-scoped and fail-closed: never show
                      // the previous batch's verdict next to a new selection.
                      setReadiness(null);
                      setSelectedBatchId(event.target.value);
                    }}
                  >
                    {batches.map((batch) => (
                      <option
                        key={batch.displayKey}
                        value={batch.batchId}
                        disabled={batch.displayIdentityState !== "ready"}
                      >
                        {shadowBatchOptionLabel(batch)}
                        {batch.displayIdentityState !== "ready" ? " · 身份待核对" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {batches.some((batch) => batch.displayIdentityState !== "ready") && (
                <p className="monitoring-rule-release-note warning">
                  部分冻结批次身份重复，仅可读；影子检查路径只接受唯一批次。
                </p>
              )}
              {selectedBatchId && (
                <div className="monitoring-rule-release-action">
                  <button
                    className="primary-button"
                    type="button"
                    disabled={!canRunShadow}
                    onClick={runAutomaticShadow}
                  >
                    {busyAction === "shadow" ? <LoaderCircle size={15} /> : null}
                    {inspection ? "按所选批次重新抽样" : "运行自动影子检查"}
                  </button>
                </div>
              )}
            </section>
          )}

          {showSampleSection && (
            <section className="monitoring-rule-release-section" aria-label="影子样本">
              <header>
                <strong>影子样本</strong>
                <span className={`monitoring-rule-release-pack-status ${inspectionConfirmed ? "confirmed" : "shadow"}`}>
                  {inspectionConfirmed ? "影子样本已确认" : inspection.statusLabel}
                </span>
              </header>
              {!inspectionConfirmed && (
                <p className="monitoring-rule-release-note">{PROVISIONAL_INSPECTION_NOTE}</p>
              )}
              <ReleaseSamples samples={inspection.samples} />
              {inspectionConfirmed && confirmation && (
                <p className="monitoring-rule-release-note success">
                  医学已确认
                  {confirmation.confirmedAt
                    ? ` · 确认时间 ${confirmedAtLabel(confirmation.confirmedAt)}`
                    : ""}
                  {confirmation.sampleSetId ? ` · 确认集 ${confirmation.sampleSetId}` : ""}
                </p>
              )}
              {inspectionConfirmed && shadowRun && (
                <p className="monitoring-rule-release-note success">{shadowRun.label}</p>
              )}
            </section>
          )}

          {pack?.status === "shadow" && inspection && (
            <section className="monitoring-rule-release-section" aria-label="确认影子样本">
              <header>
                <strong>确认影子样本</strong>
              </header>
              <p className="monitoring-rule-release-note">{SHADOW_CONFIRMATION_NOTE}</p>
              <div className="monitoring-rule-release-action">
                <button
                  className="primary-button"
                  type="button"
                  disabled={!canConfirm}
                  onClick={confirmShadow}
                >
                  {busyAction === "confirm" ? <LoaderCircle size={15} /> : null}
                  确认影子样本结果
                </button>
              </div>
            </section>
          )}

          {pack?.status === "confirmed" && (
            <section className="monitoring-rule-release-section" aria-label="发布规则包">
              <header>
                <strong>发布规则包</strong>
              </header>
              <p className="monitoring-rule-release-note">
                发布内容与您确认的影子样本结果完全一致；发布后该版本规则才用于正式日常医学监查。
              </p>
              <div className="monitoring-rule-release-action">
                <button
                  className="primary-button"
                  type="button"
                  disabled={!canPublish}
                  onClick={publish}
                >
                  {busyAction === "publish" ? <LoaderCircle size={15} /> : null}
                  发布规则包
                </button>
              </div>
            </section>
          )}

          {pack?.status === "published" && (
            <section
              className={`monitoring-rule-release-section monitoring-rule-release-readiness ${ready ? "ready" : "blocked"}`}
              aria-label="日常监查就绪"
            >
              <header>
                <strong>日常监查就绪</strong>
                <span>只读核对，不会修改任何数据</span>
              </header>
              {ready ? (
                <p className="monitoring-rule-release-note success">
                  {readiness.message || "当前批次已具备正式日常医学监查启动条件。"}
                </p>
              ) : (
                <p className="monitoring-rule-release-note warning">
                  {readiness?.message || "就绪状态读取失败，请刷新。"}
                </p>
              )}
              {!ready && remediation?.key === "mapping" && onOpenMapping && (
                <div className="monitoring-rule-release-action">
                  <button type="button" onClick={onOpenMapping}>
                    {remediation.label}
                  </button>
                </div>
              )}
            </section>
          )}

          {message && (
            <p className="monitoring-rule-release-message">
              <CheckCircle2 size={15} />
              {message}
            </p>
          )}
          {error && (
            <p className="monitoring-rule-release-error">
              <CircleAlert size={15} />
              {error}
            </p>
          )}
          {auxiliaryReadError && (
            <p className="monitoring-rule-release-error" role="alert">
              <CircleAlert size={15} />
              {auxiliaryReadError}
            </p>
          )}
          {!loading && packs.length > 0 && nextAction.key !== "readiness" && (
            <p className="monitoring-rule-release-next">
              下一步：{nextAction.label}
            </p>
          )}
        </div>
      </aside>
    </div>
  );
}
