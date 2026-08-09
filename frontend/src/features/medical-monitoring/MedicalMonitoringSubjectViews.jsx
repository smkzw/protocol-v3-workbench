import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Minus, Plus, Search } from "lucide-react";
import { severityLabel } from "./medicalMonitoringModels.mjs";
import { createMedicalMonitoringApi } from "./medicalMonitoringApi.mjs";
import {
  metricConfigurationReviewState,
  metricConfigurationCandidateSource,
  metricConfigurationCandidateDisplayKey,
  metricConfigurationDirectionLabel,
} from "./medicalMonitoringMetricConfiguration.mjs";
import {
  eventCategoryClassName,
  eventTone,
  hasActualTimelineDate,
  metricDataCoverage,
  metricDisplayRows,
  metricRiskCount,
  monitoringStatusClass,
  plannedVisitAxis,
  profileDomainCoverage,
  profileMetricEmptyStateMessage,
  profileSubjectMeta,
  referenceEventTooltip,
  referenceTimelineLanes,
  relatedTimelineEvents,
  riskPromptDisplayKey,
  riskPromptDisplayRows,
  riskPromptEvidenceSummary,
  subjectCatalogDisplayRows,
  subjectCatalogSubjectId,
  subjectCenterGroups,
  subjectEvidenceLineageSummary,
  subjectSourceLocatorState,
  timelineEventCategoryLabel,
  timelineDataCoverage,
  timelineEventSelectionKey,
  timelineHeaderMeta,
  timelineLaneClassName,
  timelineLegendItems,
  timelineLegendLabel,
  timelineVisitDisplayRows,
  trendPointDisplayRows,
} from "./medicalMonitoringSubjectModels.mjs";
import "./MedicalMonitoringSubjectViews.css";

function SectionTitle({ eyebrow, title, action }) {
  return (
    <div className="section-title">
      <div>
        {eyebrow && <span>{eyebrow}</span>}
        <h2>{title}</h2>
      </div>
      {action}
    </div>
  );
}

function Tag({ children, tone = "neutral" }) {
  return <span className={`tag ${tone}`}>{children}</span>;
}

function lineageTone(status) {
  return {
    bound: "success",
    partial: "warning",
    unbound: "danger",
    empty: "info",
  }[status] || "info";
}

function sourceLocatorLabel(record) {
  const state = subjectSourceLocatorState(record);
  if (state.status === "malformed") {
    return state.locator ? `来源定位形状异常：${state.locator}` : "来源定位形状异常";
  }
  return state.locator ? `来源定位：${state.locator}` : "来源定位：缺失";
}

function riskEvidenceLabel(prompt) {
  const summary = riskPromptEvidenceSummary(prompt);
  return summary.identifiers.length
    ? `${summary.label}：${summary.identifiers.join("、")}`
    : summary.label;
}

function formatTrendNumber(value, digits = 2) {
  if (typeof value !== "number" || !Number.isFinite(value)) return value;
  return Number(value.toFixed(digits)).toString();
}

function trendPointExplicitValue(value) {
  if (value === undefined || value === null || value === "") return "未提供";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "值形状不可展示";
    }
  }
  return String(value);
}

function trendPointRawValue(point) {
  const value = Object.prototype.hasOwnProperty.call(point || {}, "raw_value")
    ? point.raw_value
    : point?.value;
  return trendPointExplicitValue(value);
}

function trendPointReferenceRange(point) {
  if (typeof point?.reference_range_text === "string" && point.reference_range_text.trim()) {
    return point.reference_range_text.trim();
  }
  const range = point?.reference_range;
  if (range && typeof range === "object" && !Array.isArray(range)) {
    const low = range.low ?? range.lower ?? range.min;
    const high = range.high ?? range.upper ?? range.max;
    const values = [low, high].filter((value) => value !== undefined && value !== null && value !== "");
    if (values.length) return values.join(" – ");
  }
  const low = point?.reference_low;
  const high = point?.reference_high;
  if (low !== undefined || high !== undefined) {
    return [low, high].filter((value) => value !== undefined && value !== null && value !== "").join(" – ");
  }
  return "未提供";
}

function trendPointClinicalSignificance(point) {
  return trendPointExplicitValue(
    point?.clinical_significance
      ?? point?.cs_ncs
      ?? point?.investigator_assessment,
  );
}

function trendPointSourceText(point) {
  const candidates = [
    point?.source_excerpt,
    point?.source_text,
    point?.evidence_text,
    point?.source_content,
    point?.source_body,
  ];
  const explicit = candidates.find((value) => typeof value === "string" && value.trim())
    ?? candidates.find((value) => value !== undefined && value !== null);
  return trendPointExplicitValue(explicit);
}

function trendPointRiskLabel(point) {
  const riskIds = Array.isArray(point?.related_risk_ids)
    ? point.related_risk_ids.filter((value) => typeof value === "string" && value.trim())
    : [];
  if (riskIds.length) return `已绑定：${riskIds.join("、")}`;
  if (point?.risk_flag || ["high", "low"].includes(point?.normality)) return "异常标记；未提供风险 ID";
  return "未提供显式关联风险 ID";
}

function timelineEventSourceText(event) {
  const candidates = [
    event?.source_excerpt,
    event?.source_text,
    event?.evidence_text,
    event?.source_content,
    event?.source_body,
  ];
  const explicit = candidates.find((value) => typeof value === "string" && value.trim())
    ?? candidates.find((value) => value !== undefined && value !== null);
  return trendPointExplicitValue(explicit);
}

function timelineEventRiskLabel(event) {
  const riskIds = Array.isArray(event?.related_risk_ids)
    ? event.related_risk_ids.filter((value) => typeof value === "string" && value.trim())
    : [];
  return riskIds.length ? `已绑定：${riskIds.join("、")}` : "未提供显式关联风险 ID";
}

function trendPointStatusLabel(point, isFocused) {
  if (isFocused) return "当前风险";
  if (typeof point.value !== "number" || !Number.isFinite(point.value)) return "数值未提供";
  if (point.related_risk_ids?.length) return "风险关联";
  if (point.risk_flag) return "异常关注";
  if (point.is_baseline) return "基线组成";
  return {
    normal: "正常",
    high: "偏高",
    low: "偏低",
    abnormal: "异常",
    not_applicable: "已记录",
  }[point.normality] || "已记录";
}

function SubjectCatalogControl({ subjectCatalog = [], selectedSubject, setSelectedSubject, className = "" }) {
  const displayRows = subjectCatalogDisplayRows(subjectCatalog);
  if (subjectCatalog.length > 12) {
    return (
      <label className={`subject-catalog-select ${className}`}>
        <select value={selectedSubject} onChange={(event) => setSelectedSubject(event.target.value)}>
          {displayRows.map((item) => {
            const subjectId = subjectCatalogSubjectId(item);
            const ambiguous = item.displayIdentityState !== "ready";
            return (
              <option key={item.displayKey} value={subjectId} disabled={ambiguous}>
                {subjectId || "受试者身份待核对"} | 中心 {item.site || "-"} | {item.status || "状态未记录"}{ambiguous ? " · 身份待核对" : ""}
              </option>
            );
          })}
        </select>
      </label>
    );
  }
  return (
    <div className={`segmented subject-switch ${className}`}>
      {displayRows.map((item) => {
        const subjectId = subjectCatalogSubjectId(item);
        const ambiguous = item.displayIdentityState !== "ready";
        return (
          <button
            key={item.displayKey}
            className={subjectId === selectedSubject ? "active" : ""}
            disabled={ambiguous}
            aria-disabled={ambiguous ? "true" : undefined}
            title={ambiguous ? item.displayIdentityIssue : undefined}
            onClick={() => {
              if (!ambiguous) setSelectedSubject(subjectId);
            }}
          >
            {subjectId || "身份待核对"}
          </button>
        );
      })}
    </div>
  );
}

