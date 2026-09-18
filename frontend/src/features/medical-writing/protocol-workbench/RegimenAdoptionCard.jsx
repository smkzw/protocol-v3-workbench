import { useEffect, useRef, useState } from "react";
import { RegimenProposalCard } from "./RegimenProposalCard";

function restored(key) {
  try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; }
}
function publicMessage(reason) {
  const text = reason?.detail?.message || reason?.message;
  return typeof text === "string" && /[\u3400-\u9fff]/u.test(text)
    ? text : "本次保存结果尚未确认，方案和操作记录已保留。";
}
function AdoptionSession({ projectId, studyDefinitionId, actorId, runId, proposal, api, freshAdoptionAllowed = true }) {
  const key = "protocol-v3:regimen-adoption:" + JSON.stringify([projectId, studyDefinitionId, runId]);
  const [intent, setIntent] = useState(() => restored(key));
  const [configurationRejected, setConfigurationRejected] = useState(() => {
    const original = restored(key);
    return Boolean(original && restored(key + ":not-executed") === original.operation_id);
  });
  const [study, setStudy] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [validity, setValidity] = useState(null);
  const [validityRefresh, setValidityRefresh] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [lookup, setLookup] = useState(0);
  const flight = useRef(false);
  const alive = useRef(true);
  const request = useRef(null);
  const apiRef = useRef(api); apiRef.current = api;
  function accept(value, original) {
    if (value?.study_definition_id !== studyDefinitionId || !value.effective_decision?.decision_record_id
      || !value.revision_sha256 || value.definition?.study_definition_id !== studyDefinitionId
      || !Number.isInteger(value.revision) || value.definition.revision !== value.revision
      || value.revision < original.expected_revision + 1) {
      throw new Error("确认回执尚未核对清楚，原操作记录已保留。");
    }
    setReceipt(value); setError("");
  }
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; request.current?.abort(); };
  }, []);
  useEffect(() => {
    if (!receipt) return undefined;
    const controller = new AbortController();
    setValidity(null);
    async function readValidity() {
      try {
        const graph = await apiRef.current.getDecisionGraph(projectId, studyDefinitionId, {signal:controller.signal});
        if (controller.signal.aborted) return;
        if (graph?.project_id !== projectId || graph.study_definition_id !== studyDefinitionId || !Array.isArray(graph.records)) {
          throw new Error('decision graph mismatch');
        }
        const record = graph.records.find(item => item.decision_key === 'decision:dose-regimen');
        setValidity(record?.decision_record_id && record.decision_record_id !== receipt.effective_decision.decision_record_id
          ? 'superseded' : ['current','stale'].includes(record?.current_validity) && record.decision_record_id === receipt.effective_decision.decision_record_id
            ? record.current_validity : 'unverified');
      } catch {
        if (!controller.signal.aborted) setValidity('unavailable');
      }
    }
    readValidity();
    return () => controller.abort();
  }, [projectId, studyDefinitionId, receipt, validityRefresh]);
  useEffect(() => {
    const controller = new AbortController();
    async function read() {
      try {
        if (intent && configurationRejected) {
          setError("工作台配置尚未就绪，本次操作未执行。原选择已保留。配置恢复后可继续保存。");
        } else if (intent) {
          const value = await apiRef.current.recoverRegimenAdoption(projectId, runId, intent, { signal: controller.signal });
          if (!controller.signal.aborted) accept(value, intent);
        } else {
          const value = await apiRef.current.getStudyDefinition(projectId, studyDefinitionId, { signal: controller.signal });
          if (controller.signal.aborted) return;
          if (value?.definition?.study_definition_id !== studyDefinitionId || !value.revision_sha256
            || !Number.isInteger(value.definition.revision)) throw new Error("暂时无法读取当前研究版本，请刷新后核对。");
          setStudy(value); setError("");
        }
      } catch (reason) {
        if (!controller.signal.aborted) setError(publicMessage(reason));
      }
    }
    read();
    return () => controller.abort();
  }, [projectId, studyDefinitionId, runId, lookup]);

  async function confirm() {
    if (!freshAdoptionAllowed) return;
    if (flight.current || (intent && !configurationRejected) || (!intent && !study) || !actorId) return;
    flight.current = true; setBusy(true); setError(""); setNotice("");
    const original = configurationRejected ? intent : { study_definition_id: studyDefinitionId, operation_id: "regimen-adopt:" + crypto.randomUUID(),
      expected_revision: study.definition.revision, snapshot_sha256: study.revision_sha256,
      actor_id: actorId, decided_at: new Date().toISOString(), reason: "采用已展示的完整给药方案" };
    // A stable saved intent is necessary before any mutation; no clinical values are copied into it.
    try {
      localStorage.removeItem(key + ":not-executed");
      localStorage.setItem(key + ":attempt:" + original.operation_id, JSON.stringify(original));
      localStorage.setItem(key, JSON.stringify(original));
    }
    catch { flight.current = false; setBusy(false); setError("浏览器无法保存本次操作记录，请恢复存储后再确认。"); return; }
    setIntent(original); setConfigurationRejected(false);
    const controller = new AbortController(); request.current = controller;
    try {
      const value = await apiRef.current.adoptRegimenDesign(projectId, runId, original, { signal: controller.signal });
      if (alive.current && !controller.signal.aborted) accept(value, original);
    } catch (reason) {
      if (alive.current && !controller.signal.aborted) {
        if (reason?.status === 424) {
          // This response explicitly proves rejection before any mutation.
          // Preserve the original choice; a later explicit save reuses its CAS.
          try {
            localStorage.setItem(key + ":not-executed", JSON.stringify(original.operation_id));
            setConfigurationRejected(true);
          } catch { /* Without durable proof, reopening conservatively reconciles. */ }
          setError(publicMessage(reason));
        } else if ([400, 404, 409, 422].includes(reason?.status)) {
          // The server explicitly rejected this apply. Preserve its original
          // attempt; only clear the active recovery pointer, never auto-apply.
          try {
            localStorage.removeItem(key);
            setIntent(null); setStudy(null); setNotice(publicMessage(reason));
            setLookup(value => value + 1);
          } catch { setError(publicMessage(reason)); }
        } else setError(publicMessage(reason));
      }
    } finally {
      if (alive.current) { flight.current = false; setBusy(false); }
    }
  }
  return <>
    {notice && <p role="status">{notice}</p>}
    {receipt && <div className="rpc-validity" role="status" aria-label="当前确认状态">
      <p>{validity === 'current' ? '当前研究内容下，这份确认仍有效。'
        : validity === 'stale' ? '研究内容已变化，这份历史确认需要重新核对。'
        : validity === 'superseded' ? '本研究已有后续给药确认，此处保留原确认记录。'
        : validity === null ? '原确认已保存，正在核对当前有效性。'
        : '原确认已保存，当前有效性尚未核实。'}</p>
      <button type="button" onClick={() => setValidityRefresh(value => value + 1)}>更新确认状态</button>
    </div>}
    <RegimenProposalCard proposal={proposal} onConfirm={confirm} savedReceipt={receipt}
      busy={busy} error={error}
      confirmationBlockedReason={!freshAdoptionAllowed && !receipt ? "这份旧建议尚未结合本研究参数，请先整理本研究的给药建议。"
        : configurationRejected ? "原选择已保留，等待配置恢复后保存。" : intent && !receipt ? "本次提交待核对，请先找回原确认记录。"
        : !study && !receipt ? "正在读取当前研究版本。"
        : !actorId ? "请先选择当前研究负责人。" : ""}
      sourceDownloadUrl={id => api.sourceDownloadUrl(projectId, id)} />
    {configurationRejected && freshAdoptionAllowed && !receipt && !busy && <button type="button" onClick={confirm}>配置恢复后继续保存原选择</button>}
    {intent && !receipt && !busy && !configurationRejected && <button type="button" onClick={() => setLookup(value => value + 1)}>核对本次确认</button>}
    {!intent && error && <button type="button" onClick={() => setLookup(value => value + 1)}>读取当前研究</button>}
  </>;
}
export function RegimenAdoptionCard(props) {
  return <AdoptionSession key={JSON.stringify([props.projectId, props.studyDefinitionId, props.runId])} {...props} />;
}
