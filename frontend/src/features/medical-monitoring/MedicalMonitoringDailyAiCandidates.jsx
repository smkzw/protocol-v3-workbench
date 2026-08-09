import { AlertTriangle, Bot, FileWarning } from "lucide-react";

import {
  medicalMonitoringAiCandidateConfidenceTone,
  medicalMonitoringAiCandidateClaimKey,
  medicalMonitoringAiCandidateDisplayKey,
  medicalMonitoringAiCandidateEvidenceKey,
  medicalMonitoringAiCandidateReviewStateLabel,
  medicalMonitoringAiCandidateStatusLabel,
  medicalMonitoringAiClaimKindLabel,
  normalizeMedicalMonitoringDailyAiCandidates,
} from "./medicalMonitoringDailyAiCandidates.mjs";
import "./MedicalMonitoringDailyAiCandidates.css";

function display(value) {
  return value || "待核对";
}

function shortHash(value) {
  if (typeof value !== "string" || !value.trim()) return "待核对";
  const clean = value.trim();
  return clean.length > 16 ? `${clean.slice(0, 12)}…` : clean;
}

function provenanceReady(candidate) {
  return Boolean(
    candidate.inputRevisionSha256
      && candidate.promptVersion
      && candidate.createdAt
      && candidate.evidence.length > 0
      && candidate.evidence.every((item) => (
        item.sourceEntryId
          && item.sourceContentSha256
          && item.inputRevisionSha256
          && item.locator
      )),
  );
}

function CandidateRow({ candidate }) {
  const confidence = candidate.confidenceSummary;
  const tone = medicalMonitoringAiCandidateConfidenceTone(confidence);
  const evidence = candidate.evidence.slice(0, 2);
  return (
    <article className="monitoring-daily-ai-candidate-row">
      <div className="monitoring-daily-ai-candidate-row-head">
        <div>
          <strong>{candidate.title}</strong>
          <span>个例 {display(candidate.subjectId)} · {display(candidate.candidateType)} · {medicalMonitoringAiCandidateStatusLabel(candidate.status)}</span>
        </div>
        <span className={`monitoring-daily-ai-candidate-confidence ${tone}`}>{display(confidence?.label)}</span>
      </div>
      <section className="monitoring-daily-ai-candidate-facts" aria-label="候选引用的来源事实">
        <strong>候选引用的来源事实</strong>
        {evidence.length > 0
          ? evidence.map((item, index) => (
            <blockquote key={`fact-${medicalMonitoringAiCandidateEvidenceKey(item, index)}`}>
              <span>{item.quote || "来源事实正文待核对"}</span>
              <small>证据 {display(item.evidenceId)}</small>
            </blockquote>
          ))
          : <span>来源事实正文待核对</span>}
        <small>引用只反映显式来源片段，不等于医学风险确认；来源定位在下方。</small>
      </section>
      <p>{display(candidate.text)}</p>
      {candidate.claims.length > 0 && (
        <div className="monitoring-daily-ai-candidate-claims" aria-label="候选声明">
          {candidate.claims.slice(0, 2).map((claim, index) => (
            <span
              key={medicalMonitoringAiCandidateClaimKey(claim, index)}
              title={claim.identityIssue ? `${claim.text} · ${claim.identityIssue}` : claim.text}
            >
              {medicalMonitoringAiClaimKindLabel(claim.kind)} · {claim.text}
              {claim.identityState !== "ready" && " · 身份待核对"}
            </span>
          ))}
          {candidate.claims.length > 2 && <small>其余 {candidate.claims.length - 2} 条声明仍绑定在候选中。</small>}
        </div>
      )}
      <div className="monitoring-daily-ai-candidate-meta">
        <span>声明 {candidate.claims.length} 条</span>
        <span>证据 {candidate.evidence.length} 条</span>
        <span>{medicalMonitoringAiCandidateReviewStateLabel(candidate)}</span>
      </div>
      <details className="monitoring-daily-ai-candidate-provenance">
        <summary>查看来源身份 {provenanceReady(candidate) ? "· 字段齐全" : "· 待核对"}</summary>
        <div className="monitoring-daily-ai-candidate-provenance-grid">
          <span>候选输入修订 <code title={candidate.inputRevisionSha256 || undefined}>{shortHash(candidate.inputRevisionSha256)}</code></span>
          <span>提示词版本 <code>{display(candidate.promptVersion)}</code></span>
          <span>生成时间 <code>{display(candidate.createdAt)}</code></span>
          <span>身份状态 <strong>{provenanceReady(candidate) ? "字段齐全，仍需回源核对" : "字段缺失或异常"}</strong></span>
        </div>
        <div className="monitoring-daily-ai-candidate-provenance-sources">
          {candidate.evidence.slice(0, 2).map((item, index) => (
            <div key={`provenance-${medicalMonitoringAiCandidateEvidenceKey(item, index)}`}>
              <span>{display(item.sourceEntryId)} · {display(item.locator)}</span>
              <code title={item.sourceContentSha256 || undefined}>源哈希 {shortHash(item.sourceContentSha256)}</code>
              <code title={item.inputRevisionSha256 || undefined}>输入 {shortHash(item.inputRevisionSha256)}</code>
            </div>
          ))}
          {!candidate.evidence.length && <span>来源身份待核对</span>}
          {candidate.evidence.length > 2 && <small>其余 {candidate.evidence.length - 2} 条来源身份仍绑定在候选中。</small>}
        </div>
        <small className="monitoring-daily-ai-candidate-provenance-note">来源身份只用于版本与回源核对，不是医学风险结论；哈希不代表原始数据内容。</small>
      </details>
      <div className="monitoring-daily-ai-candidate-evidence">
        {evidence.length > 0
          ? evidence.map((item, index) => <code key={medicalMonitoringAiCandidateEvidenceKey(item, index)}>{item.sourceEntryId} · {item.locator}</code>)
          : <span>来源证据待核对</span>}
        {candidate.evidence.length > evidence.length && <small>其余 {candidate.evidence.length - evidence.length} 条证据仍绑定在候选中。</small>}
      </div>
    </article>
  );
}

