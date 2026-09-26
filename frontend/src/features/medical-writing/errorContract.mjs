// 0927V1 G7 (0926V1 A701/A702): controlled state/error-code contract for
// user-facing medical-writing error copy.
//
// Contract (replaces the 0924V2 blacklist whose non-matches passed through
// verbatim — F09: engineering text leaked and timeouts claimed a background
// job without evidence):
//   1. Known backend error codes/keywords map to fixed safe Chinese copy.
//   2. Our own Chinese contract copy passes through unchanged.
//   3. Everything else (unknown, non-Chinese, engineering text) falls back to
//      one controlled default — never raw passthrough.
//   4. Timeout copy only claims a background job when the caller has real
//      job evidence (jobState: 'confirmed_running'); the default is honest
//      "not yet confirmed".
// Raw technical text stays available for the explicit 展开-诊断 details view
// (redacted by redactDiagnosticText) and in backend logs.

export function apiErrorText(error) {
  return error?.message || error?.status || "network";
}

function hasChinese(text) {
  return /[\u3400-\u9fff]/.test(text);
}

const ERROR_CODE_COPY = [
  {
    pattern: /product_ai_provider_transient/i,
    copy: "模型服务暂时没有响应：已完成的内容不会丢失，请稍后重试一次。",
  },
  {
    pattern: /failed_retryable/i,
    copy: "本次处理没有完成，可以重试；已完成的内容保持不变。",
  },
  {
    pattern: /\b409\b|conflict|stale|expected_revision|版本冲突/i,
    copy: "内容版本已发生变化，请刷新页面后按当前版本重新提交。",
  },
  {
    pattern: /\b429\b|rate limit|quota|\b507\b/i,
    copy: "模型服务繁忙或资源不足，请稍等片刻后重试；任务进度不会丢失。",
  },
  {
    pattern: /download|fetch|network|URLError|ConnectionError|ECONNREFUSED|ENOTFOUND/i,
    copy: "网络或下载暂时不可用，请检查连接后重试；已完成的内容会保留。",
  },
];

const TIMEOUT_RE = /timeout|timed?\s?out|等待超时/i;

const GENERIC_FALLBACK = "操作未能完成：发生未知的服务端错误。请稍后重试；如反复出现，请展开诊断详情并联系管理员。";

export function medicalWritingSafeErrorText(error, { jobState = "unknown" } = {}) {
  const raw = String(apiErrorText(error) || "");
  if (TIMEOUT_RE.test(raw)) {
    // A702: only confirmed live jobs may be described as running in background.
    return jobState === "confirmed_running"
      ? "请求等待超时：任务仍在后台进行，请稍后回来查看进度。"
      : "请求等待超时，本次结果尚未确认：请稍后在任务列表查看进度；确认任务没有完成后再重试，避免重复提交。";
  }
  for (const rule of ERROR_CODE_COPY) {
    if (rule.pattern.test(raw)) return rule.copy;
  }
  // Our own backend contracts send user-facing Chinese copy — keep it.
  if (raw && hasChinese(raw)) return raw;
  return GENERIC_FALLBACK;
}

// Explicit 展开-诊断 is the permission gate; any non-empty error may expose
// its technical detail there (redacted first — see redactDiagnosticText).
// Reads the raw message only — no fallback string, so absence stays absence.
export function medicalWritingDiagnosticRef(error) {
  const raw = error?.message;
  return typeof raw === "string" ? raw : "";
}

// Redact hosts, credentials and emails before diagnostics reach the screen.
export function redactDiagnosticText(text) {
  return String(text ?? "")
    .replace(/(https?:\/\/)[^/\s]+/gi, "$1***")
    .replace(/(Bearer\s+)[^\s,;]+/gi, "$1***")
    .replace(/([Aa]pi[_-]?[Kk]ey|[Tt]oken|[Ss]ecret|[Pp]assword|[Aa]uthorization)(\s*[:=]\s*)[^\s,;]+/g, "$1$2***")
    .replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, "***");
}
