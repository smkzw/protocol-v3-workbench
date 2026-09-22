import { useEffect, useRef, useState } from 'react';
import { ChapterDraftPreview } from './ChapterDraftPreview';
import { GenOfficeFrame } from './office/GenOfficeFrame';
import './kangzheProtocol.css';
import './ManuscriptWorkspace.css';

const SOURCE_ROLE_LABELS = {
  confirmed_project_facts: '本项目已确认研究事实',
  company_sop_or_protocol_reference: '公司SOP与方案参考',
  shared_reference_only: '共享参考资料',
  project_source: '本项目资料',
};

function savedValue(key) {
  try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; }
}
function readableError(error) {
  const message = error?.detail?.message || error?.message;
  return typeof message === 'string' && /[\u3400-\u9fff]/u.test(message)
    ? message : '本次写作结果尚未核对清楚，原资料和操作记录已保留。';
}

// One-line readable preview of a residual recommendation value, so the user
// can see every item's actual content before committing it (R-C05).
// 组织信息确认列表的字段中文名（T17 第六轮 P1-2：内部键名不直出）。
// 未映射键回落为"相关内容"，绝不把英文键名暴露给用户。
const RESIDUAL_KEY_LABELS = {
  role: '角色', name_note: '姓名说明', note: '说明', policy: '安排',
  contact: '联系人', channels: '招募渠道', measures: '招募方式',
  reference: '参照', software: '软件', path: '报告路径',
  composition: '组成', flow: '信息流向', arrangement: '审阅安排',
  roles: '职责分工', reserved_for_signing: '签署时填写', summary: '摘要',
  parameters: '判定参数', logic: '判定规则',
};
function residualKeyLabel(key) {
  return RESIDUAL_KEY_LABELS[key] || '相关内容';
}
function summarizeResidualValue(value) {
  if (value === true) return '适用';
  if (value === false) return '不适用';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(item => summarizeResidualValue(item)).join('；');
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .filter(([, item]) => item !== null && item !== undefined && item !== '')
      .map(([key, item]) => `${residualKeyLabel(key)}：${summarizeResidualValue(item)}`)
      .join('；');
  }
  return '（空）';
}

// One normalization at the client boundary (B08): server receipts name the
// document hash differently per endpoint; every consumer reads the single
// normalized field, and an absent hash blocks the commit instead of racing on.
function normalizeSavedDocument(value) {
  if (!value) return value;
  const hash = value.document_sha256 ?? value.revision_sha256
    ?? value.document_revision_hash ?? value.documentSha256;
  if (!hash) throw new Error('保存回执缺少文档哈希，系统已拦截本次提交以保护已保存内容。');
  return { ...value, document_sha256: hash,
    revision: value.revision ?? value.document?.revision };
}

function savedChapter(document, nodeId) {
  const blocks = document?.semantic_blocks?.filter(block => block.semantic_node_id === nodeId);
  if (!blocks?.length) return null;
  return { blocks: blocks.map(block => {
    if (block.block_kind === 'paragraph') return { block_id: block.semantic_block_id, kind: 'paragraph', text: block.content };
    if (block.block_kind === 'table') {
      try {
        const value = JSON.parse(block.content);
        if (value.schema_version === 'semantic-structured-table.v1' && value.table) {
          return { block_id: block.semantic_block_id, kind: 'table', table: value.table };
        }
      } catch { /* Keep malformed stored content visible as a diagnostic, never as JSON prose. */ }
    }
    return { block_id: block.semantic_block_id, kind: 'unreadable' };
  }) };
}

function historyEntries(key) {
  const entries = [];
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const item = localStorage.key(i);
      if (item && item.startsWith(key + ':history:')) {
        try { entries.push(JSON.parse(localStorage.getItem(item))); } catch { /* keep unreadable history untouched */ }
      }
    }
  } catch { /* storage unavailable: history simply not listed */ }
  return entries.filter(Boolean);
}

function HistoryVersions({ storageKey, onRestore, busy }) {
  const [open, setOpen] = useState(false);
  // Existence is computed eagerly: gating the button on an `open`-gated list
  // hid the only entry point forever (B06).
  const entries = historyEntries(storageKey);
  return <div>
    {entries.length > 0 && <button type="button" disabled={busy} aria-expanded={open}
      onClick={() => setOpen(value => !value)}>查看历史写作记录（{entries.length}）</button>}
    {open && <ul>
      {entries.map((entry, index) => <li key={index}>
        <button type="button" disabled={busy} onClick={() => onRestore(entry)}>
          {entry.phase === 'draft' ? `初稿（${entry.intent?.expected_workflow_run_id?.slice(0, 24) || '记录'}…）`
            : `资料准备（${entry.sourceRunId?.slice(0, 24) || '记录'}…）`}</button>
      </li>)}
      <li><small>历史记录一直保留；当前页面只显示其中一份，不会自动删除。</small></li>
    </ul>}
  </div>;
}

