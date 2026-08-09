function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function isSha256(value) {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

function isNonNegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

const DETAIL_SAMPLE_LIMIT = 8;

function issue(field, kind, message) {
  return { field, kind, message };
}

function readText(record, field, issues) {
  const value = record[field];
  if (value === undefined || value === null) {
    issues.push(issue(field, "missing", "字段未提供。"));
    return null;
  }
  if (!isNonEmptyString(value)) {
    issues.push(issue(field, "invalid", "字段不是非空文本。"));
    return null;
  }
  return value.trim();
}

function readSha256(record, field, issues) {
  const value = record[field];
  if (value === undefined || value === null || value === "") {
    issues.push(issue(field, "missing", "输出摘要未提供。"));
    return null;
  }
  if (!isSha256(value)) {
    issues.push(issue(field, "invalid", "输出摘要不是小写 SHA-256。"));
    return null;
  }
  return value;
}

function readList(record, field, issues) {
  const value = record[field];
  if (value === undefined || value === null) {
    issues.push(issue(field, "missing", "数组未提供。"));
    return null;
  }
  if (!Array.isArray(value) || value.some((item) => !isNonEmptyString(item))) {
    issues.push(issue(field, "invalid", "数组或数组成员形状异常。"));
    return null;
  }
  return value;
}

function readRecordList(record, field, issues) {
  const value = record[field];
  if (value === undefined || value === null) {
    issues.push(issue(field, "missing", "数组未提供。"));
    return null;
  }
  if (!Array.isArray(value) || value.some((item) => !isRecord(item))) {
    issues.push(issue(field, "invalid", "记录数组形状异常。"));
    return null;
  }
  return value;
}

function detailText(record, field) {
  const value = record?.[field];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function summarizeFieldChanges(records, issues) {
  if (!Array.isArray(records)) return [];
  return records.slice(0, DETAIL_SAMPLE_LIMIT).map((record, index) => {
    const domain = detailText(record, "domain");
    const businessKey = detailText(record, "business_key");
    const fieldName = detailText(record, "field_name");
    const changeKind = detailText(record, "change_kind");
    if (!domain || !businessKey || !fieldName || !changeKind) {
      issues.push(issue(
        `field_changes[${index}]`,
        "invalid",
        "字段变更明细缺少域、业务键、字段名或变更类型；该明细保持待核对。",
      ));
      return null;
    }
    return {
      domain,
      businessKey,
      fieldName,
      changeKind,
      previousLocator: detailText(record, "previous_locator"),
      currentLocator: detailText(record, "current_locator"),
    };
  }).filter(Boolean);
}

function summarizeSchemaDiffs(records, issues) {
  if (!Array.isArray(records)) return [];
  return records.slice(0, DETAIL_SAMPLE_LIMIT).map((record, index) => {
    const domain = detailText(record, "domain");
    const addedFields = Array.isArray(record?.added_fields)
      && record.added_fields.every(isNonEmptyString)
      ? record.added_fields.map((field) => field.trim())
      : null;
    const removedFields = Array.isArray(record?.removed_fields)
      && record.removed_fields.every(isNonEmptyString)
      ? record.removed_fields.map((field) => field.trim())
      : null;
    if (!domain || addedFields === null || removedFields === null) {
      issues.push(issue(
        `schema_diffs[${index}]`,
        "invalid",
        "结构变更明细缺少域或新旧字段列表；该明细保持待核对。",
      ));
      return null;
    }
    return { domain, addedFields, removedFields };
  }).filter(Boolean);
}

function summarizeIdentitySamples(records, issues) {
  if (!Array.isArray(records)) return [];
  return records.slice(0, DETAIL_SAMPLE_LIMIT).map((record, index) => {
    const previousBusinessKey = detailText(record, "previous_business_key");
    const currentBusinessKey = detailText(record, "current_business_key");
    const matchBasis = detailText(record, "match_basis");
    if (!previousBusinessKey || !currentBusinessKey || !matchBasis) {
      issues.push(issue(
        `identity_match_samples[${index}]`,
        "invalid",
        "身份匹配样本缺少前后业务键或匹配依据；该样本保持待核对。",
      ));
      return null;
    }
    return { previousBusinessKey, currentBusinessKey, matchBasis };
  }).filter(Boolean);
}

function readCountMap(record, field, issues) {
  const value = record[field];
  if (value === undefined || value === null) {
    issues.push(issue(field, "missing", "计数映射未提供。"));
    return null;
  }
  if (!isRecord(value)) {
    issues.push(issue(field, "invalid", "计数映射形状异常。"));
    return null;
  }
  const entries = Object.entries(value);
  if (entries.some(([key, count]) => !isNonEmptyString(key) || !isNonNegativeInteger(count))) {
    issues.push(issue(field, "invalid", "计数映射包含非严格非负整数。"));
    return null;
  }
  const normalizedEntries = entries.map(([key, count]) => [key.trim(), count]);
  if (new Set(normalizedEntries.map(([key]) => key)).size !== normalizedEntries.length) {
    issues.push(issue(field, "invalid", "计数映射包含重复键。"));
    return null;
  }
  return Object.fromEntries(normalizedEntries);
}

function countOrNull(list) {
  return Array.isArray(list) ? list.length : null;
}

function summarizeIssues(issues) {
  return issues.map(({ field, kind, message }) => ({ field, kind, message }));
}

function deriveSafetyReasons({ rowLists, schemaDiffs, removalBlockedKeys, fullSnapshotProven }) {
  const reasons = [];
  if (Array.isArray(schemaDiffs) && schemaDiffs.length > 0) {
    reasons.push({
      code: "schema_drift",
      label: "listing 结构发生变化",
      action: "先复核字段映射与新旧列含义，再继续规则或 AI。",
    });
  }
  if (Array.isArray(rowLists.missing_current_domains) && rowLists.missing_current_domains.length > 0) {
    reasons.push({
      code: "missing_expected_domain",
      label: "预期数据域缺失",
      action: "先核对本批来源是否完整，不能把缺失域当作无风险。",
    });
  }
  if (Array.isArray(removalBlockedKeys) && removalBlockedKeys.length > 0) {
    reasons.push({
      code: "removal_resolution_blocked",
      label: "移除记录身份无法唯一解析",
      action: "先回到来源行核对删除/变更身份，不得直接视为已解决。",
    });
  }
  if (fullSnapshotProven === false) {
    reasons.push({
      code: "full_snapshot_unproven",
      label: "全量快照未被证明",
      action: "先确认本批是完整 listing；未证明前不应解释移除记录。",
    });
  } else if (fullSnapshotProven !== true) {
    reasons.push({
      code: "full_snapshot_unverified",
      label: "全量快照证明待核对",
      action: "先补齐全量快照证据，再判断本批是否可继续。",
    });
  }
  return reasons;
}

export function normalizeMedicalMonitoringDailyDiff(diff) {
  if (diff === null || diff === undefined) {
    return { status: "empty", value: null, issues: [] };
  }
  if (!isRecord(diff) || !isRecord(diff.payload)) {
    return {
      status: "malformed",
      value: null,
      issues: [issue("diff", "invalid", "差异快照或 payload 形状异常。")],
    };
  }

  const issues = [];
  const payload = diff.payload;
  const rowDiff = payload.row_diff;
  if (!isRecord(rowDiff)) {
    return {
      status: "malformed",
      value: null,
      issues: [issue("payload.row_diff", "invalid", "行级差异证据缺失或形状异常。")],
    };
  }

  const listFields = [
    "new_keys",
    "changed_keys",
    "persisting_keys",
    "removed_keys",
    "requires_rereview_keys",
    "missing_current_domains",
    "removal_resolution_blocked_keys",
  ];
  const rowLists = Object.fromEntries(
    listFields.map((field) => [field, readList(rowDiff, field, issues)]),
  );
  const fieldChanges = readRecordList(payload, "field_changes", issues);
  const schemaDiffs = readRecordList(payload, "schema_diffs", issues);
  const identityMatchSamples = payload.identity_match_samples === undefined
    ? []
    : readRecordList(payload, "identity_match_samples", issues);
  const identityMatchCounts = readCountMap(payload, "identity_match_counts", issues);
  const removalEligibleKeys = readList(payload, "removal_eligible_keys", issues);
  const removalBlockedKeys = readList(payload, "removal_blocked_keys", issues);
  const fullSnapshotProven = payload.full_snapshot_proven;
  if (fullSnapshotProven === undefined || fullSnapshotProven === null) {
    issues.push(issue("full_snapshot_proven", "missing", "完整快照证据字段未提供。"));
  } else if (typeof fullSnapshotProven !== "boolean") {
    issues.push(issue("full_snapshot_proven", "invalid", "完整快照证据字段不是严格布尔值。"));
  }

  const outputSha256 = readSha256(diff, "output_sha256", issues);
  const payloadOutputSha256 = readSha256(payload, "output_sha256", issues);
  if (outputSha256 && payloadOutputSha256 && outputSha256 !== payloadOutputSha256) {
    issues.push(issue("output_sha256", "invalid", "快照摘要与 payload 摘要不一致。"));
  }

  const snapshotId = readText(diff, "snapshot_id", issues);
  const previousBatchId = readText(diff, "previous_batch_id", issues);
  const currentBatchId = readText(diff, "current_batch_id", issues);
  const algorithmVersion = readText(diff, "algorithm_version", issues);
  const createdAt = readText(diff, "created_at", issues);

  const counts = {
    newRows: countOrNull(rowLists.new_keys),
    changedRows: countOrNull(rowLists.changed_keys),
    persistingRows: countOrNull(rowLists.persisting_keys),
    removedRows: countOrNull(rowLists.removed_keys),
    rereviewRows: countOrNull(rowLists.requires_rereview_keys),
    missingDomains: countOrNull(rowLists.missing_current_domains),
    removalResolutionBlockedRows: countOrNull(rowLists.removal_resolution_blocked_keys),
    fieldChanges: countOrNull(fieldChanges),
    schemaChanges: countOrNull(schemaDiffs),
    removalEligibleRows: countOrNull(removalEligibleKeys),
    removalBlockedRows: countOrNull(removalBlockedKeys),
  };
  const identityMatchTotal = identityMatchCounts
    ? Object.values(identityMatchCounts).reduce((sum, count) => sum + count, 0)
    : null;
  const safetyReasons = deriveSafetyReasons({
    rowLists,
    schemaDiffs,
    removalBlockedKeys,
    fullSnapshotProven,
  });
  const details = {
    fieldChanges: summarizeFieldChanges(fieldChanges, issues),
    schemaDiffs: summarizeSchemaDiffs(schemaDiffs, issues),
    identityMatchSamples: summarizeIdentitySamples(identityMatchSamples, issues),
    newKeys: Array.isArray(rowLists.new_keys) ? rowLists.new_keys.slice(0, DETAIL_SAMPLE_LIMIT) : [],
    changedKeys: Array.isArray(rowLists.changed_keys) ? rowLists.changed_keys.slice(0, DETAIL_SAMPLE_LIMIT) : [],
    rereviewKeys: Array.isArray(rowLists.requires_rereview_keys)
      ? rowLists.requires_rereview_keys.slice(0, DETAIL_SAMPLE_LIMIT)
      : [],
    removedKeys: Array.isArray(rowLists.removed_keys) ? rowLists.removed_keys.slice(0, DETAIL_SAMPLE_LIMIT) : [],
    removalBlockedKeys: Array.isArray(removalBlockedKeys)
      ? removalBlockedKeys.slice(0, DETAIL_SAMPLE_LIMIT)
      : [],
    missingDomains: Array.isArray(rowLists.missing_current_domains)
      ? rowLists.missing_current_domains.slice(0, DETAIL_SAMPLE_LIMIT)
      : [],
    truncated: [
      fieldChanges,
      schemaDiffs,
      identityMatchSamples,
      rowLists.new_keys,
      rowLists.changed_keys,
      rowLists.requires_rereview_keys,
      rowLists.removed_keys,
      removalBlockedKeys,
      rowLists.missing_current_domains,
    ].some((items) => Array.isArray(items) && items.length > DETAIL_SAMPLE_LIMIT),
  };
  const hasInvalid = issues.some((item) => item.kind === "invalid");

  return {
    status: issues.length === 0 ? "ready" : "partial",
    value: {
      snapshotId,
      previousBatchId,
      currentBatchId,
      algorithmVersion,
      outputSha256,
      createdAt,
      counts,
      identityMatchTotal,
      fullSnapshotProven: typeof fullSnapshotProven === "boolean" ? fullSnapshotProven : null,
      safetyReasons,
      hasInvalid,
      details,
    },
    issues: summarizeIssues(issues),
  };
}

export function dailyDiffCountLabel(value) {
  return isNonNegativeInteger(value) ? String(value) : "待核对";
}