function timelineDateValue(value, precision = "day") {
  const match = String(value || "").match(/^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = match[2] ? Number(match[2]) - 1 : precision === "year" ? 6 : 0;
  const day = match[3] ? Number(match[3]) : precision === "month" ? 15 : 1;
  const result = Date.UTC(year, month, day);
  return Number.isNaN(result) ? null : result;
}

function timelineEventBounds(event, fallbackMin, fallbackMax) {
  const start = timelineDateValue(event.event_date, event.date_precision);
  const end = timelineDateValue(event.event_end_date, "day");
  return {
    start: start ?? fallbackMin,
    end: end ?? (event.ongoing && start !== null ? fallbackMax : start ?? fallbackMin),
    undated: start === null,
    preWindow: start !== null && start < fallbackMin,
    postWindow: start !== null && start > fallbackMax,
  };
}

function packLaneEvents(events, xForDate, minDate, maxDate) {
  const minimumEventWidth = 16;
  const tracks = [];
  return events.map(({ event, displayLabel, selectionKey }) => {
    const bounds = timelineEventBounds(event, minDate, maxDate);
    const startX = xForDate(bounds.start);
    const endX = Math.max(startX, xForDate(bounds.end));
    const packedEndX = Math.max(endX, startX + minimumEventWidth);
    let track = tracks.findIndex((trackEnd) => startX > trackEnd + 8);
    if (track < 0) {
      track = tracks.length;
      tracks.push(packedEndX);
    } else {
      tracks[track] = packedEndX;
    }
    return { event, displayLabel, selectionKey, bounds, startX, endX, track };
  });
}

export function ReferenceTimelineSvg({ visits, lanes, focusRiskId = "", zoom = 1, selectedEventId = "", onEventSelect }) {
  const left = 150;
  const right = 120;
  const timelineEvents = lanes.flatMap((lane) => lane.events.map(({ event }) => event));
  const visitRows = timelineVisitDisplayRows(visits);
  const ambiguousVisitCount = visitRows.filter(({ displayIdentityState }) => displayIdentityState !== "ready").length;
  const coverage = timelineDataCoverage(visits, timelineEvents);
  if (!coverage.hasDateAxis) {
    return (
      <div className="empty-state" role="status">
        日期轴不可建立：未获得有效实际日期；计划日/研究日不替代实际日期。请核对下方来源事件明细。
      </div>
    );
  }
  const datedLanes = lanes.map((lane) => ({
    ...lane,
    events: lane.events.filter(({ event }) => hasActualTimelineDate(event.event_date)),
  }));
  const visitDates = visitRows
    .filter(({ visit }) => hasActualTimelineDate(visit.date))
    .map(({ visit }) => timelineDateValue(visit.date))
    .filter(Number.isFinite);
  const eventDates = datedLanes.flatMap((lane) => lane.events.flatMap(({ event }) => [
    timelineDateValue(event.event_date),
    hasActualTimelineDate(event.event_end_date) ? timelineDateValue(event.event_end_date) : null,
  ])).filter(Number.isFinite);
  const boundedDates = visitDates.length ? visitDates : eventDates;
  const minDate = boundedDates.length ? Math.min(...boundedDates) : Date.now();
  const maxDate = boundedDates.length ? Math.max(...boundedDates, minDate + 86400000) : minDate + 86400000;
  const spanDays = Math.max((maxDate - minDate) / 86400000, 1);
  const width = Math.round(Math.max(1500, Math.min(3200, 420 + spanDays * 7)));
  const xForDate = (value) => {
    const bounded = Math.min(Math.max(value, minDate), maxDate);
    return left + ((bounded - minDate) / Math.max(maxDate - minDate, 1)) * (width - left - right);
  };

  const visitLayout = [];
  let cluster = [];
  const flushCluster = () => {
    cluster.forEach((item, index) => {
      visitLayout.push({
        ...item,
        side: index % 2 === 0 ? "below" : "above",
        level: Math.floor(index / 2),
      });
    });
    cluster = [];
  };
  visitRows.forEach(({ visit, displayKey, displayIdentityState, displayIdentityIssue }) => {
    if (!hasActualTimelineDate(visit.date)) return;
    const visitDate = timelineDateValue(visit.date);
    if (!Number.isFinite(visitDate)) return;
    const x = xForDate(visitDate);
    if (cluster.length && Math.abs(x - cluster[cluster.length - 1].x) >= 108) flushCluster();
    cluster.push({ visit, x, displayKey, displayIdentityState, displayIdentityIssue });
  });
  flushCluster();

  const maxAbove = Math.max(0, ...visitLayout.filter((item) => item.side === "above").map((item) => item.level));
  const maxBelow = Math.max(0, ...visitLayout.filter((item) => item.side === "below").map((item) => item.level));
  const tagGap = 38;
  const axisY = 96 + maxAbove * tagGap;
  let cursorY = axisY + 76 + maxBelow * tagGap;
  const rowGap = 20;
  const laneGap = 22;
  const laneLayouts = datedLanes.map((lane) => {
    const packedEvents = packLaneEvents(lane.events, xForDate, minDate, maxDate);
    const trackCount = Math.max(0, ...packedEvents.map((item) => item.track)) + 1;
    const height = Math.max(48, Math.max(trackCount, 1) * rowGap + 14);
    const layout = { lane, packedEvents, y: cursorY, height };
    cursorY += height + laneGap;
    return layout;
  });
  const height = cursorY + 24;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="reference-timeline-svg"
      role="group"
      aria-label="受试者时间线"
      style={{ width: `${Math.round(width * zoom)}px`, maxWidth: "none" }}
    >
      <line x1={left} y1={axisY} x2={width - right} y2={axisY} className="reference-svg-axis" />
      <text x={left} y="30" className="reference-svg-date">{visitRows.find(({ visit }) => hasActualTimelineDate(visit.date))?.visit.date || ""}</text>
      <text x={width - right} y="30" textAnchor="end" className="reference-svg-date">{[...visitRows].reverse().find(({ visit }) => hasActualTimelineDate(visit.date))?.visit.date || ""}</text>
      {ambiguousVisitCount > 0 && (
        <text x={left} y="48" className="reference-svg-date">访视身份待核对 {ambiguousVisitCount} 条</text>
      )}
      {visitLayout.map((item) => {
        const labelY = item.side === "above" ? axisY - 38 - item.level * tagGap : axisY + 28 + item.level * tagGap;
        const dateY = item.side === "above" ? axisY - 20 - item.level * tagGap : axisY + 46 + item.level * tagGap;
        return (
          <g key={item.displayKey} aria-label={item.displayIdentityState !== "ready" ? item.displayIdentityIssue : undefined}>
            <line x1={item.x} y1={axisY - 16} x2={item.x} y2={height - 30} className="reference-svg-visit-line" />
            <circle cx={item.x} cy={axisY} r="4.5" className={`reference-svg-visit-dot ${item.visit.isUnscheduled ? "unscheduled" : ""}`}>
              <title>{[item.visit.code, item.visit.date, item.visit.label].filter(Boolean).join("｜")}</title>
            </circle>
            <text x={item.x} y={labelY} textAnchor="middle" className="reference-svg-visit-label">{item.visit.code}</text>
            <text x={item.x} y={dateY} textAnchor="middle" className="reference-svg-visit-date">{item.visit.date}</text>
          </g>
        );
      })}
      {laneLayouts.map(({ lane, packedEvents, y, height: laneHeight }) => (
        <g key={lane.key}>
          <text x="22" y={y + 14} className="reference-svg-lane-title">{lane.label} ({lane.events.length})</text>
          <line x1={left} y1={y - 14} x2={width - right} y2={y - 14} className="reference-svg-lane-rule" />
          {packedEvents.length ? packedEvents.map(({ event, displayLabel, selectionKey, bounds, startX, endX, track }) => {
            const eventY = y + track * rowGap;
            const eventBlockX = Math.min(Math.max(startX, left), width - right - 12);
            const eventBlockWidth = Math.max(16, Math.min(width - right - eventBlockX, endX - startX || 16));
            const isFocused = Boolean(focusRiskId && event.related_risk_ids?.includes(focusRiskId));
            const isSelected = selectedEventId === selectionKey;
            const handleEventKeyDown = (keyboardEvent) => {
              if (keyboardEvent.key !== "Enter" && keyboardEvent.key !== " ") return;
              keyboardEvent.preventDefault();
              onEventSelect?.(selectionKey);
            };
            return (
              <g
                key={selectionKey}
                className={`${isFocused ? "risk-focus-event" : ""} timeline-event-interactive ${isSelected ? "timeline-event-selected" : ""}`}
                role="button"
                tabIndex="0"
                aria-pressed={isSelected}
                aria-label={`查看 ${event.title || displayLabel || "时间线事件"} 原始事实`}
                onClick={() => onEventSelect?.(selectionKey)}
                onKeyDown={handleEventKeyDown}
              >
                <rect
                  x={eventBlockX}
                  y={eventY}
                  width={eventBlockWidth}
                  height="17"
                  rx="3"
                  className={`reference-svg-event-block ${timelineLaneClassName(lane.key)} ${eventCategoryClassName(event)} ${eventTone(event)} ${isFocused ? "risk-focus-event" : ""}`}
                >
                  <title>{referenceEventTooltip(event, displayLabel)}</title>
                </rect>
                {eventBlockWidth >= 44 && (
                  <text x={eventBlockX + 5} y={eventY + 12} className="reference-svg-event-inline">{displayLabel}</text>
                )}
                {bounds.undated && (
                  <text x={eventBlockX + 16} y={eventY + 12} className="reference-svg-event-undated">日期未提供</text>
                )}
                {bounds.preWindow && (
                  <text x={eventBlockX + 3} y={eventY + 12} className="reference-svg-boundary-arrow">‹</text>
                )}
                {bounds.postWindow && (
                  <text x={eventBlockX + eventBlockWidth - 3} y={eventY + 12} textAnchor="end" className="reference-svg-boundary-arrow">›</text>
                )}
              </g>
            );
          }) : (
            <text x="142" y={y + 13} textAnchor="end" className="reference-svg-event-empty">暂无</text>
          )}
          <line x1={left} y1={y + laneHeight + 6} x2={width - right} y2={y + laneHeight + 6} className="reference-svg-lane-rule soft" />
        </g>
      ))}
    </svg>
  );
}

