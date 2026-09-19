import { useMemo, useRef, useState } from 'react';
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
 * One-instance-one-iframe GenOffice docs runtime (T10/P3).
 *
 * The iframe boots the GenOffice docs renderer with our bridge shim: it opens
 * the exported working copy and every in-editor save lands as an immutable
 * office snapshot bound to the semantic revision that was current at open
 * time — a stale save surfaces a conflict instead of overwriting.
 */
export function GenOfficeFrame({ projectId, studyDefinitionId, actorId, savedDocument, onClose }) {
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const frameRef = useRef(null);
  const docUrl = `/api/projects/${encodeURIComponent(projectId)}/protocol-workflow/study-definitions/`
    + `${encodeURIComponent(studyDefinitionId)}/manuscript-draft/export/docx`;

  const params = useMemo(() => {
    if (!savedDocument) return null;
    const query = new URLSearchParams({
      docUrl,
      docName: `研究方案工作稿_第${savedDocument.document?.revision ?? 1}版.docx`,
      saveUrl: `/api/projects/${encodeURIComponent(projectId)}/protocol-workflow/study-definitions/`
        + `${encodeURIComponent(studyDefinitionId)}/manuscript-draft/office-draft/snapshots`,
      rev: String(savedDocument.document?.revision ?? 1),
      sha: savedDocument.document_sha256 || '',
      actor: actorId || 'medical_manager',
    });
    return query.toString();
  }, [projectId, studyDefinitionId, actorId, savedDocument, docUrl]);

  if (!savedDocument) return null;
  if (!open) {
    return <section className="gz-office-entry" aria-label="浏览器Office编辑">
      <button type="button" className="kz-manuscript-primary" onClick={async () => {
        if (!(await bundleInstalled())) {
          setNotice('Office编辑器尚未安装：先在仓库根目录运行 scripts/qc/protocol_v3/build_genoffice_renderer.sh 构建并安装渲染器。');
          return;
        }
        setOpen(true); setNotice('');
      }}>在浏览器Office中打开工作稿（可编辑，保存为Office快照）</button>
      {notice && <p role="alert">{notice}</p>}
    </section>;
  }
  return <section className="gz-office-frame" aria-label="GenOffice编辑器">
    <header>
      <p>已打开第 {savedDocument.document?.revision ?? 1} 版工作稿。编辑器内保存会生成Office快照；
        若此时正文在别处被修改，保存会提示冲突而不会覆盖。</p>
      <div>
        <a href={docUrl} download>下载当前Word</a>
        <button type="button" onClick={() => setOpen(false)}>关闭编辑器</button>
      </div>
    </header>
    <iframe
      ref={frameRef}
      title="GenOffice文档编辑器"
      src={`/genoffice/index.html?${params}`}
      onLoad={() => setNotice('')}
    />
  </section>;
}
