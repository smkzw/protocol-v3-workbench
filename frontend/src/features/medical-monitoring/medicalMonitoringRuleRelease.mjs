export const RULE_PACK_STATUS_LABELS = Object.freeze({
  draft: "规则包草稿",
  shadow: "影子检查中",
  confirmed: "影子样本已确认",
  published: "已发布",
  retired: "已停用",
});

export const RULE_STATUS_LABELS = Object.freeze({
  candidate: "待确认候选",
  confirmed: "医学已确认",
  enabled: "已启用",
  disabled: "已停用",
  superseded: "已被替代",
});

export const SHADOW_SAMPLE_BUCKET_LABELS = Object.freeze({
  positive: "命中样本",
  negative: "未命中样本",
  boundary: "边界样本",
  diagnostic: "不可判定样本",
});

const PROVISIONAL_INSPECTION_STATUS = "provisional";

export const RULE_RELEASE_STEPS = Object.freeze([
  Object.freeze({ key: "draft", label: "组建规则包" }),
  Object.freeze({ key: "shadow", label: "自动影子检查" }),
  Object.freeze({ key: "confirm", label: "确认影子样本" }),
  Object.freeze({ key: "publish", label: "发布规则包" }),
  Object.freeze({ key: "readiness", label: "日常监查就绪" }),
]);

function normalizedText(value) {
  return String(value || "").trim();
}

function requireText(value, message) {
  const text = normalizedText(value);
  if (!text) throw new TypeError(message);
  return text;
}

export function normalizedRulePack(pack) {
  if (!pack) return null;
  const rulePackId = normalizedText(pack.rule_pack_id);
  if (!rulePackId) return null;
  const packRevision = Number(pack.pack_revision);
  return {
    rulePackId,
    protocolVersionId: normalizedText(pack.protocol_version_id),
    packRevision: Number.isInteger(packRevision) && packRevision >= 1
      ? packRevision
      : null,
    status: normalizedText(pack.status) || "draft",
    statusLabel: RULE_PACK_STATUS_LABELS[normalizedText(pack.status)] || "状态待核对",
    ruleCount: Array.isArray(pack.rule_revision_ids)
      ? pack.rule_revision_ids.length
      : 0,
    publishedAt: normalizedText(pack.published_at),
  };
}

export function sortedRulePacks(items) {
  const normalized = (Array.isArray(items) ? items : [])
    .map((item, index) => {
      const pack = normalizedRulePack(item);
      return pack ? { ...pack, displaySourceIndex: index } : null;
    })
    .filter(Boolean);
  const idCounts = new Map();
  normalized.forEach((pack) => {
    idCounts.set(pack.rulePackId, (idCounts.get(pack.rulePackId) || 0) + 1);
  });
  return normalized
    .map((pack) => ({
      ...pack,
      displayIdentityState: idCounts.get(pack.rulePackId) > 1 ? "duplicate" : "ready",
      displayIdentityIssue: idCounts.get(pack.rulePackId) > 1
        ? "规则包 rule_pack_id 重复；保留版本但暂不能选择。"
        : null,
    }))
    .sort((left, right) => (
      (right.packRevision || 0) - (left.packRevision || 0)
      || left.displaySourceIndex - right.displaySourceIndex
    ));
}

export function latestRulePack(items) {
  return sortedRulePacks(items).find((pack) => pack.displayIdentityState === "ready") || null;
}

export function latestPublishedRulePack(items) {
  return sortedRulePacks(items).find((pack) => (
    pack.status === "published" && pack.displayIdentityState === "ready"
  )) || null;
}

export function rulePackDisplayKey(pack, index = 0) {
  const identity = normalizedText(pack?.rulePackId || pack?.rule_pack_id) || "missing";
  const sourceIndex = Number.isInteger(pack?.displaySourceIndex)
    ? pack.displaySourceIndex
    : index;
  return `rule-pack:${identity}:${sourceIndex}`;
}

