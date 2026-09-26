// Source-derived excerpt: App.jsx lines 580-615 @53feb06f.
// Pure-function probe only. No React/DOM/browser run is claimed.
function apiErrorText(error) { return error?.message || error?.status || "network"; }
const _MEDICAL_WRITING_DIAGNOSTIC_RE = /(Traceback|Exception|RuntimeError|ValueError|KeyError|Pydantic|schema|schema_version|stage_run_id|mwjob_|mwprefill|wref_|docplan_|ct_run_|ct_chunk_|mwsec_|mwdoc_|HTTP \d{3}|at line \d+|expected_revision|payload_json)/i;
function medicalWritingSafeErrorText(error) {
  const raw = String(apiErrorText(error) || "");
  if (!_MEDICAL_WRITING_DIAGNOSTIC_RE.test(raw)) return raw;
  if (/409|conflict|stale|revision/i.test(raw)) return "内容版本已发生变化，请刷新页面后按当前版本重新提交。";
  if (/timeout|timed?\s?out|连接|网络/i.test(raw)) return "请求等待超时：任务仍在后台执行，请稍后在任务列表查看结果，或重试一次。";
  if (/429|rate|quota|507/i.test(raw)) return "模型服务繁忙或资源不足，请稍等片刻后重试；任务进度不会丢失。";
  if (/download|fetch|network|URLError/i.test(raw)) return "网络或下载暂时不可用，请检查连接后重试；已完成的内容会保留。";
  return "操作未能完成：发生未知的服务端错误。请稍后重试；如反复出现，请展开诊断详情并联系管理员。";
}
import fs from 'node:fs';
const cases = ['product_ai_provider_transient__urlerror','failed_retryable','network','RuntimeError: timed out','内容已保存'];
const result = {kind:'source-derived pure JS message function, not browser validation',cases:cases.map((message,i)=>({id:`U0${i+1}`,input:message,output:medicalWritingSafeErrorText({message})}))};
fs.writeFileSync(new URL('../evidence/ui_message_probe_results.json',import.meta.url),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result,null,2));
