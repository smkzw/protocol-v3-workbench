// 第10轮末修订（P1-51）：批量冻结批结果的人话汇总。
// 现场（r10-A 卡67）：后端 skipped+reason 已返回但前端无清单展示——
// 连点8次零反馈的根因是『跳过章行内不可见』，不是要强冻占位章。
export function buildBatchFreezeSummary(payload = {}) {
  const frozen = (payload.frozen_section_ids || []).length;
  const skipped = payload.skipped || [];
  const failures = payload.failures || [];
  const skippedItems = skipped
    .filter((item) => item && item.section_id)
    .map((item) => ({
      label: `${item.section_number || ""} ${item.section_heading || item.section_id}`.trim(),
      reason: item.message || item.reason_code || "原因未返回，请刷新后重试",
    }));
  const segments = [`已冻结 ${frozen} 个章节`];
  if (skippedItems.length) segments.push(`跳过 ${skippedItems.length} 个章节（原因见清单）`);
  if (failures.length) segments.push(`失败 ${failures.length} 个章节（版本冲突，请刷新后重试该章）`);
  let line = segments.join("；") + "。";
  const allFrozenNote = skipped.find(
    (item) => item && !item.section_id && item.reason_code === "already_frozen",
  );
  if (allFrozenNote && !skippedItems.length && !failures.length) {
    line = `已冻结 ${frozen} 个章节。（此前批次已全部冻结，无需重复操作。）`;
  }
  return {
    line,
    skippedItems,
    failures,
    failuresCount: failures.length,
    frozenCount: frozen,
  };
}
