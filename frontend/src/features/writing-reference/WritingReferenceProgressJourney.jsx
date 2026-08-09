import { CheckCircle2, Circle, AlertTriangle, Loader2 } from "lucide-react";
import {
  STAGE_SEQUENCE,
  normalizeStage,
  getStageLabel,
  getActiveStages,
  getNextAction,
  isBusyStage,
  deriveDocumentTranslationProgress,
} from "./progressJourneyLogic.mjs";

export function getStageIcon(stage, isActive) {
  if (stage === "candidate_ready" || stage === "prepared") {
    return <CheckCircle2 size={14} className="success" />;
  }
  if (stage === "failed_retryable" || stage === "failed_terminal" || stage === "fidelity_blocked") {
    return <AlertTriangle size={14} className="danger" />;
  }
  if (isActive) return <Loader2 size={14} className="spin info" />;
  return <Circle size={14} className="muted" />;
}

export function WritingReferenceProgressJourney({ items = [], compact = false }) {
  const stageCounts = getActiveStages(items);
  const totalItems = items.length;
  const readyCount = stageCounts.get("candidate_ready") || 0;
  const preparedCount = stageCounts.get("prepared") || 0;
  const excludedCount = stageCounts.get("excluded") || 0;
  const failedCount = (stageCounts.get("failed_retryable") || 0)
    + (stageCounts.get("failed_terminal") || 0)
    + (stageCounts.get("fidelity_blocked") || 0);
  const activeStages = STAGE_SEQUENCE.filter((stage) => stageCounts.has(stage) && isBusyStage(stage));
  const isBusy = items.some((item) => isBusyStage(item.status || item.generation_status));
  const waitingCount = stageCounts.get("waiting") || 0;
  const unknownCount = stageCounts.get("unknown") || 0;
  const compactProgress = deriveDocumentTranslationProgress(items);

  if (compact) {
    return (
      <div className="writing-reference-progress-compact" role="status" aria-live="polite" aria-busy={isBusy}>
        <div className="writing-reference-progress-content">
          <span className="progress-summary">
            <span className={isBusy ? "info" : "muted"} data-testid="writing-reference-compact-current-progress">
              {compactProgress.activeStageDetail}
              {" · "}
              {compactProgress.progressCompleted}/{compactProgress.progressTotal}
              {" · "}
              {compactProgress.progressPercent}%
            </span>
            {readyCount > 0 && <span className="success">{readyCount} 项已就绪</span>}
            {preparedCount > 0 && <span className="success">{preparedCount} 项资料已准备</span>}
            {excludedCount > 0 && <span className="muted">{excludedCount} 项规划后排除</span>}
            {failedCount > 0 && <span className="danger">{failedCount} 项失败</span>}
            {waitingCount > 0 && <span className="muted">{waitingCount} 项等待开始</span>}
            {unknownCount > 0 && <span className="warning">{unknownCount} 项状态待同步</span>}
            {activeStages.length === 0 && readyCount === 0 && preparedCount === 0 && excludedCount === 0 && failedCount === 0 && waitingCount === 0 && unknownCount === 0 && (
              <span className="muted">等待启动</span>
            )}
          </span>
          <div
            className="writing-reference-progress-track"
            role="progressbar"
            aria-label="资料处理进度"
            aria-valuemin="0"
            aria-valuemax="100"
            aria-valuenow={compactProgress.progressPercent}
            data-testid="writing-reference-compact-progressbar"
          >
            <span style={{ width: `${compactProgress.progressPercent}%` }} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="writing-reference-progress-journey" role="status" aria-live="polite" aria-busy={isBusy}>
      <div className="progress-header">
        <strong>处理进度</strong>
        <span className="progress-stats">
          共 {totalItems} 项 ·
          {readyCount > 0 && <span className="success"> {readyCount} 项已就绪</span>}
          {preparedCount > 0 && <span className="success"> {preparedCount} 项资料已准备</span>}
          {excludedCount > 0 && <span className="muted"> {excludedCount} 项规划后排除</span>}
          {failedCount > 0 && <span className="danger"> {failedCount} 项失败</span>}
        </span>
      </div>
      <div
        className="writing-reference-progress-track"
        role="progressbar"
        aria-label="资料处理进度"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={compactProgress.progressPercent}
        data-testid="writing-reference-full-progressbar"
      >
        <span style={{ width: `${compactProgress.progressPercent}%` }} />
      </div>
      <div className="progress-stages">
        {STAGE_SEQUENCE.map((stage) => {
          const count = stageCounts.get(stage) || 0;
          const isActive = count > 0 && isBusyStage(stage);
          const isComplete = count > 0 && (stage === "candidate_ready" || stage === "prepared");
          return (
            <div key={stage} className={`progress-stage ${isActive ? "active" : ""} ${isComplete ? "complete" : ""}`}>
              {getStageIcon(stage, isActive)}
              <span className="stage-label">{getStageLabel(stage)}</span>
              {count > 0 && <span className="stage-count">{count}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
