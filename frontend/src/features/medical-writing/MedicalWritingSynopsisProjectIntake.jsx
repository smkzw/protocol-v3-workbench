import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  LoaderCircle,
  RotateCcw,
  Upload,
  XCircle,
} from "lucide-react";

const PHASES = ["I期", "I/II期", "II期", "II/III期", "III期"];

// NEW-8（R27 第1轮末修订）：AI 提取的分期写法千差万别（Ⅲ期/三期/２期/
// ii/iii），而下拉只认 PHASES——旧行为里不匹配值让 select 显示「请选择」
// 但 state 非空，canConfirm 放行，合同层拿到 'MW-PHASE' 原料。这里做与
// 后端合同归一（workbench_contracts.models._normalize_study_phase_label）
// 同口径的前端映射：能映射进选项的直接映射；映射不出的返回 ""，由调用方
// 显式标「分期待确认」并阻断确认。
const PHASE_WIDTH_MAP = { "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "０": "0", "１": "1", "２": "2", "３": "3", "４": "4" };
const PHASE_CN_NUMERALS = [["一期", "1"], ["二期", "2"], ["三期", "3"], ["四期", "4"]];
const PHASE_DIGIT_ROMAN = { "1": "I", "2": "II", "3": "III", "4": "IV" };

export function resolvePhaseOption(value) {
  let normalized = String(value || "").trim();
  if (!normalized) return "";
  normalized = normalized.replace(/[ⅠⅡⅢⅣ０-４]/g, (char) => PHASE_WIDTH_MAP[char] ?? char).toUpperCase();
  for (const [source, target] of PHASE_CN_NUMERALS) normalized = normalized.split(source).join(target);
  normalized = normalized.split("期").join("").trim();
  const tokens = normalized.match(/IV|III|II|I|[1-4]/g) || [];
  if (!tokens.length) return "";
  const canonical = tokens.map((token) => PHASE_DIGIT_ROMAN[token] || token).join("/") + "期";
  return PHASES.includes(canonical) ? canonical : "";
}
const TERMINAL_JOB_STATES = new Set(["review_ready", "failed", "cancelled"]);
const POLL_INTERVAL_MS = 4000;
const POLL_REQUEST_TIMEOUT_MS = 15000;
const COMMAND_REQUEST_TIMEOUT_MS = 30000;
const UPLOAD_REQUEST_TIMEOUT_MS = 120000;
const MAX_CONSECUTIVE_POLL_FAILURES = 3;

// NEW-5（R27 第1轮修订）：刷新/重开弹窗前，把在途任务的寻址指纹存进
// sessionStorage；挂载时回查并恢复进度面板。服务端任务本身是持久的
// （progress_json 列 + 冷恢复钩子），丢的从来只是前端弹窗状态。
export const ACTIVE_JOB_STORAGE_KEY = "workbench.synopsisIntake.activeJob";

function readStoredActiveJob() {
  try {
    const raw = globalThis.sessionStorage?.getItem(ACTIVE_JOB_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.intake_id || !parsed?.idempotency_key) return null;
    return { intake_id: String(parsed.intake_id), idempotency_key: String(parsed.idempotency_key) };
  } catch {
    return null;
  }
}

function persistActiveJob(started) {
  try {
    globalThis.sessionStorage?.setItem(
      ACTIVE_JOB_STORAGE_KEY,
      JSON.stringify({ intake_id: started.intake_id, idempotency_key: started.idempotency_key }),
    );
  } catch {
    // 存储不可用（隐私模式等）：刷新恢复退化为不可用，不影响任务本身。
  }
}

function clearActiveJob() {
  try {
    globalThis.sessionStorage?.removeItem(ACTIVE_JOB_STORAGE_KEY);
  } catch {
    // 同上：忽略存储异常。
  }
}

export class SynopsisRequestTimeoutError extends Error {
  constructor(message = "请求超时") {
    super(message);
    this.name = "SynopsisRequestTimeoutError";
  }
}

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail
          ? JSON.stringify(detail)
          : `请求失败（${response.status}）`,
    );
  }
  return payload;
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

