import { ProtocolWritingDesk } from './ProtocolWritingDesk';
import protocolLogo from './assets/logo_bot.svg';
import { useEffect, useMemo, useRef, useState } from "react";
import { ProtocolSourceIntake } from "./ProtocolSourceIntake";
import { StudyContextWorkspace } from "./StudyContextWorkspace";
import { ResearchInformationCard } from "./ResearchInformationCard";
import { RegimenDesignWorkspace } from "./RegimenDesignWorkspace";
import { DesignElementsCards } from "./DesignElementsCards";
import { createProtocolWorkspaceApi } from "./protocolWorkspaceApi.mjs";
import "./ProtocolIntakeWorkspace.css";
import { sourceRoleDisplayText } from "./sourceRoleLabels.mjs";

const LABELS = {
  research_drug: "研究药物", dosage_form_and_route: "剂型与给药途径",
  anticipated_dose: "拟用剂量", target_or_mechanism: "靶点或作用机制",
  indication: "适应症", clinical_phase: "研究期别", populations: "研究人群", comparator: "对照方式",
};
function pending(job) { return job?.status === "running" || job?.can_resume === true; }
function restored(key) {
  try { return JSON.parse(localStorage.getItem(key) || "{}") || {}; } catch { return {}; }
}
function publicError(error) {
  const text = error?.detail?.message || error?.message;
  return typeof text === "string" && /[\u3400-\u9fff]/u.test(text) ? text : "暂时无法读取整理结果，请稍后查看进度。";
}

