import { useEffect, useRef, useState } from 'react';
import { MedicalWritingLiteraturePanel } from '../../MedicalWritingLiteraturePanel';
import './GenOfficeFrame.css';

async function bundleInstalled() {
  try {
    const response = await fetch('/genoffice/index.html', { method: 'HEAD' });
    return response.ok;
  } catch {
    return false;
  }
}

function formatReferenceBody(reference) {
  const authors = (reference.authors || []).map(item => String(item).trim()).filter(Boolean);
  const authorText = authors.length === 0 ? '佚名' : authors.length <= 3 ? authors.join(', ')
    : `${authors.slice(0, 3).join(', ')}, ${authors.slice(0, 3).some(item => /[\u4e00-\u9fff]/u.test(item)) ? '等' : 'et al'}`;
  const title = String(reference.title || '').trim() || '题名缺失';
  const journal = String(reference.journal || '').trim();
  let source;
  if (journal) {
    source = `${title}[J]. ${journal}`;
    const publication = [String(reference.year || '').trim(),
      `${String(reference.volume || '').trim()}${reference.issue ? `(${String(reference.issue).trim()})` : ''}`]
      .filter(Boolean).join(', ');
    const pages = String(reference.pages || '').trim();
    if (publication || pages) source += `, ${publication}${publication && pages ? ': ' : ''}${pages}`;
    source += '.';
  } else source = `${title}[EB/OL].`;
  const identifier = reference.doi ? `DOI: ${String(reference.doi).trim()}`
    : String(reference.url || '').trim();
  if (identifier) source += ` ${identifier}.`;
  return `${authorText}. ${source}`;
}

/**
 * One-instance-one-iframe GenOffice docs runtime (T10/P3; audit G1 rework).
 *
 * 打开来源 = 当前Office工作稿：已有Office快照时从最新快照初始化（唯一标记、
 * 表格、页眉修改在关闭重开后保留）；尚无快照时才从语义稿导出初始化。下载
 * 链接与打开来源同源，不再固定指向语义稿（F01）。一次会话冻结一个iframe：
 * 宿主状态刷新不重建运行中的编辑器（F03）；关闭前确认，避免无声丢弃未保存
 * 修改。每次保存携带打开时的 artifact revision 做条件写，双窗口不会互相
 * 静默覆盖（F04）；研究基线取工作稿绑定的版本，不再被贴上当前版本（F05）。
 */
