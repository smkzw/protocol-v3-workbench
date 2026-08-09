const ACTIVE_IMPLEMENTATION_STATUS = "real_source_slice";
const SOURCE_ONLY_IMPLEMENTATION_STATUS = "source_manifest_only";
const LEGACY_OR_DEMO_IMPLEMENTATION_STATUSES = new Set([
  "demo_available",
  "legacy_available",
]);

export function monitoringSourceReadiness(binding) {
  const implementationStatus = String(binding?.implementation_status || "").trim();
  if (
    implementationStatus === ACTIVE_IMPLEMENTATION_STATUS
    || LEGACY_OR_DEMO_IMPLEMENTATION_STATUSES.has(implementationStatus)
  ) {
    return {
      kind: "active",
      implementationStatus,
      canRead: true,
      canStart: true,
      label: "来源已确认",
      message: "当前项目已具备医学监查来源绑定。",
    };
  }
  if (implementationStatus === SOURCE_ONLY_IMPLEMENTATION_STATUS) {
    return {
      kind: "source_only",
      implementationStatus,
      canRead: false,
      canStart: false,
      label: "仅来源登记",
      message: "研究方案与数据来源已登记，但尚未完成结构解析、医学监查适配器和独立AI确认；当前不开放运行或医学处置动作。",
    };
  }
  return {
    kind: "unconfirmed",
    implementationStatus,
    canRead: false,
    canStart: false,
    label: "来源状态待确认",
    message: "当前医学监查来源状态尚未确认；为保护数据与医学判断，不开放读取、运行或处置动作。",
  };
}

export const monitoringSourceImplementationStatuses = Object.freeze({
  ACTIVE: ACTIVE_IMPLEMENTATION_STATUS,
  SOURCE_ONLY: SOURCE_ONLY_IMPLEMENTATION_STATUS,
});