export async function requestJsonWithTimeout(
  url,
  options = {},
  {
    timeoutMs = COMMAND_REQUEST_TIMEOUT_MS,
    signal,
    fetchImpl = fetch,
  } = {},
) {
  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetchImpl(url, { ...options, signal: controller.signal });
    return await readJson(response);
  } catch (error) {
    if (timedOut) {
      throw new SynopsisRequestTimeoutError(`请求在 ${Math.ceil(timeoutMs / 1000)} 秒内未响应`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
    signal?.removeEventListener("abort", abortFromCaller);
  }
}

export function synopsisJobState(job) {
  if (TERMINAL_JOB_STATES.has(job?.status)) return job.status;
  if (TERMINAL_JOB_STATES.has(job?.phase)) return job.phase;
  if (job?.status === "recoverable" || job?.phase === "recoverable") return "recoverable";
  return job?.status || job?.phase || "pending";
}

export function synopsisJobErrorKind(job) {
  // AGG25-P1-1: the backend now stores a structured failure_code; the regex
  // fallback keeps legacy rows classifiable.  ENV-02 correction: a timeout
  // means "model busy/slow", a refused connection means "service offline" —
  // different user guidance, never merged again.
  const code = String(job?.failure_code || "");
  if (code === "model_timeout") return "model_timeout";
  if (code === "local_model_offline") return "model_offline";
  if (code === "route_config_changed") return "route_config";
  if (code === "binding_mismatch") return "binding_mismatch";
  const raw = String(job?.error_message || "");
  if (/approved direct route|route configuration changed|route_identity/i.test(raw)) {
    return "route_config";
  }
  if (/binding.*mismatch|binding_base_url_mismatch/i.test(raw)) {
    return "binding_mismatch";
  }
  if (/timed out|timeout/i.test(raw)) {
    return "model_timeout";
  }
  if (/urlerror|connection refused|connection reset|connection error/i.test(raw)) {
    return "model_offline";
  }
  return "";
}

export function synopsisJobMessage(job) {
  const state = synopsisJobState(job);
  if (state === "failed" || state === "recoverable") {
    // A route/policy denial can never be fixed by "resume": the frozen route
    // identity check blocks re-entry after any settings change, so the only
    // real path is re-importing the file. Say so plainly instead of showing
    // internal jargon next to a dead-end button.
    const kind = synopsisJobErrorKind(job);
    if (kind === "route_config") {
      return "解析未完成：模型配置已变更，请重新选择文件重新导入。";
    }
    if (kind === "model_timeout") {
      // ENV-02: honest busy-model guidance. The old copy promised "系统会自动
      // 排队并在模型可用时拉起" — a promise nothing in the dispatch path
      // keeps (the job never enters an arbiter queue). Say what is true:
      // the model was busy, the request can be retried, and the user may cancel.
      return "解析未完成：模型本次响应超时，通常是因为模型正被其他任务占用（繁忙，不是故障）。您可以点“继续处理”再试一次，也可以取消本次任务稍后再来。";
    }
    if (kind === "model_offline") {
      return "解析未完成：本地模型服务未就绪或无法连接。请确认模型服务已启动后点“继续处理”再试，也可以取消本次任务。";
    }
    if (kind === "binding_mismatch") {
      return "解析未完成：项目绑定的模型服务地址与受管服务不一致，请在 AI 设置中改绑后重试。";
    }
    if (job?.error_message) return job.error_message;
  }
  if (state === "failed") return "方案摘要解析失败。已完成的解析进度仍会保留，您可以继续处理。";
  if (state === "recoverable") return "方案摘要解析已暂停，已完成的进度仍会保留。";
  if (state === "cancelled") return "本次解析已取消。您可以重新选择文件。";
  return "";
}

export function synopsisAttemptLabel(job) {
  // ENV-02: honest attempt progress for the waiting panel. The backend now
  // stamps the real per-chunk attempt count onto the job.
  const attempts = Number(job?.attempt_count || 0);
  if (!Number.isFinite(attempts) || attempts <= 1) return "";
  return `第${attempts}次解析尝试`;
}

export function modelLifecycleSummary(payload) {
  // ENV-02: a truthful one-line model residency summary for the waiting
  // panel (replaces the retracted "auto queueing" promise). Empty string
  // means "no trustworthy status — show nothing".
  if (!payload || payload.status !== "ok") return "";
  const arbiter = payload.arbiter || {};
  const current = String(arbiter.current || "");
  if (!current) return "模型服务空闲";
  const users = Object.values(arbiter.users || {}).reduce(
    (sum, value) => sum + Number(value || 0),
    0,
  );
  const queue = Array.isArray(arbiter.queue) ? arbiter.queue.length : 0;
  const busy = `模型正被${Math.max(users, 1)}个任务占用`;
  return queue ? `${busy}，另有${queue}项在排队` : busy;
}

function waitForNextPoll(delayMs, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const abort = () => {
      clearTimeout(timeoutId);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timeoutId = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, delayMs);
    signal?.addEventListener("abort", abort, { once: true });
  });
}