export function TrendSparkline({ metric, compact = false, focusRiskId = "" }) {
  const points = Array.isArray(metric?.points)
    ? metric.points.filter((point) => point && typeof point === "object" && !Array.isArray(point))
    : [];
  const [showAllPoints, setShowAllPoints] = useState(false);
  const [selectedPointKey, setSelectedPointKey] = useState("");
  const metricKey = metric?.metric_key || metric?.metric_label || "metric";
  const pointEntries = trendPointDisplayRows(points, metricKey).map((entry) => ({
    ...entry,
    key: entry.displayKey,
  }));
  const pointKeySignature = pointEntries.map(({ key }) => key).join("|");
  const pointIdentityWarningCount = pointEntries.filter(({ displayIdentityState }) => displayIdentityState !== "ready").length;

  useEffect(() => {
    setSelectedPointKey("");
    setShowAllPoints(false);
  }, [metricKey, pointKeySignature]);

  if (!points.length) return <div className="empty-state">暂无 {metric?.metric_label || "指标"} 趋势</div>;
  const coverage = metricDataCoverage({ ...metric, points });
  const chartPointEntries = pointEntries.filter(({ point }) => (
    typeof point.value === "number"
    && Number.isFinite(point.value)
    && hasActualTimelineDate(point.assessment_date)
  ));
  const chartPoints = chartPointEntries.map(({ point }) => point);
  const width = 620;
  const height = compact ? 132 : 170;
  const pad = { left: 42, right: 18, top: 18, bottom: 30 };
  const values = chartPoints.map((point) => point.value);
  const refs = chartPoints
    .flatMap((point) => [point.reference_low, point.reference_high])
    .filter((value) => typeof value === "number" && Number.isFinite(value));
  const minValue = values.length ? Math.min(...values, ...refs) : 0;
  const maxValue = values.length ? Math.max(...values, ...refs) : 1;
  const yMin = minValue === maxValue ? minValue - 1 : minValue - (maxValue - minValue) * 0.12;
  const yMax = minValue === maxValue ? maxValue + 1 : maxValue + (maxValue - minValue) * 0.12;
  const pointDates = chartPoints.map((point) => timelineDateValue(point.assessment_date));
  const datedValues = pointDates.filter(Number.isFinite);
  const minDate = datedValues.length ? Math.min(...datedValues) : Date.now();
  const maxDate = datedValues.length ? Math.max(...datedValues, minDate + 86400000) : minDate + 86400000;
  const xFor = (index) => {
    const value = pointDates[index];
    if (!Number.isFinite(value)) {
      return pad.left + (chartPoints.length === 1 ? 0 : (index / (chartPoints.length - 1)) * (width - pad.left - pad.right));
    }
    return pad.left + ((value - minDate) / Math.max(maxDate - minDate, 1)) * (width - pad.left - pad.right);
  };
  const yFor = (value) => pad.top + ((yMax - value) / (yMax - yMin || 1)) * (height - pad.top - pad.bottom);
  const line = chartPoints.map((point, index) => `${xFor(index)},${yFor(point.value)}`).join(" ");
  const baselineValue = chartPoints.find((point) => typeof point.baseline_value === "number" && Number.isFinite(point.baseline_value))?.baseline_value;
  const baselinePoint = chartPoints.find((point) => point.is_baseline) || chartPoints[0];
  const baselineExpected = baselinePoint?.baseline_expected_count;
  const baselineObserved = baselinePoint?.baseline_observed_count;
  const baselineRule = baselinePoint?.baseline_rule;
  const riskCount = metricRiskCount({ points });
  const visiblePointDetails = showAllPoints || points.length <= 12
    ? pointEntries
    : pointEntries.filter(({ point }, index) => (
        index === 0
        || index === points.length - 1
        || point.is_baseline
        || point.risk_flag
        || (focusRiskId && point.related_risk_ids?.includes(focusRiskId))
      ));
  const selectedPointEntry = pointEntries.find(({ key }) => key === selectedPointKey) || null;
  const selectedPoint = selectedPointEntry?.point || null;
  const selectPoint = (key) => setSelectedPointKey((current) => (current === key ? "" : key));
  const handlePointKeyDown = (event, key) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    selectPoint(key);
  };
  return (
    <div className="metric-chart">
      <div className="metric-chart-head">
        <div>
          <strong>{metric.metric_label}</strong>
          <span>{metric.unit || "分值"} · {metric.direction === "lower_is_better" ? "越低越好" : metric.direction === "stable_range" ? "参考范围内稳定" : "越高越好"}</span>
          {baselineRule && (
            <span className="metric-baseline-note">
              {typeof baselineValue === "number" ? `基线 ${baselineValue.toFixed(2)}` : "未生成基线"}
              {Number.isFinite(baselineExpected) && Number.isFinite(baselineObserved)
                ? ` · ${baselineObserved}/${baselineExpected} 个组成点`
                : ""}
              {` · ${baselineRule}`}
            </span>
          )}
          {coverage.invalidValuePoints > 0 && (
            <span className="metric-baseline-note">
              {coverage.invalidValuePoints} 个原始点数值不可绘制，已保留在明细中，未纳入图形。
            </span>
          )}
          {coverage.undatedDatePoints > 0 && (
            <span className="metric-baseline-note">
              {coverage.undatedDatePoints} 个原始点缺少有效实际日期，已保留在明细中，未纳入图形。
            </span>
          )}
          {pointIdentityWarningCount > 0 && (
            <span className="metric-baseline-note">
              {pointIdentityWarningCount} 个数据点身份待核对，已保留原始事实但暂不能确认单点来源。
            </span>
          )}
          {metric.displayIdentityState !== "ready" && (
            <span className="metric-baseline-note">{metric.displayIdentityIssue}</span>
          )}
        </div>
        <Tag tone={riskCount || coverage.invalidValuePoints || coverage.undatedDatePoints || pointIdentityWarningCount ? "warning" : "success"}>{riskCount ? `${riskCount} 个关注点` : coverage.invalidValuePoints || coverage.undatedDatePoints || pointIdentityWarningCount ? "数据待核对" : "趋势可读"}</Tag>
      </div>
      {chartPoints.length ? (
        <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label={`${metric.metric_label} 历时趋势`}>
          <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="chart-axis-line" />
          <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} className="chart-axis-line" />
          {chartPointEntries.map(({ point, key }, index) => {
            if (!Number.isFinite(point.reference_low) && !Number.isFinite(point.reference_high)) return null;
            const x = xFor(index);
            const lowY = Number.isFinite(point.reference_low) ? yFor(point.reference_low) : height - pad.bottom;
            const highY = Number.isFinite(point.reference_high) ? yFor(point.reference_high) : pad.top;
            return (
              <g key={`reference-${key}`} className="chart-point-reference">
                <line x1={x} y1={highY} x2={x} y2={lowY} />
                <line x1={x - 4} y1={highY} x2={x + 4} y2={highY} />
                <line x1={x - 4} y1={lowY} x2={x + 4} y2={lowY} />
              </g>
            );
          })}
          {typeof baselineValue === "number" && (
            <g className="chart-baseline">
              <line x1={pad.left} y1={yFor(baselineValue)} x2={width - pad.right} y2={yFor(baselineValue)} />
              <text x={width - pad.right} y={yFor(baselineValue) - 4} textAnchor="end">基线 {baselineValue.toFixed(2)}</text>
            </g>
          )}
          <polyline points={line} className="chart-line" />
          {chartPointEntries.map(({ point, key }, index) => {
            const isFocused = Boolean(focusRiskId && point.related_risk_ids?.includes(focusRiskId));
            return (
              <g
                key={key}
                className={`chart-point-interactive ${isFocused ? "risk-focus-point" : ""} ${selectedPointKey === key ? "chart-point-selected" : ""}`}
                role="button"
                tabIndex="0"
                aria-pressed={selectedPointKey === key}
                aria-label={`查看 ${metric.metric_label || "指标"} ${point.assessment_date || point.visit_code || "数据点"} 原始事实`}
                onClick={() => selectPoint(key)}
                onKeyDown={(event) => handlePointKeyDown(event, key)}
              >
                <circle cx={xFor(index)} cy={yFor(point.value)} r="12" className="chart-point-hit-area" aria-hidden="true" />
                <circle cx={xFor(index)} cy={yFor(point.value)} r={isFocused ? 7 : point.risk_flag ? 5 : point.is_baseline ? 4.5 : 3.5} className={`${point.risk_flag ? "chart-point risk" : "chart-point"} ${point.is_baseline ? "baseline" : ""} ${isFocused ? "risk-focus-point" : ""}`}>
                  <title>
                    {[point.assessment_date, point.visit_code, `${point.value} ${point.unit || metric.unit || ""}`, point.is_baseline ? "基线组成点" : "", point.reference_range_text, point.clinical_significance, point.ctcae_grade !== null && point.ctcae_grade !== undefined ? `CTCAE ${point.ctcae_grade}级` : ""].filter(Boolean).join("｜")}
                  </title>
                </circle>
                {(chartPoints.length <= 8 || index === 0 || index === chartPoints.length - 1 || point.risk_flag) && (
                  <text x={xFor(index)} y={height - 10} textAnchor="middle" className="chart-label">{point.visit_code || point.assessment_date}</text>
                )}
                {(chartPoints.length <= 12 || index === 0 || index === chartPoints.length - 1 || point.risk_flag || isFocused) && (
                  <text x={xFor(index)} y={yFor(point.value) - 8} textAnchor="middle" className="chart-value">{point.value}</text>
                )}
              </g>
            );
          })}
        </svg>
      ) : (
        <div className="empty-state" role="status">
          暂无可绘制的 {metric?.metric_label || "指标"} 数值/实际日期；原始测量点仍保留在下方明细。
        </div>
      )}
      {selectedPoint && (
        <aside className="metric-point-inspector" aria-label={`${metric.metric_label || "指标"}数据点详情`}>
          <header>
            <div>
              <span>Selected point</span>
              <strong>数据点原始事实</strong>
            </div>
            <button type="button" onClick={() => setSelectedPointKey("")}>关闭</button>
          </header>
          <dl>
            {selectedPointEntry?.displayIdentityState !== "ready" && (
              <div><dt>点身份</dt><dd>{selectedPointEntry.displayIdentityIssue}</dd></div>
            )}
            <div><dt>原始值</dt><dd>{trendPointRawValue(selectedPoint)}{selectedPoint.unit || metric.unit ? ` ${selectedPoint.unit || metric.unit}` : ""}</dd></div>
            <div><dt>日期 / 访视</dt><dd>{selectedPoint.assessment_date || "日期未提供"} · {selectedPoint.visit_code || selectedPoint.visit_label || "访视未提供"}</dd></div>
            <div><dt>参考范围</dt><dd>{trendPointReferenceRange(selectedPoint)}</dd></div>
            <div><dt>CS / NCS</dt><dd>{trendPointClinicalSignificance(selectedPoint)}</dd></div>
            <div><dt>值状态</dt><dd>{trendPointExplicitValue(selectedPoint.value_status || selectedPoint.normality)}</dd></div>
            <div><dt>关联风险</dt><dd>{trendPointRiskLabel(selectedPoint)}</dd></div>
            <div><dt>来源正文</dt><dd>{trendPointSourceText(selectedPoint)}</dd></div>
          </dl>
          <div className="metric-point-inspector-source">
            <span>来源定位</span>
            <code>{subjectSourceLocatorState(selectedPoint).locator || "未提供"}</code>
          </div>
          <p>原始事实优先展示；来源定位存在不等于来源真实性或风险已确认。</p>
        </aside>
      )}
      <div className="metric-point-list">
        {visiblePointDetails.map(({ point, key, displayIdentityState, displayIdentityIssue }) => {
          const isFocused = Boolean(focusRiskId && point.related_risk_ids?.includes(focusRiskId));
          const hasNumericValue = typeof point.value === "number" && Number.isFinite(point.value);
          return (
            <div
              className={`${isFocused ? "risk-focus-point" : ""} ${selectedPointKey === key ? "metric-point-selected" : ""}`}
              key={key}
              role="button"
              tabIndex="0"
              aria-pressed={selectedPointKey === key}
              aria-label={`查看 ${metric.metric_label || "指标"} ${point.assessment_date || point.visit_code || "数据点"} 原始事实`}
              onClick={() => selectPoint(key)}
              onKeyDown={(event) => handlePointKeyDown(event, key)}
            >
              <strong>{point.visit_code}</strong>
              <span>
                {point.assessment_date || "日期未提供"} · {hasNumericValue ? point.value : "数值未提供"}{hasNumericValue && (point.unit || metric.unit) ? ` ${point.unit || metric.unit}` : ""}
                {typeof point.change_from_baseline === "number" ? ` · 较基线 ${formatTrendNumber(point.change_from_baseline)}` : ""}
                {point.reference_range_text ? ` · ref(${point.reference_range_text})` : ""}
                {point.abnormal_direction === "high" ? " ↑" : point.abnormal_direction === "low" ? " ↓" : ""}
                {point.ctcae_grade !== null && point.ctcae_grade !== undefined ? ` · CTCAE ${point.ctcae_grade}级` : ""}
                {` · ${sourceLocatorLabel(point)}`}
              </span>
              {displayIdentityState !== "ready" && (
                <Tag tone="warning" title={displayIdentityIssue}>{displayIdentityState === "duplicate" ? "身份重复" : "身份待核对"}</Tag>
              )}
              <Tag tone={!hasNumericValue || point.risk_flag || point.normality === "high" || point.normality === "low" ? "warning" : "success"}>
                {trendPointStatusLabel(point, isFocused)}
              </Tag>
            </div>
          );
        })}
      </div>
      {points.length > visiblePointDetails.length && (
        <button type="button" className="metric-points-toggle" onClick={() => setShowAllPoints(true)}>
          查看全部 {points.length} 个原始测量点
        </button>
      )}
      {showAllPoints && points.length > 12 && (
        <button type="button" className="metric-points-toggle" onClick={() => setShowAllPoints(false)}>
          收起原始测量点
        </button>
      )}
    </div>
  );
}