export function GenOfficeFrame({ projectId, studyDefinitionId, actorId, savedDocument, onClose, onSessionChange, onNavigationGuardChange, api }) {
  const [open, setOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [focused, setFocused] = useState(false);
  const [notice, setNotice] = useState('');
  const [confirmingClose, setConfirmingClose] = useState(false);
  // 一次会话冻结一次打开参数：savedDocument 在编辑器打开期间变化只更新外层
  // 展示，不重建 iframe（F03）。
  const [session, setSession] = useState(null);
  const iframeRef = useRef(null);
  const initialOpen = useRef(false);
  const [head, setHead] = useState(null);
  const [headReady, setHeadReady] = useState(false);
  const [headReload, setHeadReload] = useState(0);
  const [backupUrl, setBackupUrl] = useState(null);
  const backupRef = useRef(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState(null);
  const [historyError, setHistoryError] = useState('');
  const [reconciliation, setReconciliation] = useState(null);
  const [reconciliationError, setReconciliationError] = useState('');
  const pendingCommands = useRef(new Map());
  const [selection, setSelection] = useState(null);
  const [revisionInstruction, setRevisionInstruction] = useState('');
  const [revisionCandidate, setRevisionCandidate] = useState(null);
  const [revisionBusy, setRevisionBusy] = useState(false);
  const [lastAppliedRevision, setLastAppliedRevision] = useState(null);

  const semanticDocUrl = `/api/projects/${encodeURIComponent(projectId)}/protocol-workflow/study-definitions/`
    + `${encodeURIComponent(studyDefinitionId)}/manuscript-draft/candidate/docx`;
  const snapshotsBase = `/api/projects/${encodeURIComponent(projectId)}/protocol-workflow/study-definitions/`
    + `${encodeURIComponent(studyDefinitionId)}/manuscript-draft/office-draft/snapshots`;

  function snapshotUrl(receipt) {
    return `${snapshotsBase}/${encodeURIComponent(receipt.operation_id)}/content`;
  }

  useEffect(() => {
    let active = true;
    setHeadReady(false);
    Promise.resolve().then(() => api.latestOfficeSnapshot(projectId, studyDefinitionId))
      .then(value => { if (active) { setHead(value); setHeadReady(true); } })
      .catch(error => {
        if (!active) return;
        if (error?.status === 404) { setHead(null); setHeadReady(true); }
        else setNotice('暂时无法读取已保存工作稿，请重新打开页面后再试。');
      });
    return () => { active = false; };
  }, [api, projectId, studyDefinitionId, headReload]);

  useEffect(() => {
    function receiveSave(event) {
      if (event.origin !== window.location.origin || event.source !== iframeRef.current?.contentWindow
        ) return;
      if (event.data?.type === 'protocol-office:dirty') { setDirty(Boolean(event.data.dirty)); return; }
      if (event.data?.type === 'protocol-office:result') {
        const pending = pendingCommands.current.get(event.data.request_id);
        if (!pending) return;
        clearTimeout(pending.timeout);
        pendingCommands.current.delete(event.data.request_id);
        if (event.data.ok) pending.resolve(event.data.result);
        else pending.reject(new Error(event.data.error || '文档操作没有完成。'));
        return;
      }
      if (event.data?.type === 'protocol-office:save-failed') {
        if (event.data.latest_snapshot?.operation_id) setHead(event.data.latest_snapshot);
        setNotice(`${event.data.error || '本次保存未完成。'} 本次修改尚未确认保存；请先下载未保存修改，再关闭编辑器核对最新版本。`);
        if (event.data.data) {
          if (backupRef.current) URL.revokeObjectURL(backupRef.current);
          backupRef.current = URL.createObjectURL(new Blob([event.data.data], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }));
          setBackupUrl(backupRef.current);
        }
        return;
      }
      if (event.data?.type !== 'protocol-office:saved') return;
      const receipt = event.data.receipt;
      if (!receipt?.operation_id || !receipt?.artifact_revision) return;
      setHead(receipt);
      setHeadReady(true);
      setNotice(`修改已保存，第 ${receipt.artifact_revision} 版；可下载当前工作稿。`);
    }
    window.addEventListener('message', receiveSave);
    return () => {
      window.removeEventListener('message', receiveSave);
      if (backupRef.current) URL.revokeObjectURL(backupRef.current);
      pendingCommands.current.forEach(pending => {
        clearTimeout(pending.timeout); pending.reject(new Error('文档编辑器已关闭。'));
      });
      pendingCommands.current.clear();
    };
  }, []);

  function sendOfficeCommand(command, payload = {}) {
    const target = iframeRef.current?.contentWindow;
    if (!open || !target) return Promise.reject(new Error('请先打开文档编辑器。'));
    const requestId = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        pendingCommands.current.delete(requestId);
        reject(new Error('文档编辑器尚未响应，请稍后重试。'));
      }, 10000);
      pendingCommands.current.set(requestId, { resolve, reject, timeout });
      target.postMessage({ type: 'protocol-office:command', version: 1,
        request_id: requestId, command, payload }, window.location.origin);
    });
  }

  useEffect(() => {
    const insertReference = event => {
      if (event.detail?.projectId !== projectId || !open || !iframeRef.current) return;
      event.preventDefault();
      const reference = event.detail.reference;
      void sendOfficeCommand('insert-project-citation', {
        reference, formatted_entry_body: formatReferenceBody(reference),
      }).then(() => setNotice('引文已插入当前光标，编号和参考文献表已按首次出现顺序更新。'))
        .catch(error => setNotice(error.message));
    };
    window.addEventListener('protocol-office:insert-reference', insertReference);
    return () => window.removeEventListener('protocol-office:insert-reference', insertReference);
  }, [open, projectId]);

  useEffect(() => {
    onNavigationGuardChange?.(dirty ? { dirty: true, sectionTitle: '当前 Word 工作稿', hasRecoveryDraft: false } : null);
    if (!dirty) return undefined;
    const beforeUnload = event => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', beforeUnload);
    return () => { window.removeEventListener('beforeunload', beforeUnload); onNavigationGuardChange?.(null); };
  }, [dirty, onNavigationGuardChange]);

  useEffect(() => {
    if (!historyOpen) return undefined;
    const controller = new AbortController();
    setHistory(null); setHistoryError('');
    Promise.resolve().then(() => api.officeSnapshotHistory(projectId, studyDefinitionId, { signal: controller.signal }))
      .then(result => {
        if (!Array.isArray(result?.snapshots)) throw new Error('unreadable history');
        if (!controller.signal.aborted) setHistory(result.snapshots);
      }).catch(() => {
        if (!controller.signal.aborted) setHistoryError('暂时无法读取历史版本，当前编辑内容不受影响。');
      });
    return () => controller.abort();
  }, [historyOpen, head?.operation_id, api, projectId, studyDefinitionId]);

  useEffect(() => {
    if (!head?.operation_id || !api?.getOfficeSnapshotReconciliation) {
      setReconciliation(null); setReconciliationError(''); return undefined;
    }
    const controller = new AbortController();
    setReconciliation(null); setReconciliationError('');
    Promise.resolve().then(() => api.getOfficeSnapshotReconciliation(
      projectId, studyDefinitionId, { signal: controller.signal }))
      .then(result => { if (!controller.signal.aborted) setReconciliation(result); })
      .catch(error => {
        if (!controller.signal.aborted) setReconciliationError(
          error?.detail?.message || '当前 Word 已保存，自动核对暂未完成。');
      });
    return () => controller.abort();
  }, [head?.operation_id, api, projectId, studyDefinitionId]);

  useEffect(() => {
    if (!focused) return undefined;
    const escape = event => { if (event.key === 'Escape') setFocused(false); };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [focused]);

  function belongsToOlderDraft(receipt) {
    if (!receipt) return false;
    if (receipt.document_sha256) return receipt.document_sha256 !== savedDocument.document_sha256;
    return receipt.document_revision != null && receipt.document_revision !== savedDocument.document?.revision;
  }

  async function beginSession(mode = 'current') {
    if (!(await bundleInstalled())) {
      setNotice('文档编辑器暂不可用，已保存工作稿仍可下载。');
      return;
    }
    const revision = savedDocument.document?.revision ?? 1;
    let studySha = savedDocument.document?.study_definition_sha256 || '';
    let docUrl = semanticDocUrl;
    let officeRevision = null;
    let baseArtifactRevision = 0;
    let expectedRevision = revision;
    let expectedDocumentSha = savedDocument.document_sha256 || '';
    let openingCandidate = false;
    let continuingExisting = false;
    try {
      const latest = await api?.latestOfficeSnapshot?.(projectId, studyDefinitionId);
      if (latest?.operation_id && latest?.artifact_revision) {
        setHead(latest);
        baseArtifactRevision = latest.artifact_revision;
        if (belongsToOlderDraft(latest)) {
          if (mode !== 'candidate' && mode !== 'existing') {
            setNotice('本次新起草候选尚未替换现有工作稿。可继续编辑已保存的 Word，或选择新候选。');
            return;
          }
          openingCandidate = mode === 'candidate';
          continuingExisting = mode === 'existing';
        }
        if (!openingCandidate) {
          docUrl = `${snapshotsBase}/${encodeURIComponent(latest.operation_id)}/content`;
          officeRevision = latest.artifact_revision;
          studySha = latest.study_revision_sha256 || studySha;
          expectedRevision = latest.document_revision ?? expectedRevision;
          expectedDocumentSha = latest.document_sha256 || expectedDocumentSha;
        }
      }
    } catch (error) {
      if (error?.status !== 404) {
        setNotice('无法核对最新工作稿，暂未打开编辑器。请重试。');
        return;
      }
    }
    const query = new URLSearchParams({
      docUrl,
      docName: officeRevision ? `研究方案工作稿_编辑版${officeRevision}.docx` : `研究方案工作稿_初稿${revision}.docx`,
      saveUrl: `${snapshotsBase}`,
      rev: String(expectedRevision),
      sha: expectedDocumentSha,
      actor: actorId || 'medical_manager',
      openedStudySha: studySha,
      baseArtifactRevision: String(baseArtifactRevision),
    });
    setSession({ query: query.toString(), docUrl, revision, officeRevision, studySha, openingCandidate });
    setOpen(true);
    onSessionChange?.(true);
    setNotice(openingCandidate ? '正在编辑新起草候选；保存后成为当前工作稿，原稿保留。'
      : continuingExisting ? '正在编辑已保存的 Word；新起草候选尚未采用。' : '');

  }

  useEffect(() => {
    if (!headReady || initialOpen.current) return;
    initialOpen.current = true;
    void beginSession();
  }, [headReady]);

  function requestClose() {
    // Reuse the renderer close-check state; only unsaved changes need confirmation.
    if (dirty && !confirmingClose) {
      setConfirmingClose(true);
      return;
    }
    setConfirmingClose(false);
    setDirty(false);
    setOpen(false);
    setFocused(false);
    onSessionChange?.(false);
    setSession(null);
    setSelection(null);
    setRevisionCandidate(null);
    setRevisionInstruction('');

    onClose?.();
  }

  async function captureSelection() {
    setRevisionCandidate(null); setRevisionBusy(true);
    try {
      if (selection?.anchor_id) await sendOfficeCommand('release-selection', { anchor_id: selection.anchor_id }).catch(() => {});
      const captured = await sendOfficeCommand('capture-selection');
      setSelection(captured); setNotice('已锁定当前选区。可用一句话说明希望如何修改。');
    } catch (error) { setNotice(error.message); }
    finally { setRevisionBusy(false); }
  }

  async function generateSelectionRevision() {
    if (!selection || !revisionInstruction.trim() || revisionBusy) return;
    setRevisionBusy(true); setRevisionCandidate(null);
    const operationId = `office-selection-revision:${crypto.randomUUID()}`;
    try {
      await api.prepareOfficeSelectionRevision(projectId, studyDefinitionId, {
        operation_id: operationId,
        actor_id: actorId || 'medical_manager',
        anchor_id: selection.anchor_id,
        target_kind: selection.target_kind,
        selected_text: selection.text,
        instruction: revisionInstruction.trim(),
        office_artifact_revision: session?.officeRevision || 0,
      });
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, attempt < 3 ? 1000 : 5000));
        const status = await api.getOfficeSelectionRevision(projectId, studyDefinitionId, operationId);
        if (status.status === 'candidate_ready') {
          setRevisionCandidate({ operationId, ...status.candidate });
          setNotice('局部修改建议已生成。采用前请核对原文与建议。');
          return;
        }
        if (status.status === 'failed' || status.status === 'unavailable') {
          throw new Error(status.message || '本次局部修改建议未生成，原文没有变化。');
        }
      }
      throw new Error('建议仍在生成，可保留当前页面后稍后再试。');
    } catch (error) { setNotice(error.message); }
    finally { setRevisionBusy(false); }
  }

  async function applySelectionRevision() {
    if (!selection || !revisionCandidate) return;
    setRevisionBusy(true);
    try {
      await sendOfficeCommand('replace-selection', {
        anchor_id: selection.anchor_id,
        replacement_text: revisionCandidate.replacement_content,
        operation_id: revisionCandidate.operationId,
      });
      setLastAppliedRevision(revisionCandidate);
      setSelection(null); setRevisionCandidate(null); setRevisionInstruction('');
      setNotice('建议已写入原选区，其他内容未改。请保存 Word；如需可立即撤销。');
    } catch (error) { setNotice(error.message); }
    finally { setRevisionBusy(false); }
  }

  async function undoSelectionRevision() {
    if (!lastAppliedRevision) return;
    setRevisionBusy(true);
    try {
      await sendOfficeCommand('undo-replacement', { operation_id: lastAppliedRevision.operationId });
      setLastAppliedRevision(null); setNotice('刚才采用的局部修改已撤销。');
    } catch (error) { setNotice(error.message); }
    finally { setRevisionBusy(false); }
  }

  function insertProjectReference(reference) {
    if (!open || !iframeRef.current) return '请先打开文档编辑器，再插入引文。';
    void sendOfficeCommand('insert-project-citation', {
      reference, formatted_entry_body: formatReferenceBody(reference),
    }).then(() => setNotice('引文已插入当前光标，编号和参考文献表已按首次出现顺序更新。'))
      .catch(error => setNotice(error.message));
    return '正在插入当前 Word 光标；编号和参考文献表会自动更新。';
  }

  const params = session?.query ?? null;

  if (!savedDocument) return null;
  const currentUrl = head?.operation_id ? snapshotUrl(head) : semanticDocUrl;
  const hasNewCandidate = belongsToOlderDraft(head);
  return <section className={open ? `gz-office-frame${focused ? ' gz-office-frame--focus' : ''}` : 'gz-office-entry'} aria-label="文档编辑与下载">
    <header>
      <strong>{head ? `已保存工作稿 · 第 ${head.artifact_revision} 版` : '研究方案工作稿'}</strong>
      <div>
        <button type="button" aria-expanded={historyOpen} onClick={() => setHistoryOpen(value => !value)}>Word 版本记录</button>
        {open && <button type="button" aria-pressed={focused} onClick={() => setFocused(value => !value)}>{focused ? '返回研究工作台' : '专注编辑'}</button>}
        {headReady && <a href={currentUrl} download={head ? `研究方案工作稿_编辑版${head.artifact_revision}.docx` : `研究方案工作稿_初稿${savedDocument.document.revision}.docx`}>下载当前 Word 工作稿</a>}
        {!open ? <button type="button" className="kz-manuscript-primary" disabled={!headReady}
          onClick={() => beginSession(hasNewCandidate ? 'candidate' : 'current')}>{hasNewCandidate ? '编辑本次新起草候选' : '打开文档编辑器'}</button> : <button type="button" onClick={requestClose}>
          {confirmingClose ? '确认关闭（未保存修改将丢失）' : '关闭编辑器'}
        </button>}
        {!open && headReady && hasNewCandidate && <button type="button" onClick={() => beginSession('existing')}>继续编辑已保存的 Word</button>}
      </div>
    </header>
    {historyOpen && <div className="gz-office-history" aria-label="已保存的Word版本">
      {historyError ? <p role="alert">{historyError}</p> : history === null ? <p role="status">正在读取版本记录…</p>
        : history.length === 0 ? <p>首次保存后，版本会出现在这里。</p>
          : <ul>{history.map(version => <li key={version.operation_id}>
            <span>第 {version.artifact_revision} 版{version.operation_id === head?.operation_id ? ' · 当前已保存版本' : ''}</span>
            <time dateTime={version.saved_at}>{version.saved_at ? new Date(version.saved_at).toLocaleString('zh-CN') : ''}</time>
            <a href={snapshotUrl(version)} download={`研究方案工作稿_编辑版${version.artifact_revision}.docx`}>下载第 {version.artifact_revision} 版</a>
          </li>)}</ul>}
    </div>}
    {head && <div className="gz-office-reconciliation" aria-label="当前Word科学核对">
      <strong>当前 Word 核对</strong>
      {reconciliationError ? <p>{reconciliationError} 保存、编辑和下载不受影响。</p>
        : !reconciliation ? <p role="status">正在核对当前已保存版本…</p>
          : <>
            <ul>
              <li>已定位 {reconciliation.located?.length || 0} 项关键事实。</li>
              {(reconciliation.differences?.length || 0) > 0
                ? <li><strong>需处理：</strong>{reconciliation.differences.map(item => item.message).join('；')}</li>
                : <li>在本次可检查范围内未发现确定的数值缺失。</li>}
              {(reconciliation.unverified?.length || 0) > 0 && <li><strong>仍需人工核对：</strong>
                {reconciliation.unverified.map(item => item.label).join('、')}</li>}
              {!reconciliation.study_matches_opened_baseline && <li><strong>研究设计已有更新：</strong>当前 Word 仍绑定打开时的研究版本。</li>}
            </ul>
            <p>{reconciliation.coverage_note}</p>
          </>}
    </div>}
    {notice && <p role="status">{notice}</p>}
    {!headReady && notice && <button type="button" onClick={() => { setNotice(''); setHeadReload(value => value + 1); }}>重新读取已保存稿</button>}
    {backupUrl && <a href={backupUrl} download="研究方案_未保存修改.docx">下载未保存修改（本地备份）</a>}
    {open && <section className="gz-office-ai-edit" aria-label="选区AI修改">
      <div className="gz-office-ai-edit__bar">
        <strong>只改选中内容</strong>
        <button type="button" disabled={revisionBusy} onClick={captureSelection}>读取当前选区</button>
        {lastAppliedRevision && <button type="button" disabled={revisionBusy} onClick={undoSelectionRevision}>撤销刚才采用</button>}
      </div>
      {selection && <div className="gz-office-ai-edit__body">
        <blockquote>{selection.text}</blockquote>
        <label>修改要求<input value={revisionInstruction} onChange={event => setRevisionInstruction(event.target.value)}
          placeholder="例如：压缩为两句话，并保留全部数值和限定条件" /></label>
        <button type="button" className="kz-manuscript-primary" disabled={revisionBusy || !revisionInstruction.trim()}
          onClick={generateSelectionRevision}>{revisionBusy ? '正在生成建议…' : '生成局部修改建议'}</button>
      </div>}
      {revisionCandidate && <div className="gz-office-ai-edit__candidate">
        <div><span>原文</span><p>{selection?.text}</p></div>
        <div><span>建议</span><p>{revisionCandidate.replacement_content}</p></div>
        <div className="gz-office-ai-edit__actions">
          <button type="button" onClick={() => setRevisionCandidate(null)}>暂不采用</button>
          <button type="button" className="kz-manuscript-primary" disabled={revisionBusy} onClick={applySelectionRevision}>采用到原选区</button>
        </div>
      </div>}
    </section>}
    {open && <details className="gz-office-literature">
      <summary>项目文献库 · 插入当前 Word 光标</summary>
      <MedicalWritingLiteraturePanel projectId={projectId} onInsertReference={insertProjectReference} />
    </details>}
    {open && params && <iframe ref={iframeRef} title="GenOffice文档编辑器"
      src={`/genoffice/index.html?${params}`} />}
  </section>;
}