export function normalizedRule(rule) {
  if (!rule) return null;
  const ruleKey = normalizedText(rule.rule_key);
  if (!ruleKey) return null;
  const status = normalizedText(rule.status);
  return {
    ruleRevisionId: normalizedText(rule.rule_revision_id),
    ruleKey,
    title: normalizedText(rule.title) || ruleKey,
    status,
    statusLabel: RULE_STATUS_LABELS[status] || "状态待核对",
    severity: normalizedText(rule.severity),
    requiredDomains: (Array.isArray(rule.required_domains) ? rule.required_domains : [])
      .map((domain) => normalizedText(domain))
      .filter(Boolean),
    sourceLocator: normalizedText(rule.source_locator),
    stateVersion: Number(rule.state_version) || null,
  };
}

export function rulePackRules(payload) {
  return (Array.isArray(payload?.rules) ? payload.rules : [])
    .map(normalizedRule)
    .filter(Boolean);
}

export function isProvisionalInspection(payload) {
  return normalizedText(payload?.status) === PROVISIONAL_INSPECTION_STATUS;
}

export function provisionalSampleView(sample) {
  if (!sample) return null;
  const sampleId = normalizedText(sample.sample_id);
  if (!sampleId) return null;
  const state = normalizedText(sample.actual_evaluation_state).toLowerCase();
  const outcome = state === "true"
    ? { label: "实际命中", tone: "hit" }
    : state === "false"
      ? { label: "实际未命中", tone: "miss" }
      : { label: "不可判定", tone: "indeterminate" };
  const bucket = normalizedText(sample.bucket);
  return {
    sampleId,
    displaySourceIndex: Number.isInteger(sample.displaySourceIndex) ? sample.displaySourceIndex : null,
    displayIdentityState: sample.displayIdentityState || "ready",
    displayIdentityIssue: sample.displayIdentityIssue || null,
    ruleKey: normalizedText(sample.rule_key),
    bucket,
    bucketLabel: SHADOW_SAMPLE_BUCKET_LABELS[bucket] || "样本",
    caseLabel: normalizedText(sample.case_label),
    businessKey: normalizedText(sample.business_key),
    outcomeLabel: outcome.label,
    outcomeTone: outcome.tone,
    diagnosticCode: normalizedText(sample.actual_diagnostic_code),
    evidenceSummary: normalizedText(sample.evidence_summary),
  };
}

export function provisionalInspectionViewModel(payload) {
  if (!isProvisionalInspection(payload)) return null;
  const sampleSetId = normalizedText(payload.sample_set_id);
  if (!sampleSetId) return null;
  const samples = (Array.isArray(payload.samples) ? payload.samples : [])
    .map(provisionalSampleView)
    .filter(Boolean);
  return {
    sampleSetId,
    status: PROVISIONAL_INSPECTION_STATUS,
    statusLabel: "自动影子样本待医学确认",
    batchId: normalizedText(payload.batch_id),
    sampleCount: samples.length,
    samples,
  };
}

function normalizedLineageConfirmation(payload) {
  if (!payload) return null;
  const confirmationId = normalizedText(payload.confirmation_id);
  const sampleSetId = normalizedText(payload.sample_set_id);
  if (!confirmationId && !sampleSetId) return null;
  return {
    confirmationId,
    sampleSetId,
    trustedShadowRunId: normalizedText(payload.trusted_shadow_run_id),
    confirmedAt: normalizedText(payload.confirmed_at),
  };
}

function lineageSampleSetView(item, confirmed) {
  if (!item) return null;
  const sampleSetId = normalizedText(item.sample_set_id);
  if (!sampleSetId) return null;
  const samples = (Array.isArray(item.samples) ? item.samples : [])
    .map(provisionalSampleView)
    .filter(Boolean)
    .map((sample) => ({ ...sample, confirmed }));
  return {
    sampleSetId,
    status: normalizedText(item.status) || PROVISIONAL_INSPECTION_STATUS,
    statusLabel: confirmed ? "医学已确认" : "自动影子样本待医学确认",
    batchId: normalizedText(item.batch_id),
    sampleCount: samples.length,
    samples,
    confirmed,
  };
}

