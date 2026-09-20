import { useEffect, useRef, useState } from 'react';
import './kangzheProtocol.css';
import './DesignElementsCards.css';

const CARD_TITLES = {
  'objectives-endpoint': '研究目的与主要终点',
  'estimand': '估计目标与伴发事件策略',
  'sample-size': '样本量假设',
  'non-inferiority-margin': '非劣效界值',
  'interim': '期中分析与alpha分配',
};

const REGULATORY_CRITICAL = new Set(['estimand', 'sample-size', 'non-inferiority-margin', 'interim']);

function readable(error) {
  const text = error?.detail?.message || error?.message;
  return typeof text === 'string' && /[\u3400-\u9fff]/u.test(text)
    ? text : '设计要素建议尚未核对清楚，已保存内容保留。';
}

function OptionList({ options }) {
  if (!Array.isArray(options) || !options.length) return null;
  return <ul className="kz-design-options">
    {options.map((option, index) => <li key={index}>
      <strong>{option.text}</strong>
      <span className="kz-design-basis">{option.basis === 'recommendation' ? 'AI建议' : option.basis === 'source' ? '资料依据' : '研究者输入'}</span>
      <p>{option.reason}</p>
    </li>)}
  </ul>;
}

function CardSection({ card, proposal, confirmed, busy, onConfirm }) {
  const critical = REGULATORY_CRITICAL.has(card);
  return <section className={`kz-design-card${critical ? ' kz-design-critical' : ''}`}
    aria-label={CARD_TITLES[card] || card}>
    <header>
      <h4>{CARD_TITLES[card] || card}</h4>
      {critical && <span className="kz-design-risk-tag" role="note">监管答辩级，需逐项确认</span>}
    </header>
    {confirmed ? <p role="status">当前研究已保存本卡片内容；研究信息变化时会提示重新核对。</p> : <>
      {card === 'objectives-endpoint' && <>
        <h5>主要研究目的</h5>
        <OptionList options={proposal?.objectives?.primary}/>
        <h5>主要终点</h5>
        <OptionList options={[proposal?.endpoint?.primary_endpoint].filter(Boolean)}/>
      </>}
      {card === 'estimand' && <>
        <h5>估计目标五要素（含伴发事件策略）</h5>
        <dl className="kz-design-estimand">
          <dt>治疗</dt><dd>{proposal?.estimand?.treatment?.text}</dd>
          <dt>人群</dt><dd>{proposal?.estimand?.population?.text}</dd>
          <dt>变量</dt><dd>{proposal?.estimand?.variable?.text}</dd>
          <dt>伴发事件策略</dt><dd>{proposal?.estimand?.ice_strategy?.text}</dd>
          <dt>群体层面汇总量</dt><dd>{proposal?.estimand?.summary_measure?.text}</dd>
        </dl>
      </>}
      {card === 'sample-size' && <>
        <h5>样本量假设（可复算）</h5>
        <p>{proposal?.sample_size?.planned_n}</p>
        <ul className="kz-design-assumptions">
          {(proposal?.sample_size?.assumptions || []).map((item, index) => <li key={index}>{item}</li>)}
        </ul>
        <p>alpha {proposal?.sample_size?.alpha}；power {proposal?.sample_size?.power}；{proposal?.sample_size?.model}；失访 {proposal?.sample_size?.attrition}</p>
        <p>{proposal?.sample_size?.justification}</p>
      </>}
      {card === 'non-inferiority-margin' && <>
        <h5>非劣效界值</h5>
        <p>{proposal?.non_inferiority_margin?.margin}</p>
        <p>{proposal?.non_inferiority_margin?.clinical_justification}</p>
      </>}
      {card === 'interim' && <>
        <h5>期中分析</h5>
        <p>{proposal?.interim_planning?.timing}；信息分数 {proposal?.interim_planning?.information_fraction}</p>
        <p>目的：{proposal?.interim_planning?.purpose}</p>
        <p>决策规则：{proposal?.interim_planning?.decision_rule}</p>
        <p>责任：{proposal?.interim_planning?.decision_responsibility}；对最终分析：{proposal?.interim_planning?.final_analysis_impact}</p>
        {proposal?.interim_planning?.alpha_spending && <p>alpha分配：{proposal.interim_planning.alpha_spending}</p>}
      </>}
      <button type="button" className="kz-design-confirm" disabled={busy}
        onClick={onConfirm}>确认本卡片内容</button>
    </>}
  </section>;
}

