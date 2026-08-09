const REMEDIATION = Object.freeze({
  confirm_mapping: Object.freeze({
    key: "mapping",
    label: "校对字段映射",
  }),
  prepare_rule_pack: Object.freeze({
    key: "rule_pack",
    label: "准备医学规则",
  }),
});

export function canStartMonitoringDailyRun(readiness) {
  return readiness?.ready === true
    && readiness?.next_action === "start_daily_run";
}

export function monitoringDailyRunRemediation(readiness) {
  if (!readiness || canStartMonitoringDailyRun(readiness)) return null;
  return REMEDIATION[readiness.next_action] || null;
}