function ProfileFilterBar({ selectedCenter, setSelectedCenter, search, setSearch, visibleSubjects, selectedSubject, setSelectedSubject, allSubjects = [] }) {
  const displaySubjects = subjectCatalogDisplayRows(allSubjects);
  const centers = subjectCenterGroups(displaySubjects).map((group) => group.center);
  const useCenterSelect = centers.length > 8;
  return (
    <section className="panel profile-filter-bar">
      <div>
        <strong>中心筛选</strong>
        {useCenterSelect ? (
          <select
            className="profile-center-select"
            aria-label="中心筛选"
            value={selectedCenter}
            onChange={(event) => setSelectedCenter(event.target.value)}
          >
            <option value="all">全部中心（{centers.length}）</option>
            {centers.map((center) => <option key={center} value={center}>中心 {center}</option>)}
          </select>
        ) : (
          <div className="segmented">
            <button className={selectedCenter === "all" ? "active" : ""} onClick={() => setSelectedCenter("all")}>全部</button>
            {centers.map((center) => (
              <button key={center} className={selectedCenter === center ? "active" : ""} onClick={() => setSelectedCenter(center)}>
                {center}
              </button>
            ))}
          </div>
        )}
      </div>
      <div>
        <strong>受试者切换</strong>
        <SubjectCatalogControl
          subjectCatalog={visibleSubjects}
          selectedSubject={selectedSubject}
          setSelectedSubject={setSelectedSubject}
        />
      </div>
      <label>
        <strong>检索</strong>
        <span>
          <Search size={15} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="受试者、中心、状态" />
        </span>
      </label>
    </section>
  );
}

function ProfileSubjectTree({ selectedCenter, search, selectedSubject, setSelectedSubject, allSubjects = [] }) {
  const treeContainerRef = useRef(null);
  const selectedButtonRef = useRef(null);
  const query = search.trim().toLowerCase();
  const displaySubjects = subjectCatalogDisplayRows(allSubjects);
  const groups = subjectCenterGroups(displaySubjects)
    .filter((group) => selectedCenter === "all" || group.center === selectedCenter)
    .map((group) => ({
      ...group,
      subjects: group.subjects.filter((item) => {
        const haystack = [subjectCatalogSubjectId(item), item.site, item.status, item.profile].filter(Boolean).join(" ").toLowerCase();
        return !query || haystack.includes(query);
      }),
    }))
    .filter((group) => group.subjects.length);

  useEffect(() => {
    const container = treeContainerRef.current;
    const selected = selectedButtonRef.current;
    if (!container || !selected) return;
    const offset = selected.getBoundingClientRect().top - container.getBoundingClientRect().top;
    container.scrollTop += offset - 64;
  }, [selectedSubject, selectedCenter, query]);

  return (
    <aside className="panel profile-subject-list" ref={treeContainerRef}>
      <SectionTitle title="中心 / 受试者树" />
      <div className="profile-tree">
        {groups.map((group) => (
          <div className="profile-tree-group" key={group.center}>
            <div className="profile-tree-center">
              <strong>中心 {group.center}</strong>
              <span>{group.subjects.length} 例</span>
            </div>
            {group.subjects.map((item) => {
              const subjectId = subjectCatalogSubjectId(item);
              const ambiguous = item.displayIdentityState !== "ready";
              return (
                <button
                  key={item.displayKey}
                  ref={!ambiguous && subjectId === selectedSubject ? selectedButtonRef : null}
                  className={!ambiguous && subjectId === selectedSubject ? "selected" : ""}
                  disabled={ambiguous}
                  aria-disabled={ambiguous ? "true" : undefined}
                  title={ambiguous ? item.displayIdentityIssue : undefined}
                  onClick={() => {
                    if (!ambiguous) setSelectedSubject(subjectId);
                  }}
                >
                  <strong>{subjectId || "身份待核对"}</strong>
                  <span>{item.profile || `中心 ${item.site || "-"}`}</span>
                  <Tag tone={ambiguous ? "warning" : monitoringStatusClass(item.status)}>
                    {ambiguous ? "身份待核对" : item.status}
                  </Tag>
                </button>
              );
            })}
          </div>
        ))}
        {!groups.length && <div className="empty-state">当前筛选下无受试者。</div>}
      </div>
    </aside>
  );
}

