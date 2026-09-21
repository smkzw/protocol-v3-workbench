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

const REGULATORY_CRITICAL = new Set(['objectives-endpoint', 'estimand', 'sample-size', 'non-inferiority-margin', 'interim']);
const DESIGN_CARD_IDS = ['objectives-endpoint', 'estimand', 'sample-size',
  'non-inferiority-margin', 'interim'];

function restoreJson(key, fallback = null) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

function readable(error) {
  const text = error?.detail?.message || error?.message;
  return typeof text === 'string' && /[\u3400-\u9fff]/u.test(text)
    ? text : '设计要素建议尚未核对清楚，已保存内容保留。';
}

function validIndex(value) {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function selectionIndex(record) {
  const value = record?.selections?.primary_objective;
  return validIndex(value) ? value : null;
}

function OptionList({ options, name, selectedIndex, onSelect, disabled = false }) {
  if (!Array.isArray(options) || !options.length) return null;
  const interactive = typeof onSelect === 'function';
  return <ul className="kz-design-options">
    {options.map((option, index) => <li key={index}>
      {interactive
        ? <label>
          <input type="radio" name={name} value={index}
            checked={selectedIndex === index} disabled={disabled}
            onChange={() => onSelect(index)} />
          <strong>{option.text}</strong>
        </label>
        : <strong>{option.text}</strong>}
      <span className="kz-design-basis">{option.basis === 'recommendation' ? 'AI建议' : option.basis === 'source' ? '资料依据' : '研究者输入'}</span>
      {option.reason && <p><strong>依据：</strong>{option.reason}</p>}
    </li>)}
  </ul>;
}

function CardSection({ card, proposal, confirmed, confirmedRecord, intent, notExecuted,
  cardMessage, busy, adoptable, canConfirm, onConfirm, onReconcile, onRetry }) {
  const critical = REGULATORY_CRITICAL.has(card);
  const historicalIndex = selectionIndex(confirmedRecord || intent);
  const conditional = card === 'non-inferiority-margin' || card === 'interim';
  const [selectedObjective, setSelectedObjective] = useState(
    historicalIndex ?? (confirmed || intent ? null : 0),
  );
  const [applicabilityConfirmed, setApplicabilityConfirmed] = useState(adoptable);
  useEffect(() => {
    setSelectedObjective(historicalIndex ?? (confirmed || intent ? null : 0));
  }, [confirmed, confirmedRecord?.operation_id, intent?.operation_id, historicalIndex]);
  useEffect(() => { if (adoptable) setApplicabilityConfirmed(true); }, [adoptable]);
  const objectiveList = proposal?.objectives?.primary;
  const applicabilityReady = adoptable || (conditional && applicabilityConfirmed);
  const locked = busy || !applicabilityReady || !canConfirm || Boolean(confirmed) || Boolean(intent);
  return <section className={`kz-design-card${critical ? ' kz-design-critical' : ''}`}
    aria-label={CARD_TITLES[card] || card}>
    <header>
      <h4>{CARD_TITLES[card] || card}</h4>
      {critical && <span className="kz-design-risk-tag" role="note">监管答辩级，需逐项确认</span>}
    </header>
    {cardMessage && <p role="alert">{cardMessage}</p>}
    {!adoptable && conditional && !confirmed && !intent && <label>
      <input type="checkbox" checked={applicabilityConfirmed}
        onChange={event => setApplicabilityConfirmed(event.target.checked)} />
      {card === 'non-inferiority-margin'
        ? '确认本研究采用非劣效设计，并同时核对本卡界值'
        : '确认本研究安排期中分析，并同时核对本卡方案'}
    </label>}
    {confirmed && <p role="status">已确认，内容保留在下方供核对。</p>}
    {card === 'objectives-endpoint' && selectionIndex(confirmedRecord) === null && confirmed &&
      <p role="status">已确认，但历史确认未记录所选主要研究目的；下方建议仅供核对。</p>}
    {card === 'objectives-endpoint' && !confirmed && intent && selectionIndex(intent) === null &&
      <p role="status">原确认意图未记录所选主要研究目的，系统不会替换原选择。</p>}
    <>
      {card === 'objectives-endpoint' && <>
        <h5>主要研究目的</h5>
        {objectiveList?.length > 1 && <p>请选择本次要确认的主要研究目的；默认预选第一项，点击确认后才会保存。</p>}
        <OptionList options={objectiveList} name={`design-primary-objective-${card}`}
          selectedIndex={selectedObjective} onSelect={setSelectedObjective} disabled={locked} />
        {selectionIndex(confirmedRecord) !== null && <p role="status">
          已确认主要研究目的：{objectiveList?.[selectionIndex(confirmedRecord)]?.text || '历史选择未能匹配当前建议。'}
        </p>}
        {selectionIndex(intent) !== null && <p role="status">
          原确认选择：{objectiveList?.[selectionIndex(intent)]?.text || '历史选择未能匹配当前建议。'}
        </p>}
        <h5>主要终点</h5>
        <OptionList options={[proposal?.endpoint?.primary_endpoint].filter(Boolean)} />
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
        <dl className="kz-design-facts">
          <dt>计划样本量</dt><dd>{proposal?.sample_size?.planned_n}</dd>
          <dt>显著性水平</dt><dd>{proposal?.sample_size?.alpha}</dd>
          <dt>把握度</dt><dd>{proposal?.sample_size?.power}</dd>
          <dt>统计模型</dt><dd>{proposal?.sample_size?.model}</dd>
          <dt>失访假设</dt><dd>{proposal?.sample_size?.attrition}</dd>
        </dl>
        <ul className="kz-design-assumptions">
          {(proposal?.sample_size?.assumptions || []).map((item, index) => <li key={index}>{item}</li>)}
        </ul>
        {proposal?.sample_size?.justification && <p><strong>计算依据：</strong>{proposal.sample_size.justification}</p>}
      </>}
      {card === 'non-inferiority-margin' && <>
        <h5>非劣效界值</h5>
        <dl className="kz-design-facts">
          <dt>界值</dt><dd>{proposal?.non_inferiority_margin?.margin}</dd>
          <dt>临床依据</dt><dd>{proposal?.non_inferiority_margin?.clinical_justification}</dd>
        </dl>
      </>}
      {card === 'interim' && <>
        <h5>期中分析</h5>
        <dl className="kz-design-facts">
          <dt>时间点</dt><dd>{proposal?.interim_planning?.timing}</dd>
          <dt>信息分数</dt><dd>{proposal?.interim_planning?.information_fraction}</dd>
          <dt>目的</dt><dd>{proposal?.interim_planning?.purpose}</dd>
          <dt>决策规则</dt><dd>{proposal?.interim_planning?.decision_rule}</dd>
          <dt>决策责任</dt><dd>{proposal?.interim_planning?.decision_responsibility}</dd>
          <dt>对最终分析的影响</dt><dd>{proposal?.interim_planning?.final_analysis_impact}</dd>
          {proposal?.interim_planning?.alpha_spending && <><dt>alpha 分配</dt><dd>{proposal.interim_planning.alpha_spending}</dd></>}
        </dl>
      </>}
      {!confirmed && !intent && <button type="button" className="kz-design-confirm"
        disabled={locked || (card === 'objectives-endpoint' && !validIndex(selectedObjective))}
        onClick={() => onConfirm(card === 'objectives-endpoint'
          ? { primary_objective: selectedObjective, primary_endpoint_confirmed: true }
          : card === 'non-inferiority-margin'
            ? { ni_margin_confirmed: true,
                noninferiority_applicable_confirmed: applicabilityConfirmed }
            : card === 'interim'
              ? { interim_confirmed: true,
                  interim_applicable_confirmed: applicabilityConfirmed }
              : undefined)}>确认本卡片内容</button>}
      {!confirmed && intent && notExecuted && <button type="button" className="kz-design-confirm"
        disabled={busy} onClick={onRetry}>配置恢复后继续保存原选择</button>}
      {!confirmed && intent && !notExecuted && <button type="button" className="kz-design-confirm"
        disabled={busy} onClick={onReconcile}>核对本次确认</button>}
      {!confirmed && intent && !notExecuted && <button type="button" className="kz-design-confirm"
        disabled={busy} onClick={onRetry}>使用原操作继续保存</button>}
    </>
  </section>;
}

export function DesignElementsCards({ projectId, seedRunId, studyDefinitionId, actorId, api }) {
  const storageKey = 'protocol-v3:design-elements:' + JSON.stringify([projectId, studyDefinitionId, seedRunId]);
  const [runId, setRunId] = useState(() => restoreJson(storageKey));
  const [state, setState] = useState(null);
  const [confirmedCards, setConfirmedCards] = useState(() => {
    const value = restoreJson(storageKey + ':confirmed', {});
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  });
  const [cardIntents, setCardIntents] = useState(() => Object.fromEntries(
    DESIGN_CARD_IDS.map(card => [card, restoreJson(`${storageKey}:intent:${card}`)])
      .filter(([, value]) => value),
  ));
  const [notExecuted, setNotExecuted] = useState(() => Object.fromEntries(
    DESIGN_CARD_IDS.map(card => {
      const intent = restoreJson(`${storageKey}:intent:${card}`);
      return [card, Boolean(intent && restoreJson(`${storageKey}:not-executed:${card}`) === intent.operation_id)];
    }).filter(([, value]) => value),
  ));
  const [cardMessages, setCardMessages] = useState({});
  const [reconcilingCards, setReconcilingCards] = useState({});
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const flight = useRef(false), alive = useRef(true), request = useRef(null);
  const apiRef = useRef(api); apiRef.current = api;

  function setCardMessage(card, message) {
    setCardMessages(previous => ({ ...previous, [card]: message }));
  }

  function saveIntent(card, intent) {
    localStorage.setItem(`${storageKey}:attempt:${intent.operation_id}`, JSON.stringify(intent));
    localStorage.setItem(`${storageKey}:intent:${card}`, JSON.stringify(intent));
    localStorage.removeItem(`${storageKey}:not-executed:${card}`);
    setCardIntents(previous => ({ ...previous, [card]: intent }));
    setNotExecuted(previous => {
      const next = { ...previous };
      delete next[card];
      return next;
    });
  }

  function clearIntent(card) {
    try {
      localStorage.removeItem(`${storageKey}:intent:${card}`);
      localStorage.removeItem(`${storageKey}:not-executed:${card}`);
    } catch {
      // The attempt record remains the durable local evidence.
    }
    setCardIntents(previous => {
      const next = { ...previous };
      delete next[card];
      return next;
    });
    setNotExecuted(previous => {
      const next = { ...previous };
      delete next[card];
      return next;
    });
  }

  function markNotExecuted(card, intent) {
    try {
      localStorage.setItem(`${storageKey}:not-executed:${card}`, JSON.stringify(intent.operation_id));
    } catch {
      // Keep the known terminal status for this mounted session.
    }
    setNotExecuted(previous => ({ ...previous, [card]: true }));
  }

  function acceptReceipt(card, receipt, intent) {
    if (receipt?.project_id !== projectId
      || receipt.study_definition_id !== studyDefinitionId
      || receipt.definition?.project_id !== projectId
      || receipt.definition.study_definition_id !== studyDefinitionId
      || !receipt.effective_decision?.decision_record_id
      || !receipt.revision_sha256
      || !Number.isInteger(receipt.revision)
      || receipt.definition.revision !== receipt.revision
      || receipt.revision < Number(intent.expected_revision) + 1) {
      throw new Error('本次确认回执尚未核对清楚，原选择已保留。');
    }
    // A current client knows the exact option it sent even when an older
    // compatible server receipt does not yet echo selection_status. Preserve
    // that bound choice; only historical receipts restored without an intent
    // remain legacy_unknown.
    const echoedSelections = receipt.selection_status === 'verified' ? receipt.selections : null;
    const receiptSelections = echoedSelections
      || (intent?.selections && typeof intent.selections === 'object' ? intent.selections : null);
    const confirmed = {
      operation_id: intent.operation_id,
      revision: receipt.revision,
      revision_sha256: receipt.revision_sha256,
      selection_status: receipt.selection_status || (receiptSelections ? 'client_bound' : 'legacy_unknown'),
      selections: receiptSelections && typeof receiptSelections === 'object' ? receiptSelections : null,
    };
    setConfirmedCards(previous => {
      const next = { ...previous, [card]: confirmed };
      try { localStorage.setItem(storageKey + ':confirmed', JSON.stringify(next)); } catch { /* state remains visible */ }
      return next;
    });
    clearIntent(card);
    setCardMessage(card, '');
    if (Number.isInteger(receipt.revision)) {
      setState(previous => {
        const currentRevision = Number(previous?.expected_revision) || 0;
        if (receipt.revision < currentRevision) return previous;
        return { ...(previous || {}), expected_revision: receipt.revision,
          snapshot_sha256: receipt.revision_sha256 || previous?.snapshot_sha256 };
      });
    }
  }

  function handleApplyFailure(card, intent, reason) {
    if (reason?.status === 424) {
      markNotExecuted(card, intent);
      setCardMessage(card, readable(reason));
    } else if ([400, 404, 409, 422].includes(reason?.status)) {
      // The server explicitly rejected the apply. The original attempt is
      // retained, but the active pointer is cleared so a new choice requires
      // another deliberate click.
      clearIntent(card);
      setCardMessage(card, readable(reason));
    } else {
      // Network/500 outcomes remain attached to the exact operation id.
      setCardMessage(card, readable(reason));
    }
  }

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
  }, [runId, projectId, studyDefinitionId]);

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

  async function confirmCard(card, selections) {
    if (flight.current || !actorId || !runId || confirmedCards[card] || cardIntents[card]) return;
    const operationId = 'design-card:' + crypto.randomUUID();
    const intent = { study_definition_id: studyDefinitionId, operation_id: operationId,
      card,
      expected_revision: state?.expected_revision ?? 0,
      snapshot_sha256: state?.snapshot_sha256 ?? '',
      actor_id: actorId, decided_at: new Date().toISOString(),
      reason: `确认设计要素：${CARD_TITLES[card] || card}`,
      seed_run_id: seedRunId,
      selections: selections || (card === 'sample-size'
        ? { sample_size_confirmed: true }
        : { treatment: true, population: true, variable: true,
            ice_strategy: true, summary_measure: true }) };
    try {
      saveIntent(card, intent);
    } catch {
      setCardMessage(card, '浏览器无法保存本次确认意图，请恢复存储后再试。');
      return;
    }
    flight.current = true; setBusy(true); setError(''); setCardMessage(card, '');
    const controller = new AbortController(); request.current = controller;
    try {
      let receipt;
      try {
        receipt = await apiRef.current.recoverDesignCard(projectId, runId, card, intent,
          { signal: controller.signal });
      } catch (reason) {
        if (reason?.status !== 404) throw reason;
      }
      if (!controller.signal.aborted && !receipt) {
        receipt = await apiRef.current.adoptDesignCard(projectId, runId, card, intent,
          { signal: controller.signal });
      }
      if (!controller.signal.aborted && receipt) acceptReceipt(card, receipt, intent);
    } catch (reason) {
      if (!controller.signal.aborted) handleApplyFailure(card, intent, reason);
    } finally {
      flight.current = false; if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function reconcileCard(card) {
    const intent = cardIntents[card];
    if (flight.current || !intent || notExecuted[card] || confirmedCards[card] || !runId) return;
    flight.current = true; setBusy(true); setCardMessage(card, '正在核对本次确认。');
    const controller = new AbortController(); request.current = controller;
    try {
      const receipt = await apiRef.current.recoverDesignCard(projectId, runId, card, intent,
        { signal: controller.signal });
      if (!controller.signal.aborted && receipt) acceptReceipt(card, receipt, intent);
    } catch (reason) {
      if (!controller.signal.aborted) {
        if (reason?.status === 404) {
          setCardMessage(card, '尚未查到本次确认的保存回执，原选择已保留；请稍后再次核对。');
        } else handleApplyFailure(card, intent, reason);
      }
    } finally {
      flight.current = false; if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function retryCard(card) {
    const intent = cardIntents[card];
    if (flight.current || !intent || confirmedCards[card] || !runId) return;
    flight.current = true; setBusy(true); setCardMessage(card, '');
    const controller = new AbortController(); request.current = controller;
    try {
      const receipt = await apiRef.current.adoptDesignCard(projectId, runId, card, intent,
        { signal: controller.signal });
      if (!controller.signal.aborted && receipt) acceptReceipt(card, receipt, intent);
    } catch (reason) {
      if (!controller.signal.aborted) handleApplyFailure(card, intent, reason);
    } finally {
      flight.current = false; if (!controller.signal.aborted) setBusy(false);
    }
  }

  const proposal = state?.validation?.proposal;
  const availableCards = state?.status === 'ready_for_review' && proposal
    ? ['objectives-endpoint', 'estimand', 'sample-size',
       ...(proposal.non_inferiority_margin ? ['non-inferiority-margin'] : []),
       ...(proposal.interim_planning ? ['interim'] : [])]
    : [];
  const adoptableCards = new Set(state?.adoptable_cards || ['objectives-endpoint', 'estimand', 'sample-size']);
  const availableCardKey = availableCards.join('|');

  useEffect(() => {
    if (!runId || !availableCardKey) return undefined;
    const pending = availableCards.filter(card => cardIntents[card]
      && !confirmedCards[card] && !notExecuted[card]);
    if (!pending.length) return undefined;
    const controller = new AbortController();
    setReconcilingCards(previous => Object.fromEntries(
      [...Object.entries(previous), ...pending.map(card => [card, true])],
    ));
    async function recoverPending() {
      for (const card of pending) {
        if (controller.signal.aborted || !alive.current) return;
        const intent = cardIntents[card];
        try {
          const receipt = await apiRef.current.recoverDesignCard(projectId, runId, card, intent,
            { signal: controller.signal });
          if (!controller.signal.aborted && receipt) acceptReceipt(card, receipt, intent);
        } catch (reason) {
          if (controller.signal.aborted || !alive.current) return;
          if (reason?.status === 404) {
            setCardMessage(card, '尚未查到本次确认的保存回执，原选择已保留；请核对本次确认。');
          } else handleApplyFailure(card, intent, reason);
        } finally {
          if (alive.current) setReconcilingCards(previous => {
            const next = { ...previous };
            delete next[card];
            return next;
          });
        }
      }
    }
    recoverPending();
    return () => {
      controller.abort();
      setReconcilingCards(previous => {
        const next = { ...previous };
        pending.forEach(card => delete next[card]);
        return next;
      });
    };
  }, [runId, projectId, studyDefinitionId, availableCardKey]);

  return <section className="kz-protocol kz-design-elements" aria-label="研究设计要素建议">
    <header><p className="kz-design-eyebrow">研究设计</p><h3>确认研究设计要素</h3>
      <ul className="kz-design-guide">
        <li>推荐项已预选，确认前可以调整。</li>
        <li>红色标记的关键设计需要逐卡确认。</li>
        <li>非关键缺口可在初稿生成后补充。</li>
      </ul></header>
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
    {runId && !actorId && <p role="alert">当前用户身份尚未就绪，建议和已保存内容可查看，暂不能确认。</p>}
    {availableCards.map(card => <CardSection key={card} card={card} proposal={proposal}
      confirmed={Boolean(confirmedCards[card])} confirmedRecord={confirmedCards[card]}
      intent={cardIntents[card]} notExecuted={Boolean(notExecuted[card])}
      cardMessage={cardMessages[card]} busy={busy || Boolean(reconcilingCards[card])}
      adoptable={adoptableCards.has(card)} canConfirm={Boolean(actorId)}
      onConfirm={selections => confirmCard(card, selections)}
      onReconcile={() => reconcileCard(card)} onRetry={() => retryCard(card)} />)}
    {error && <p role="alert">{error}</p>}
  </section>;
}
