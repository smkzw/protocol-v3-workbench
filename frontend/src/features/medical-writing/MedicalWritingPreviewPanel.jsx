import { CheckCircle2, RefreshCw, ShieldAlert, X } from "lucide-react";

const PAGE_COUNT_BASIS_LABELS = Object.freeze({
  style_profile_estimate: "快速估算",
  microsoft_word_receipt: "Word已核验",
});

const PREVIEW_STATUS_LABELS = Object.freeze({
  fast_preview: "快速分页预览",
  word_verified: "Microsoft Word/PDF核验",
  stale: "核验已过期",
});

export function previewPageCountBasisLabel(basis) {
  return PAGE_COUNT_BASIS_LABELS[basis] || "待确认来源";
}

export function previewStatusLabel(status) {
  return PREVIEW_STATUS_LABELS[status] || "版式状态待确认";
}

export function previewPageSummary(page) {
  const sections = Array.isArray(page?.section_ids) ? page.section_ids.length : 0;
  const blocks = Array.isArray(page?.block_ids) ? page.block_ids.length : 0;
  return `${sections}个章节 · ${blocks}个内容块`;
}

function previewTone(preview) {
  if (preview?.page_count_basis === "microsoft_word_receipt") return "verified";
  if (preview?.preview_status === "stale") return "stale";
  return "estimated";
}

export function MedicalWritingPreviewPanel({
  preview,
  busy = false,
  message = "",
  onRefresh,
  onClose,
}) {
  if (!preview) return null;
  const tone = previewTone(preview);
  const pages = Array.isArray(preview.pages) ? preview.pages : [];
  const visiblePages = pages.slice(0, 8);
  const hiddenPageCount = Math.max(0, pages.length - visiblePages.length);
  const isVerified = preview.page_count_basis === "microsoft_word_receipt";
  const statusDescription = isVerified
    ? "当前页数来自同一方案快照的 Microsoft Word/PDF 核验，可作为最终版式依据。"
    : "当前页数是同一方案快照的快速估算，不等同于 Word 最终页数；封面、目录、表格跨页和版式节可能造成差异。";

  return (
    <section className={`medical-writing-preview-panel ${tone}`} aria-label="方案版式预览状态">
      <div className="medical-writing-preview-panel-header">
        <div>
          <span className="medical-writing-preview-eyebrow">版式状态</span>
          <strong>{previewStatusLabel(preview.preview_status)}</strong>
        </div>
        <div className="medical-writing-preview-panel-actions">
          <button type="button" onClick={onRefresh} disabled={busy} title="重新读取当前方案快照的版式状态">
            <RefreshCw size={13} /> {busy ? "读取中" : "刷新"}
          </button>
          <button type="button" className="medical-writing-preview-close" onClick={onClose} title="关闭版式状态面板" aria-label="关闭版式状态面板">
            <X size={14} />
          </button>
        </div>
      </div>
      <div className="medical-writing-preview-summary">
        <div className="medical-writing-preview-page-count">
          {isVerified ? <CheckCircle2 size={17} /> : <ShieldAlert size={17} />}
          <span><strong>{preview.page_count}页</strong><small>{previewPageCountBasisLabel(preview.page_count_basis)}</small></span>
        </div>
        <p>{statusDescription}</p>
      </div>
      {preview.warning && <p className="medical-writing-preview-warning">{preview.warning}</p>}
      {message && <p className="medical-writing-preview-message" role="alert">{message}</p>}
      <div className="medical-writing-preview-meta">
        <span>快照 <code>{String(preview.snapshot_sha256 || "").slice(0, 12) || "待生成"}…</code></span>
        <span>{preview.style_profile_id || "StyleProfile待确认"}</span>
      </div>
      {visiblePages.length > 0 && (
        <ol className="medical-writing-preview-pages" aria-label="方案页状态">
          {visiblePages.map((page) => (
            <li key={page.page_number}>
              <span>第{page.page_number}页</span>
              <small>{previewPageSummary(page)}</small>
            </li>
          ))}
        </ol>
      )}
      {hiddenPageCount > 0 && <p className="medical-writing-preview-more">其余 {hiddenPageCount} 页已折叠；需要最终页数请以 Word 核验为准。</p>}
    </section>
  );
}