function ProfilePanel({ title, eyebrow, children, action }) {
  return (
    <section className="panel profile-section">
      <SectionTitle eyebrow={eyebrow} title={title} action={action} />
      {children}
    </section>
  );
}

export function SubjectTimelinePage({ subject, setSelectedSubject, onNavigate, subjectCatalog = [], focusRiskId = "" }) {
  const rawProfile = subject.rawProfile;
  const profileUnavailable = !rawProfile;
  const rawEvents = rawProfile?.timeline || [];
  const profileShapeWarnings = Array.isArray(rawProfile?.profile_shape_warnings)
    ? rawProfile.profile_shape_warnings
    : [];
  const capabilityLimitations = rawProfile?.capability_limitations
    && typeof rawProfile.capability_limitations === "object"
    && !Array.isArray(rawProfile.capability_limitations)
    ? rawProfile.capability_limitations
    : {};
  const capabilityMessages = Object.entries(capabilityLimitations).flatMap(([capability, values]) => (
    Array.isArray(values) && values.length
      ? values.map((value) => `${capability}：${value}`)
      : []
  ));
  const capabilityRestricted = rawProfile?.capability_mode === "restricted";
  const visits = plannedVisitAxis(subject, rawEvents);
  const visitDisplayRows = timelineVisitDisplayRows(visits);
  const ambiguousVisitCount = visitDisplayRows.filter(({ displayIdentityState }) => displayIdentityState !== "ready").length;
  const nonVisitEvents = rawEvents.filter((event) => event.event_type !== "visit");
  const timelineCoverage = timelineDataCoverage(visits, nonVisitEvents);
  const actualVisitCount = timelineCoverage.datedVisits;
  const plannedOnlyVisitCount = visits.filter((visit) => (
    !hasActualTimelineDate(visit.date) && visit.plannedDay !== null && visit.plannedDay !== undefined
  )).length;
  const unresolvedVisitDateCount = Math.max(timelineCoverage.undatedVisits - plannedOnlyVisitCount, 0);
  const unscheduledVisitCount = visits.filter((visit) => visit.isUnscheduled).length;
  const visitSummary = profileUnavailable
    ? "个例资料尚未载入"
    : [
      `${actualVisitCount} 个实际日期访视`,
      plannedOnlyVisitCount ? `${plannedOnlyVisitCount} 个计划访视待匹配` : "",
      unresolvedVisitDateCount ? `${unresolvedVisitDateCount} 个访视日期缺失或无效` : "",
      unscheduledVisitCount ? `${unscheduledVisitCount} 个计划外访视` : "",
    ].filter(Boolean).join(" · ");
  const meta = timelineHeaderMeta(subject, rawEvents);
  const evidenceLineage = subjectEvidenceLineageSummary(subject);
  const displayLanes = referenceTimelineLanes(nonVisitEvents);
  const legendItems = timelineLegendItems(displayLanes);
  const focusedEvents = focusRiskId
    ? nonVisitEvents.filter((event) => event.related_risk_ids?.includes(focusRiskId))
    : [];
  const [zoom, setZoom] = useState(1);
  const [expandedLanes, setExpandedLanes] = useState(() => new Set());
  const [selectedEventId, setSelectedEventId] = useState("");

  useEffect(() => {
    setZoom(1);
    setExpandedLanes(new Set());
    setSelectedEventId("");
  }, [subject.id]);

  const selectedEvent = displayLanes
    .flatMap((lane) => lane.events)
    .find(({ selectionKey }) => selectionKey === selectedEventId)?.event || null;

  const toggleLane = (laneKey) => {
    setExpandedLanes((current) => {
      const next = new Set(current);
      if (next.has(laneKey)) next.delete(laneKey);
      else next.add(laneKey);
      return next;
    });
  };

  const selectTimelineEvent = (eventId) => {
    setSelectedEventId((current) => (current === eventId ? "" : eventId));
    const lane = displayLanes.find((item) => item.events.some(({ selectionKey }) => selectionKey === eventId));
    if (lane && lane.events.length > 6) {
      setExpandedLanes((current) => new Set([...current, lane.key]));
    }
  };

  const handleTimelineEventKeyDown = (keyboardEvent, eventId) => {
    if (keyboardEvent.key !== "Enter" && keyboardEvent.key !== " ") return;
    keyboardEvent.preventDefault();
    selectTimelineEvent(eventId);
  };

  const selectedEventLocator = selectedEvent ? subjectSourceLocatorState(selectedEvent) : null;

  return (
    <main className="page timeline-page reference-timeline-page">
      <section className="reference-subject-head">
        <div>
          <h2>{meta.subjectId}</h2>
          <strong>{meta.arm} | {meta.randomization}</strong>
          <p>{meta.site} | {meta.center} | {meta.arm} | {meta.randomization} | 研究窗口 {meta.window}</p>
        </div>
        <div className="reference-subject-actions">
          <span>{meta.sexAgeStatus}</span>
          <button onClick={() => onNavigate("monitoring")}>返回医学监查</button>
        </div>
      </section>

      <section className="reference-subject-switch">
        <span>受试者</span>
        <SubjectCatalogControl
          subjectCatalog={subjectCatalog}
          selectedSubject={subject.id}
          setSelectedSubject={setSelectedSubject}
        />
      </section>

      <section className={`timeline-context-summary ${focusRiskId ? "focused" : ""}`}>
        <strong>{focusRiskId && !profileUnavailable ? `当前风险关联 ${focusedEvents.length} 个事件` : profileUnavailable ? "个例资料尚未载入" : `${nonVisitEvents.length} 个事件 · ${visitSummary}`}</strong>
        <Tag tone={lineageTone(evidenceLineage.status)}>{evidenceLineage.label}</Tag>
        <span>
          {profileUnavailable
            ? "当前个例画像尚未载入；以下空态不代表无风险，也不会用计划日或访视编号补造事件。"
            : focusRiskId
            ? "橙色外框标记当前风险直接关联事实，其余事件保留完整上下文。"
            : timelineCoverage.status === "no_actual_dates"
              ? "未建立日期轴；仅保留来源事件明细，不根据计划日或研究日推算。"
              : timelineCoverage.status === "partial_dates"
                ? "仅将有可验证实际日期的记录放入时间轴；缺失日期记录保留在明细，不作时间窗或先后结论。"
                : "按真实日期展示；计划外访视、持续事件和试验药物记录均保留原始来源。"}
        </span>
        <span role="status">{evidenceLineage.message}</span>
        {profileUnavailable && (
          <p className="profile-data-warning" role="alert">
            当前个例资料尚未载入；Timeline 事件集合保持为空，不能据此判定无风险。请返回医学监查并重试当前受试者读取。
          </p>
        )}
        {profileShapeWarnings.length > 0 && (
          <p className="profile-data-warning" role="alert">
            个例数据字段形状异常，异常字段已停止展示：{profileShapeWarnings.join("、")}；请回到来源证据核查。
          </p>
        )}
        {capabilityRestricted && (
          <p className="profile-data-warning" role="alert">
            当前字段映射处于受限模式，页面仅展示已确认的数据；{capabilityMessages.join("；") || "部分 Timeline/Profile 能力不可用，请勿将空态视为无风险。"}
          </p>
        )}
        {timelineCoverage.status === "no_actual_dates" && (
          <p className="profile-data-warning" role="alert">
            未获得可用于日期轴的有效实际日期；计划日、研究日和访视编号不会替代实际日期。图形时间轴已停用，以下事件明细仍保留来源事实。
          </p>
        )}
        {timelineCoverage.status === "partial_dates" && (
          <p className="profile-data-warning" role="alert">
            {timelineCoverage.undatedEvents + timelineCoverage.undatedVisits} 条访视/事件缺少可验证实际日期，未放入日期轴；不据此作时间窗或先后结论。请在来源证据中核对日期字段。
          </p>
        )}
        {ambiguousVisitCount > 0 && (
          <p className="profile-data-warning" role="alert">
            {ambiguousVisitCount} 条访视缺少或重复来源身份；访视事实仍保留，但暂不能确认单点来源或据此补写身份。
          </p>
        )}
      </section>

      <section className="reference-timeline-shell">
        <div className="timeline-shell-toolbar">
          <div className="timeline-category-legend" aria-label="事件类别颜色图例">
            {legendItems.map((item) => (
              <span className={`timeline-category-chip ${item.className}`} key={item.key}>
                <span aria-hidden="true" />
                {timelineLegendLabel(item)}
              </span>
            ))}
          </div>
          {timelineCoverage.hasDateAxis && <div className="timeline-zoom-control" aria-label="时间线缩放">
            <button
              type="button"
              title="缩小时间线"
              aria-label="缩小时间线"
              disabled={zoom <= 0.8}
              onClick={() => setZoom((current) => Math.max(0.8, Number((current - 0.2).toFixed(1))))}
            >
              <Minus size={15} />
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button
              type="button"
              title="放大时间线"
              aria-label="放大时间线"
              disabled={zoom >= 2}
              onClick={() => setZoom((current) => Math.min(2, Number((current + 0.2).toFixed(1))))}
            >
              <Plus size={15} />
            </button>
          </div>}
        </div>
        {timelineCoverage.hasDateAxis ? (
          <div className="reference-timeline-scroll">
            <div className="reference-timeline-canvas">
              <ReferenceTimelineSvg
                visits={visits}
                lanes={displayLanes}
                focusRiskId={focusRiskId}
                zoom={zoom}
                selectedEventId={selectedEventId}
                onEventSelect={selectTimelineEvent}
              />
            </div>
          </div>
        ) : (
          <div className="empty-state" role="status">
            日期轴不可建立：未获得有效实际日期；计划日/研究日不替代实际日期。请使用下方明细核对来源记录。
          </div>
        )}
      </section>

      {selectedEvent && (
        <aside className="timeline-event-inspector" aria-label="时间线事件原始事实">
          <header>
            <div>
              <span>Selected event / 事件原始事实</span>
              <strong>{selectedEvent.title || "未命名事件"}</strong>
            </div>
            <button type="button" onClick={() => setSelectedEventId("")} aria-label="关闭时间线事件原始事实">关闭</button>
          </header>
          <dl>
            <div>
              <dt>事件类别</dt>
              <dd>{timelineEventCategoryLabel(selectedEvent)}</dd>
            </div>
            <div>
              <dt>原始事实</dt>
              <dd>{[selectedEvent.title, selectedEvent.detail].filter(Boolean).join(" · ") || "未提供"}</dd>
            </div>
            <div>
              <dt>实际日期</dt>
              <dd>{selectedEvent.raw_event_date || selectedEvent.event_date || "未提供"}</dd>
            </div>
            <div>
              <dt>访视 / 研究日</dt>
              <dd>{selectedEvent.visit_code || (Number.isFinite(selectedEvent.study_day) ? `D${selectedEvent.study_day}` : "未提供")}</dd>
            </div>
            <div>
              <dt>严重程度</dt>
              <dd>{selectedEvent.severity || selectedEvent.event_severity || "未提供"}</dd>
            </div>
            <div>
              <dt>关系 / 结局</dt>
              <dd>{[selectedEvent.relationship, selectedEvent.outcome].filter(Boolean).join(" · ") || "未提供"}</dd>
            </div>
            <div>
              <dt>来源正文</dt>
              <dd>{timelineEventSourceText(selectedEvent)}</dd>
            </div>
            <div>
              <dt>关联风险</dt>
              <dd>{timelineEventRiskLabel(selectedEvent)}</dd>
            </div>
          </dl>
          <div className="timeline-event-inspector-source">
            <span>来源定位</span>
            <code>{selectedEventLocator?.locator || "未提供"}</code>
          </div>
          <p>原始事实优先；来源定位存在不等于来源真实性或风险已确认。</p>
        </aside>
      )}

      <section className="timeline-detail-grid">
        {displayLanes.map((lane) => {
          const expanded = expandedLanes.has(lane.key);
          const orderedEvents = focusRiskId
            ? [
                ...lane.events.filter(({ event }) => event.related_risk_ids?.includes(focusRiskId)),
                ...lane.events.filter(({ event }) => !event.related_risk_ids?.includes(focusRiskId)),
              ]
            : lane.events;
          const visibleEvents = expanded ? orderedEvents : orderedEvents.slice(0, 6);
          return (
            <div className="panel timeline-detail-card" key={lane.key}>
              <SectionTitle
                title={`${lane.label} 明细`}
                action={lane.events.length > 6 ? (
                  <button type="button" className="button-link" onClick={() => toggleLane(lane.key)}>
                    {expanded ? "收起" : `查看全部 ${lane.events.length} 条`}
                  </button>
                ) : null}
              />
              {visibleEvents.length ? visibleEvents.map(({ event, displayLabel, selectionKey }) => (
                <div
                  className={`timeline-detail-row ${eventCategoryClassName(event)} ${focusRiskId && event.related_risk_ids?.includes(focusRiskId) ? "risk-focus-event" : ""} timeline-event-interactive ${selectedEventId === selectionKey ? "timeline-event-selected" : ""}`}
                  key={selectionKey}
                  role="button"
                  tabIndex="0"
                  aria-pressed={selectedEventId === selectionKey}
                  aria-label={`查看 ${event.title || displayLabel || "时间线事件"} 原始事实`}
                  onClick={() => selectTimelineEvent(selectionKey)}
                  onKeyDown={(keyboardEvent) => handleTimelineEventKeyDown(keyboardEvent, selectionKey)}
                >
                  <Tag tone={eventTone(event) === "critical" ? "danger" : eventTone(event) === "warning" ? "warning" : "info"}>{timelineEventCategoryLabel(event)}</Tag>
                  <div>
                    <strong>{displayLabel} · {event.visit_code || (Number.isFinite(event.study_day) ? `D${event.study_day}` : "访视未标注")} · {event.title}</strong>
                    <span>
                      {event.source_domain ? `${event.source_domain} · ` : ""}
                      {[
                        event.raw_event_date || event.event_date || "日期未提供",
                        (event.raw_event_end_date || event.event_end_date)
                          ? `至 ${event.raw_event_end_date || event.event_end_date}`
                          : event.ongoing ? "持续中" : "",
                        event.detail,
                      ].filter(Boolean).join(" · ")}
                    </span>
                    <span title={subjectSourceLocatorState(event).message}>{sourceLocatorLabel(event)}</span>
                    {event.clinical_interpretation && <em>{event.clinical_interpretation}</em>}
                  </div>
                </div>
              )) : <p className="quiet-text">当前受试者该域暂无事件。</p>}
              {!expanded && lane.events.length > visibleEvents.length && (
                <button type="button" className="timeline-detail-more" onClick={() => toggleLane(lane.key)}>
                  其余 {lane.events.length - visibleEvents.length} 条按时间收起
                </button>
              )}
            </div>
          );
        })}
      </section>
    </main>
  );
}

