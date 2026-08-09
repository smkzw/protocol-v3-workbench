import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  FileCheck2,
  FileText,
  RefreshCw,
  ShieldAlert,
  X,
} from "lucide-react";

const ACTOR = "medical_manager";

const LEGACY_BOOTSTRAP_CONFIRMED_PATHS = Object.freeze([
  "framing.protocol_id",
  "framing.version",
  "framing.document_title",
  "framing.indication",
  "framing.study_phase",
  "framing.investigational_product",
  "framing.target_mechanism",
  "framing.design_pattern",
  "framing.population_intent",
  "picos.population_summary",
  "picos.intervention_summary",
  "picos.comparator_summary",
  "picos.primary_endpoint",
]);

function apiErrorText(error) {
  return String(error?.detail || error?.message || error || "请求失败");
}

async function readJsonOrThrow(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload?.detail || `请求失败（${response.status}）`);
    error.status = response.status;
    error.detail = payload?.detail || "";
    throw error;
  }
  return payload;
}

function roleLabel(role) {
  return role === "synopsis" ? "方案摘要" : "完整研究方案";
}

function extractionStageLabel(jobStatus) {
  return {
    queued: "等待独立AI处理",
    parsing: "正在解析文件内容",
    ai_synthesis: "正在提取研究设计",
    validating: "正在合并并核对结果",
  }[jobStatus] || "正在处理原始文件";
}

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function warningList(candidate) {
  return Array.from(new Set(
    (candidate?.source?.validation_warnings || []).filter(Boolean),
  ));
}

function storageKey(projectId) {
  return `mw-legacy-bootstrap:${projectId}`;
}

function readStoredImportKey(projectId) {
  try {
    return globalThis.sessionStorage?.getItem(storageKey(projectId)) || "";
  } catch {
    return "";
  }
}

function writeStoredImportKey(projectId, value) {
  try {
    globalThis.sessionStorage?.setItem(storageKey(projectId), value);
  } catch {
    // The server-side idempotency key still protects the active request.
  }
}

function clearStoredImportKey(projectId) {
  try {
    globalThis.sessionStorage?.removeItem(storageKey(projectId));
  } catch {
    // A blocked session store must not make the import workflow unusable.
  }
}

function TextField({
  fieldPath,
  label,
  value,
  onChange,
  wide = false,
  multiline = false,
}) {
  const confirmedPath = LEGACY_BOOTSTRAP_CONFIRMED_PATHS.includes(fieldPath)
    ? fieldPath
    : undefined;
  return (
    <label className={wide ? "span-2" : ""} data-confirmed-path={confirmedPath}>
      <span>{label}</span>
      {multiline
        ? <textarea rows={3} value={value || ""} onChange={(event) => onChange(event.target.value)} />
        : <input value={value || ""} onChange={(event) => onChange(event.target.value)} />}
    </label>
  );
}

