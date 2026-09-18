import { useEffect, useMemo, useRef, useState } from "react";
import { ProtocolSourceIntake } from "./ProtocolSourceIntake";
import { createProtocolWorkspaceApi } from "./protocolWorkspaceApi.mjs";
import "./ProtocolIntakeWorkspace.css";

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

function IntakeProject({ projectId, api }) {
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
  const missing = Array.isArray(proposal?.missing_fields) ? proposal.missing_fields.map(field => LABELS[field]).filter(Boolean) : [];
  return <main className="pvi-workspace">
    <header className="pvi-heading">
      <p className="pvi-eyebrow">研究方案 · 准备资料</p>
      <h2>准备研究资料</h2>
      <p>添加已有方案、研究者手册或参考资料，整理研究信息和需要补充的内容。</p>
    </header>
    {storageError && <p role="alert">{storageError}</p>}
    <fieldset className="pvi-inputs" disabled={submitting || pending(job) || Boolean(pendingRequest)}>
      <ProtocolSourceIntake projectId={projectId} api={api} brief={brief} refreshKey={sourceRefresh}
        onBriefChange={value => { setBrief(value); remember({ brief: value }); }} onPrepare={prepare} />
    </fieldset>
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
    {proposal && <section className="pvi-proposal" aria-label="整理建议">
      <h3>已整理的研究信息</h3><p>以下是上次提交资料时的整理建议，尚未确认为研究事实。</p>
      <dl>{Object.entries(LABELS).flatMap(([field, label]) => {
        const values = proposal.fields?.[field];
        if (!Array.isArray(values) || !values.length) return [];
        return <div key={field} className="pvi-proposal-row"><dt>{label}</dt><dd>
          {values.map((value, index) => <div key={index}>
            <strong>{Array.isArray(value.candidate) ? value.candidate.join("、") : value.candidate}</strong>
            {value.reason && <p>{value.reason}</p>}
          </div>)}
        </dd></div>;
      })}</dl>
      {missing.length > 0 && <p className="pvi-missing">还需要补充：{missing.join("、")}。可添加资料或在写作说明中补充。</p>}
    </section>}
  </main>;
}

export function ProtocolIntakeWorkspace({ projectId, api }) {
  const defaultApi = useMemo(() => createProtocolWorkspaceApi(), []);
  return <IntakeProject key={projectId} projectId={projectId} api={api || defaultApi} />;
}