function ProfileDomainCoverage({ coverage }) {
  const tone = coverage.declarationState === "declared"
    ? (coverage.domains.some((item) => item.tone === "danger") ? "danger" : coverage.domains.some((item) => item.tone === "warning") ? "warning" : "info")
    : coverage.declarationState === "missing" || coverage.declarationState === "empty"
      ? "warning"
      : "danger";
  return (
    <section className="profile-domain-coverage" aria-label="来源域覆盖状态">
      <div className="profile-domain-coverage-header">
        <div>
          <span>Data coverage</span>
          <strong>来源域覆盖</strong>
          {coverage.declaredCount > 0 && (
            <small>{coverage.availableCount} / {coverage.declaredCount} 个域已声明可用</small>
          )}
        </div>
        <Tag tone={tone}>{coverage.declarationLabel}</Tag>
      </div>
      {coverage.domains.length ? (
        <div className="profile-domain-coverage-grid">
          {coverage.domains.map((domain) => (
            <div
              className={`profile-domain-coverage-item ${domain.tone}`}
              key={domain.key}
              title={[domain.detail, domain.sourceLocator ? `来源：${domain.sourceLocator}` : ""].filter(Boolean).join("；")}
            >
              <span>{domain.label}</span>
              <strong>{domain.statusLabel}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="profile-domain-coverage-message" role="status">{coverage.declarationMessage}</p>
      )}
      <p className="profile-domain-coverage-disclaimer">{coverage.disclaimer}</p>
    </section>
  );
}

function MetricConfigurationCandidateReview({ state }) {
  const candidates = state?.candidates || [];
  const issues = state?.issues || [];
  const visibleCandidates = candidates.slice(0, 4);
  const hiddenCandidateCount = Math.max(0, candidates.length - visibleCandidates.length);
  const visibleIssues = issues.slice(0, 3);
  const hiddenIssueCount = Math.max(0, issues.length - visibleIssues.length);
  return (
    <section className="profile-metric-candidate-review" aria-label="指标配置候选审阅">
      <div className="profile-metric-candidate-header">
        <div>
          <span>Candidate review</span>
          <strong>指标配置候选</strong>
          <small>只读候选 · 不等同于医学确认或规则发布</small>
        </div>
        <Tag tone={state?.tone || "info"}>{state?.label || "待读取"}</Tag>
      </div>
      <p className="profile-metric-candidate-message" role="status">
        {state?.message || "指标候选尚未读取。"}
      </p>
      {state?.status === "candidate_only" && (
        <>
          <div className="profile-metric-candidate-summary">
            <div><strong>{candidates.length}</strong><span>候选指标</span></div>
            <div><strong>{state.usableCandidateCount}</strong><span>可供审阅</span></div>
            <div><strong>{issues.length}</strong><span>需核对问题</span></div>
          </div>
          <div className="profile-metric-candidate-list">
            {visibleCandidates.map((candidate, index) => (
              <div className="profile-metric-candidate-row" key={metricConfigurationCandidateDisplayKey(candidate, candidate.sourceIndex ?? index)}>
                <div>
                  <strong>{candidate.metric_label || candidate.metric_key || "未命名指标"}</strong>
                  <span>
                    {[candidate.metric_kind, candidate.unit || "单位待确认", metricConfigurationDirectionLabel(candidate.direction)]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </div>
                <div>
                  <Tag tone={candidate.identityState !== "ready" || (Array.isArray(candidate.review_flags) && candidate.review_flags.length) ? "warning" : "info"}>
                    {candidate.identityState === "missing"
                      ? "身份待核对"
                      : candidate.identityState === "duplicate"
                        ? "身份重复"
                        : Array.isArray(candidate.review_flags) && candidate.review_flags.length
                          ? "需复核"
                          : "候选"}
                  </Tag>
                  <small>{metricConfigurationCandidateSource(candidate)}</small>
                  {candidate.identityState !== "ready" && <small>{candidate.identityIssue}</small>}
                </div>
              </div>
            ))}
          </div>
          {hiddenCandidateCount > 0 && <p className="profile-metric-candidate-overflow">其余 {hiddenCandidateCount} 个候选保留在只读接口响应中。</p>}
        </>
      )}
      {issues.length > 0 && (
        <div className="profile-metric-candidate-issues">
          <strong>核对问题</strong>
          {visibleIssues.map((issue, index) => (
            <p key={`${issue.code || "issue"}-${issue.subject || index}-${issue.metric_key || ""}`}>
              <span>{issue.code || "未分类"}</span>
              {issue.detail || issue.subject || "来源/字段问题待核对"}
            </p>
          ))}
          {hiddenIssueCount > 0 && <small>其余 {hiddenIssueCount} 个问题保留在接口响应中。</small>}
        </div>
      )}
    </section>
  );
}

export function PatientProfilePage({
  subject,
  setSelectedSubject,
  onNavigate,
  subjectCatalog = [],
  focusRiskId = "",
  metricConfigurationContext = null,
  metricConfigurationApi = null,
}) {
  const [selectedCenter, setSelectedCenter] = useState(subject.site || "all");
  const [search, setSearch] = useState("");
  const rawProfile = subject.rawProfile;
  const profileUnavailable = !rawProfile;
  const profileShapeWarnings = Array.isArray(rawProfile?.profile_shape_warnings)
    ? rawProfile.profile_shape_warnings
    : [];
  const capabilityLimitations = rawProfile?.capability_limitations
    && typeof rawProfile.capability_limitations === "object"
    && !Array.isArray(rawProfile.capability_limitations)
    ? rawProfile.capability_limitations
    : {};
  const capabilityMessages = Object.entries(capabilityLimitations).flatMap(([capability, values]) => (
    Array.isArray(values) && values.length
      ? values.map((value) => `${capability}：${value}`)
      : []
  ));
  const capabilityRestricted = rawProfile?.capability_mode === "restricted";
  const profileContextKey = `${rawProfile?.project_id || ""}:${subject.id}`;
  const efficacyMetrics = useMemo(
    () => metricDisplayRows(subject.efficacyMetrics || [], "efficacy"),
    [subject.efficacyMetrics],
  );
  const safetyMetrics = useMemo(
    () => metricDisplayRows(subject.safetyMetrics || [], "safety"),
    [subject.safetyMetrics],
  );
  const prompts = rawProfile?.risk_prompts || subject.prompts || [];
  const promptDisplayRows = useMemo(() => riskPromptDisplayRows(prompts), [prompts]);
  const events = rawProfile?.timeline || [];
  const query = search.trim().toLowerCase();
  const displaySubjectCatalog = useMemo(() => subjectCatalogDisplayRows(subjectCatalog), [subjectCatalog]);
  const visibleSubjects = useMemo(() => displaySubjectCatalog.filter((item) => {
    const matchesCenter = selectedCenter === "all" || item.site === selectedCenter;
    const haystack = [subjectCatalogSubjectId(item), item.site, item.status, item.profile].filter(Boolean).join(" ").toLowerCase();
    return matchesCenter && (!query || haystack.includes(query));
  }), [selectedCenter, query, displaySubjectCatalog]);
  const subjectMeta = profileSubjectMeta(subject);
  const evidenceLineage = subjectEvidenceLineageSummary(subject);
  const medicalContext = rawProfile?.subject?.key_medical_context || [];
  const pdQueryEvents = relatedTimelineEvents(events, ["protocol_deviation", "query"]);
  const pdQueryPrompts = promptDisplayRows.filter((prompt) => prompt.query_id || prompt.pd_id);
  const nonVisitEvents = events.filter((event) => event.event_type !== "visit");
  const totalTrendPoints = [...efficacyMetrics, ...safetyMetrics].reduce((sum, metric) => sum + (metric.points?.length || 0), 0);
  const domainCoverage = profileDomainCoverage(rawProfile);
  const metricContextKey = [
    metricConfigurationContext?.projectId || "",
    metricConfigurationContext?.protocolVersionId || "",
    metricConfigurationContext?.batchId || "",
  ].join("|");
  const [metricConfigurationRead, setMetricConfigurationRead] = useState({
    loading: false,
    payload: null,
    error: null,
  });
  const metricConfigurationState = useMemo(
    () => metricConfigurationReviewState({
      context: metricConfigurationContext || undefined,
      ...metricConfigurationRead,
    }),
    [metricConfigurationContext, metricConfigurationRead],
  );

  useEffect(() => {
    const context = metricConfigurationContext;
    if (!context?.ready) {
      setMetricConfigurationRead({ loading: false, payload: null, error: null });
      return undefined;
    }
    let cancelled = false;
    setMetricConfigurationRead({ loading: true, payload: null, error: null });
    const api = metricConfigurationApi || createMedicalMonitoringApi();
    api.getMetricConfigurationCandidates(
      context.projectId,
      context.protocolVersionId,
      context.batchId,
    ).then((payload) => {
      if (!cancelled) setMetricConfigurationRead({ loading: false, payload, error: null });
    }).catch((error) => {
      if (!cancelled) setMetricConfigurationRead({ loading: false, payload: null, error });
    });
    return () => {
      cancelled = true;
    };
  }, [metricContextKey, metricConfigurationApi]);

  useEffect(() => {
    const subjectCenter = subjectCatalog.some((item) => item.site === subject.site) ? subject.site : "all";
    setSelectedCenter(subjectCenter || "all");
    setSearch("");
  }, [profileContextKey]);

  useEffect(() => {
    if (!visibleSubjects.length || visibleSubjects.some((item) => subjectCatalogSubjectId(item) === subject.id)) return;
    const firstReady = visibleSubjects.find((item) => item.displayIdentityState === "ready");
    if (firstReady) setSelectedSubject(subjectCatalogSubjectId(firstReady));
  }, [subject.id, visibleSubjects, setSelectedSubject]);

  return (
    <main className="page patient-profile-page">
      <section className="profile-hero">
        <div>
          <span>医学监查 / Patient Profile</span>
          <h2>{subject.id} 疗效、安全性和医学解释画像</h2>
          <p>{rawProfile?.subject?.key_medical_context?.join("；") || subject.profile}</p>
        </div>
        <button onClick={() => onNavigate("monitoring")}>返回医学监查</button>
      </section>
      {profileShapeWarnings.length > 0 && (
        <p className="profile-data-warning" role="alert">
          个例数据字段形状异常，异常字段已停止展示：{profileShapeWarnings.join("、")}；请回到来源证据核查。
        </p>
      )}
      {capabilityRestricted && (
        <p className="profile-data-warning" role="alert">
          当前字段映射处于受限模式，页面仅展示已确认的数据；{capabilityMessages.join("；") || "部分 Timeline/Profile 能力不可用，请勿将空态视为无风险。"}
        </p>
      )}
      {profileUnavailable && (
        <p className="profile-data-warning" role="alert">
          当前个例资料尚未载入；各数据域保持为空，不能据此判定疗效稳定、安全性稳定或无风险。请返回医学监查并重试当前受试者读取。
        </p>
      )}
      <p
        className={evidenceLineage.status === "bound" ? "profile-domain-footnote" : "profile-data-warning"}
        role="status"
      >
        <Tag tone={lineageTone(evidenceLineage.status)}>{evidenceLineage.label}</Tag>{" "}{evidenceLineage.message}
      </p>

      <ProfileFilterBar
        selectedCenter={selectedCenter}
        setSelectedCenter={setSelectedCenter}
        search={search}
        setSearch={setSearch}
        visibleSubjects={visibleSubjects}
        selectedSubject={subject.id}
        setSelectedSubject={setSelectedSubject}
        allSubjects={subjectCatalog}
      />

      <div className="profile-workbench">
        <ProfileSubjectTree
          selectedCenter={selectedCenter}
          search={search}
          selectedSubject={subject.id}
          setSelectedSubject={setSelectedSubject}
          allSubjects={subjectCatalog}
        />
        <section className="profile-main">
          <div className="panel profile-summary-band">
            <div><strong>{subject.status}</strong><span>当前医学复核状态</span></div>
            <div><strong>{efficacyMetrics.length || "-"}</strong><span>疗效指标</span></div>
            <div><strong>{safetyMetrics.length || "-"}</strong><span>安全性指标</span></div>
            <div><strong>{totalTrendPoints || prompts.length}</strong><span>趋势点 / 风险提示</span></div>
          </div>

          <ProfileDomainCoverage coverage={domainCoverage} />

          <MetricConfigurationCandidateReview state={metricConfigurationState} />

          <ProfilePanel title="基本信息" eyebrow="Profile">
            <div className="profile-info-grid">
              {subjectMeta.length ? subjectMeta.map((item) => (
                <div key={item.label}>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              )) : (
                <div>
                  <span>个例资料</span>
                  <strong>{subject.profile || "待生成完整个例下钻资料"}</strong>
                </div>
              )}
            </div>
            <div className="profile-context-list">
              {(medicalContext.length ? medicalContext : [subject.profile || "完整个例下钻资料待生成；当前仅显示风险登记入口。"]).map((item) => (
                <p key={item}>{item}</p>
              ))}
            </div>
          </ProfilePanel>

          <ProfilePanel title="疗效指标历时变化" eyebrow="Efficacy" action={<Tag tone={efficacyMetrics.length ? "info" : "warning"}>{efficacyMetrics.length || 0} 个指标</Tag>}>
            <div className="metric-chart-grid">
              {efficacyMetrics.length ? efficacyMetrics.map((metric) => (
                <TrendSparkline metric={metric} focusRiskId={focusRiskId} key={metric.displayKey} />
              )) : <div className="empty-state" role="status">{profileMetricEmptyStateMessage(subject, "efficacy")}</div>}
            </div>
          </ProfilePanel>

          <ProfilePanel title="安全性历时变化" eyebrow="Safety" action={<Tag tone={safetyMetrics.some(metricRiskCount) ? "warning" : "info"}>{safetyMetrics.length || 0} 个指标</Tag>}>
            <div className="metric-chart-grid">
              {safetyMetrics.length ? safetyMetrics.map((metric) => (
                <TrendSparkline metric={metric} focusRiskId={focusRiskId} key={metric.displayKey} compact />
              )) : <div className="empty-state" role="status">{profileMetricEmptyStateMessage(subject, "safety")}</div>}
            </div>
          </ProfilePanel>

          <ProfilePanel title="PD / Query" eyebrow="Protocol Deviation">
            <div className="profile-pd-query-grid">
              <div>
                <h3>开放 PD / Query</h3>
                {pdQueryPrompts.length ? pdQueryPrompts.map((prompt, index) => (
                  <div className="profile-query-card" key={riskPromptDisplayKey(prompt, index)}>
                    <Tag tone={monitoringStatusClass(prompt.severity)}>{severityLabel(prompt.severity)}</Tag>
                    {prompt.displayIdentityState !== "ready" && (
                      <Tag tone="warning">{prompt.displayIdentityState === "duplicate" ? "身份重复" : "身份待核对"}</Tag>
                    )}
                    <div>
                      <strong>{prompt.query_id || prompt.pd_id || prompt.visit_code} · {prompt.title}</strong>
                      <span title={prompt.displayIdentityIssue || riskPromptEvidenceSummary(prompt).message}>{prompt.recommended_action} · {sourceLocatorLabel(prompt)} · {riskEvidenceLabel(prompt)}</span>
                    </div>
                  </div>
                )) : <p className={profileUnavailable ? "profile-data-warning" : "quiet-text"} role={profileUnavailable ? "alert" : undefined}>{profileUnavailable ? "个例资料尚未载入；不能据此判定没有开放 PD / Query。" : "当前未识别到开放 PD / Query 提示。"}</p>}
              </div>
              <div>
                <h3>时间线事件</h3>
                {pdQueryEvents.length ? pdQueryEvents.map((event, index) => (
                  <div className="profile-query-card" key={`profile-query:${timelineEventSelectionKey(event, `profile-query-${index}`)}:${index}`}>
                    <Tag tone={event.event_type === "query" ? "info" : "warning"}>{event.source_domain}</Tag>
                    <div>
                      <strong>{event.visit_code || `D${event.study_day}`} · {event.title}</strong>
                      <span>{event.detail} · {sourceLocatorLabel(event)}</span>
                    </div>
                  </div>
                )) : <p className={profileUnavailable ? "profile-data-warning" : "quiet-text"} role={profileUnavailable ? "alert" : undefined}>{profileUnavailable ? "个例资料尚未载入；不能据此判定没有 PD / Query 时间线事件。" : "当前受试者暂无 PD / Query 时间线事件。"}</p>}
              </div>
            </div>
          </ProfilePanel>

          <section className="profile-two-col">
            <ProfilePanel title="风险提示" eyebrow="Risk">
              <div className="risk-list profile-risk-prompts">
                {promptDisplayRows.length ? promptDisplayRows.map((prompt, index) => (
                  <p key={riskPromptDisplayKey(prompt, index)}>
                    <AlertTriangle size={14} />
                    {prompt.displayIdentityState !== "ready" && (
                      <Tag tone="warning">{prompt.displayIdentityState === "duplicate" ? "身份重复" : "身份待核对"}</Tag>
                    )}
                    <span title={prompt.displayIdentityIssue || riskPromptEvidenceSummary(prompt).message}><strong>{prompt.visit_code}</strong> {prompt.title}：{prompt.prompt_text || prompt.recommended_action} · {sourceLocatorLabel(prompt)} · {riskEvidenceLabel(prompt)}</span>
                  </p>
                )) : subject.risks?.length ? subject.risks.map((risk) => <p key={risk}><AlertTriangle size={14} /> {risk}</p>) : (
                  <p className={profileUnavailable ? "profile-data-warning" : "quiet-text"} role={profileUnavailable ? "alert" : undefined}>{profileUnavailable ? "个例资料尚未载入；不能据此判定暂无风险提示。" : "当前暂无风险提示。"}</p>
                )}
              </div>
              {subject.reviewFocus?.length > 0 && (
                <div className="profile-review-focus">
                  {subject.reviewFocus.map((item) => <p key={item}>{item}</p>)}
                </div>
              )}
            </ProfilePanel>
            <ProfilePanel title="关联事件索引" eyebrow="Source Events">
              <div className="profile-event-index">
                {nonVisitEvents.slice(0, 12).map((event, index) => (
                  <div key={`profile-index:${timelineEventSelectionKey(event, `profile-index-${index}`)}:${index}`}>
                    <Tag tone={event.related_risk_ids?.length ? "warning" : "info"}>{event.source_domain}</Tag>
                    <span>{event.visit_code || `D${event.study_day}`} · {event.title} · {sourceLocatorLabel(event)}</span>
                  </div>
                ))}
                {!nonVisitEvents.length && <p className={profileUnavailable ? "profile-data-warning" : "quiet-text"} role={profileUnavailable ? "alert" : undefined}>{profileUnavailable ? "个例资料尚未载入；不能据此判定没有可索引事件。" : "当前暂无可索引事件。"}</p>}
              </div>
            </ProfilePanel>
          </section>
        </section>
      </div>
    </main>
  );
}