export async function pollSynopsisJob(
  started,
  {
    request,
    signal,
    onJob = () => {},
    wait = waitForNextPoll,
    pollIntervalMs = POLL_INTERVAL_MS,
    maxConsecutiveFailures = MAX_CONSECUTIVE_POLL_FAILURES,
  },
) {
  if (["review_ready", "failed", "recoverable", "cancelled"].includes(synopsisJobState(started))) {
    onJob(started);
    return started;
  }
  let consecutiveFailures = 0;
  while (!signal?.aborted) {
    try {
      const current = await request(
        `/api/medical-writing/project-intake/synopsis/${started.intake_id}/jobs/${encodeURIComponent(started.idempotency_key)}`,
        { signal },
      );
      consecutiveFailures = 0;
      onJob(current);
      if (["review_ready", "failed", "recoverable", "cancelled"].includes(synopsisJobState(current))) {
        return current;
      }
    } catch (error) {
      if (isAbortError(error)) throw error;
      consecutiveFailures += 1;
      if (consecutiveFailures >= maxConsecutiveFailures) {
        throw new Error(
          "状态查询连续超时或失败。后台任务仍会保留；您可以重新查询、取消任务或关闭窗口后稍后重试。",
          { cause: error },
        );
      }
    }
    await wait(pollIntervalMs, signal);
  }
  throw new DOMException("Aborted", "AbortError");
}

export async function cancelSynopsisJob(intake, { abortPolling, request, signal }) {
  abortPolling();
  return request(
    `/api/medical-writing/project-intake/synopsis/${intake.intake_id}/jobs/${encodeURIComponent(intake.idempotency_key)}/cancel`,
    { method: "POST", signal },
  );
}

async function fileRequestKey(file) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  const hex = [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  return `file-first-synopsis-${hex}`.slice(0, 200);
}

