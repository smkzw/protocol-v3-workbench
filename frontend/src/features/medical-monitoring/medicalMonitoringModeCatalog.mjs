/**
 * Frozen user-facing vocabulary for the three medical-monitoring workflows.
 *
 * The catalog is a read-only presentation contract. It does not select a
 * workflow, create a task, mutate a baseline, or grant runtime authority.
 * Internal assurance IDs remain compatible with the existing API while the
 * commercial mode IDs stay explicit for release/acceptance evidence.
 */

export const MONITORING_MODE_IDS = Object.freeze([
  "daily_incremental",
  "pre_lock_total",
  "post_lock_fixed_total",
]);

const MODE_CATALOG = Object.freeze({
  daily_incremental: Object.freeze({
    id: "daily_incremental",
    label: "日常医学监查（增量）",
    shortLabel: "日常增量",
    surface: "daily_run",
    source: "最新全量 EDC listing",
    baseline: "上一已确认批次",
    completion: "本批次风险处置完成并确认为下一次比较基线",
  }),
  pre_lock_total: Object.freeze({
    id: "pre_lock_total",
    label: "锁库前医学监查（全量）",
    shortLabel: "锁库前全量",
    surface: "assurance",
    assuranceMode: "pre_lock",
    source: "冻结候选全量快照",
    baseline: "全量重算，不以日常增量结果简单累加",
    completion: "全量重算、三级对账和开放风险证据均满足完成门",
  }),
  post_lock_fixed_total: Object.freeze({
    id: "post_lock_fixed_total",
    label: "锁库后—CFDI核查前医学监查（固定总量）",
    shortLabel: "核查前固定总量",
    surface: "assurance",
    assuranceMode: "pre_inspection",
    source: "锁库后固定总量快照",
    baseline: "固定总量，不再追加日常批次",
    completion: "受试者、中心、项目三级汇总与整改证据均可核验",
  }),
});

export function monitoringModeDefinition(modeId) {
  return MODE_CATALOG[modeId] || null;
}

export function monitoringModeLabel(modeId) {
  return monitoringModeDefinition(modeId)?.label || "医学监查模式";
}

export function monitoringModeShortLabel(modeId) {
  return monitoringModeDefinition(modeId)?.shortLabel || "待识别模式";
}

export function monitoringModeFromAssuranceMode(assuranceMode) {
  return MONITORING_MODE_IDS.find(
    (modeId) => MODE_CATALOG[modeId].assuranceMode === assuranceMode,
  ) || "";
}

export function monitoringModeForDailyRun() {
  return MODE_CATALOG.daily_incremental;
}