export function shadowLineageEvidenceViewModel(payload) {
  if (!payload || typeof payload !== "object") return null;
  const shadowRulePackId = normalizedText(payload.shadow_rule_pack_id);
  const items = Array.isArray(payload.items) ? payload.items : [];
  const confirmation = normalizedLineageConfirmation(payload.confirmation);
  // The confirmed sample set is authoritative; without a confirmation the
  // latest provisional set (items arrive in ascending time order) is shown.
  let item = null;
  if (confirmation?.sampleSetId) {
    item = items.find(
      (entry) => normalizedText(entry?.sample_set_id) === confirmation.sampleSetId,
    ) || null;
  }
  if (!item && items.length) item = items[items.length - 1];
  const sampleSet = lineageSampleSetView(item, Boolean(confirmation));
  return { shadowRulePackId, sampleSet, confirmation };
}

export function confirmedShadowRunView(run) {
  if (!run) return null;
  const shadowRunId = normalizedText(run.shadow_run_id);
  if (!shadowRunId) return null;
  const caseCount = Number(run.case_count) || 0;
  const passedCount = Number(run.passed_count) || 0;
  const diagnosticCaseCount = Number(run.diagnostic_case_count) || 0;
  const diagnosticPassedCount = Number(run.diagnostic_passed_count) || 0;
  const total = caseCount + diagnosticCaseCount;
  const passed = passedCount + diagnosticPassedCount;
  return {
    shadowRunId,
    total,
    passed,
    allPassed: total > 0 && passed === total,
    label: total > 0
      ? `已确认样本 ${passed}/${total} 条符合医学确认结果`
      : "已确认影子样本",
  };
}

export function rulePackDiffView(impact) {
  if (!impact) return null;
  const keys = (value) => (Array.isArray(value) ? value : [])
    .map((item) => normalizedText(item))
    .filter(Boolean);
  const added = keys(impact.added_rule_keys);
  const changed = keys(impact.changed_rule_keys);
  const superseded = keys(impact.superseded_rule_keys);
  if (!added.length && !changed.length && !superseded.length) return null;
  const parts = [];
  if (added.length) parts.push(`新增 ${added.length} 条`);
  if (changed.length) parts.push(`变更 ${changed.length} 条`);
  if (superseded.length) parts.push(`停用 ${superseded.length} 条`);
  return {
    added,
    changed,
    superseded,
    summary: `相较当前已发布规则包：${parts.join(" · ")}`,
  };
}

export function ruleReleaseChainSteps({ pack, inspection, readiness } = {}) {
  const status = pack?.status || "";
  const hasPack = Boolean(pack);
  const provisionalShown = Boolean(inspection);
  const confirmed = ["confirmed", "published", "retired"].includes(status);
  const published = ["published", "retired"].includes(status);
  const ready = readiness?.ready === true;
  const states = [
    hasPack ? "done" : "current",
    !hasPack ? "locked" : (provisionalShown || confirmed) ? "done" : "current",
    confirmed ? "done" : provisionalShown ? "current" : "locked",
    published ? "done" : confirmed ? "current" : "locked",
    published ? (ready ? "done" : "current") : "locked",
  ];
  return RULE_RELEASE_STEPS.map((step, index) => ({
    ...step,
    state: states[index],
  }));
}

export function ruleReleaseNextAction({ pack, inspection, readiness } = {}) {
  if (!pack) {
    return { key: "draft", label: "组建规则包草稿" };
  }
  if (pack.status === "draft" || (pack.status === "shadow" && !inspection)) {
    return { key: "shadow", label: "运行自动影子检查" };
  }
  if (pack.status === "shadow" && inspection) {
    return { key: "confirm", label: "确认影子样本结果" };
  }
  if (pack.status === "confirmed") {
    return { key: "publish", label: "发布规则包" };
  }
  if (pack.status === "published") {
    return readiness?.ready === true
      ? { key: "readiness", label: "日常监查已就绪" }
      : { key: "readiness", label: "查看日常监查就绪状态" };
  }
  return { key: "draft", label: "组建规则包草稿" };
}

