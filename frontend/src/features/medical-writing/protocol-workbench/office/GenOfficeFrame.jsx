import { useEffect, useMemo, useRef, useState } from 'react';
import './GenOfficeFrame.css';

async function bundleInstalled() {
  try {
    const response = await fetch('/genoffice/index.html', { method: 'HEAD' });
    return response.ok;
  } catch {
    return false;
  }
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
export function GenOfficeFrame({ projectId, studyDefinitionId, actorId, savedDocument, onClose, api }) {
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const [confirmingClose, setConfirmingClose] = useState(false);
  // 一次会话冻结一次打开参数：savedDocument 在编辑器打开期间变化只更新外层
  // 展示，不重建 iframe（F03）。
  const [session, setSession] = useState(null);
  const openedOnce = useRef(false);

  const semanticDocUrl = `/api/projects/${encodeURIComponent(projectId)}/protocol-workflow/study-definitions/`
    + `${encodeURIComponent(studyDefinitionId)}/manuscript-draft/export/docx`;
  const snapshotsBase = `/api/projects/${encodeURIComponent(projectId)}/protocol-workflow/study-definitions/`
    + `${encodeURIComponent(studyDefinitionId)}/manuscript-draft/office-draft/snapshots`;

  async function beginSession() {
    if (!(await bundleInstalled())) {
      setNotice('Office编辑器尚未安装：先在仓库根目录运行 scripts/qc/protocol_v3/build_genoffice_renderer.sh 构建并安装渲染器。');
      return;
    }
    const revision = savedDocument.document?.revision ?? 1;
    const studySha = savedDocument.document?.study_definition_sha256 || '';
    let docUrl = semanticDocUrl;
    let officeRevision = null;
    try {
      const latest = await api?.latestOfficeSnapshot?.(projectId, studyDefinitionId);
      if (latest?.operation_id && latest?.artifact_revision) {
        docUrl = `${snapshotsBase}/${encodeURIComponent(latest.operation_id)}/content`;
        officeRevision = latest.artifact_revision;
      }
    } catch {
      // 尚无Office快照（404等）：从语义稿初始化。
    }
    const query = new URLSearchParams({
      docUrl,
      docName: `研究方案工作稿_第${revision}版.docx`,
      saveUrl: `${snapshotsBase}`,
      rev: String(revision),
      sha: savedDocument.document_sha256 || '',
      actor: actorId || 'medical_manager',
      openedStudySha: studySha,
    });
    setSession({ query: query.toString(), docUrl, revision, officeRevision, studySha });
    setOpen(true);
    setNotice('');
    openedOnce.current = true;
  }

  function requestClose() {
    // 渲染器内部 dirty 状态对宿主不可见：关闭前固定一次确认，杜绝无声丢弃。
    if (!confirmingClose) {
      setConfirmingClose(true);
      return;
    }
    setConfirmingClose(false);
    setOpen(false);
    setSession(null);
    openedOnce.current = false;
    onClose?.();
  }

  const params = session?.query ?? null;

  if (!savedDocument) return null;
  if (!open) {
    return <section className="gz-office-entry" aria-label="浏览器Office编辑">
      <button type="button" className="kz-manuscript-primary" onClick={beginSession}>在浏览器Office中打开工作稿（可编辑，保存为Office快照）</button>
      {notice && <p role="alert">{notice}</p>}
    </section>;
  }
  return <section className="gz-office-frame" aria-label="GenOffice编辑器">
    <header>
      <p>已打开{session.officeRevision
        ? `当前Office工作稿（快照版本 ${session.officeRevision}）`
        : `第 ${session.revision} 版工作稿（首次从语义稿初始化）`}。
        编辑器内保存会生成Office快照并在下次打开时延续；若另一窗口已保存新版本，
        您的保存会收到冲突提示而不会静默覆盖。</p>
      <div>
        <a href={session.docUrl} download>下载当前工作稿</a>
        <button type="button" onClick={requestClose}>
          {confirmingClose ? '再点一次确认关闭（未保存的修改将丢失）' : '关闭编辑器'}
        </button>
      </div>
    </header>
    {params && (
      <iframe
        title="GenOffice文档编辑器"
        src={`/genoffice/index.html?${params}`}
        onLoad={() => setNotice('')}
      />
    )}
  </section>;
}