function IntakeProject({ projectId, api, studyDefinitionId, actorId, onNavigationGuardChange }) {
  const key = "protocol-v3:intake:" + projectId;
  const saved = useMemo(() => restored(key), [key]);
  const restoredRequest = saved.pendingRequest && typeof saved.pendingRequest.userBrief === "string"
    && Array.isArray(saved.pendingRequest.sourceArtifactIds) ? saved.pendingRequest : null;
  const [pendingRequest, setPendingRequest] = useState(restoredRequest);
  const [brief, setBrief] = useState(typeof saved.brief === "string" ? saved.brief : "");
  const [job, setJob] = useState(!restoredRequest && saved.runId ? { workflow_run_id: saved.runId, status: "running" } : null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [storageError, setStorageError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [sourceRefresh, setSourceRefresh] = useState(0);
  const [canRefreshSources, setCanRefreshSources] = useState(false);
  const alive = useRef(true);
  const resumeOnRestore = useRef(Boolean(saved.runId));
  const submittingRef = useRef(false);
  const submitController = useRef(null);
  const apiRef = useRef(api);
  apiRef.current = api;

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false; submitController.current?.abort();
      submitController.current = null; submittingRef.current = false;
    };
  }, []);

  function remember(values) {
    try { localStorage.setItem(key, JSON.stringify({ ...restored(key), ...values })); setStorageError(""); }
    catch { setStorageError("浏览器暂时无法保留本页进度。请暂时保持页面打开。"); }
  }

  useEffect(() => {
    if (restoredRequest) recoverPending(restoredRequest);
  }, []);

  useEffect(() => {
    if (!job?.workflow_run_id || !pending(job)) return undefined;
    const controller = new AbortController();
    let timer;
    let delay = 1000;
    const id = job.workflow_run_id;
    const read = async () => {
      try {
        let next = await apiRef.current.getResearchIntake(projectId, id, { signal: controller.signal });
        if (controller.signal.aborted || !alive.current) return;
        if (next?.workflow_run_id !== id || typeof next.status !== "string") throw new Error("整理进度返回不完整，请再次查看。");
        const restore = resumeOnRestore.current;
        resumeOnRestore.current = false;
        if (restore && next.can_resume === true) {
          await apiRef.current.resumeResearchIntake(projectId, id, { signal: controller.signal });
          if (controller.signal.aborted || !alive.current) return;
          next = await apiRef.current.getResearchIntake(projectId, id, { signal: controller.signal });
          if (controller.signal.aborted || !alive.current) return;
          if (next?.workflow_run_id !== id || typeof next.status !== "string") throw new Error("整理进度返回不完整，请再次查看。");
        }
        setJob(next); setError("");
        if (pending(next)) {
          timer = setTimeout(read, delay);
          delay = Math.min(delay * 2, 30000);
        }
      } catch (reason) {
        if (!controller.signal.aborted && alive.current) setError(publicError(reason));
      }
    };
    read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [projectId, job?.workflow_run_id, refresh]);

  async function prepare(payload) {
    if (submittingRef.current || pending(job) || pendingRequest) return;
    resumeOnRestore.current = false;
    setCanRefreshSources(false);
    submittingRef.current = true;
    setSubmitting(true); setError("");
    const controller = new AbortController();
    submitController.current = controller;
    const originalRequest = { userBrief: payload.userBrief, sourceArtifactIds: [...payload.sourceArtifactIds] };
    setPendingRequest(originalRequest); setJob(null);
    remember({ brief: payload.userBrief, pendingRequest: originalRequest });
    try {
      const next = await apiRef.current.startResearchIntake(projectId, payload, { signal: controller.signal });
      if (!alive.current || controller.signal.aborted) return;
      if (!next?.workflow_run_id || typeof next.status !== "string") throw new Error("本次整理的保存结果尚未确认，资料和说明已保留。");
      remember({ brief: payload.userBrief, runId: next.workflow_run_id, pendingRequest: null });
      setPendingRequest(null);
      setJob(next);
    } catch (reason) {
      if (alive.current && !controller.signal.aborted) {
        setError(publicError(reason));
        setCanRefreshSources(reason?.status === 409);
        if ([400, 404, 409, 422].includes(reason?.status)) {
          setPendingRequest(null); remember({ pendingRequest: null });
        }
      }
    } finally {
      if (alive.current && submitController.current === controller) { submittingRef.current = false; setSubmitting(false); }
    }
  }

  async function recoverPending(request = pendingRequest) {
    if (!request || submittingRef.current) return;
    submittingRef.current = true; setSubmitting(true); setError("");
    const controller = new AbortController();
    submitController.current = controller;
    try {
      const next = await apiRef.current.recoverResearchIntake(projectId, request, { signal: controller.signal });
      if (!alive.current || controller.signal.aborted) return;
      if (!next?.workflow_run_id || typeof next.status !== "string") throw new Error("整理记录尚未查明，请稍后再次核对。");
      remember({ runId: next.workflow_run_id, pendingRequest: null });
      setPendingRequest(null); resumeOnRestore.current = next.can_resume === true;
      setJob(next);
    } catch (reason) {
      if (alive.current && !controller.signal.aborted) {
        if (reason?.status === 404) {
          setPendingRequest(null); remember({ pendingRequest: null });
          setError("尚未找到已保存的整理任务。资料和说明已保留，可再次开始整理。");
        } else setError(publicError(reason));
      }
    } finally {
      if (alive.current && submitController.current === controller) { submittingRef.current = false; setSubmitting(false); }
    }
  }

  async function resume() {
    if (submittingRef.current || job?.can_resume !== true) return;
    submittingRef.current = true; setSubmitting(true); setError("");
    const controller = new AbortController();
    submitController.current = controller;
    try {
      const next = await apiRef.current.resumeResearchIntake(projectId, job.workflow_run_id, { signal: controller.signal });
      if (!alive.current || controller.signal.aborted) return;
      if (next?.workflow_run_id !== job.workflow_run_id || typeof next.status !== "string") throw new Error("续接结果尚未确认，请查看进度。");
      setJob(next); setRefresh(value => value + 1);
    } catch (reason) {
      if (alive.current && !controller.signal.aborted) setError(publicError(reason));
    } finally {
      if (alive.current && submitController.current === controller) { submittingRef.current = false; setSubmitting(false); }
    }
  }

  const proposal = job?.validation?.proposal;
  const confirming = Boolean(actorId && job?.validation?.valid === true);
  const missing = Array.isArray(proposal?.missing_fields) ? proposal.missing_fields.map(field => LABELS[field]).filter(Boolean) : [];
  return <main className={`pvi-workspace${confirming ? ' pvi-workspace--writing' : ''}`}>
    <header className="pvi-heading">
      <img src={protocolLogo} width="121" height="25" alt="康哲药业"/>
      {!confirming && <p className="pvi-eyebrow">研究方案 · 准备资料</p>}
      <h2>{confirming ? '研究方案工作台' : '准备研究资料'}</h2>
      <p>{confirming ? '左侧确认研究设计，右侧编辑、保存和下载方案。' : '添加已有方案、研究者手册或参考资料，整理研究信息和需要补充的内容。'}</p>
    </header>
    <details className="pvi-howto">
      <summary>整套流程怎么做？（三步）</summary>
      <ol>
        <li><b>整理资料</b>：把研究简述写/粘贴在说明框里，点"准备写作材料"。没有正式文件也能开始。</li>
        <li><b>逐项确认</b>：系统逐项给建议（含推荐理由），您逐张卡片点"确认"；红色标识的内容重点核对。</li>
        <li><b>生成初稿并导出</b>：关键设计确认后点"生成完整初稿"，阅读修改后"保存"，最后"导出Word"。</li>
      </ol>
      <p>以编辑器的保存回执为准；保存失败时先下载本地备份。</p>
    </details>
    {storageError && <p role="alert">{storageError}</p>}
    <details className="pvi-source-disclosure" open={!confirming}>
    <summary>{confirming ? '已保存的研究资料与写作说明' : '研究资料与写作说明'}</summary>
    <fieldset className="pvi-inputs" disabled={submitting || pending(job) || Boolean(pendingRequest)}>
      <ProtocolSourceIntake projectId={projectId} api={api} brief={brief} refreshKey={sourceRefresh}
        initialExcludedKeys={Array.isArray(saved.excludedSourceKeys) ? saved.excludedSourceKeys.filter(value => typeof value === "string") : []}
        onExcludedKeysChange={excludedSourceKeys => remember({ excludedSourceKeys })}
        onBriefChange={value => { setBrief(value); remember({ brief: value }); }} onPrepare={prepare} />
    </fieldset>
    </details>
    {(submitting || pending(job)) && <p className="pvi-progress" role="status">正在整理资料，已保存的文件和说明会保留。</p>}
    {pendingRequest && !submitting && <button className="pvi-recovery" type="button" onClick={() => recoverPending()}>核对本次整理</button>}
    {job?.can_resume === true && <button className="pvi-recovery" type="button" disabled={submitting} onClick={resume}>继续本次整理</button>}
    {error && <div className="pvi-message" role="alert"><p>{error}</p>
      {job?.workflow_run_id && <button type="button" onClick={() => setRefresh(value => value + 1)}>查看进度</button>}
      {canRefreshSources && <button type="button" onClick={() => {
        setSourceRefresh(value => value + 1); setCanRefreshSources(false); setError("");
      }}>更新资料列表</button>}
    </div>}
    {job?.status === "blocked" && <p className="pvi-message" role="status">本次整理结果需要核对，资料和记录已保留。</p>}
    {job?.status === "needs_structure_correction" && !pending(job) && <p className="pvi-message" role="status">整理尚未完成，资料和本次记录已保留。</p>}
    {proposal && <details className="pvi-seed-details pvi-intake-summary" aria-label="整理建议" open={!actorId}>
      <summary>资料整理建议与原文依据</summary>
      <p>以下保留资料整理时的候选信息；本研究选择以确认记录为准。</p>
      <dl>{Object.entries(LABELS).flatMap(([field, label]) => {
        const values = proposal.fields?.[field];
        if (!Array.isArray(values) || !values.length) return [];
        return <div key={field} className="pvi-proposal-row"><dt>{label}</dt><dd>
          {values.map((value, index) => <div key={index}>
            <strong>{Array.isArray(value.candidate) ? value.candidate.join("、") : value.candidate}</strong>
            <p className="pvi-basis">{value.source_support === "reference_only" ? "参考资料中的信息"
              : value.basis === "user" ? "来自您的写作说明"
                : value.basis === "recommendation" ? "AI建议，仍需结合研究确认" : "来自所提供的方案资料"}</p>
            {value.reason && <p>{sourceRoleDisplayText(value.reason)}</p>}
            {Array.isArray(value.references) && value.references.length > 0 && <details className="pvi-evidence">
              <summary>查看原文依据</summary>
              {value.references.map((reference, referenceIndex) => <div key={referenceIndex}>
                <blockquote>{reference.quote}</blockquote>
                <a href={api.sourceDownloadUrl(projectId, reference.source_artifact_id)} download>下载对应原文件</a>
              </div>)}
            </details>}
          </div>)}
        </dd></div>;
      })}</dl>
      {missing.length > 0 && <p className="pvi-missing">还需要补充：{missing.join("、")}。可添加资料或在写作说明中补充。</p>}
    </details>}
    {job?.validation?.valid === true && (studyDefinitionId || !actorId
      ? (studyDefinitionId && actorId
        ? <ProtocolWritingDesk projectId={projectId} seedRunId={job.workflow_run_id}
          studyDefinitionId={studyDefinitionId} actorId={actorId} api={api} proposal={proposal} onNavigationGuardChange={onNavigationGuardChange}/>
        : <RegimenDesignWorkspace projectId={projectId} seedRunId={job.workflow_run_id}
          api={api} studyDefinitionId={studyDefinitionId} actorId={actorId}/>)
      : <StudyContextWorkspace projectId={projectId} seedRunId={job.workflow_run_id} api={api} actorId={actorId} proposal={proposal} onNavigationGuardChange={onNavigationGuardChange} />)}
  </main>;
}

