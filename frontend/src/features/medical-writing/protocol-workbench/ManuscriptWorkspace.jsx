import { useEffect, useRef, useState } from 'react';
import { ChapterDraftPreview } from './ChapterDraftPreview';
import './kangzheProtocol.css';
import './ManuscriptWorkspace.css';

function savedValue(key) {
  try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; }
}
function readableError(error) {
  const message = error?.detail?.message || error?.message;
  return typeof message === 'string' && /[\u3400-\u9fff]/u.test(message)
    ? message : '本次写作结果尚未核对清楚，原资料和操作记录已保留。';
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
  const entries = open ? historyEntries(storageKey) : [];
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

function ManuscriptSession({ projectId, studyDefinitionId, seedRunId, actorId, api }) {
  const key = 'protocol-v3:manuscript:' + JSON.stringify([projectId, studyDefinitionId, seedRunId]);
  const [packet, setPacket] = useState(() => savedValue(key));
  const [plan, setPlan] = useState(null), [job, setJob] = useState(null);
  const [selected, setSelected] = useState(null), [error, setError] = useState('');
  const [savedDocument, setSavedDocument] = useState(null);
  const [sourceState, setSourceState] = useState(null);
  const [planRefresh, setPlanRefresh] = useState(0);
  const [busy, setBusy] = useState(false), [refresh, setRefresh] = useState(0);
  const [factsBusy, setFactsBusy] = useState(false);
  const [residual, setResidual] = useState(null);
  const apiRef = useRef(api); apiRef.current = api;
  const request = useRef(null), flight = useRef(false);

  useEffect(() => {
    // Once drafting is otherwise blocked, offer the residual user-decidable
    // facts (organization/signing facts with transparent recommendations).
    if (!apiRef.current?.getChapterFactsResidual) return undefined;
    if (plan?.all_applicable_inputs_ready || factsBusy) return undefined;
    const controller = new AbortController();
    Promise.resolve().then(() => apiRef.current.getChapterFactsResidual(projectId, studyDefinitionId, { signal: controller.signal }))
      .then(value => { if (!controller.signal.aborted) setResidual(value?.residual || null); })
      .catch(() => {});
    return () => controller.abort();
  }, [projectId, studyDefinitionId, plan, factsBusy, refresh]);

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
        if (status?.progress && !status.progress.running) break;
      }
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
          if (state.status !== 'running') return;
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
    if (!controller.signal.aborted) setSavedDocument(current);
  }

  useEffect(() => {
    if (!packet?.saveIntent && !packet?.savedDocumentId) return undefined;
    const controller = new AbortController();
    const loading = packet.savedDocumentId
      ? apiRef.current.getSemanticDocument(projectId, studyDefinitionId, packet.savedDocumentId, { signal: controller.signal })
        .then(current => { if (!controller.signal.aborted) setSavedDocument(current); })
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
              setSavedDocument(current);
              setError('已读取更新的文档，本次初稿没有覆盖它。需要保留本次初稿时，可另存为新版本。');
            }
          } catch (recoveryError) { if (!controller.signal.aborted) setError(readableError(recoveryError)); }
        } else setError(readableError(reason));
      }
    }
    finally { flight.current = false; if (!controller.signal.aborted) setBusy(false); }
  }

  async function begin(newVersion = false) {
    if (flight.current || (packet && newVersion !== true)) return;
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
        if (!state || state.can_resume) await apiRef.current.startManuscriptDraft(projectId, studyDefinitionId, packet.intent, { signal: controller.signal });
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

  // --- Controlled editing: local drafts keyed by the exact document version,
  // IME-safe submit, server-side EditClass reclassification (the client's
  // wording claim is advisory only). Fact-class edits surface proposals.
  const composingRef = useRef(false);
  const [editingBlockId, setEditingBlockId] = useState(null);
  const [editBusy, setEditBusy] = useState(false);
  const [editNotice, setEditNotice] = useState('');
  const draftsKey = savedDocument
    ? `${key}:drafts:${savedDocument.document.revision}:${savedDocument.document_sha256}`
    : null;
  const [localDrafts, setLocalDrafts] = useState(() => draftsKey ? savedValue(draftsKey) || {} : {});
  useEffect(() => { setLocalDrafts(draftsKey ? savedValue(draftsKey) || {} : {}); setEditingBlockId(null); },
    [draftsKey]);
  function stashDraft(blockId, text) {
    setLocalDrafts(previous => {
      const next = { ...previous, [blockId]: text };
      try { if (draftsKey) localStorage.setItem(draftsKey, JSON.stringify(next)); } catch { /* keep in memory */ }
      return next;
    });
  }
  async function saveBlockEdit(blockId, newText) {
    if (editBusy || !savedDocument) return;
    setEditBusy(true); setError('');
    const controller = new AbortController(); request.current = controller;
    try {
      const intent = { study_definition_id: studyDefinitionId,
        expected_workflow_run_id: packet.intent?.expected_workflow_run_id,
        operation_id: 'manuscript-edit:' + crypto.randomUUID(),
        actor_id: actorId,
        expected_revision: savedDocument.document.revision,
        expected_document_sha256: savedDocument.document_sha256,
        edits: [{ semantic_block_id: blockId, block: { content: newText }, claimed_class: 'wording_only' }] };
      localStorage.setItem(key + ':edit:' + intent.operation_id, JSON.stringify(intent));
      let receipt;
      try { receipt = await apiRef.current.recoverEdit?.(projectId, studyDefinitionId, intent, { signal: controller.signal }); }
      catch (reason) { if (reason?.status !== 404) throw reason; }
      if (!controller.signal.aborted && !receipt) {
        receipt = await apiRef.current.editManuscriptDraft(projectId, studyDefinitionId, intent, { signal: controller.signal });
      }
      if (!controller.signal.aborted && receipt) {
        if (receipt.status === 'needs_fact_confirmation') {
          const paths = (receipt.fact_proposals || []).flatMap(proposal => proposal.affected_fact_paths);
          setEditNotice(`这段修改涉及研究事实（${[...new Set(paths)].join('、') || '研究信息'}），已转为研究信息确认建议，未直接改正文。`);
        } else {
          setSavedDocument(receipt);
          setEditNotice('');
          stashDraft(blockId, newText);
        }
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        if (reason?.status === 409) { setEditNotice('文档已有更新版本，本次修改没有覆盖它。请刷新后基于最新版本重试。'); setRefresh(v => v + 1); }
        else setError(readableError(reason));
      }
    }
    finally { flight.current = false; setEditBusy(false); setEditingBlockId(null); }
  }
  return <section className="kz-protocol kz-manuscript" aria-label="完整方案初稿">
    <header><p className="kz-manuscript-eyebrow">阅读与修改</p><h2>把研究建议写成完整方案</h2>
      <p>保留已确认的研究选择，按模板撰写全部适用章节。</p></header>
    {!packet && <>
      <button className="kz-manuscript-primary" type="button" onClick={() => begin()}
        disabled={busy || !plan?.all_applicable_inputs_ready}>生成完整初稿</button>
      {plan && !plan.all_applicable_inputs_ready && <p>请先完成研究建议中的未决内容，已有确认会保留。</p>}
      {plan && !plan.all_applicable_inputs_ready && apiRef.current?.deriveChapterFacts && <>
        <button type="button" disabled={factsBusy} onClick={deriveFacts}>
          {factsBusy ? '正在按已确认设计补齐章节事实…' : '按已确认设计补齐章节事实（AI建议）'}</button>
        <p>缺失的章节级事实由模型按已确认研究设计起草并标为AI建议；初稿与受控编辑中可逐条核对修改。设计变化后需重新补齐。</p>
      </>}
      {plan && !plan.all_applicable_inputs_ready && residual && Object.keys(residual).length > 0 && <>
        <div className="kz-manuscript-residual" role="group" aria-label="待确认的研究组织信息">
          <p>还有 {Object.keys(residual).length} 项研究组织与执行信息需要你确认（已按常规给出建议，全部确认后即可生成初稿；正文中可继续修改）：</p>
          <ul>
            {Object.entries(residual).slice(0, 6).map(([path, rec]) => (
              <li key={path}>{rec.basis || '按方案常规建议'}</li>
            ))}
            {Object.keys(residual).length > 6 && <li>… 其余 {Object.keys(residual).length - 6} 项同类信息</li>}
          </ul>
          <button type="button" disabled={factsBusy || !actorId} onClick={confirmResidual}>确认以上建议</button>
        </div>
      </>}
    </>}
    {packet && !job?.complete_candidate && <p role="status">{packet.phase === 'sources'
      ? (sourceState?.status === 'completed' ? '资料已准备，完整初稿尚未开始。' : sourceState && sourceState.status !== 'running' ? '资料准备已停止，原资料与记录已保留。' : '正在准备本次写作资料。')
      : job?.status === 'blocked' ? '本次写作已停止，已生成章节仍可阅读。' : `正在撰写方案，已有 ${readable.length} 个章节可阅读。`}</p>}
    {job?.status === 'blocked' && <p>尚未完成：{chapters.filter(chapter => !['not_applicable', 'needs_content_review'].includes(chapter.status)).map(chapter => chapter.title).join('、')}</p>}
    {packet && plan?.study_sha256 && plan.study_sha256 !== packet.studySha && <>
      <button type="button"
        disabled={busy || !plan.all_applicable_inputs_ready} onClick={() => begin(true)}>按当前研究准备新稿，保留原记录</button>
      {!plan.all_applicable_inputs_ready && <p role="status">研究信息更新后，部分章节的建议尚未重新确认（
        {(plan.chapters || []).filter(chapter => chapter.status === 'needs_information')
          .map(chapter => chapter.title).join('、') || '见研究建议页提示'}）。
        确认完成后即可准备新稿；原稿与已保存版本不受影响。</p>}
    </>}
    {packet && <HistoryVersions storageKey={key} onRestore={entry => { remember(entry); setJob(null); setSavedDocument(null); setSourceState(null); setRefresh(v => v + 1); }} busy={busy}/>}
    {job?.complete_candidate && <p role="status">全部适用章节初稿已生成，可开始逐章阅读核对。</p>}
    {job?.complete_candidate && !savedDocument && <button type="button" className="kz-manuscript-primary"
      disabled={busy || !actorId} onClick={saveCompleteDraft}>{packet?.saveIntent ? '核对并完成原稿保存' : '保存完整初稿'}</button>}
    {savedDocument && <p role="status">完整工作初稿已保存，第 {savedDocument.document.revision} 版。医学核对和正式导出验收尚未完成。</p>}
    {savedDocument && savedDocument.study_binding_status !== 'current' && <p role="alert">研究信息已变化或暂不可读，这份已保存初稿尚未与当前研究重新核对。</p>}
    {savedDocument && packet?.saveConflict && <button type="button" disabled={busy}
      onClick={saveCompleteDraft}>将本次初稿另存为新版本（保留历史）</button>}
    {packet?.phase === 'sources' && sourceState?.can_retry && <button type="button" disabled={busy}
      onClick={retrySources}>使用原资料重试本次准备</button>}
    {error && <p role="alert">{error}</p>}
    {packet && (error || job?.can_resume) && <button type="button" disabled={busy} onClick={resume}>核对并继续本次写作</button>}
    <button type="button" disabled={busy} onClick={() => setRefresh(value => value + 1)}>更新研究与文档状态</button>
    {chapters.length > 0 && <div className="kz-manuscript-layout">
      <nav aria-label="方案章节"><ol>{chapters.map(chapter => <li key={chapter.node_id}>
        <button type="button" aria-current={current?.node_id === chapter.node_id ? 'true' : undefined}
          disabled={!chapter.validation?.proposal} onClick={() => setSelected(chapter.node_id)}>{chapter.title}</button>
        <small>{chapter.status === 'not_applicable' ? '本研究不适用' : chapter.validation?.valid ? '初稿已生成' : '尚未完成'}</small>
      </li>)}</ol></nav>
      <div>{current && <ChapterDraftPreview title={current.title} candidate={persistedChapter || current.validation.proposal} saved={Boolean(persistedChapter)}
        edit={savedDocument ? { busy: editBusy, composingRef, localDrafts,
          editingBlockId, onStartEdit: setEditingBlockId, onCancelEdit: () => setEditingBlockId(null),
          onSave: saveBlockEdit } : undefined}/>}</div>
    </div>}
    {editNotice && <p role="status">{editNotice}</p>}
  </section>;
}

export function ManuscriptWorkspace(props) {
  return <ManuscriptSession key={JSON.stringify([props.projectId, props.studyDefinitionId, props.seedRunId])} {...props}/>;
}