function ManuscriptSession({ projectId, studyDefinitionId, seedRunId, actorId, api, onNavigationGuardChange }) {
  const key = 'protocol-v3:manuscript:' + JSON.stringify([projectId, studyDefinitionId, seedRunId]);
  const [packet, setPacket] = useState(() => savedValue(key));
  const [plan, setPlan] = useState(null), [job, setJob] = useState(null);
  const [selected, setSelected] = useState(null), [error, setError] = useState('');
  const [savedDocument, setSavedDocument] = useState(null);
  const [officeOpen, setOfficeOpen] = useState(false);
  const [sourceState, setSourceState] = useState(null);
  const [planRefresh, setPlanRefresh] = useState(0);
  const [busy, setBusy] = useState(false), [refresh, setRefresh] = useState(0);
  const [factsBusy, setFactsBusy] = useState(false);
  const [derivedCandidate, setDerivedCandidate] = useState(null);
  const [residual, setResidual] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [showAllResidual, setShowAllResidual] = useState(false);
  const apiRef = useRef(api); apiRef.current = api;
  const request = useRef(null), flight = useRef(false);
  // R2 admission: critical design confirmed and no applicability contradiction
  // generate the draft; non-key gaps ride along as explicit gap objects.
  const canGenerate = readiness
    ? Boolean(readiness.can_generate_working_draft)
    : Boolean(plan?.all_applicable_inputs_ready);

  useEffect(() => {
    // Versioned readiness (draft-readiness.v1): admission plus gap map. An
    // older api surface degrades to the plan's all-ready flag above.
    if (!apiRef.current?.getDraftReadiness) return undefined;
    const controller = new AbortController();
    Promise.resolve().then(() => apiRef.current.getDraftReadiness(projectId, studyDefinitionId, { signal: controller.signal }))
      .then(value => { if (!controller.signal.aborted) setReadiness(value); })
      .catch(() => {});
    return () => controller.abort();
  }, [projectId, studyDefinitionId, refresh, planRefresh]);

  useEffect(() => {
    // Residual organization facts are optional one-click enrichment once the
    // critical design is confirmed; they never gate generation (R2/R-C05).
    if (!apiRef.current?.getChapterFactsResidual) return undefined;
    if (readiness && !readiness.critical_design_confirmed) return undefined;
    if (factsBusy) return undefined;
    const controller = new AbortController();
    Promise.resolve().then(() => apiRef.current.getChapterFactsResidual(projectId, studyDefinitionId, { signal: controller.signal }))
      .then(value => { if (!controller.signal.aborted) setResidual(value?.residual || null); })
      .catch(() => {});
    return () => controller.abort();
  }, [projectId, studyDefinitionId, readiness, factsBusy, refresh]);

  useEffect(() => {
    if (!apiRef.current?.getChapterFactsStatus || factsBusy) return undefined;
    const controller = new AbortController();
    Promise.resolve().then(() => apiRef.current.getChapterFactsStatus(projectId, studyDefinitionId, { signal: controller.signal }))
      .then(value => {
        if (!controller.signal.aborted && !value?.progress?.running) {
          setDerivedCandidate(value?.progress?.candidate || null);
        }
      }).catch(() => {});
    return () => controller.abort();
  }, [projectId, studyDefinitionId, factsBusy, refresh]);

  async function confirmResidual() {
    if (factsBusy || !residual || !actorId) return;
    setFactsBusy(true); setError('');
    try {
      const paths = Object.keys(residual);
      await apiRef.current.confirmChapterFactsResidual(projectId, studyDefinitionId, {
        operation_id: 'chapter-facts-residual:' + crypto.randomUUID(),
        actor_id: actorId,
        expected_revision: plan?.expected_revision ?? 0,
        snapshot_sha256: plan?.snapshot_sha256 ?? '',
        decided_at: new Date().toISOString(),
        accepted_fact_paths: paths,
      });
      const next = await apiRef.current.getManuscriptPlan(projectId, studyDefinitionId);
      if (next?.plan || next?.chapters) setPlan(next?.plan || next);
      setResidual(null);
      setRefresh(v => v + 1);
    } catch (reason) { setError(readableError(reason)); }
    finally { setFactsBusy(false); }
  }

  async function deriveFacts() {
    if (factsBusy) return;
    setFactsBusy(true); setError('');
    try {
      const client = apiRef.current;
      await client.deriveChapterFacts(projectId, studyDefinitionId);
      // The derivation runs in background batches; keep the plan view live
      // until every applicable chapter is ready or the run stops progressing.
      for (let round = 0; round < 120; round++) {
        await new Promise(resolve => setTimeout(resolve, round < 4 ? 4000 : 15000));
        const next = await client.getManuscriptPlan(projectId, studyDefinitionId);
        if (!next?.plan && !next?.chapters) break;
        setPlan(next?.plan || next);
        if ((next?.plan || next)?.all_applicable_inputs_ready) break;
        const status = await client.getChapterFactsStatus(projectId, studyDefinitionId)
          .catch(() => null);
        if (status?.progress && !status.progress.running) {
          setDerivedCandidate(status.progress.candidate || null);
          break;
        }
      }
    } catch (reason) { setError(readableError(reason)); }
    finally { setFactsBusy(false); }
  }

  async function confirmDerivedFacts() {
    const candidate = derivedCandidate;
    const paths = Object.keys(candidate?.updates || {});
    if (factsBusy || !candidate || !paths.length || !actorId) return;
    setFactsBusy(true); setError('');
    try {
      await apiRef.current.confirmDerivedChapterFacts(projectId, studyDefinitionId, {
        operation_id: 'chapter-facts-derived-confirm:' + crypto.randomUUID(),
        candidate_id: candidate.candidate_id,
        actor_id: actorId,
        expected_revision: candidate.expected_revision,
        snapshot_sha256: candidate.snapshot_sha256,
        decided_at: new Date().toISOString(),
        accepted_fact_paths: paths,
      });
      const next = await apiRef.current.getManuscriptPlan(projectId, studyDefinitionId);
      if (next?.plan || next?.chapters) setPlan(next?.plan || next);
      setDerivedCandidate(null);
      setRefresh(v => v + 1);
    } catch (reason) { setError(readableError(reason)); }
    finally { setFactsBusy(false); }
  }

  function remember(next) {
    try {
    // Three stored views, each with a distinct recovery consumer; none is a
    // redundant duplicate to purge: the active pointer (key), per-operation
    // save receipts (key:save:op) and per-run drafts (key:runId). History
    // entries are archived before the pointer advances and are listed in the
    // UI; deletion is never automatic (data-loss boundary).
    if (packet) localStorage.setItem(key + ':history:' + JSON.stringify([
      packet.studySha, packet.intent?.expected_workflow_run_id || packet.sourceRunId,
      packet.saveIntent?.operation_id || packet.retryDecisionId || 'original']), JSON.stringify(packet));
    if (next.saveIntent) localStorage.setItem(key + ':save:' + next.saveIntent.operation_id, JSON.stringify(next));
    localStorage.setItem(key, JSON.stringify(next));
    if (next.intent) localStorage.setItem(key + ':' + next.intent.expected_workflow_run_id, JSON.stringify(next));
    setPacket(next);
    } catch { throw new Error('暂存操作记录失败，已有内容仍保留。请保留当前页面并核对保存状态。'); }
  }

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    // An api surface without the manuscript methods (narrower embeds, older
    // mocks) degrades to "drafting unavailable" instead of crashing the tree.
    if (!apiRef.current?.getManuscriptPlan) { setPlan({ all_applicable_inputs_ready: false, chapters: [] }); return undefined; }
    const controller = new AbortController();
    Promise.resolve().then(() => apiRef.current.getManuscriptPlan(projectId, studyDefinitionId, { signal: controller.signal }))
      .then(value => { if (!controller.signal.aborted) setPlan(value?.plan || value); })
      .catch(reason => { if (!controller.signal.aborted) setError(readableError(reason)); });
    return () => controller.abort();
  }, [projectId, studyDefinitionId, refresh, planRefresh]);

  async function finishSources(original, controller) {
    const client = apiRef.current;
    const prepared = await client.prepareManuscriptDraft(projectId, studyDefinitionId, {
      source_run_id: original.sourceRunId, study_revision_sha256: original.studySha,
    }, { signal: controller.signal });
    if (controller.signal.aborted) return;
    if (!prepared?.expected_workflow_run_id) throw new Error('整稿写作内容尚未准备完整。');
    const next = { ...original, phase: 'draft', intent: {
      source_run_id: original.sourceRunId, study_revision_sha256: original.studySha,
      expected_workflow_run_id: prepared.expected_workflow_run_id,
    }};
    remember(next);
    const state = await client.startManuscriptDraft(projectId, studyDefinitionId, next.intent, { signal: controller.signal });
    if (!controller.signal.aborted) { setJob(state); setRefresh(value => value + 1); }
  }

  useEffect(() => {
    if (!packet) return undefined;
    const controller = new AbortController();
    let timer, delay = 1000;
    async function read() {
      try {
        if (packet.phase === 'sources') {
          const source = await apiRef.current.getManuscriptSources(projectId, packet.sourceRunId, { signal: controller.signal });
          if (controller.signal.aborted) return;
          if (source.workflow_run_id !== packet.sourceRunId) throw new Error('资料准备记录尚未核对完整。');
          setSourceState(source); setError('');
          if (source.status === 'completed') {
            if (!flight.current) {
              flight.current = true; setBusy(true);
              const dispatch = new AbortController(); request.current = dispatch;
              try { await finishSources(packet, dispatch); }
              catch (reason) {
                if (!dispatch.signal.aborted) {
                  setError(readableError(reason));
                  // Refresh facts only; restarting the source effect here loops on the same stale request.
                  if (reason?.status === 409) setPlanRefresh(value => value + 1);
                }
              }
              finally { flight.current = false; if (!dispatch.signal.aborted) setBusy(false); }
            }
            return;
          }
          if (source.status !== 'running') throw new Error('资料准备需要核对，已有资料和写作记录已保留。');
        } else {
          const state = await apiRef.current.recoverManuscriptDraft(projectId, studyDefinitionId, packet.intent, { signal: controller.signal });
          if (controller.signal.aborted) return;
          if (state.workflow_run_id !== packet.intent.expected_workflow_run_id) throw new Error('本次写作记录尚未核对完整。');
          setJob(state); setError('');
          // Partial blockage can coexist with siblings that are progressing.
          // Keep observing the original run; reads never dispatch a retry.
          if (state.status !== 'running' && !state.can_resume) return;
        }
        timer = setTimeout(read, delay); delay = Math.min(delay * 2, 30000);
      } catch (reason) { if (!controller.signal.aborted) setError(readableError(reason)); }
    }
    read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [packet, projectId, studyDefinitionId, refresh]);

  async function loadSavedDocument(intent, controller) {
    const receipt = await apiRef.current.recoverManuscriptSave(projectId, studyDefinitionId, intent, { signal: controller.signal });
    if (controller.signal.aborted) return;
    // A recovered receipt proves the old save, not the current editable revision.
    const current = await apiRef.current.getSemanticDocument(projectId, studyDefinitionId,
      receipt.document.semantic_document_revision_id, { signal: controller.signal });
    if (!controller.signal.aborted) setSavedDocument(normalizeSavedDocument(current));
  }

  useEffect(() => {
    if (!packet?.saveIntent && !packet?.savedDocumentId) return undefined;
    const controller = new AbortController();
    const loading = packet.savedDocumentId
      ? apiRef.current.getSemanticDocument(projectId, studyDefinitionId, packet.savedDocumentId, { signal: controller.signal })
        .then(current => { if (!controller.signal.aborted) setSavedDocument(normalizeSavedDocument(current)); })
      : loadSavedDocument(packet.saveIntent, controller);
    loading.catch(reason => {
      if (!controller.signal.aborted && reason?.status !== 404) setError(readableError(reason));
    });
    return () => controller.abort();
  }, [packet?.saveIntent, packet?.savedDocumentId, projectId, studyDefinitionId, refresh]);

  async function saveCompleteDraft() {
    if (flight.current || !packet?.intent || !actorId) return;
    flight.current = true; setBusy(true); setError('');
    const controller = new AbortController(); request.current = controller;
    let intent = packet.saveIntent;
    try {
      if (!intent) {
        const current = await apiRef.current.prepareManuscriptSave(projectId, studyDefinitionId,
          packet.intent, { signal: controller.signal });
        if (controller.signal.aborted) return;
        intent = { ...packet.intent, operation_id: 'manuscript-save:' + crypto.randomUUID(),
          actor_id: actorId, expected_revision: current.expected_revision,
          expected_document_sha256: current.expected_document_sha256 };
        remember({ ...packet, saveIntent: intent });
      }
      let receipt;
      try { receipt = await apiRef.current.recoverManuscriptSave(projectId, studyDefinitionId, intent, { signal: controller.signal }); }
      catch (reason) { if (reason?.status !== 404) throw reason; }
      if (controller.signal.aborted) return;
      if (!receipt) await apiRef.current.saveManuscriptDraft(projectId, studyDefinitionId, intent, { signal: controller.signal });
      await loadSavedDocument(intent, controller);
      if (!controller.signal.aborted) remember({ ...packet, saveIntent: intent, savedDocumentId: null, saveConflict: false });
    } catch (reason) {
      if (!controller.signal.aborted) {
        if (reason?.status === 409 && reason?.recoveryKind === 'document_revision_changed') {
          try {
            const latest = await apiRef.current.prepareManuscriptSave(projectId, studyDefinitionId, packet.intent, { signal: controller.signal });
            const current = await apiRef.current.getSemanticDocument(projectId, studyDefinitionId,
              latest.semantic_document_revision_id, { signal: controller.signal });
            if (!controller.signal.aborted) {
              // Do not silently mint another operation and overwrite a competing save.
              localStorage.setItem(key + ':save:' + intent.operation_id, JSON.stringify({ ...packet, saveIntent: intent }));
              remember({ ...packet, saveIntent: null, savedDocumentId: latest.semantic_document_revision_id, saveConflict: true });
              setSavedDocument(normalizeSavedDocument(current));
              setError('已读取更新的文档，本次初稿没有覆盖它。需要保留本次初稿时，可另存为新版本。');
            }
          } catch (recoveryError) { if (!controller.signal.aborted) setError(readableError(recoveryError)); }
        } else setError(readableError(reason));
      }
    }
    finally { flight.current = false; if (!controller.signal.aborted) setBusy(false); }
  }

  async function begin(newVersion = false) {
    if (flight.current || officeOpen || (packet && newVersion !== true)) return;
    flight.current = true; setBusy(true); setError('');
    const controller = new AbortController(); request.current = controller;
    try {
      const client = apiRef.current;
      const current = await client.getStudyDefinition(projectId, studyDefinitionId, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const studySha = current.revision_sha256;
      if (!studySha) throw new Error('当前研究信息尚未读取完整。');
      const prepared = await client.prepareManuscriptSourceIdentity(projectId, studyDefinitionId, seedRunId, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!prepared.expected_workflow_run_id) throw new Error('写作资料尚未准备完整。');
      const next = { phase: 'sources', sourceRunId: prepared.expected_workflow_run_id, studySha };
      remember(next); setJob(null); setSavedDocument(null); setSourceState(null);
      await client.prepareManuscriptSources(projectId, studyDefinitionId, seedRunId, {
        signal: controller.signal, expectedWorkflowRunId: next.sourceRunId,
      });
      if (!controller.signal.aborted) setRefresh(value => value + 1);
    } catch (reason) { if (!controller.signal.aborted) setError(readableError(reason)); }
    finally { flight.current = false; if (!controller.signal.aborted) setBusy(false); }
  }

  async function resume() {
    if (flight.current || !packet) return;
    flight.current = true; setBusy(true); setError('');
    const controller = new AbortController(); request.current = controller;
    try {
      if (packet.phase === 'draft') {
        let state;
        try { state = await apiRef.current.recoverManuscriptDraft(projectId, studyDefinitionId, packet.intent, { signal: controller.signal }); }
        catch (reason) { if (reason?.status !== 404) throw reason; }
        if (!state) await apiRef.current.startManuscriptDraft(projectId, studyDefinitionId, packet.intent, { signal: controller.signal });
        else if (state.can_resume) await apiRef.current.resumeManuscriptDraft(projectId, studyDefinitionId, packet.intent, { signal: controller.signal });
      } else {
        let state;
        try { state = await apiRef.current.getManuscriptSources(projectId, packet.sourceRunId, { signal: controller.signal }); }
        catch (reason) { if (reason?.status !== 404) throw reason; }
        if (!state) await apiRef.current.prepareManuscriptSources(projectId, studyDefinitionId, seedRunId, {
          signal: controller.signal, expectedWorkflowRunId: packet.sourceRunId,
        });
        else if (state.can_resume) await apiRef.current.resumeManuscriptSources(projectId, packet.sourceRunId, { signal: controller.signal });
      }
      if (!controller.signal.aborted) setRefresh(value => value + 1);
    } catch (reason) { if (!controller.signal.aborted) setError(readableError(reason)); }
    finally { flight.current = false; if (!controller.signal.aborted) setBusy(false); }
  }

  async function retrySources() {
    if (flight.current || packet?.phase !== 'sources') return;
    flight.current = true; setBusy(true); setError('');
    const controller = new AbortController(); request.current = controller;
    try {
      const state = await apiRef.current.getManuscriptSources(projectId, packet.sourceRunId, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (state.workflow_run_id !== packet.sourceRunId) throw new Error('原资料准备记录尚未核对清楚。');
      if (state.can_retry) {
        const retryDecisionId = packet.retryDecisionId || 'manuscript-source-retry:' + crypto.randomUUID();
        remember({ ...packet, retryDecisionId });
        await apiRef.current.retryManuscriptSources(projectId, packet.sourceRunId, retryDecisionId, { signal: controller.signal });
      } else if (state.can_resume) {
        await apiRef.current.resumeManuscriptSources(projectId, packet.sourceRunId, { signal: controller.signal });
      }
      if (!controller.signal.aborted) setRefresh(value => value + 1);
    } catch (reason) { if (!controller.signal.aborted) setError(readableError(reason)); }
    finally { flight.current = false; if (!controller.signal.aborted) setBusy(false); }
  }

  const chapters = job?.chapters || [];
  const readable = chapters.filter(chapter => chapter.validation?.valid && chapter.validation?.proposal);
  const current = readable.find(chapter => chapter.node_id === selected) || readable[0];
  const persistedChapter = current && savedChapter(savedDocument?.document, current.node_id);

  return <section className="kz-protocol kz-manuscript" aria-label="完整方案初稿">
    <header><h2>研究方案</h2></header>
    {!packet && <>
      <button className="kz-manuscript-primary" type="button" onClick={() => begin()}
        disabled={busy || !canGenerate}>生成完整初稿</button>
      {readiness && !readiness.can_generate_working_draft && <>
        {!readiness.critical_design_confirmed
          ? <p>关键研究设计确认后即可生成初稿，已有确认会保留。</p>
          : <p role="alert">部分章节与已确认设计存在矛盾（{(readiness.blocking_design_conflicts || []).map(item => item.title).join('、')}）。处理后即可生成；缺口与未决章节不会阻止其余内容。</p>}
      </>}
      {readiness?.can_generate_working_draft && (() => {
        const counts = { write: 0, write_with_gaps: 0, pending_decision: 0, not_applicable: 0 };
        for (const item of readiness.chapter_dispositions || []) counts[item.disposition] = (counts[item.disposition] || 0) + 1;
        return <ul className="kz-manuscript-summary">
          <li><strong>可起草：</strong>{counts.write} 章资料齐备，{counts.write_with_gaps} 章带缺口起草。</li>
          <li><strong>章节范围：</strong>{counts.pending_decision} 章待判定，{counts.not_applicable} 章不适用。</li>
        </ul>;
      })()}
      {apiRef.current?.deriveChapterFacts && readiness?.critical_design_confirmed
        && !derivedCandidate && (readiness.chapter_dispositions || []).some(item => item.disposition === 'write_with_gaps') && <>
        <button type="button" disabled={factsBusy} onClick={deriveFacts}>
          {factsBusy ? '正在按已确认设计补齐章节事实…' : '先按已确认设计补齐章节事实，减少缺口（可选）'}</button>
        <ul><li>补充内容作为建议，确认后采用。</li><li>也可先起草，再补正文标出的缺口。</li></ul>
      </>}
      {derivedCandidate && Object.keys(derivedCandidate.updates || {}).length > 0 && <div
        className="kz-manuscript-residual" role="group" aria-label="章节事实建议确认">
        <p>系统根据已确认的研究设计整理了 {Object.keys(derivedCandidate.updates).length} 项章节建议：</p>
        <ul>
          {(derivedCandidate.items || []).slice(0, 8).map((item, index) => (
            <li key={`${item.title}-${index}`}><strong>{item.title}：</strong>
              {(item.values || []).map(summarizeResidualValue).join('；')}</li>
          ))}
          {(derivedCandidate.items || []).length > 8 && <li>其余 {(derivedCandidate.items || []).length - 8} 个章节的建议将在确认后用于相应正文，仍可继续修改。</li>}
        </ul>
        <button type="button" disabled={factsBusy || !actorId} onClick={confirmDerivedFacts}>
          确认并采用以上章节建议</button>
        <button type="button" disabled={factsBusy} onClick={() => setDerivedCandidate(null)}>暂不采用</button>
      </div>}
      {readiness?.critical_design_confirmed && residual && Object.keys(residual).length > 0 && <>
        <div className="kz-manuscript-residual" role="group" aria-label="可选的研究组织信息确认">
          <p>还有 {Object.keys(residual).length} 项组织与执行信息可确认（可选：现在一键采纳常规建议，或生成初稿后直接在正文修改）：</p>
          <ul>
            {(showAllResidual ? Object.entries(residual) : Object.entries(residual).slice(0, 6)).map(([path, rec]) => (
              <li key={path}>{summarizeResidualValue(rec.value)}——{rec.basis || '按方案常规建议'}</li>
            ))}
          </ul>
          {Object.keys(residual).length > 6 && <>
            <button type="button" onClick={() => setShowAllResidual(v => !v)}>
              {showAllResidual ? '收起明细' : `展开全部 ${Object.keys(residual).length} 项明细`}</button>
            {!showAllResidual && <p>确认前可展开逐项查看每条建议的内容和依据；确认操作会把以上全部 {Object.keys(residual).length} 项写入研究事实（历史可回溯）。</p>}
          </>}
          <button type="button" disabled={factsBusy || !actorId} onClick={confirmResidual}>确认以上全部 {Object.keys(residual).length} 项（可跳过）</button>
        </div>
      </>}
    </>}
    {packet && !job?.complete_candidate && <p role="status">{packet.phase === 'sources'
      ? (sourceState?.status === 'completed' ? '资料已准备，完整初稿尚未开始。' : sourceState && sourceState.status !== 'running' ? '资料准备已停止，原资料与记录已保留。' : '正在准备本次写作资料。')
      : job?.status === 'blocked' ? '本次写作已停止，已生成章节仍可阅读。' : `正在撰写方案，已有 ${readable.length} 个章节可阅读。`}</p>}
    {job?.status === 'blocked' && <>
      <ul className="kz-manuscript-summary">
        <li><strong>需要处理：</strong>{chapters.filter(chapter => !['not_applicable', 'kept_as_gap', 'needs_content_review'].includes(chapter.status)).map(chapter => chapter.title).join('、') || '正在核对未完成章节。'}</li>
        <li><strong>下一步：</strong>{job.can_resume ? '继续可起草的章节，已完成内容会保留。' : '先核对本次任务结果；暂不能重试的章节会保留当前记录。'}</li>
      </ul>
      <button type="button" className="kz-manuscript-primary" disabled={busy}
        onClick={resume}>{job.can_resume ? '继续写作（重试未完成的章节）' : '核对未完成章节的状态'}</button>
    </>}
    {packet && plan?.study_sha256 && plan.study_sha256 !== packet.studySha && <>
      <button type="button"
        disabled={busy || officeOpen || !canGenerate} onClick={() => begin(true)}>按当前研究准备新稿，保留原记录</button>
      {!canGenerate && <p role="status">研究信息更新后，本次初稿尚未与当前研究核对（
        {(readiness?.blocking_design_conflicts || []).map(item => item.title).join('、')
          || (plan.chapters || []).filter(chapter => chapter.status === 'needs_information')
            .map(chapter => chapter.title).join('、') || '见研究建议页提示'}）。
        处理完成后即可准备新稿；原稿与已保存版本不受影响。</p>}
    </>}
    {officeOpen && <p className="kz-manuscript-session-hint">切换历史或准备新稿前，请先保存并关闭编辑器。</p>}
    {packet && <HistoryVersions storageKey={key} onRestore={entry => { remember(entry); setJob(null); setSavedDocument(null); setSourceState(null); setRefresh(v => v + 1); }} busy={busy || officeOpen}/>}
    {job?.complete_candidate && (() => {
      const chapters = job?.chapters || [];
      const written = chapters.filter(c => c.status === 'needs_content_review' && (c.validation || {}).valid).length;
      const gaps = chapters.filter(c => c.status === 'kept_as_gap').length;
      return <ul className="kz-manuscript-summary" aria-label="初稿进度">
        <li><strong>已起草：</strong>{written} 个章节，需医学核对。</li>
        {gaps > 0 && <li><strong>待补充：</strong>{gaps} 个章节保留缺口；在左侧确认相关设计后补写。</li>}
        <li><strong>下一步：</strong>打开文档编辑、保存，再下载当前工作稿。</li>
      </ul>;
    })()}
    {job?.complete_candidate && !savedDocument && <button type="button" className="kz-manuscript-primary"
      disabled={busy || !actorId} onClick={saveCompleteDraft}>{packet?.saveIntent ? '核对并完成原稿保存' : '保存完整初稿'}</button>}
    {savedDocument?.study_binding_status && savedDocument.study_binding_status !== 'current' && <p role="alert">研究信息已变化或暂不可读，这份已保存初稿尚未与当前研究重新核对。</p>}
    {savedDocument && <GenOfficeFrame projectId={projectId} studyDefinitionId={studyDefinitionId}
      actorId={actorId} savedDocument={savedDocument} api={apiRef.current} onSessionChange={setOfficeOpen} onNavigationGuardChange={onNavigationGuardChange} onClose={() => setRefresh(value => value + 1)}/>}
    {savedDocument && packet?.saveConflict && <button type="button" disabled={busy || officeOpen}
      onClick={saveCompleteDraft}>将本次初稿另存为新版本（保留历史）</button>}
    {packet?.phase === 'sources' && sourceState?.can_retry && <button type="button" disabled={busy}
      onClick={retrySources}>使用原资料重试本次准备</button>}
    {error && <p role="alert">{error}</p>}
    {packet && job?.status !== 'blocked' && (error || job?.can_resume) && <button type="button" disabled={busy} onClick={resume}>核对并继续本次写作</button>}
    <button type="button" disabled={busy} onClick={() => setRefresh(value => value + 1)}>更新研究与文档状态</button>
    {chapters.length > 0 && <details className="kz-manuscript-reference" open={savedDocument ? undefined : true}>
      <summary>{savedDocument ? '查看 AI 起草依据（只读，不代表当前 Word 内容）' : '查看已生成章节'}</summary>
      <div className="kz-manuscript-layout">
      <nav aria-label="方案章节"><ol>{chapters.map(chapter => <li key={chapter.node_id}>
        <button type="button" aria-current={current?.node_id === chapter.node_id ? 'true' : undefined}
          disabled={!chapter.validation?.proposal} onClick={() => setSelected(chapter.node_id)}>{chapter.title}</button>
        <small>{chapter.status === 'not_applicable' ? '本研究不适用' : chapter.validation?.valid ? '初稿已生成' : '尚未完成'}</small>
      </li>)}</ol></nav>
      <div>{current && <ChapterDraftPreview title={current.title} candidate={persistedChapter || current.validation.proposal} saved={Boolean(persistedChapter)}
        edit={undefined}/>}</div>
    </div></details>}

  </section>;
}

function FullDraftBridgeSession({ projectId, studyDefinitionId, actorId, api, onNavigationGuardChange }) {
  const storageKey = 'protocol-v3:full-draft-bridge:' + projectId;
  const restored = savedValue(storageKey) || {};
  const [jobId, setJobId] = useState(restored.jobId || '');
  const [job, setJob] = useState(null);
  const [candidate, setCandidate] = useState(null);
  const [savedDocument, setSavedDocument] = useState(null);
  const [pendingIntent, setPendingIntent] = useState(restored.pendingIntent || null);
  const [decisionChoices, setDecisionChoices] = useState({});
  const [sourcePolicy, setSourcePolicy] = useState(null);
  const [officeOpen, setOfficeOpen] = useState(false);
  const [showOffice, setShowOffice] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const apiRef = useRef(api); apiRef.current = api;

  function remember(values) {
    const next = { jobId, pendingIntent, ...values };
    localStorage.setItem(storageKey, JSON.stringify(next));
    if (Object.prototype.hasOwnProperty.call(values, 'jobId')) setJobId(values.jobId || '');
    if (Object.prototype.hasOwnProperty.call(values, 'pendingIntent')) setPendingIntent(values.pendingIntent || null);
  }

  useEffect(() => {
    const controller = new AbortController();
    apiRef.current.getSavedManuscriptDocument(projectId, studyDefinitionId, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setSavedDocument(normalizeSavedDocument(value)); })
      .catch(reason => { if (!controller.signal.aborted && reason?.status !== 404) setError(readableError(reason)); });
    return () => controller.abort();
  }, [projectId, studyDefinitionId, refresh]);

  useEffect(() => {
    if (!jobId) return undefined;
    const controller = new AbortController();
    let timer;
    let delay = 1500;
    const read = async () => {
      try {
        const next = await apiRef.current.getDurableMedicalWritingJob(projectId, jobId, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setJob(next); setError('');
        if (next.status === 'completed') {
          const result = await apiRef.current.getFullDraftResult(projectId, jobId, { signal: controller.signal });
          if (!controller.signal.aborted) setCandidate(result?.artifact || null);
          return;
        }
        if (['failed', 'cancelled'].includes(next.status)) return;
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError('暂时无法读取生成进度；系统会继续核对同一次任务，不会重新生成。');
        }
      }
      if (!controller.signal.aborted) {
        timer = setTimeout(read, delay);
        delay = Math.min(delay * 2, 30000);
      }
    };
    read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [projectId, jobId, refresh]);

  useEffect(() => {
    if (!candidate || !jobId || !apiRef.current.getFullDraftSourcePolicy) {
      setSourcePolicy(null); return undefined;
    }
    const controller = new AbortController();
    apiRef.current.getFullDraftSourcePolicy(projectId, jobId, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setSourcePolicy(value); })
      .catch(reason => {
        if (!controller.signal.aborted) setSourcePolicy(
          reason?.status === 404 ? { status: 'not_required', current: true } : { status: 'unavailable', current: false }
        );
      });
    return () => controller.abort();
  }, [candidate, jobId, projectId, refresh]);

  async function startCandidate() {
    if (busy || jobId) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const next = await apiRef.current.startFullDraft(projectId, actorId);
      if (!next?.job_id) throw new Error('本次候选任务尚未登记。');
      remember({ jobId: next.job_id, pendingIntent: null });
      setJob(next);
    } catch (reason) { setError(readableError(reason)); }
    finally { setBusy(false); }
  }

  async function acceptCandidate() {
    if (busy || !candidate || !jobId || officeOpen) return;
    setBusy(true); setError(''); setNotice('');
    let intent = pendingIntent;
    try {
      let current = savedDocument;
      if (!current) {
        try { current = normalizeSavedDocument(await apiRef.current.getSavedManuscriptDocument(projectId, studyDefinitionId)); }
        catch (reason) { if (reason?.status !== 404) throw reason; }
      }
      if (!intent) {
        intent = {
          operation_id: 'full-draft-candidate:' + crypto.randomUUID(),
          actor_id: actorId,
          expected_revision: current?.revision || 0,
          expected_document_sha256: current?.document_sha256 || null,
          accepted_semantic_node_ids: [],
        };
        remember({ pendingIntent: intent });
      }
      await apiRef.current.recoverFullDraftCandidate(projectId, jobId, intent);
      const accepted = normalizeSavedDocument(
        await apiRef.current.getSavedManuscriptDocument(projectId, studyDefinitionId)
      );
      setSavedDocument(accepted);
      remember({ pendingIntent: null });
      setNotice('候选已进入当前语义工作稿。已有 Word 人工稿仍原样保留；打开工作稿后可核对差异。');
      setShowOffice(true);
      setRefresh(value => value + 1);
    } catch (reason) {
      setError(readableError(reason));
    } finally { setBusy(false); }
  }

  async function confirmSourcePolicy() {
    if (busy || !jobId || sourcePolicy?.current) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await apiRef.current.confirmFullDraftSourcePolicy(projectId, jobId, {
        operation_id: `source-policy:${jobId}:${candidate?.source_manifest_sha256 || 'current'}`,
        actor_id: actorId,
        routine_scope: ['常规运营流程与职责表述', '通用记录与文档管理表述'],
        excluded_scope: ['剂量取舍', '安全性医学判断', '统计设计与分析决定'],
      });
      setSourcePolicy({ ...sourcePolicy, ...result, status: 'confirmed', current: true });
      setNotice('本项目的常规SOP适用范围已确认；后续章节复用该记录。剂量、安全和统计仍分别确认。');
    } catch (reason) { setError(readableError(reason)); }
    finally { setBusy(false); }
  }

  async function confirmRelatedDecisions(items) {
    if (busy || !jobId || !items.length) return;
    const decisions = items.map(item => ({
      decision_id: item.decision_id,
      option_id: decisionChoices[item.decision_id] || item.recommended_option_id,
    }));
    if (decisions.some(item => !item.option_id)) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const groupIdentity = decisions.map(item => `${item.decision_id}:${item.option_id}`).sort().join('|');
      const result = await apiRef.current.resolveFullDraftDecisions(projectId, jobId, {
        actor: actorId,
        idempotency_key: `full-draft-related:${jobId}:${groupIdentity}`,
        decisions,
      });
      await apiRef.current.ensureAuthoringHandoff(projectId, actorId);
      const nextJobId = result?.regeneration?.job_id;
      if (!nextJobId) throw new Error('相关决定已保存，续写任务尚未读回。');
      setCandidate(null); setJob(result.regeneration); setDecisionChoices({});
      remember({ jobId: nextJobId, pendingIntent: null });
      setNotice('相关决定已一次保存，正在只补写受影响章节；其他工作稿内容保持不变。');
    } catch (reason) {
      setError(`本次确认与续写状态尚未核对：${readableError(reason)} 请保留当前选择并再次核对，不需要重新作决定。`);
    } finally { setBusy(false); }
  }

  const coverage = candidate?.coverage || {};
  const sourceManifest = candidate?.source_manifest || {};
  const sourceRoles = (sourceManifest.sources || []).reduce((counts, source) => ({
    ...counts, [source.role]: (counts[source.role] || 0) + 1,
  }), {});
  const requiresSourcePolicy = Boolean(sourceRoles.company_sop_or_protocol_reference);
  const gaps = (candidate?.sections || []).flatMap(section => [
    ...(section.gap_items || []).map(item => ({ ...item, section: section.section_id })),
    ...(section.decision_items || []).map(item => ({
      category: 'decision_pending', section: section.section_id,
      action: item.question || '确认本章节科学决定',
    })),
  ]);
  const decisionItems = (candidate?.sections || []).flatMap(section => section.decision_items || []);
  const running = jobId && !candidate && !['failed', 'cancelled'].includes(job?.status);
  const candidateAlreadyAdopted = Boolean(
    candidate && jobId && savedDocument?.accepted_candidate_id === jobId
  );

  return <section className="kz-protocol kz-manuscript kz-manuscript--bridge" aria-label="完整方案初稿">
    <header><h2>研究方案工作稿</h2></header>
    <ul className="kz-manuscript-summary">
      <li><strong>研究设计：</strong>已沿用本项目此前确认的内容。</li>
      <li><strong>当前文档：</strong>{savedDocument ? `已保存第 ${savedDocument.revision} 版` : '尚未建立工作稿'}。</li>
      <li><strong>候选规则：</strong>有依据的正文与待补事项可同时保留；关键决定不会自动写成既定要求。</li>
    </ul>
    {!jobId && <button type="button" className="kz-manuscript-primary" disabled={busy || !actorId} onClick={startCandidate}>
      准备完整候选初稿
    </button>}
    {running && <div role="status">
      <p>正在生成候选初稿。关闭页面后任务仍会继续；再次进入会核对同一任务。</p>
      <button type="button" disabled={busy} onClick={() => setRefresh(value => value + 1)}>查看最新进度</button>
    </div>}
    {job?.status === 'failed' && <p role="alert">本次候选生成没有完成，当前工作稿未被修改。</p>}
    {job?.status === 'cancelled' && <p role="status">本次候选已停止，当前工作稿未被修改。</p>}
    {candidate && (!savedDocument || !showOffice) && <section className="kz-manuscript-candidate"
      aria-label={candidateAlreadyAdopted ? '已采用的候选依据' : '新候选初稿'}>
      <h3>{candidateAlreadyAdopted ? '已采用的候选依据' : '新候选初稿'}</h3>
      <ul>
        <li><strong>正文范围：</strong>{(candidate.sections || []).filter(item => item.proposal_text).length} 个章节已有正文。</li>
        <li><strong>待处理：</strong>{gaps.length} 项；其中关键决定需在对应位置确认。</li>
        <li><strong>正式就绪：</strong>{coverage.formal_ready ? '是' : '否，当前仅作为可编辑工作稿'}。</li>
        <li><strong>冻结资料：</strong>{sourceManifest.source_count || 0} 个版本；本次候选始终使用提交时版本。</li>
      </ul>
      {(sourceManifest.sources || []).length > 0 && <details><summary>查看本次使用的资料版本</summary><ul>
        {Object.entries(sourceRoles).map(([role, count]) => <li key={role}>{SOURCE_ROLE_LABELS[role] || role}：{count} 项</li>)}
        {(sourceManifest.sources || []).slice(0, 8).map(source => <li key={`${source.source_id}:${source.content_sha256}`}>
          <strong>{source.title || source.source_type}</strong> · {source.source_version || '当前版本'} · {source.locator}
        </li>)}
        {(sourceManifest.sources || []).length > 8 && <li>
          其余 {(sourceManifest.sources || []).length - 8} 个冻结版本已记录，可在来源台账按章节查看。
        </li>}
      </ul></details>}
      {sourcePolicy && sourcePolicy.status !== 'not_required' && <section className="kz-manuscript-source-policy" aria-label="公司SOP项目适用范围">
        <h4>公司SOP适用范围</h4>
        <ul>
          <li><strong>常规运营：</strong>{sourcePolicy.current ? '本项目已确认，可复用' : '需做一次项目级确认'}。</li>
          <li><strong>仍分别确认：</strong>剂量取舍、安全性医学判断、统计设计与分析决定。</li>
          {sourcePolicy.status === 'source_version_changed' && <li><strong>资料已换版：</strong>仅需重新核对受影响范围。</li>}
        </ul>
        {!sourcePolicy.current && <button type="button" className="kz-manuscript-primary" disabled={busy || !actorId}
          onClick={confirmSourcePolicy}>确认本项目复用常规SOP</button>}
      </section>}
      {requiresSourcePolicy && !sourcePolicy && <p role="status">正在读取本项目已有的SOP适用确认…</p>}
      {gaps.length > 0 && <details><summary>查看待处理事项（{gaps.length}）</summary><ul>
        {gaps.slice(0, 20).map((item, index) => <li key={`${item.gap_id || item.section}-${index}`}>
          {item.action || '补充本章节所需信息。'}
        </li>)}
        {gaps.length > 20 && <li>其余 {gaps.length - 20} 项将在工作稿对应章节中继续保留。</li>}
      </ul></details>}
      {decisionItems.length > 0 && <div className="kz-manuscript-decisions" role="group" aria-label="相关研究决定">
        <h4>需要确认的相关决定</h4>
        {decisionItems.map(item => <fieldset key={item.decision_id} disabled={busy}>
          <legend>{item.question}</legend>
          {(item.options || []).map(option => <label key={option.option_id}>
            <input type="radio" name={`bridge-decision-${item.decision_id}`}
              checked={(decisionChoices[item.decision_id] || item.recommended_option_id) === option.option_id}
              onChange={() => setDecisionChoices(current => ({ ...current, [item.decision_id]: option.option_id }))}/>
            <strong>{option.option_id === item.recommended_option_id ? '推荐 · ' : ''}{option.label}</strong>
            <span>{option.summary}</span>
          </label>)}
        </fieldset>)}
        <button type="button" className="kz-manuscript-primary" disabled={busy}
          onClick={() => confirmRelatedDecisions(decisionItems)}>
          一次确认这 {decisionItems.length} 项相关决定
        </button>
      </div>}
      {!candidateAlreadyAdopted && <button type="button" className="kz-manuscript-primary"
        disabled={busy || officeOpen || !coverage.working_draft_ready
          || (requiresSourcePolicy && !sourcePolicy?.current)}
        onClick={acceptCandidate}>{pendingIntent ? '核对并完成原候选采用' : '采用候选并打开工作稿'}</button>}
      {savedDocument && <p>{candidateAlreadyAdopted
        ? '该候选已进入当前语义工作稿。已有 Word 人工稿仍原样保留；打开工作稿后可选择编辑新候选或继续当前 Word。'
        : '采用新候选不会静默覆盖当前 Word 人工稿；系统会保留现有版本并提示核对。'}</p>}
    </section>}
    {savedDocument && !showOffice && <button type="button" className="kz-manuscript-primary" onClick={() => setShowOffice(true)}>
      打开工作稿
    </button>}
    {showOffice && savedDocument && <GenOfficeFrame
      projectId={projectId} studyDefinitionId={studyDefinitionId}
      actorId={actorId} savedDocument={savedDocument} api={apiRef.current}
      onSessionChange={setOfficeOpen} onNavigationGuardChange={onNavigationGuardChange}
      onClose={() => { setShowOffice(false); setRefresh(value => value + 1); }}/>}
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}

export function ManuscriptWorkspace(props) {
  if (props.bridgeMode) {
    return <FullDraftBridgeSession key={JSON.stringify([props.projectId, props.studyDefinitionId])} {...props}/>;
  }
  return <ManuscriptSession key={JSON.stringify([props.projectId, props.studyDefinitionId, props.seedRunId])} {...props}/>;
}