function ProtocolEntry({ projectId, api, studyDefinitionId, actorId, onNavigationGuardChange }) {
  const [handoff, setHandoff] = useState(null);
  const [fallback, setFallback] = useState(Boolean(studyDefinitionId || !actorId || !api?.ensureAuthoringHandoff));
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (fallback) return undefined;
    const controller = new AbortController();
    api.ensureAuthoringHandoff(projectId, actorId, { signal: controller.signal })
      .then(value => {
        if (!controller.signal.aborted) {
          if (value?.study_definition_id && ['ready', 'source_changed'].includes(value.status)) {
            setHandoff(value); setError('');
          } else setFallback(true);
        }
      })
      .catch(reason => {
        if (controller.signal.aborted) return;
        if (reason?.status === 404) setFallback(true);
        else setError(publicError(reason));
      });
    return () => controller.abort();
  }, [projectId, actorId, api, fallback, refresh]);

  if (handoff) return <main className="pvi-workspace pvi-workspace--writing">
    <header className="pvi-heading">
      <img src={protocolLogo} width="121" height="25" alt="康哲药业"/>
      <h2>研究方案工作台</h2>
      <p>已接续本项目确认过的研究设计。打开工作稿即可继续，无需重新上传或抄录。</p>
    </header>
    {handoff.status === 'source_changed' && <p role="status">研究设计已有较新确认版本；现有工作稿会保留，采用新候选前请核对差异。</p>}
    <ProtocolWritingDesk projectId={projectId} studyDefinitionId={handoff.study_definition_id}
      actorId={actorId} api={api} bridgeMode onNavigationGuardChange={onNavigationGuardChange}/>
  </main>;
  if (!fallback) return <main className="pvi-workspace" aria-busy="true">
    <p role="status">正在接续本项目已确认的研究设计和工作稿。</p>
    {error && <div className="pvi-message" role="alert"><p>{error}</p>
      <button type="button" onClick={() => setRefresh(value => value + 1)}>重新核对</button></div>}
  </main>;
  return <IntakeProject projectId={projectId} api={api} studyDefinitionId={studyDefinitionId}
    actorId={actorId} onNavigationGuardChange={onNavigationGuardChange}/>;
}

export function ProtocolIntakeWorkspace({ projectId, api, studyDefinitionId, actorId, onNavigationGuardChange }) {
  const defaultApi = useMemo(() => createProtocolWorkspaceApi(), []);
  return <ProtocolEntry key={projectId} projectId={projectId} api={api || defaultApi}
    studyDefinitionId={studyDefinitionId} actorId={actorId} onNavigationGuardChange={onNavigationGuardChange} />;
}
