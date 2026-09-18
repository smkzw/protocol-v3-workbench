import { useEffect, useRef, useState } from "react";
import { RegimenProposalCard } from "./RegimenProposalCard";
import { RegimenAdoptionCard } from "./RegimenAdoptionCard";

function readSaved(key) {
  try { return JSON.parse(localStorage.getItem(key) || "{}") || {}; } catch { return {}; }
}
function checked(value, expectedId) {
  if (!value?.workflow_run_id || typeof value.status !== "string"
      || (expectedId && value.workflow_run_id !== expectedId)) {
    throw new Error("本次设计记录尚未核对清楚，资料已保留。");
  }
  return value;
}
function message(error) {
  const text = error?.detail?.message || error?.message;
  return typeof text === "string" && /[\u3400-\u9fff]/u.test(text)
    ? text : "暂时无法核对设计进度，已保存的记录会保留。";
}

function DesignSession({ projectId, seedRunId, api, onConfirm, studyDefinitionId, actorId }) {
  const legacyKey = "protocol-v3:regimen:" + JSON.stringify([projectId, seedRunId]);
  const key = studyDefinitionId
    ? "protocol-v3:regimen:" + JSON.stringify([projectId, seedRunId, studyDefinitionId]) : legacyKey;
  const [saved, setSaved] = useState(() => {
    const scoped = readSaved(key);
    if (Object.keys(scoped).length || key === legacyKey) return scoped;
    const legacy = readSaved(legacyKey);
    // Preserve source-only history and unknown acknowledgements. Never move a
    // known study-bound intent to a different target; do not delete old records.
    return legacy.intent?.study_definition_id && legacy.intent.study_definition_id !== studyDefinitionId ? {} : legacy;
  });
  const [job, setJob] = useState(null);
  const [historicalJob, setHistoricalJob] = useState(null);
  const historicalRequest = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [storageError, setStorageError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const flight = useRef(false);
  const alive = useRef(true);
  const request = useRef(null);
  const apiRef = useRef(api);
  apiRef.current = api;

  function remember(value) {
    setSaved(value);
    try { localStorage.setItem(key, JSON.stringify(value)); setStorageError(""); }
    catch { setStorageError("浏览器暂时无法保留进度，请保持页面打开。"); }
  }
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; request.current?.abort(); historicalRequest.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!saved.runId && !saved.pending) return undefined;
    if (!saved.runId && studyDefinitionId && (
      saved.intent?.study_definition_id !== studyDefinitionId
      || saved.intent?.seed_run_id !== seedRunId
      || !saved.intent?.expected_workflow_run_id)) {
      setError("旧设计请求的研究归属尚未核实，原记录已保留。");
      return undefined;
    }
    const controller = new AbortController();
    let timer;
    let delay = 1000;
    let allowResume = true;
    const read = async () => {
      try {
        let next = checked(saved.runId
          ? await apiRef.current.getRegimenDesign(projectId, saved.runId, { signal: controller.signal })
          : await apiRef.current.recoverRegimenDesign(projectId, saved.intent || seedRunId, { signal: controller.signal }), saved.runId || saved.intent?.expected_workflow_run_id);
        if (controller.signal.aborted) return;
        if (!saved.runId) {
          remember({ runId: next.workflow_run_id, previousRunIds: saved.previousRunIds }); setJob(next); setError(""); return;
        }
        if (allowResume && next.can_resume === true) {
          allowResume = false;
          next = checked(await apiRef.current.resumeRegimenDesign(projectId, saved.runId,
            { signal: controller.signal }), saved.runId);
          if (controller.signal.aborted) return;
        }
        setJob(next); setError("");
        if (next.status === "running" || next.can_resume === true) {
          timer = setTimeout(read, delay); delay = Math.min(delay * 2, 30000);
        }
      } catch (reason) {
        if (controller.signal.aborted) return;
        if (!saved.runId && reason?.status === 404) {
          remember({}); setError("尚未找到已保存的设计任务，资料仍保留，可再次开始整理。");
        } else setError(message(reason));
      }
    };
    read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [projectId, seedRunId, saved.runId, saved.pending, refresh]);

  const canStartSuccessor = Boolean(studyDefinitionId && job && saved.runId
    && job.study_definition_id !== studyDefinitionId && !job.can_resume
    && job.status !== "running" && !saved.pending && !saved.uncertain);
  async function start(replaceReference = false) {
    if (flight.current || (saved.runId && !(replaceReference && canStartSuccessor)) || saved.pending) return;
    const previousRunIds = replaceReference
      ? [...new Set([...(saved.previousRunIds || []), saved.runId])] : saved.previousRunIds;
    flight.current = true; setBusy(true); setError("");
    const controller = new AbortController(); request.current = controller;
    let intent;
    let dispatched = false;
    try {
      intent = studyDefinitionId
        ? await apiRef.current.prepareRegimenDesign(projectId, seedRunId, studyDefinitionId, {signal: controller.signal})
        : seedRunId;
      if (!alive.current || controller.signal.aborted) return;
      if (studyDefinitionId && (intent?.seed_run_id !== seedRunId
        || intent.study_definition_id !== studyDefinitionId || !intent.expected_workflow_run_id)) {
        throw new Error('本次研究的设计请求尚未核实，尚未开始生成。');
      }
      // Save the exact server identity before the request can start work.
      localStorage.setItem(key, JSON.stringify({pending: true, intent, previousRunIds}));
      dispatched = true;
      const next = checked(await apiRef.current.startRegimenDesign(projectId, intent, { signal: controller.signal }), intent?.expected_workflow_run_id);
      if (!alive.current || controller.signal.aborted) return;
      remember({ runId: next.workflow_run_id, previousRunIds }); setJob(next);
    } catch (reason) {
      if (!alive.current || controller.signal.aborted) return;
      // Do not start automatic lookup while the original request is still in flight.
      if (!dispatched || [400, 404, 409, 422].includes(reason?.status)) remember(replaceReference ? saved : {});
      else { setSaved({ uncertain: true, intent, previousRunIds }); }
      setError(message(reason));
    } finally {
      if (alive.current) { flight.current = false; setBusy(false); }
    }
  }
  const proposal = job?.validation?.proposal;
  async function readHistory(runId) {
    historicalRequest.current?.abort();
    const controller = new AbortController(); historicalRequest.current = controller;
    try {
      const value = checked(await apiRef.current.getRegimenDesign(projectId, runId, {signal:controller.signal}), runId);
      if (alive.current && !controller.signal.aborted) setHistoricalJob(value);
    } catch (reason) {
      if (alive.current && !controller.signal.aborted) setError(message(reason));
    }
  }
  return <section className="pvi-proposal" aria-label="完整给药建议">
    {!saved.runId && !saved.pending && !saved.uncertain && <button type="button" disabled={busy} onClick={() => start()}>整理完整给药建议</button>}
    {canStartSuccessor && <button type="button" disabled={busy} onClick={() => start(true)}>基于本研究整理新建议</button>}
    {(busy || job?.status === "running") && <p role="status">正在整理各治疗期和组别的给药关系，记录已保存。</p>}
    {storageError && <p role="alert">{storageError}</p>}
    {error && <p role="alert">{error}</p>}
    {(error || saved.uncertain) && <button type="button" onClick={() => {
      if (saved.uncertain) setSaved({ pending: true, intent: saved.intent, previousRunIds: saved.previousRunIds });
      else setRefresh(value => value + 1);
    }}>核对本次设计</button>}
    {job?.status === "blocked" && <p role="status">本次设计结果需要核对，原资料和记录已保留。</p>}
    {job?.status === "needs_structure_correction" && !job.can_resume && <p role="status">设计整理尚未完成，本次记录已保留。</p>}
    {proposal?.regimen && (studyDefinitionId && actorId
      ? <RegimenAdoptionCard projectId={projectId} studyDefinitionId={studyDefinitionId} actorId={actorId}
          freshAdoptionAllowed={job.study_definition_id === studyDefinitionId}
          runId={job.workflow_run_id} proposal={proposal} api={api} />
      : <RegimenProposalCard proposal={proposal} onConfirm={onConfirm}
          sourceDownloadUrl={id => api.sourceDownloadUrl(projectId, id)} />)}
    {!proposal?.regimen && proposal?.questions?.length > 0 && <ul>{proposal.questions.map((question, index) => <li key={index}>{question}</li>)}</ul>}
    {saved.previousRunIds?.map((runId, index) => <button key={runId} type="button" onClick={() => readHistory(runId)}>查看之前的给药建议（{index + 1}）</button>)}
    {historicalJob && <section aria-label="之前的给药建议">
      <h3>之前的给药建议</h3>
      {historicalJob.validation?.proposal?.regimen && (studyDefinitionId && actorId
        ? <RegimenAdoptionCard projectId={projectId} studyDefinitionId={studyDefinitionId} actorId={actorId}
            runId={historicalJob.workflow_run_id} proposal={historicalJob.validation.proposal} api={api} freshAdoptionAllowed={false}/>
        : <RegimenProposalCard proposal={historicalJob.validation.proposal}
            sourceDownloadUrl={id => api.sourceDownloadUrl(projectId, id)}/>)}
      {!historicalJob.validation?.proposal?.regimen && <p>原任务尚未形成完整建议，记录仍保留。</p>}
    </section>}
  </section>;
}

export function RegimenDesignWorkspace(props) {
  return <DesignSession key={JSON.stringify([props.projectId, props.seedRunId, props.studyDefinitionId])} {...props} />;
}
