import { useMemo, useRef, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronUp } from "lucide-react";

function requestKey() {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `ocr-consistency-confirm-${suffix}`;
}

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload;
  throw new Error(typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`);
}

export function MixedOcrReviewPanel({
  projectId,
  reviews = [],
  artifacts = [],
  onSettled = () => {},
}) {
  const keyRef = useRef("");
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const artifactsById = useMemo(
    () => new Map(artifacts.map((item) => [item.artifact_id, item])),
    [artifacts],
  );
  const pending = useMemo(
    () => reviews.filter((item) => (
      item.effective_status === "pending_medical_confirmation"
      && item.recheck_verdict === "review_required"
    )),
    [reviews],
  );

  if (!pending.length) return null;

  const confirmAll = async () => {
    setBusy(true);
    setMessage("");
    if (!keyRef.current) keyRef.current = requestKey();
    try {
      const response = await fetch(
        `/api/projects/${projectId}/medical-writing/references/ocr-consistency-reviews/batch-disposition`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision: "confirmed",
            comment: "已核对当前批次中 AI 定位的 OCR 衔接差异，同意按原始页面与已保存提取结果继续进入翻译和语料库流程。",
            actor: "medical_manager",
            idempotency_key: keyRef.current,
          }),
        },
      );
      const payload = await readJson(response);
      const failed = (payload.outcomes || []).filter((item) => (
        item.outcome === "failed" || item.outcome === "stale"
      ));
      if (failed.length) {
        setMessage(`${failed.length} 项状态已变化，请刷新后重试。`);
      } else {
        keyRef.current = "";
        setMessage("已批量确认，相关方案可继续进入翻译与语料库流程。");
        onSettled(payload);
      }
    } catch (error) {
      setMessage(`批量确认未完成：${error.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mixed-ocr-review-panel" data-testid="mixed-ocr-review-panel">
      <div className="mixed-ocr-review-summary">
        <div>
          <strong>{pending.length} 份方案的 OCR 衔接需确认</strong>
          <span>AI 已聚焦到具体页面；确认后可一次性继续后续流程。</span>
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={() => setExpanded((current) => !current)}
          aria-expanded={expanded}
        >
          {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          {expanded ? "收起" : "查看差异"}
        </button>
        <button
          type="button"
          className="primary-button"
          onClick={confirmAll}
          disabled={busy}
        >
          <CheckCircle2 size={15} />
          {busy ? "确认中…" : "批量确认并继续"}
        </button>
      </div>
      {expanded && (
        <div className="mixed-ocr-review-details">
          {pending.map((item) => {
            const artifact = artifactsById.get(item.artifact_id);
            return (
              <article key={`${item.artifact_id}-${item.recheck_id}`}>
                <div>
                  <strong>{artifact?.nct_id || "已导入方案"}</strong>
                  <span>{artifact?.filename || item.artifact_id}</span>
                </div>
                <p>{item.recheck_notes || "AI 建议对当前 OCR 衔接结果进行快速核对。"}</p>
              </article>
            );
          })}
        </div>
      )}
      {message && <p className="mixed-ocr-review-message">{message}</p>}
    </section>
  );
}
