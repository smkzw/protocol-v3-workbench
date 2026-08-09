const CAPABILITY_LABELS = Object.freeze({
  raw_source_review: "原始数据复核",
  subject_timeline: "受试者时间线",
  patient_profile: "Patient Profile",
  ae_mh_reconciliation: "AE/MH 漏报核查",
  standard_coding_rules: "标准编码规则",
  precise_temporal_rules: "精确时间规则",
  lab_ctcae_rules: "实验室异常与 CTCAE 分级",
  protocol_medication_rules: "方案用药规则",
  ip_exposure_adherence: "试验药物暴露与依从性",
  scale_recalculation: "量表复算",
});

function uniqueVisible(values, limit = 3) {
  return [...new Set(values.filter(Boolean))].slice(0, limit);
}

function semanticQualityShapeError(report) {
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    return "语义质量报告不是对象";
  }
  for (const key of [
    "global_blocker_count",
    "capability_blocker_count",
    "warning_count",
  ]) {
    if (report[key] === undefined) continue;
    if (
      typeof report[key] !== "number"
      || !Number.isInteger(report[key])
      || report[key] < 0
    ) {
      return `${key} 不是非负整数`;
    }
  }
  for (const key of ["finding_groups", "capability_states"]) {
    if (report[key] === undefined) continue;
    if (!Array.isArray(report[key])) return `${key} 不是数组`;
  }
  for (const key of ["status", "activation_disposition"]) {
    if (report[key] !== undefined && typeof report[key] !== "string") {
      return `${key} 不是字符串`;
    }
  }
  if (Array.isArray(report.finding_groups)) {
    for (const item of report.finding_groups) {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return "finding_groups 含有非对象项";
      }
      if (
        item.affected_capability_ids !== undefined
        && item.affected_capability_ids !== null
        && !Array.isArray(item.affected_capability_ids)
      ) {
        return "affected_capability_ids 不是数组";
      }
    }
  }
  if (Array.isArray(report.capability_states)) {
    for (const item of report.capability_states) {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return "capability_states 含有非对象项";
      }
    }
  }
  return "";
}

function inferredDisposition(report) {
  const explicit = String(report?.activation_disposition || "");
  if (explicit) return explicit;
  if (
    report?.status === "blocked"
    || (report?.global_blocker_count || 0) > 0
  ) {
    return "reject";
  }
  if ((report?.capability_blocker_count || 0) > 0) {
    return "activate_restricted";
  }
  return "activate_full";
}

function affectedCapabilityLabels(report) {
  const stateCapabilityIds = (report?.capability_states || [])
    .filter((item) => (
      item && typeof item === "object"
      && (
      item?.state === "limited"
      || item?.state === "blocked_by_quality"
      || item?.state === "disabled_by_design"
      )
    ))
    .map((item) => item.capability_id);
  const findingCapabilityIds = (report?.finding_groups || [])
    .filter((item) => item && item.severity === "capability_blocker")
    .flatMap((item) => Array.isArray(item.affected_capability_ids)
      ? item.affected_capability_ids
      : []);
  return uniqueVisible(
    [...stateCapabilityIds, ...findingCapabilityIds]
      .map((capabilityId) => CAPABILITY_LABELS[capabilityId]),
  );
}

function findingTitles(report, severity) {
  return uniqueVisible(
    (report?.finding_groups || [])
      .filter((item) => !severity || item?.severity === severity)
      .map((item) => String(item?.title_zh || "").trim()),
  );
}

export function semanticQualityPresentation(report) {
  if (!report) {
    return {
      level: "unknown",
      title: "",
      detail: "",
      blocksConfirmation: false,
    };
  }

  const shapeError = semanticQualityShapeError(report);
  if (shapeError) {
    return {
      level: "blocked",
      title: "语义质量报告字段形状异常，当前不能确认",
      detail: shapeError,
      blocksConfirmation: true,
    };
  }

  const disposition = inferredDisposition(report);
  const status = String(report.status || "");

  if (status === "blocked" || disposition === "reject") {
    const blockerCount = report.global_blocker_count || 0;
    const details = findingTitles(report, "global_blocker");
    return {
      level: "blocked",
      title: blockerCount > 0
        ? `存在 ${blockerCount} 个全局阻断，当前不能确认`
        : "存在全局阻断，当前不能确认",
      detail: details.length ? details.join(" · ") : "请先修订阻断字段",
      blocksConfirmation: true,
    };
  }

  if (disposition === "activate_restricted") {
    const capabilities = affectedCapabilityLabels(report);
    const fallbackTopics = findingTitles(report, "capability_blocker");
    const visibleItems = capabilities.length ? capabilities : fallbackTopics;
    return {
      level: "restricted",
      title: "可启用，但以下分析将受限",
      detail: visibleItems.length
        ? visibleItems.join(" · ")
        : "部分依赖字段语义的分析暂不可用",
      blocksConfirmation: false,
    };
  }

  if (status === "pass_with_warnings") {
    const warningCount = report.warning_count || 0;
    const warnings = findingTitles(report, "review_warning");
    return {
      level: "warning",
      title: "字段映射可完整启用",
      detail: warnings.length
        ? `建议核对：${warnings.join(" · ")}`
        : (
          warningCount > 0
            ? `仍有 ${warningCount} 项建议核对，不影响分析能力`
            : "存在非阻断提示，不影响分析能力"
        ),
      blocksConfirmation: false,
    };
  }

  return {
    level: "ready",
    title: "字段语义校验完全通过",
    detail: "全部已登记分析能力可用",
    blocksConfirmation: false,
  };
}