export default function MedicalMonitoringDailyAiCandidates({ candidates, candidateCount }) {
  const view = normalizeMedicalMonitoringDailyAiCandidates({ candidates, candidateCount });
  if (view.status === "unavailable") {
    return (
      <section className="monitoring-daily-ai-candidates unavailable" aria-label="AI候选线索">
        <header><strong><Bot size={14} /> AI候选线索</strong><AlertTriangle size={14} /></header>
        <p role="alert">已声明有候选线索，但候选明细未返回；不能据此确认或排除风险。</p>
      </section>
    );
  }
  if (view.status === "malformed" || !view.value) {
    return (
      <section className="monitoring-daily-ai-candidates malformed" aria-label="AI候选线索">
        <header><strong><Bot size={14} /> AI候选线索</strong><FileWarning size={14} /></header>
        <p role="alert">候选线索格式异常，暂不展示候选内容；请回到 AI 任务账本核对。</p>
      </section>
    );
  }
  const rows = view.value.candidates.slice(0, 6);
  return (
    <section className={`monitoring-daily-ai-candidates ${view.status}`} aria-label="AI候选线索预览">
      <header className="monitoring-daily-ai-candidates-head">
        <div>
          <strong><Bot size={14} /> AI候选线索预览</strong>
          <span>候选只代表 source-bound 线索；不自动采纳、不替代医学判断。</span>
        </div>
        <span className="monitoring-daily-ai-candidates-count">候选 {view.value.candidateCount ?? "待核对"}</span>
      </header>
      {!rows.length && (
        <p className="monitoring-daily-ai-candidates-empty">当前未返回候选线索；这不等于当前批次无风险。</p>
      )}
      {rows.map((candidate, index) => <CandidateRow key={medicalMonitoringAiCandidateDisplayKey(candidate, index)} candidate={candidate} />)}
      {view.value.candidates.length > rows.length && (
        <small className="monitoring-daily-ai-candidates-more">仅显示前 {rows.length} 条；其余候选仍需逐条医学复核。</small>
      )}
      {view.issues.length > 0 && (
        <p className="monitoring-daily-ai-candidates-warning" role="alert">
          <AlertTriangle size={13} />部分候选字段待核对；来源身份不完整或异常时，不得确认或作为无风险依据。
        </p>
      )}
      <small className="monitoring-daily-ai-candidates-source">此卡只读展示当前运行的候选与声明证据；没有采纳、驳回或风险处置操作。</small>
    </section>
  );
}
