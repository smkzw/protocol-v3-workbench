import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookPlus,
  CheckCircle2,
  ExternalLink,
  RefreshCw,
  Search,
} from "lucide-react";


function requestKey(prefix) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}-${suffix}`;
}


async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload;
  const error = new Error(typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`);
  error.status = response.status;
  throw error;
}


function validationLabel(status) {
  return {
    confirmed: ["信息完整", "success"],
    needs_review: ["信息待补", "warning"],
    overridden: ["医学确认", "info"],
  }[status] || ["待确认", "warning"];
}


function referenceAuthorYear(reference) {
  const author = reference.authors?.[0] || "作者待补";
  return `${author}${reference.authors?.length > 1 ? " 等" : ""} · ${reference.year || "年份待补"}`;
}


export function MedicalWritingLiteraturePanel({ projectId, onInsertReference = () => {} }) {
  const activeProjectRef = useRef(projectId);
  const [library, setLibrary] = useState(null);
  const [sourceInput, setSourceInput] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [manualMetadata, setManualMetadata] = useState({
    title: "",
    authors: "",
    journal: "",
    year: "",
    url: "",
  });
  const [overrideReason, setOverrideReason] = useState("");

  const refresh = async ({ preserveMessage = false } = {}) => {
    const requestedProject = projectId;
    setBusy((current) => current || "refresh");
    if (!preserveMessage) setMessage("");
    try {
      const payload = await fetch(`/api/projects/${projectId}/medical-writing/literature`).then(readJson);
      if (activeProjectRef.current !== requestedProject) return;
      setLibrary(payload);
    } catch (error) {
      if (activeProjectRef.current === requestedProject) setMessage(`文献库读取失败：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestedProject) setBusy("");
    }
  };

  useEffect(() => {
    activeProjectRef.current = projectId;
    setLibrary(null);
    setSourceInput("");
    setQuery("");
    setMessage("");
    setManualMetadata({ title: "", authors: "", journal: "", year: "", url: "" });
    setOverrideReason("");
    refresh();
  }, [projectId]);

  const references = library?.references || [];
  const visibleReferences = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return references;
    return references.filter((reference) => [
      reference.title,
      reference.journal,
      reference.year,
      reference.doi,
      reference.pmid,
      ...(reference.authors || []),
    ].some((value) => String(value || "").toLowerCase().includes(needle)));
  }, [references, query]);

  const importReference = async ({ override = false } = {}) => {
    if (!sourceInput.trim()) return;
    const requestedProject = projectId;
    setBusy(override ? "override" : "import");
    setMessage("");
    try {
      const payload = await fetch(`/api/projects/${projectId}/medical-writing/literature/imports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_input: sourceInput.trim(),
          manual_metadata: override ? {
            ...manualMetadata,
            authors: manualMetadata.authors.split(/[，,;；]/).map((item) => item.trim()).filter(Boolean),
          } : null,
          override_validation: override,
          override_reason: override ? overrideReason.trim() : "",
          actor: "medical_manager",
          idempotency_key: requestKey(override ? "literature-override" : "literature-import"),
        }),
      }).then(readJson);
      if (activeProjectRef.current !== requestedProject) return;
      setMessage(payload.created
        ? "文献已加入当前项目文献库。"
        : `已与现有文献合并（按${payload.matched_on.toUpperCase()}识别）。`);
      setSourceInput("");
      setManualMetadata({ title: "", authors: "", journal: "", year: "", url: "" });
      setOverrideReason("");
      await refresh({ preserveMessage: true });
    } catch (error) {
      if (activeProjectRef.current === requestedProject) setMessage(`文献导入失败：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestedProject) setBusy("");
    }
  };

  const canOverride = sourceInput.trim()
    && manualMetadata.title.trim()
    && overrideReason.trim().length >= 10;

  return (
    <section className="medical-literature-panel" aria-label="项目文献库">
      <header>
        <div>
          <span>项目文献库</span>
          <strong>{references.length} 条可追溯文献</strong>
        </div>
        <button className="icon-button" onClick={() => refresh()} disabled={Boolean(busy)} title="刷新项目文献库">
          <RefreshCw size={16} />
        </button>
      </header>

      <div className="medical-literature-import">
        <label>
          DOI、PMID 或文献官网链接
          <div>
            <input value={sourceInput} onChange={(event) => setSourceInput(event.target.value)} placeholder="例如 10.1016/... 或 PMID: 33957195" />
            <button className="primary-button" onClick={() => importReference()} disabled={Boolean(busy) || !sourceInput.trim()}>
              <BookPlus size={15} /> {busy === "import" ? "读取中" : "导入"}
            </button>
          </div>
        </label>
        <label>
          当前项目引文格式
          <select value="gbt_7714_2015_numeric" disabled title="当前生产导出固定使用 GB/T 7714-2015 顺序编码制">
            <option value="gbt_7714_2015_numeric">GB/T 7714-2015 顺序编码制</option>
          </select>
        </label>
        <details>
          <summary>官网链接无法自动识别时，手动确认基本信息</summary>
          <div className="medical-literature-manual-grid">
            <label>题名<input value={manualMetadata.title} onChange={(event) => setManualMetadata((current) => ({ ...current, title: event.target.value }))} /></label>
            <label>作者<input value={manualMetadata.authors} onChange={(event) => setManualMetadata((current) => ({ ...current, authors: event.target.value }))} placeholder="多位作者用逗号分隔" /></label>
            <label>期刊<input value={manualMetadata.journal} onChange={(event) => setManualMetadata((current) => ({ ...current, journal: event.target.value }))} /></label>
            <label>年份<input value={manualMetadata.year} onChange={(event) => setManualMetadata((current) => ({ ...current, year: event.target.value }))} /></label>
            <label className="span-2">文献官网链接<input value={manualMetadata.url} onChange={(event) => setManualMetadata((current) => ({ ...current, url: event.target.value }))} /></label>
            <label className="span-2">医学确认理由<textarea value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} placeholder="说明已核对的原始页面及确认依据，至少10个字" /></label>
          </div>
          <button onClick={() => importReference({ override: true })} disabled={Boolean(busy) || !canOverride}>确认信息并导入</button>
        </details>
      </div>

      {message && <p className={`medical-literature-message ${message.includes("失败") ? "danger" : ""}`}>{message}</p>}

      <label className="medical-literature-search">
        <Search size={15} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按题名、作者、期刊、DOI 或 PMID 搜索" />
      </label>

      <div className="medical-literature-list">
        {visibleReferences.map((reference) => {
          const [label, tone] = validationLabel(reference.validation_status);
          const citable = reference.validation_status !== "needs_review";
          return (
            <article key={reference.reference_id}>
              <header>
                <span className={`tag ${tone}`}>{label}</span>
                <span>{referenceAuthorYear(reference)}</span>
              </header>
              <strong>{reference.title}</strong>
              <p>{[reference.journal, reference.volume, reference.issue, reference.pages].filter(Boolean).join(" · ")}</p>
              <footer>
                <span>{reference.doi ? `DOI ${reference.doi}` : reference.pmid ? `PMID ${reference.pmid}` : "官网元数据"}</span>
                <div>
                  {reference.url && <a href={reference.url} target="_blank" rel="noreferrer" title="打开文献来源"><ExternalLink size={14} /></a>}
                  <button
                    onClick={() => {
                      const insertionMessage = onInsertReference(reference);
                      if (insertionMessage) setMessage(insertionMessage);
                    }}
                    disabled={!citable}
                    title={citable ? "在当前光标处插入引文" : "请先补全或医学确认缺失元数据"}
                  >
                    {citable ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />} 插入引文
                  </button>
                </div>
              </footer>
              {reference.validation_warnings?.length > 0 && <small>{reference.validation_warnings.join("；")}</small>}
            </article>
          );
        })}
        {!visibleReferences.length && <div className="empty-state">当前项目尚无匹配文献。</div>}
      </div>
    </section>
  );
}
