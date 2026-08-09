import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

/**
 * Sort assessment-instrument appendix pages deterministically by page_number.
 * Does not copy or transform image_base64 payloads.
 */
export function orderInstrumentAppendixPages(pages = []) {
  return [...(pages || [])]
    .filter((block) => block && block.block_type === "appendix_image")
    .sort((left, right) => {
      const leftPage = Number(left.page_number) || 0;
      const rightPage = Number(right.page_number) || 0;
      if (leftPage !== rightPage) return leftPage - rightPage;
      return String(left.block_id || "").localeCompare(String(right.block_id || ""));
    });
}

export function imageDataUrl(block) {
  if (!block?.image_base64) return "";
  const mediaType = block.media_type || "image/png";
  return `data:${mediaType};base64,${block.image_base64}`;
}

/**
 * Real per-page assessment-instrument appendix preview.
 * Thumbnails use lazy loading; the enlarged overlay mounts only the current page image.
 * Page index state never stores base64 copies.
 */
export function InstrumentAppendixPreview({
  pages = [],
  declaredPageCount = null,
  instrumentLabel = "量表附件",
  emptyMessage = "",
}) {
  const orderedPages = useMemo(() => orderInstrumentAppendixPages(pages), [pages]);
  const actualCount = orderedPages.length;
  const declared = Number(declaredPageCount) || Number(orderedPages[0]?.page_count) || actualCount;
  const hasMismatch = actualCount > 0 && declared > 0 && declared !== actualCount;
  const [reviewIndex, setReviewIndex] = useState(null);

  useEffect(() => {
    setReviewIndex(null);
  }, [pages]);

  useEffect(() => {
    if (reviewIndex === null) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setReviewIndex(null);
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setReviewIndex((current) => (current === null ? null : Math.max(0, current - 1)));
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        setReviewIndex((current) => (
          current === null ? null : Math.min(actualCount - 1, current + 1)
        ));
      }
    };
    globalThis.addEventListener?.("keydown", onKeyDown);
    return () => globalThis.removeEventListener?.("keydown", onKeyDown);
  }, [reviewIndex, actualCount]);

  if (!actualCount) {
    if (!emptyMessage) return null;
    return (
      <div className="instrument-appendix-preview is-empty" data-testid="instrument-appendix-preview" data-page-count="0">
        <p>{emptyMessage}</p>
      </div>
    );
  }

  const openIndex = reviewIndex === null ? -1 : Math.min(Math.max(reviewIndex, 0), actualCount - 1);
  const currentPage = openIndex >= 0 ? orderedPages[openIndex] : null;
  const currentSrc = currentPage ? imageDataUrl(currentPage) : "";

  return (
    <section
      className="instrument-appendix-preview"
      data-testid="instrument-appendix-preview"
      data-page-count={String(actualCount)}
      aria-label={`${instrumentLabel}逐页预览`}
    >
      <header className="instrument-appendix-preview-head">
        <strong>原始页面预览</strong>
        <span>{actualCount} 页可审阅</span>
      </header>
      {hasMismatch && (
        <p className="instrument-appendix-consistency-notice" role="status" data-testid="appendix-page-count-mismatch">
          附件声明 {declared} 页，当前工作副本实际可读 {actualCount} 页；按实际页序审阅，不阻断核对。
        </p>
      )}
      <div className="instrument-appendix-thumbnail-grid" role="list">
        {orderedPages.map((block, index) => {
          const pageNumber = Number(block.page_number) || index + 1;
          const src = imageDataUrl(block);
          return (
            <button
              key={block.block_id || `page-${pageNumber}-${index}`}
              type="button"
              className="instrument-appendix-thumbnail"
              role="listitem"
              data-page-number={String(pageNumber)}
              data-testid={`appendix-thumbnail-${pageNumber}`}
              onClick={() => setReviewIndex(index)}
              title={`查看第 ${pageNumber} 页`}
              aria-label={`查看${instrumentLabel}第 ${pageNumber} 页，共 ${actualCount} 页`}
            >
              {src ? (
                <img
                  src={src}
                  alt={`${instrumentLabel}第 ${pageNumber} 页缩略图`}
                  loading="lazy"
                  decoding="async"
                />
              ) : (
                <span className="instrument-appendix-thumbnail-missing">第 {pageNumber} 页图像不可用</span>
              )}
              <em>{pageNumber}/{actualCount}</em>
            </button>
          );
        })}
      </div>

      {currentPage && openIndex >= 0 && (
        <div
          className="instrument-appendix-review-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={`${instrumentLabel}第 ${currentPage.page_number || openIndex + 1} 页放大审阅`}
          data-testid="instrument-appendix-review-overlay"
          data-review-index={String(openIndex)}
        >
          <div className="instrument-appendix-review-backdrop" onClick={() => setReviewIndex(null)} />
          <div className="instrument-appendix-review-panel">
            <header>
              <div>
                <span>放大审阅</span>
                <strong>
                  第 {Number(currentPage.page_number) || openIndex + 1} 页 / 共 {actualCount} 页
                </strong>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={() => setReviewIndex(null)}
                title="关闭放大审阅"
                aria-label="关闭放大审阅"
                data-action="close-appendix-review"
              >
                <X size={16} />
              </button>
            </header>
            <div className="instrument-appendix-review-stage">
              {/* Only the current full-page image is mounted; base64 is read from the source block. */}
              {currentSrc ? (
                <img
                  key={currentPage.block_id || `review-${openIndex}`}
                  src={currentSrc}
                  alt={`${instrumentLabel}第 ${currentPage.page_number || openIndex + 1} 页`}
                  data-testid="instrument-appendix-review-image"
                  data-page-number={String(currentPage.page_number || openIndex + 1)}
                />
              ) : (
                <p>当前页图像不可用。</p>
              )}
            </div>
            <footer className="instrument-appendix-review-controls">
              <button
                type="button"
                onClick={() => setReviewIndex((current) => Math.max(0, (current ?? 0) - 1))}
                disabled={openIndex <= 0}
                data-action="appendix-prev"
                aria-label="上一页"
              >
                <ChevronLeft size={15} /> 上一页
              </button>
              <label className="instrument-appendix-page-selector">
                <span>页码</span>
                <select
                  value={String(openIndex)}
                  onChange={(event) => setReviewIndex(Number(event.target.value))}
                  aria-label="选择页码"
                  data-testid="appendix-page-selector"
                >
                  {orderedPages.map((block, index) => (
                    <option key={block.block_id || index} value={String(index)}>
                      第 {Number(block.page_number) || index + 1} 页
                    </option>
                  ))}
                </select>
              </label>
              <span className="instrument-appendix-page-indicator" data-testid="appendix-page-indicator">
                {openIndex + 1} / {actualCount}
              </span>
              <button
                type="button"
                onClick={() => setReviewIndex((current) => Math.min(actualCount - 1, (current ?? 0) + 1))}
                disabled={openIndex >= actualCount - 1}
                data-action="appendix-next"
                aria-label="下一页"
              >
                下一页 <ChevronRight size={15} />
              </button>
            </footer>
          </div>
        </div>
      )}
    </section>
  );
}

export default InstrumentAppendixPreview;