export function DesignElementsCards({ projectId, seedRunId, studyDefinitionId, actorId, api }) {
  const storageKey = 'protocol-v3:design-elements:' + JSON.stringify([projectId, studyDefinitionId, seedRunId]);
  const [runId, setRunId] = useState(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch { return null; }
  });
  const [state, setState] = useState(null);
  const [confirmedCards, setConfirmedCards] = useState(() => {
    try { return JSON.parse(localStorage.getItem(storageKey + ':confirmed') || '{}') || {}; } catch { return {}; }
  });
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const flight = useRef(false), alive = useRef(true), request = useRef(null);
  const apiRef = useRef(api); apiRef.current = api;

  useEffect(() => {
    // StrictMode remounts effects: restore the liveness flag on every mount,
    // otherwise the cleanup of the first mount silences the second.
    alive.current = true;
    return () => { alive.current = false; request.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!runId) return undefined;
    const controller = new AbortController();
    let timer, delay = 1000, missing = 0;
    async function poll() {
      try {
        const value = await apiRef.current.getDesignElements(projectId, runId,
          { signal: controller.signal, studyDefinitionId });
        if (!alive.current || controller.signal.aborted) return;
        setState(value); setError('');
        if (value.status === 'running') timer = setTimeout(poll, delay), delay = Math.min(delay * 2, 30000);
      } catch (reason) {
        if (!alive.current || controller.signal.aborted) return;
        // prepare() publishes the expected run id before start() commits it;
        // a short-lived 404 in that window must not end polling.
        if (reason?.status === 404 && missing < 40) {
          missing += 1;
          timer = setTimeout(poll, delay);
          return;
        }
        setError(readable(reason));
      }
    }
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [runId, projectId]);

  async function begin() {
    if (flight.current || !studyDefinitionId) return;
    flight.current = true; setBusy(true); setError('');
    const controller = new AbortController(); request.current = controller;
    try {
      const client = apiRef.current;
      const prepared = await client.prepareDesignElements(projectId, seedRunId, studyDefinitionId,
        { signal: controller.signal });
      if (!controller.signal.aborted && prepared?.expected_workflow_run_id) {
        localStorage.setItem(storageKey, JSON.stringify(prepared.expected_workflow_run_id));
        setRunId(prepared.expected_workflow_run_id);
        const started = await client.startDesignElements(projectId, {
          seed_run_id: seedRunId, study_definition_id: studyDefinitionId,
          expected_workflow_run_id: prepared.expected_workflow_run_id,
        }, { signal: controller.signal });
        if (!controller.signal.aborted) setState(started);
      }
    } catch (reason) { if (!controller.signal.aborted) setError(readable(reason)); }
    finally { flight.current = false; if (!controller.signal.aborted) setBusy(false); }
  }

  async function confirmCard(card) {
    if (flight.current || !actorId || !runId) return;
    flight.current = true; setBusy(true); setError('');
    const controller = new AbortController(); request.current = controller;
    const operationId = 'design-card:' + crypto.randomUUID();
    try {
      // Save the local intent first: an unknown outcome is reconciled by the
      // same operation id instead of a repeated confirmation.
      const intent = { study_definition_id: studyDefinitionId, operation_id: operationId,
        card,
        expected_revision: state.expected_revision ?? 0,
        snapshot_sha256: state.snapshot_sha256 ?? '',
        actor_id: actorId, decided_at: new Date().toISOString(),
        reason: `确认设计要素：${CARD_TITLES[card] || card}`,
        seed_run_id: seedRunId,
        selections: card === 'objectives-endpoint'
          ? { primary_objective: 0, primary_endpoint_confirmed: true }
          : card === 'sample-size' || card === 'non-inferiority-margin' || card === 'interim'
            ? { [`${card.replace(/-/g, '_')}_confirmed`]: true }
            : { treatment: true, population: true, variable: true, ice_strategy: true, summary_measure: true } };
      localStorage.setItem(storageKey + ':intent:' + card, JSON.stringify(intent));
      let receipt;
      try { receipt = await apiRef.current.recoverDesignCard(projectId, runId, card, intent, { signal: controller.signal }); }
      catch (reason) { if (reason?.status !== 404) throw reason; }
      if (!controller.signal.aborted && !receipt) {
        receipt = await apiRef.current.adoptDesignCard(projectId, runId, card, intent, { signal: controller.signal });
      }
      if (!controller.signal.aborted && receipt) {
        const next = { ...confirmedCards, [card]: { operation_id: operationId, revision: receipt.revision } };
        setConfirmedCards(next);
        localStorage.setItem(storageKey + ':confirmed', JSON.stringify(next));
        // Each confirmation bumps the study revision; the next card's CAS
        // needs the receipt's values, not the pre-confirmation snapshot.
        if (Number.isInteger(receipt.revision)) {
          setState(prev => ({ ...(prev || {}), expected_revision: receipt.revision,
            snapshot_sha256: receipt.revision_sha256 || prev?.snapshot_sha256 }));
        }
      }
    } catch (reason) { if (!controller.signal.aborted) setError(readable(reason)); }
    finally { flight.current = false; if (!controller.signal.aborted) setBusy(false); }
  }

  const proposal = state?.validation?.proposal;
  const availableCards = state?.status === 'ready_for_review' && proposal
    ? ['objectives-endpoint', 'estimand', 'sample-size',
       ...(proposal.non_inferiority_margin ? ['non-inferiority-margin'] : []),
       ...(proposal.interim_planning ? ['interim'] : [])]
    : [];
  return <section className="kz-protocol kz-design-elements" aria-label="研究设计要素建议">
    <header><p className="kz-design-eyebrow">研究设计</p><h3>确认研究设计要素</h3>
      <p>以下建议来自已确认的研究信息与资料；逐卡核对后确认，全部确认后才可生成完整初稿。</p></header>
    {!runId && <button type="button" className="kz-design-primary" disabled={busy || !studyDefinitionId}
      onClick={begin}>生成设计要素建议</button>}
    {runId && state?.status === 'running' && <p role="status">正在整理设计要素建议，已确认内容保留。</p>}
    {runId && state?.status === 'needs_information' && (() => {
      // 审计后第6轮 P1：questions 与 unresolved_questions 是两组来源；
      // 只渲染其一会得到"冒号后空白"。合并去重并给出用户可执行的下一步。
      const pending = [...new Set([
        ...(proposal?.questions || []),
        ...(proposal?.unresolved_questions || []),
      ])].filter(Boolean);
      return <div role="alert">
        <p>设计建议尚有 {pending.length} 项未决内容，需要您补充后才能继续：</p>
        {pending.length > 0 && <ul>
          {pending.map((question, index) => <li key={index}>{question}</li>)}
        </ul>}
        <p>请在上方「写作说明」或研究信息确认中补充以上内容，然后重新生成设计要素建议；
          已确认的内容会保留。</p>
      </div>;
    })()}
    {runId && state?.status === 'needs_structure_correction' && <p role="alert">
      设计建议的结构尚未核对通过，原建议与记录已保留。</p>}
    {availableCards.map(card => <CardSection key={card} card={card} proposal={proposal}
      confirmed={Boolean(confirmedCards[card])} busy={busy} onConfirm={() => confirmCard(card)}/>)}
    {error && <p role="alert">{error}</p>}
  </section>;
}
