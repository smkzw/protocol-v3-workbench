import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ExternalLink, Filter, RefreshCw, Search, ShieldAlert } from "lucide-react";


const reviewLabels = {
  not_reviewed: ["待共享适用性确认", "warning"],
  approved: ["已确认可复用", "success"],
  returned: ["已退回", "warning"],
  rejected: ["已拒绝", "danger"],
};

const admissionLabels = {
  not_admitted: ["未准入", "neutral"],
  admitted: ["已纳入共享语料", "success"],
  invalidated: ["准入已失效", "danger"],
};

const modalityLabels = {
  monoclonal_antibody: "抗体类",
  bispecific_fusion_protein: "双特异性融合蛋白",
  engineered_biologic: "工程化生物制品",
  small_molecule: "小分子",
};

function requestKey(prefix) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}-${suffix}`;
}

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload;
  const detail = typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`;
  throw new Error(detail);
}

function StatusTag({ value, labels }) {
  const [label, tone] = labels[value] || [value || "待确认", "neutral"];
  return <span className={`tag ${tone}`}>{label}</span>;
}

export function SharedPhase1CorpusPanel() {
  const [catalog, setCatalog] = useState(null);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [modality, setModality] = useState("all");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");

  const load = async ({ preserveMessage = false } = {}) => {
    if (!preserveMessage) setMessage("");
    const params = new URLSearchParams({ query, status, modality });
    try {
      const payload = await fetch(`/api/medical-writing/shared-corpus/phase1?${params}`).then(readJson);
      setCatalog(payload);
      setSelectedId((current) => payload.items?.some((item) => item.segment_id === current)
        ? current
        : payload.items?.[0]?.segment_id || "");
    } catch (error) {
      setMessage(`共享语料读取失败：${error.message}`);
    }
  };

  useEffect(() => {
    const timer = globalThis.setTimeout(() => load(), 180);
    return () => globalThis.clearTimeout(timer);
  }, [query, status, modality]);

  const selected = useMemo(
    () => catalog?.items?.find((item) => item.segment_id === selectedId) || catalog?.items?.[0],
    [catalog, selectedId],
  );

  useEffect(() => setComment(""), [selected?.segment_id, selected?.medical_review_revision]);

  const run = async (key, action, successMessage) => {
    setBusy(key);
    setMessage("");
    try {
      const updated = await action();
      setSelectedId(updated.segment_id);
      await load({ preserveMessage: true });
      setMessage(successMessage);
      setComment("");
    } catch (error) {
      setMessage(`操作未完成：${error.message}`);
    } finally {
      setBusy("");
    }
  };

  const review = (decision) => run(
    `review-${decision}`,
    () => fetch(`/api/medical-writing/shared-corpus/phase1/${selected.segment_id}/medical-review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        comment: comment.trim(),
        actor: "medical_manager",
        expected_revision: selected.medical_review_revision,
        idempotency_key: requestKey("shared-phase1-review"),
      }),
    }).then(readJson),
    decision === "approved"
      ? "已确认该译文适合跨项目复用；仍需显式选择纳入共享语料。"
      : decision === "returned"
        ? "复用核对意见已记录；既有准入已立即失效。"
        : "该候选已拒绝，不会进入共享语料检索。",
  );

  const admit = () => run(
    "admit",
    () => fetch(`/api/medical-writing/shared-corpus/phase1/${selected.segment_id}/admissions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        medical_review_id: selected.medical_review_id,
        expected_review_revision: selected.medical_review_revision,
        actor: "medical_manager",
        idempotency_key: requestKey("shared-phase1-admission"),
      }),
    }).then(readJson),
    "当前作者确认版本已纳入I期共享语料；仅在I期且写作对象匹配时提供参考。",
  );

  return (
    <section className="shared-phase1-corpus" aria-label="I期共享语料适用性核对">
      <header className="shared-phase1-corpus-header">
        <div>
          <span>I期竞品方案语料</span>
          <strong>原文与监管中文共享适用性核对</strong>
          <small>只将作者已确认适合复用且显式准入的片段用于I期方案结构和措辞参考；药物、剂量、阈值、访视和终点仍以当前项目事实为准。</small>
        </div>
        <button type="button" className="icon-button" onClick={() => load()} title="刷新共享语料状态"><RefreshCw size={15} /></button>
      </header>
      <div className="shared-phase1-corpus-metrics">
        <span><b>{catalog?.item_count || 0}</b> 候选</span>
        <span><b>{catalog?.pending_review_count || 0}</b> 待适用性确认</span>
        <span><b>{catalog?.approved_count || 0}</b> 已确认可复用</span>
        <span><b>{catalog?.admitted_count || 0}</b> 已准入</span>
      </div>
      <div className="shared-phase1-corpus-filters">
        <label><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="检索NCT号、申办方、药物或正文" /></label>
        <label><Filter size={14} /><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">全部状态</option><option value="not_reviewed">待共享适用性确认</option><option value="approved">已确认可复用</option><option value="returned">已退回</option><option value="rejected">已拒绝</option><option value="admitted">已准入</option><option value="invalidated">准入已失效</option></select></label>
        <select value={modality} onChange={(event) => setModality(event.target.value)} aria-label="按药物类型筛选"><option value="all">全部药物类型</option>{Object.entries(modalityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      </div>
      {message && <p className={`shared-phase1-corpus-message ${message.includes("失败") || message.includes("未完成") ? "danger" : ""}`}>{message}</p>}
      <div className="shared-phase1-corpus-workspace">
        <nav aria-label="I期共享语料候选">
          {(catalog?.items || []).map((item) => (
            <button type="button" key={item.segment_id} className={item.segment_id === selected?.segment_id ? "active" : ""} onClick={() => setSelectedId(item.segment_id)}>
              <span><b>{item.nct_id}</b><StatusTag value={item.medical_review_status} labels={reviewLabels} /></span>
              <strong>{item.compound}</strong>
              <small>{item.sponsor} · {modalityLabels[item.modality] || item.modality}</small>
              <small>{item.conditions.join("、")}</small>
            </button>
          ))}
          {!catalog?.items?.length && <p>当前筛选条件下没有候选。</p>}
        </nav>
        {selected ? <article className="shared-phase1-corpus-detail">
          <header>
            <div><span>{selected.nct_id} · {selected.phases.join("/")}</span><strong>{selected.compound}</strong><small>{selected.corpus_function} · {selected.ich_m11_anchor}</small></div>
            <div><StatusTag value={selected.medical_review_status} labels={reviewLabels} /><StatusTag value={selected.admission_status} labels={admissionLabels} /></div>
          </header>
          <p className="shared-phase1-applicability"><ShieldAlert size={15} /><span><b>适用边界</b>{selected.applicability}</span></p>
          <div className="shared-phase1-text-compare">
            <section><header><strong>Protocol原文</strong><a href={selected.source_url} target="_blank" rel="noreferrer" title="打开ClinicalTrials.gov官方文件"><ExternalLink size={14} />官方文件</a></header><p lang="en">{selected.source_text}</p></section>
            <section><header><strong>监管中文候选</strong><span>{selected.model_name} · {selected.prompt_version}</span></header><p>{selected.translated_text}</p></section>
          </div>
          <details className="shared-phase1-lineage"><summary>来源与版本</summary><dl><div><dt>原文定位</dt><dd>{selected.source_locator}</dd></div><div><dt>方案版本</dt><dd>{selected.protocol_version || selected.document_date || "见官方文件"}</dd></div><div><dt>词典</dt><dd>{selected.glossary_version}</dd></div><div><dt>AI运行</dt><dd>{selected.ai_run_id}</dd></div></dl></details>
          {selected.medical_review_comment && <p className="shared-phase1-review-comment"><b>当前复用核对意见</b>{selected.medical_review_comment}</p>}
          <div className="shared-phase1-review-actions">
            {selected.medical_review_status === "approved" && selected.admission_status !== "admitted" ? (
              <button type="button" className="primary-button" onClick={admit} disabled={Boolean(busy)}><CheckCircle2 size={14} />{busy === "admit" ? "准入中" : "纳入I期共享语料"}</button>
            ) : <>
              <label><span>{selected.admission_status === "admitted" ? "撤回理由" : "共享适用性核对意见"}</span><textarea rows={3} value={comment} onChange={(event) => setComment(event.target.value)} placeholder={selected.admission_status === "admitted" ? "说明新发现的医学、翻译或适用性问题；确认后准入立即失效。" : "对照原文确认医学含义、数字、单位、时序、否定关系和跨项目适用边界。"} /></label>
              <div>
                {selected.admission_status === "admitted" ? <button type="button" onClick={() => review("returned")} disabled={comment.trim().length < 2 || Boolean(busy)}>撤回并退回修订</button> : <>
                  <button type="button" className="primary-button" onClick={() => review("approved")} disabled={comment.trim().length < 2 || Boolean(busy)}>确认可复用</button>
                  <button type="button" onClick={() => review("returned")} disabled={comment.trim().length < 2 || Boolean(busy)}>退回修改</button>
                  <button type="button" onClick={() => review("rejected")} disabled={comment.trim().length < 2 || Boolean(busy)}>拒绝</button>
                </>}
              </div>
            </>}
          </div>
        </article> : <div className="shared-phase1-corpus-empty">选择候选后对照原文和监管中文。</div>}
      </div>
    </section>
  );
}