export function LegacyAuthoringBootstrapPanel({
  projectId,
  expectedIndication = "",
  onConfirmed,
  onOpenBinding,
}) {
  const [status, setStatus] = useState(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [importKey, setImportKey] = useState("");
  const [framing, setFraming] = useState(null);
  const [picos, setPicos] = useState(null);
  const [synopsisText, setSynopsisText] = useState("");
  const [confirmedRole, setConfirmedRole] = useState("protocol");
  const [roleOverrideReason, setRoleOverrideReason] = useState("");
  const [acknowledgedWarnings, setAcknowledgedWarnings] = useState([]);
  const [validationOverrideReason, setValidationOverrideReason] = useState("");
  const requestRef = useRef(0);

  const detectedRole = status?.detected_source_role || status?.source_role || "protocol";
  const warnings = useMemo(() => warningList(status?.candidate), [status?.candidate]);
  const roleOverridden = Boolean(confirmedRole && confirmedRole !== detectedRole);
  const allWarningsAcknowledged = warnings.every((warning) => acknowledgedWarnings.includes(warning));
  const missingCoreFields = useMemo(() => {
    if (!framing || !picos) return [];
    const fields = [
      ["方案号", framing.protocol_id],
      ["版本", framing.version],
      ["方案标题", framing.document_title],
      ["适应症", framing.indication],
      ["研究分期", framing.study_phase],
      ["试验药物", framing.investigational_product],
      ["总体设计", framing.design_pattern],
      ["目标研究人群", framing.population_intent],
      ["研究人群", picos.population_summary],
      ["干预措施", picos.intervention_summary],
      ["主要终点及评价时间", picos.primary_endpoint],
      ["方案摘要文本", synopsisText],
    ];
    return fields.filter(([, value]) => !String(value || "").trim()).map(([label]) => label);
  }, [framing, picos, synopsisText]);
  const confirmationReady = Boolean(
    status?.state === "review_pending"
      && status?.candidate?.source?.source_id
      && framing
      && picos
      && synopsisText.trim()
      && missingCoreFields.length === 0
      && allWarningsAcknowledged
      && (!warnings.length || validationOverrideReason.trim().length >= 10)
      && (!roleOverridden || roleOverrideReason.trim().length >= 10)
  );

  const loadStatus = async (key = importKey, { quiet = false } = {}) => {
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    if (!quiet) setBusy("loading");
    try {
      const query = key ? `?import_idempotency_key=${encodeURIComponent(key)}` : "";
      const payload = await fetch(
        `/api/projects/${projectId}/medical-writing/legacy-authoring-bootstrap${query}`,
      ).then(readJsonOrThrow);
      if (requestId !== requestRef.current) return null;
      setStatus(payload);
      setConfirmedRole(
        payload.confirmed_source_role
          || payload.author_confirmed_source_role
          || payload.source_role
          || "protocol",
      );
      if (payload.import_idempotency_key) {
        setImportKey(payload.import_idempotency_key);
        writeStoredImportKey(projectId, payload.import_idempotency_key);
      }
      if (payload.candidate) {
        setFraming(clone(payload.candidate.proposed_framing));
        setPicos(clone(payload.candidate.proposed_picos));
        setSynopsisText(payload.candidate.proposed_synopsis_text || "");
      }
      if (["bound", "not_eligible"].includes(payload.state)) {
        clearStoredImportKey(projectId);
      }
      setMessage(payload.message || "");
      return payload;
    } catch (error) {
      if (requestId !== requestRef.current) return null;
      setMessage(apiErrorText(error));
      return null;
    } finally {
      if (requestId === requestRef.current && !quiet) setBusy("");
    }
  };

  useEffect(() => {
    const stored = readStoredImportKey(projectId);
    setImportKey(stored);
    loadStatus(stored);
    return () => {
      requestRef.current += 1;
    };
    // The bootstrap source is scoped by project and immutable source hash.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    if (!["extracting"].includes(status?.state) || !importKey) return undefined;
    let cancelled = false;
    let timer;
    const poll = async () => {
      await loadStatus(importKey, { quiet: true });
      if (!cancelled) timer = globalThis.setTimeout(poll, 3000);
    };
    timer = globalThis.setTimeout(poll, 3000);
    return () => {
      cancelled = true;
      globalThis.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.state, importKey]);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    globalThis.addEventListener?.("keydown", handleKeyDown);
    return () => globalThis.removeEventListener?.("keydown", handleKeyDown);
  }, [open]);

  useEffect(() => {
    setAcknowledgedWarnings([]);
    setValidationOverrideReason("");
  }, [
    status?.candidate?.source?.content_sha256,
    status?.candidate?.source?.extraction_revision,
  ]);

  const startExtraction = async () => {
    if (!status?.document_id || !status?.source_sha256) return;
    const retrySuffix = status.state === "failed" ? `-${Date.now()}` : "";
    const key = `legacy-extract-${projectId}-${status.source_sha256.slice(0, 16)}${retrySuffix}`.slice(0, 200);
    setBusy("prepare");
    setMessage("");
    try {
      const payload = await fetch(
        `/api/projects/${projectId}/medical-writing/legacy-authoring-bootstrap/prepare`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_document_id: status.document_id,
            expected_source_sha256: status.source_sha256,
            expected_indication: expectedIndication || "",
            actor: ACTOR,
            idempotency_key: key,
          }),
        },
      ).then(readJsonOrThrow);
      setImportKey(payload.import_idempotency_key || key);
      writeStoredImportKey(projectId, payload.import_idempotency_key || key);
      setStatus(payload);
      setMessage("正在从原始文件提取研究框架、PICOS和方案摘要。");
    } catch (error) {
      setMessage(apiErrorText(error));
    } finally {
      setBusy("");
    }
  };

  const updateFraming = (field, value) => {
    setFraming((current) => ({ ...current, [field]: value }));
  };

  const updatePicos = (field, value) => {
    setPicos((current) => ({ ...current, [field]: value }));
  };

  const toggleWarning = (warning) => {
    setAcknowledgedWarnings((current) => (
      current.includes(warning)
        ? current.filter((item) => item !== warning)
        : [...current, warning]
    ));
  };

  const confirmCandidate = async () => {
    if (!confirmationReady) return;
    setBusy("confirm");
    setMessage("");
    try {
      const payload = await fetch(
        `/api/projects/${projectId}/medical-writing/legacy-authoring-bootstrap/confirm`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_document_id: status.document_id,
            expected_source_sha256: status.source_sha256,
            import_idempotency_key: importKey,
            source_id: status.candidate.source.source_id,
            framing,
            picos,
            synopsis_text: synopsisText,
            confirmed_source_role: confirmedRole,
            source_role_override_reason: roleOverridden ? roleOverrideReason.trim() : "",
            acknowledged_validation_warnings: acknowledgedWarnings,
            validation_override_reason: warnings.length ? validationOverrideReason.trim() : "",
            actor: ACTOR,
            idempotency_key: `legacy-confirm-${projectId}-${status.source_sha256.slice(0, 16)}`.slice(0, 200),
          }),
        },
      ).then(readJsonOrThrow);
      setStatus(payload);
      clearStoredImportKey(projectId);
      setMessage("研究设计基线已建立；原始文件保持只读，下一步核对影响并重绑定。");
      await onConfirmed?.(payload);
    } catch (error) {
      setMessage(apiErrorText(error));
    } finally {
      setBusy("");
    }
  };

  if (!status || ["bound", "not_eligible"].includes(status.state)) return null;

  return (
    <>
      <section className={`legacy-bootstrap-bar ${status.state === "failed" ? "is-error" : ""}`}>
        <div>
          {status.state === "confirmed_ready_for_binding"
            ? <CheckCircle2 size={17} />
            : status.state === "failed"
              ? <ShieldAlert size={17} />
              : <FileText size={17} />}
          <span>
            <strong>
              {status.state === "confirmed_ready_for_binding"
                ? "已从原始方案建立研究设计基线"
                : status.state === "extracting"
                  ? "正在解析原始方案"
                  : status.state === "review_pending"
                    ? "研究设计候选待作者核对"
                    : status.state === "failed"
                      ? "原始方案解析未完成"
                      : "原始方案尚未建立研究设计基线"}
            </strong>
            <small>
              {status.source_filename || "原始方案"}
              {` · 系统识别为${roleLabel(detectedRole)}`}
            </small>
          </span>
        </div>
        {status.state === "confirmed_ready_for_binding"
          ? <button type="button" onClick={onOpenBinding}><FileCheck2 size={14} /> 核对影响并重绑定</button>
          : <button type="button" onClick={() => setOpen(true)}>
            {status.state === "review_pending" ? "核对提取结果" : status.state === "extracting" ? "查看进度" : "建立研究设计基线"}
          </button>}
      </section>

      {open && (
        <div className="legacy-bootstrap-layer" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setOpen(false);
        }}>
          <aside className="legacy-bootstrap-drawer" role="dialog" aria-modal="true" aria-label="原始方案研究设计基线">
            <header>
              <div>
                <span>原始方案导入</span>
                <strong>建立可追溯的研究设计基线</strong>
              </div>
              <button type="button" onClick={() => setOpen(false)} title="关闭"><X size={18} /></button>
            </header>

            <div className="legacy-bootstrap-source">
              <FileText size={18} />
              <span>
                <strong title={status.source_filename}>{status.source_filename}</strong>
                <small>原始文件只读 · {status.source_sha256?.slice(0, 12)}…</small>
              </span>
              <em>{roleLabel(detectedRole)}</em>
            </div>

            {status.state === "eligible" || status.state === "failed" ? (
              <section className="legacy-bootstrap-start">
                <p>独立AI将提取研究框架、PICOS和方案摘要；完成后直接核对并修订候选。</p>
                {message && <small className={status.state === "failed" ? "danger" : ""}>{message}</small>}
                <button type="button" className="primary-button" onClick={startExtraction} disabled={Boolean(busy)}>
                  <RefreshCw size={15} /> {busy === "prepare" ? "正在启动" : status.state === "failed" ? "重新解析" : "AI提取研究设计"}
                </button>
              </section>
            ) : status.state === "extracting" ? (
              <section className="legacy-bootstrap-progress" aria-live="polite">
                <RefreshCw size={20} className="spin" />
                <strong>{extractionStageLabel(status.job_status)}</strong>
                <span>可关闭面板继续其他工作，完成后将自动显示可编辑候选。</span>
                <ol aria-label="提取进度">
                  <li className="is-complete"><CheckCircle2 size={14} /> 文件解析</li>
                  <li className={status.job_status === "validating" ? "is-complete" : "is-active"}>
                    {status.job_status === "validating"
                      ? <CheckCircle2 size={14} />
                      : <RefreshCw size={14} className="spin" />}
                    研究设计提取
                  </li>
                  <li className={status.job_status === "validating" ? "is-active" : ""}>
                    <FileCheck2 size={14} /> 合并核对
                  </li>
                </ol>
              </section>
            ) : status.state === "review_pending" && framing && picos ? (
              <div className="legacy-bootstrap-review">
                <section className="legacy-bootstrap-role">
                  <div>
                    <strong>文件角色</strong>
                    <small>系统识别只作为建议；您的选择即为本项目确认。</small>
                  </div>
                  <select value={confirmedRole} onChange={(event) => setConfirmedRole(event.target.value)}>
                    <option value="protocol">完整研究方案</option>
                    <option value="synopsis">方案摘要</option>
                  </select>
                  {roleOverridden && (
                    <label>
                      <span>调整理由</span>
                      <textarea rows={2} value={roleOverrideReason} onChange={(event) => setRoleOverrideReason(event.target.value)} placeholder="说明为何原文件应按所选角色使用；不少于10个字符。" />
                    </label>
                  )}
                </section>

                <section>
                  <header><strong>研究基本信息</strong><small>AI已预填；仅修订不准确处。</small></header>
                  <div className="legacy-bootstrap-grid">
                    <TextField fieldPath="framing.protocol_id" label="方案号" value={framing.protocol_id} onChange={(value) => updateFraming("protocol_id", value)} />
                    <TextField fieldPath="framing.version" label="版本" value={framing.version} onChange={(value) => updateFraming("version", value)} />
                    <TextField fieldPath="framing.document_title" wide label="方案标题" value={framing.document_title} onChange={(value) => updateFraming("document_title", value)} />
                    <TextField fieldPath="framing.indication" label="适应症" value={framing.indication} onChange={(value) => updateFraming("indication", value)} />
                    <TextField fieldPath="framing.study_phase" label="研究分期" value={framing.study_phase} onChange={(value) => updateFraming("study_phase", value)} />
                    <TextField fieldPath="framing.investigational_product" label="试验药物" value={framing.investigational_product} onChange={(value) => updateFraming("investigational_product", value)} />
                    <TextField fieldPath="framing.target_mechanism" label="靶点/作用机制" value={framing.target_mechanism} onChange={(value) => updateFraming("target_mechanism", value)} />
                    <TextField fieldPath="framing.design_pattern" wide multiline label="总体设计" value={framing.design_pattern} onChange={(value) => updateFraming("design_pattern", value)} />
                    <TextField fieldPath="framing.population_intent" wide multiline label="目标研究人群" value={framing.population_intent} onChange={(value) => updateFraming("population_intent", value)} />
                  </div>
                </section>

                <section>
                  <header><strong>PICOS核心设计</strong><small>保留提取的完整结构化对象。</small></header>
                  <div className="legacy-bootstrap-grid">
                    <TextField fieldPath="picos.population_summary" wide multiline label="研究人群" value={picos.population_summary} onChange={(value) => updatePicos("population_summary", value)} />
                    <TextField fieldPath="picos.intervention_summary" wide multiline label="干预措施" value={picos.intervention_summary} onChange={(value) => updatePicos("intervention_summary", value)} />
                    <TextField fieldPath="picos.comparator_summary" wide multiline label="对照" value={picos.comparator_summary} onChange={(value) => updatePicos("comparator_summary", value)} />
                    <TextField fieldPath="picos.primary_endpoint" wide multiline label="主要终点及评价时间" value={picos.primary_endpoint} onChange={(value) => updatePicos("primary_endpoint", value)} />
                    <TextField wide multiline label="方案摘要文本" value={synopsisText} onChange={setSynopsisText} />
                  </div>
                </section>

                {status.candidate.conflict_notes?.length > 0 && (
                  <section className="legacy-bootstrap-conflicts">
                    <header><strong>提取冲突</strong><small>请直接在上方候选中修正；不会作为自动确认事实。</small></header>
                    <ul>{status.candidate.conflict_notes.map((item) => <li key={item}>{item}</li>)}</ul>
                  </section>
                )}

                {warnings.length > 0 && (
                  <section className="legacy-bootstrap-warnings">
                    <header><strong>内容校验提示</strong><small>逐项确认后仍可沿用，原提示会持续保留。</small></header>
                    {warnings.map((warning) => (
                      <label key={warning}>
                        <input type="checkbox" checked={acknowledgedWarnings.includes(warning)} onChange={() => toggleWarning(warning)} />
                        <span>{warning}</span>
                      </label>
                    ))}
                    <label>
                      <span>沿用理由</span>
                      <textarea rows={2} value={validationOverrideReason} onChange={(event) => setValidationOverrideReason(event.target.value)} placeholder="说明为何该文件仍可用于当前项目；不少于10个字符。" />
                    </label>
                  </section>
                )}
                {missingCoreFields.length > 0 && (
                  <section className="legacy-bootstrap-missing" role="status">
                    <strong>还需补全 {missingCoreFields.length} 项</strong>
                    <span>{missingCoreFields.join("、")}</span>
                  </section>
                )}
              </div>
            ) : null}

            <footer>
              <span className={message && /失败|错误|变化|冲突/.test(message) ? "danger" : ""}>
                {["review_pending", "confirmed_ready_for_binding"].includes(status.state) ? message : ""}
              </span>
              <div>
                <button type="button" onClick={() => setOpen(false)}>稍后处理</button>
                {status.state === "review_pending" && (
                  <button type="button" className="primary-button" onClick={confirmCandidate} disabled={!confirmationReady || Boolean(busy)}>
                    <FileCheck2 size={15} /> {busy === "confirm" ? "正在建立" : "确认并建立研究设计"}
                  </button>
                )}
              </div>
            </footer>
          </aside>
        </div>
      )}
    </>
  );
}