function formatSize(value) {
  if (!Number.isFinite(value)) return "";
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function phaseLabel(job) {
  return ({
    uploaded: "文件已接收",
    parsing: "正在解析文档",
    chunking: "正在识别章节",
    ai_synthesis: "AI正在提取研究框架与PICOS",
    validating: "正在核对来源与结构",
    review_ready: "提取完成，待您确认",
    recoverable: "任务可恢复",
    failed: "解析失败",
    cancelled: "已取消",
  })[job?.phase || job?.status] || "准备导入";
}

export function MedicalWritingSynopsisProjectIntake({ disabled = false, onCreated }) {
  const mountedRef = useRef(true);
  const pollGenerationRef = useRef(0);
  const pollControllerRef = useRef(null);
  const commandControllerRef = useRef(null);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [intake, setIntake] = useState(null);
  const [job, setJob] = useState(null);
  const [imported, setImported] = useState(null);
  const [framing, setFraming] = useState(null);
  // NEW-8：AI 提取的分期无法映射进下拉选项时保留原文用于点名提示；
  // 此时 framing.study_phase 置空 → canConfirm 阻断，直到医学经理手选。
  const [unresolvedPhase, setUnresolvedPhase] = useState("");
  const [picos, setPicos] = useState(null);
  const [synopsisText, setSynopsisText] = useState("");
  const [acknowledged, setAcknowledged] = useState([]);
  const [overrideReason, setOverrideReason] = useState("");
  const [modelStatus, setModelStatus] = useState(null);
  const [restoredNotice, setRestoredNotice] = useState(false);
  // NEW-30（R27 第3轮修订）：「重新选择」要真清空——React 文件 input 的
  // value/files 不可受控清空，用 key 重挂换新节点。
  const [fileInputNonce, setFileInputNonce] = useState(0);

  // ENV-02: while a job is in flight, keep an honest picture of model
  // residency in the waiting panel (best-effort; absent status shows nothing).
  useEffect(() => {
    if (!busy) {
      setModelStatus(null);
      return undefined;
    }
    let cancelled = false;
    const controller = new AbortController();
    const read = () => {
      fetch("/api/model-lifecycle/status", { signal: controller.signal })
        .then((response) => (response.ok ? response.json() : null))
        .then((payload) => {
          if (!cancelled) setModelStatus(payload);
        })
        .catch(() => {
          if (!cancelled) setModelStatus(null);
        });
    };
    read();
    const timer = globalThis.setInterval(read, 8000);
    return () => {
      cancelled = true;
      controller.abort();
      globalThis.clearInterval(timer);
    };
  }, [busy]);

  // NEW-5：挂载（含刷新后重开弹窗）时按 sessionStorage 指纹回查在途或
  // 可恢复任务并直接恢复进度面板；任务已不存在则清指纹回默认态。
  useEffect(() => {
    const saved = readStoredActiveJob();
    if (!saved) return undefined;
    const controller = new AbortController();
    commandControllerRef.current?.abort();
    commandControllerRef.current = controller;
    const generation = pollGenerationRef.current + 1;
    pollGenerationRef.current = generation;
    (async () => {
      try {
        const current = await requestJsonWithTimeout(
          `/api/medical-writing/project-intake/synopsis/${saved.intake_id}/jobs/${encodeURIComponent(saved.idempotency_key)}`,
          { signal: controller.signal },
          { timeoutMs: POLL_REQUEST_TIMEOUT_MS, signal: controller.signal },
        );
        if (!mountedRef.current || pollGenerationRef.current !== generation) return;
        const state = synopsisJobState(current);
        if (state === "failed" || state === "cancelled") {
          clearActiveJob();
          setJob(current);
          setMessage(synopsisJobMessage(current));
          return;
        }
        setIntake(saved);
        setJob(current);
        setBusy("processing");
        setRestoredNotice(true);
        await pollJob(saved, generation);
      } catch (error) {
        if (isAbortError(error)) return;
        // 任务不存在（404）或暂时查不到：清指纹回默认态，不打扰用户。
        if (mountedRef.current) clearActiveJob();
      }
    })();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      pollControllerRef.current?.abort();
      commandControllerRef.current?.abort();
    };
  }, []);

  const warnings = imported?.source?.validation_warnings || [];
  const canConfirm = useMemo(() => Boolean(
    imported?.source?.source_id
      && framing?.investigational_product?.trim()
      && framing?.indication?.trim()
      && framing?.study_phase?.trim()
      && synopsisText.trim()
      && acknowledged.length === warnings.length
  ), [acknowledged.length, framing, imported, overrideReason, synopsisText, warnings.length]);

  const reset = () => {
    pollGenerationRef.current += 1;
    pollControllerRef.current?.abort();
    commandControllerRef.current?.abort();
    setFile(null);
    setBusy("");
    setMessage("");
    setIntake(null);
    setJob(null);
    setImported(null);
    setFraming(null);
    setPicos(null);
    setSynopsisText("");
    setAcknowledged([]);
    setOverrideReason("");
    setRestoredNotice(false);
    setFileInputNonce((value) => value + 1);
    clearActiveJob();
  };

  const request = (url, options = {}, timeoutMs = COMMAND_REQUEST_TIMEOUT_MS) => {
    const { signal, ...fetchOptions } = options;
    return requestJsonWithTimeout(url, fetchOptions, { timeoutMs, signal });
  };

  const settleJob = async (current, started, generation, signal) => {
    if (!mountedRef.current || pollGenerationRef.current !== generation) return;
    setJob(current);
    const state = synopsisJobState(current);
    if (state === "review_ready") {
      const result = await request(
        `/api/medical-writing/project-intake/synopsis/${started.intake_id}/jobs/${encodeURIComponent(started.idempotency_key)}/result`,
        { signal },
      );
      if (!mountedRef.current || pollGenerationRef.current !== generation) return;
      setImported(result);
      const proposedFraming = result.proposed_framing;
      const phaseOption = resolvePhaseOption(proposedFraming?.study_phase);
      // 可映射时统一写入规范选项值（'iii期' 也归一为 'III期'）；映射失败时
      // 置空并保留原文点名，杜绝「select 显示请选择而 state 非空」的假象。
      setUnresolvedPhase(phaseOption ? "" : String(proposedFraming?.study_phase || "").trim());
      setFraming({ ...proposedFraming, study_phase: phaseOption });
      setPicos(result.proposed_picos);
      setSynopsisText(result.proposed_synopsis_text || "");
      setMessage("");
    } else {
      if (["failed", "cancelled"].includes(state)) clearActiveJob();
      setMessage(synopsisJobMessage(current));
    }
    setBusy("");
  };

  const pollJob = async (started, generation) => {
    pollControllerRef.current?.abort();
    const controller = new AbortController();
    pollControllerRef.current = controller;
    const current = await pollSynopsisJob(started, {
      signal: controller.signal,
      request: (url, options) => request(url, options, POLL_REQUEST_TIMEOUT_MS),
      onJob: (nextJob) => {
        if (mountedRef.current && pollGenerationRef.current === generation) setJob(nextJob);
      },
    });
    await settleJob(current, started, generation, controller.signal);
  };

  const start = async () => {
    if (!file || busy) return;
    setBusy("upload");
    setMessage("");
    setImported(null);
    commandControllerRef.current?.abort();
    const controller = new AbortController();
    commandControllerRef.current = controller;
    try {
      const requestKey = await fileRequestKey(file);
      const body = new FormData();
      body.append("file", file);
      body.append("actor", "medical_manager");
      body.append("idempotency_key", requestKey);
      const started = await request(
        "/api/medical-writing/project-intake/synopsis",
        { method: "POST", body, signal: controller.signal },
        UPLOAD_REQUEST_TIMEOUT_MS,
      );
      if (!mountedRef.current) return;
      setIntake(started);
      setJob(started);
      setBusy("processing");
      persistActiveJob(started);
      const generation = pollGenerationRef.current + 1;
      pollGenerationRef.current = generation;
      await pollJob(started, generation);
    } catch (error) {
      if (!mountedRef.current || isAbortError(error)) return;
      setBusy("");
      setMessage(error.message);
    } finally {
      if (commandControllerRef.current === controller) commandControllerRef.current = null;
    }
  };

  const cancel = async () => {
    if (!intake?.intake_id || !intake?.idempotency_key) return;
    const generation = pollGenerationRef.current + 1;
    pollGenerationRef.current = generation;
    setBusy("cancel");
    setMessage("");
    commandControllerRef.current?.abort();
    const controller = new AbortController();
    commandControllerRef.current = controller;
    try {
      const cancelled = await cancelSynopsisJob(intake, {
        abortPolling: () => pollControllerRef.current?.abort(),
        signal: controller.signal,
        request: (url, options) => request(url, options, COMMAND_REQUEST_TIMEOUT_MS),
      });
      if (!mountedRef.current) return;
      if (
        String(cancelled?.status || "") === "review_ready"
        || synopsisJobState(cancelled) === "review_ready"
      ) {
        // AGG-ENV-02: the extraction had already succeeded and passed
        // validation when the cancel landed — the backend refused to discard
        // it. Deliver the result instead of a dead end.
        setBusy("processing");
        setMessage("");
        await pollJob(intake, generation);
        return;
      }
      setJob(cancelled);
      setMessage(synopsisJobMessage(cancelled));
    } catch (error) {
      if (!mountedRef.current || isAbortError(error)) return;
      setMessage(error.message);
    } finally {
      if (mountedRef.current) setBusy("");
      if (commandControllerRef.current === controller) commandControllerRef.current = null;
    }
  };

  const resume = async () => {
    if (!intake?.intake_id || !intake?.idempotency_key || busy) return;
    pollControllerRef.current?.abort();
    setBusy("processing");
    setMessage("");
    commandControllerRef.current?.abort();
    const controller = new AbortController();
    commandControllerRef.current = controller;
    try {
      const body = new FormData();
      body.append("actor", "medical_manager");
      const resumed = await request(
        `/api/medical-writing/project-intake/synopsis/${intake.intake_id}/jobs/${encodeURIComponent(intake.idempotency_key)}/resume`,
        { method: "POST", body, signal: controller.signal },
      );
      if (!mountedRef.current) return;
      setJob(resumed);
      const generation = pollGenerationRef.current + 1;
      pollGenerationRef.current = generation;
      await pollJob(intake, generation);
    } catch (error) {
      if (!mountedRef.current || isAbortError(error)) return;
      setBusy("");
      setMessage(error.message);
    } finally {
      if (commandControllerRef.current === controller) commandControllerRef.current = null;
    }
  };

  const retryPoll = async () => {
    if (!intake?.intake_id || !intake?.idempotency_key || busy) return;
    setBusy("processing");
    setMessage("");
    const generation = pollGenerationRef.current + 1;
    pollGenerationRef.current = generation;
    try {
      await pollJob(intake, generation);
    } catch (error) {
      if (!mountedRef.current || isAbortError(error)) return;
      setBusy("");
      setMessage(error.message);
    }
  };

  const confirm = async () => {
    if (!canConfirm || busy || !intake) return;
    setBusy("confirm");
    setMessage("");
    commandControllerRef.current?.abort();
    const controller = new AbortController();
    commandControllerRef.current = controller;
    try {
      const payload = await request(
        "/api/medical-writing/project-intake/synopsis/confirm",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            intake_id: intake.intake_id,
            import_idempotency_key: intake.idempotency_key,
            source_id: imported.source.source_id,
            framing,
            picos,
            synopsis_text: synopsisText,
            acknowledged_validation_warnings: acknowledged,
            validation_override_reason: overrideReason,
            actor: "medical_manager",
            idempotency_key: `confirm-${intake.intake_id}-${imported.source.content_sha256}`.slice(0, 200),
          }),
        },
      );
      clearActiveJob();
      onCreated?.(payload);
    } catch (error) {
      if (!mountedRef.current || isAbortError(error)) return;
      setBusy("");
      setMessage(error.message);
    } finally {
      if (commandControllerRef.current === controller) commandControllerRef.current = null;
    }
  };

  const setFramingField = (field, value) => {
    setFraming((current) => ({ ...current, [field]: value }));
  };
  const setPicosField = (field, value) => {
    setPicos((current) => ({ ...current, [field]: value }));
  };

  if (!imported) {
    const progress = job?.progress;
    const current = progress?.chunk_index || job?.chunk_index || 0;
    const total = progress?.chunk_total || job?.chunk_total || 0;
    const elapsedMinutes = Math.max(0, Math.floor(Number(job?.elapsed_seconds || 0) / 60));
    return (
      <section className="file-first-synopsis-intake">
        <div className="file-first-dropzone">
          <input
            key={fileInputNonce}
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            disabled={disabled || Boolean(busy)}
            onChange={(event) => {
              setFile(event.target.files?.[0] || null);
              setMessage("");
            }}
          />
          <FileText size={26} />
          <div>
            <strong>{file?.name || "选择方案摘要或完整方案"}</strong>
            <span>{file ? `${formatSize(file.size)} · PDF / DOCX` : "系统先提取，您确认后才创建正式项目"}</span>
          </div>
          {file && !busy && (
            <button type="button" onClick={start}>
              <Upload size={15} /> 导入并提取
            </button>
          )}
        </div>
        {busy && (
          <div className="file-first-progress" aria-live="polite">
            <LoaderCircle size={18} className="spin" />
            <div>
              <strong>{phaseLabel(job)}</strong>
              <span>
                {total ? `正在处理 ${Math.min(current + 1, total)} / ${total} 个内容块` : "正在准备文档内容"}
                {job?.waiting_on === "model_wait" ? " · 模型处理中或排队等待空位" : ""}
                {elapsedMinutes ? ` · 已运行 ${elapsedMinutes} 分钟` : ""}
                {synopsisAttemptLabel(job) ? ` · ${synopsisAttemptLabel(job)}` : ""}
              </span>
              {restoredNotice && <small>已恢复上次的提取任务，正在继续跟踪进度；无需重新选择文件。</small>}
              {modelLifecycleSummary(modelStatus) && (
                <small>{modelLifecycleSummary(modelStatus)}；如长时间无进展可取消后稍后再来。</small>
              )}
            </div>
            {intake && (
              <button type="button" onClick={cancel} disabled={busy === "cancel"}>
                {busy === "cancel" ? "正在取消" : "取消"}
              </button>
            )}
          </div>
        )}
        {message && (
          <div className="file-first-error" role="alert">
            <AlertTriangle size={17} /><span>{message}</span>
            {intake && ["failed", "recoverable"].includes(synopsisJobState(job)) && synopsisJobErrorKind(job) !== "route_config" && (
              <button type="button" onClick={resume}><RotateCcw size={14} /> 继续处理</button>
            )}
            {intake && !["failed", "recoverable", "cancelled"].includes(synopsisJobState(job)) && (
              <>
                <button type="button" onClick={retryPoll}><RotateCcw size={14} /> 重新查询</button>
                <button type="button" onClick={cancel}>取消任务</button>
              </>
            )}
            {(!intake || ["failed", "recoverable", "cancelled"].includes(synopsisJobState(job))) && (
              <button type="button" onClick={reset}><RotateCcw size={14} /> 重新选择</button>
            )}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="file-first-synopsis-review">
      <header>
        <div>
          <span>AI 已提取 · 一次确认</span>
          <strong>{imported.source.original_filename}</strong>
        </div>
        <button type="button" onClick={reset} disabled={Boolean(busy)} title="更换文件">
          <XCircle size={16} /> 更换文件
        </button>
      </header>

      <div className="file-first-core-fields">
        <label>
          <span>试验药物</span>
          <input value={framing?.investigational_product || ""} onChange={(event) => setFramingField("investigational_product", event.target.value)} />
        </label>
        <label>
          <span>适应症</span>
          <input value={framing?.indication || ""} onChange={(event) => setFramingField("indication", event.target.value)} />
        </label>
        <label>
          <span>研究分期</span>
          <select value={framing?.study_phase || ""} onChange={(event) => { setUnresolvedPhase(""); setFramingField("study_phase", event.target.value); }}>
            <option value="">请选择</option>
            {PHASES.map((phase) => <option key={phase}>{phase}</option>)}
          </select>
          {unresolvedPhase && <small className="synopsis-phase-unresolved">分期待确认：AI提取的分期「{unresolvedPhase}」无法识别，请从上方选择 I-III 期；不选择无法确认建项。</small>}
        </label>
        <label>
          <span>方案号</span>
          <input value={framing?.protocol_id || ""} onChange={(event) => setFramingField("protocol_id", event.target.value)} />
        </label>
        <label className="span-2">
          <span>建议方案标题</span>
          <input value={framing?.document_title || ""} onChange={(event) => setFramingField("document_title", event.target.value)} />
        </label>
        <label>
          <span>版本</span>
          <input value={framing?.version || ""} onChange={(event) => setFramingField("version", event.target.value)} />
        </label>
      </div>

      <div className="file-first-design-summary">
        <label>
          <span>研究设计</span>
          <textarea rows={2} value={framing?.design_pattern || ""} onChange={(event) => setFramingField("design_pattern", event.target.value)} />
        </label>
        <label>
          <span>研究人群</span>
          <textarea rows={2} value={picos?.population_summary || framing?.population_intent || ""} onChange={(event) => {
            setPicosField("population_summary", event.target.value);
            setFramingField("population_intent", event.target.value);
          }} />
        </label>
        <label>
          <span>干预措施</span>
          <textarea rows={2} value={picos?.intervention_summary || ""} onChange={(event) => setPicosField("intervention_summary", event.target.value)} />
        </label>
        <label>
          <span>对照</span>
          <textarea rows={2} value={picos?.comparator_summary || ""} onChange={(event) => setPicosField("comparator_summary", event.target.value)} />
        </label>
        <label>
          <span>主要终点</span>
          <textarea rows={2} value={picos?.primary_endpoint || ""} onChange={(event) => setPicosField("primary_endpoint", event.target.value)} />
        </label>
      </div>

      {(imported.missing_fields?.length > 0 || imported.conflict_notes?.length > 0) && (
        <div className="file-first-findings">
          <div><strong>后续仅需补充</strong><span>{imported.missing_fields?.map((item) => item.split(".").at(-1)).join("、") || "无"}</span></div>
          <div><strong>需留意的原文差异</strong><span>{imported.conflict_notes?.join("；") || "无"}</span></div>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="file-first-warnings">
          <strong>文件内容提示</strong>
          {warnings.map((warning) => (
            <label key={warning}>
              <input
                type="checkbox"
                checked={acknowledged.includes(warning)}
                onChange={() => setAcknowledged((current) => current.includes(warning)
                  ? current.filter((item) => item !== warning)
                  : [...current, warning])}
              />
              <span>{warning}</span>
            </label>
          ))}
          <textarea rows={2} value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} placeholder="可选：补充说明该文件为何适用于当前项目" />
        </div>
      )}

      <footer>
        <span><CheckCircle2 size={15} />确认后，已提取内容直接成为当前项目事实；不会再次要求医学批准。</span>
        <button type="button" className="primary-button" disabled={!canConfirm || Boolean(busy)} onClick={confirm}>
          {busy === "confirm" ? <LoaderCircle size={15} className="spin" /> : <CheckCircle2 size={15} />}
          {busy === "confirm" ? "正在创建" : "确认并进入写作"}
        </button>
      </footer>
      {message && <p className="file-first-inline-error"><AlertTriangle size={15} />{message}</p>}
    </section>
  );
}