export function buildRulePackDraftPayload({ protocolVersionId, factRevisionIds } = {}) {
  const ids = [...new Set(
    (Array.isArray(factRevisionIds) ? factRevisionIds : [])
      .map((item) => normalizedText(item))
      .filter(Boolean),
  )];
  if (!ids.length) {
    throw new TypeError("至少需要一条已确认方案事实才能组建规则包草稿。");
  }
  return {
    protocol_version_id: requireText(protocolVersionId, "方案版本不可用，请刷新后重试。"),
    fact_revision_ids: ids,
    created_by: "medical_manager",
  };
}

export function buildAutomaticShadowRunPayload({ batchId, expectedPackRevision } = {}) {
  const payload = {
    batch_id: requireText(batchId, "请选择一个已冻结批次。"),
  };
  const revision = Number(expectedPackRevision);
  if (Number.isInteger(revision) && revision >= 1) {
    payload.expected_pack_revision = revision;
  }
  return payload;
}

export function buildShadowConfirmationPayload({ sampleSetId, expectedPackRevision } = {}) {
  const payload = {
    sample_set_id: requireText(
      sampleSetId,
      "影子样本集不可用，请重新运行自动影子检查。",
    ),
    confirmed_by: "medical_manager",
  };
  const revision = Number(expectedPackRevision);
  if (Number.isInteger(revision) && revision >= 1) {
    payload.expected_pack_revision = revision;
  }
  return payload;
}

export function buildRulePackPublishPayload({ expectedPackRevision } = {}) {
  const payload = {};
  const revision = Number(expectedPackRevision);
  if (Number.isInteger(revision) && revision >= 1) {
    payload.expected_pack_revision = revision;
  }
  return payload;
}

export function frozenShadowBatches(items) {
  const frozenItems = (Array.isArray(items) ? items : [])
    .filter((batch) => normalizedText(batch?.state) === "frozen");
  const identityCounts = new Map();
  frozenItems.forEach((batch) => {
    const identity = normalizedText(batch?.batch_id);
    if (identity) identityCounts.set(identity, (identityCounts.get(identity) || 0) + 1);
  });
  return frozenItems
    .map((batch, index) => {
      const batchId = normalizedText(batch.batch_id);
      const sourceIndex = Number.isInteger(batch.displaySourceIndex)
        ? batch.displaySourceIndex
        : index;
      const duplicate = batch.displayIdentityState === "duplicate"
        || (identityCounts.get(batchId) || 0) > 1;
      return {
        batchId,
        createdAt: normalizedText(batch.created_at),
        rowCount: Number(batch.row_count) || null,
        displaySourceIndex: sourceIndex,
        displayIdentityState: duplicate ? "duplicate" : "ready",
        displayIdentityIssue: duplicate
          ? "冻结批次 batch_id 重复；保留批次但暂不能选择"
          : "",
        displayKey: typeof batch.displayKey === "string" && batch.displayKey.trim()
          ? batch.displayKey
          : `batch:${batchId || "missing"}:${sourceIndex}`,
      };
    })
    .filter((batch) => batch.batchId);
}

export function shadowBatchOptionLabel(batch) {
  if (!batch) return "";
  const date = batch.createdAt
    ? new Date(batch.createdAt).toLocaleString("zh-CN")
    : "冻结批次";
  return batch.rowCount
    ? `${date} · ${batch.rowCount.toLocaleString("zh-CN")} 条记录`
    : date;
}

export function ruleReleaseErrorText(error, fallback = "规则发布操作失败，请重试。") {
  const detail = error?.detail?.detail;
  if (detail && typeof detail === "object" && normalizedText(detail.message)) {
    return normalizedText(detail.message);
  }
  return normalizedText(error?.message) || fallback;
}

export const SHADOW_CONFIRMATION_NOTE = "请逐条核对上方样本的实际判定与来源依据。"
  + "确认表示您认可这些冻结样本的判定结果；规则本身已在采用时完成医学决定，此处不是再次批准规则。";

export const PROVISIONAL_INSPECTION_NOTE = "以下为服务器从所选冻结批次抽取的真实样本及其实际判定，"
  + "仅供医学核对，尚需您显式确认后才可作为发布依据。";
