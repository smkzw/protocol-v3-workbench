import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, CircleDashed, Clock3, EyeOff, SlidersHorizontal } from "lucide-react";

const STATUS_OPTIONS = [
  { value: "applicable|retain_full", label: "纳入方案", status: "applicable", renderAction: "retain_full" },
  { value: "not_applicable|omit", label: "不适用，隐藏章节", status: "not_applicable", renderAction: "omit" },
  { value: "not_applicable|retain_not_applicable", label: "不适用，保留“不适用”", status: "not_applicable", renderAction: "retain_not_applicable" },
  { value: "unknown|omit", label: "待确定，暂不呈现", status: "unknown", renderAction: "omit" },
  { value: "deferred|omit", label: "延后决定，暂不呈现", status: "deferred", renderAction: "omit" },
];

const STATUS_META = {
  applicable: { label: "已纳入", tone: "included", icon: CheckCircle2 },
  not_applicable: { label: "不适用", tone: "excluded", icon: EyeOff },
  unknown: { label: "待确定", tone: "unknown", icon: CircleDashed },
  deferred: { label: "延后", tone: "deferred", icon: Clock3 },
};

const ARTIFACT_LABELS = {
  synopsis: "方案摘要",
  body: "正文",
  statistics: "统计分析",
  schedule: "研究流程表",
  evidence: "证据候选",
  ai_candidates: "AI候选",
};

const defaultRationale = (status) => ({
  applicable: "医学经理确认本研究包含该设计模块。",
  not_applicable: "医学经理确认本研究不包含该设计模块。",
  unknown: "当前信息不足，待补充研究设计事实后再确定。",
  deferred: "该设计决定延后至后续方案讨论时确定。",
}[status]);

export function ProtocolModuleResolutionPanel({
  resolutions = [],
  templateNodes = [],
  busyId = "",
  baselineReady = false,
  message = "",
  lastResult = null,
  onApply,
}) {
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState(null);
  const nodeBySemantic = useMemo(
    () => new Map(templateNodes.map((node) => [node.semantic_node_id, node])),
    [templateNodes],
  );
  const conditionalResolutions = useMemo(
    () => resolutions
      .filter((item) => {
        const node = nodeBySemantic.get(item.semantic_node_id);
        return node && node.applicability_mode !== "required";
      })
      .map((item) => ({ ...item, node: nodeBySemantic.get(item.semantic_node_id) }))
      .sort((left, right) => (
        (left.node?.section_number || "").localeCompare(
          right.node?.section_number || "",
          "zh-CN",
          { numeric: true },
        )
      )),
    [resolutions, nodeBySemantic],
  );
  const visible = statusFilter === "all"
    ? conditionalResolutions
    : conditionalResolutions.filter((item) => item.status === statusFilter);
  const selected = conditionalResolutions.find((item) => item.semantic_node_id === selectedId)
    || visible[0]
    || conditionalResolutions[0]
    || null;

  useEffect(() => {
    if (!selected) {
      setSelectedId("");
      setDraft(null);
      return;
    }
    if (selected.semantic_node_id !== selectedId) setSelectedId(selected.semantic_node_id);
    setDraft({
      status: selected.status,
      renderAction: selected.render_action,
      rationale: selected.rationale,
      sourceRefs: selected.source_fact_ids?.length
        ? selected.source_fact_ids
        : [`medical_manager:module:${selected.semantic_node_id}`],
    });
  }, [
    selected?.semantic_node_id,
    selected?.status,
    selected?.render_action,
    selected?.rationale,
    JSON.stringify(selected?.source_fact_ids || []),
  ]);

  const counts = conditionalResolutions.reduce(
    (result, item) => ({ ...result, [item.status]: (result[item.status] || 0) + 1 }),
    {},
  );
  const selectedOption = draft ? `${draft.status}|${draft.renderAction}` : "";
  const canApply = Boolean(
    selected
    && draft
    && baselineReady
    && draft.rationale.trim().length >= 5
    && busyId !== selected.semantic_node_id
    && (
      draft.status !== selected.status
      || draft.renderAction !== selected.render_action
      || draft.rationale.trim() !== selected.rationale
    ),
  );

  return (
    <section className="protocol-module-resolution-panel" aria-label="动态章节设计">
      <header>
        <div>
          <span><SlidersHorizontal size={14} /> 动态章节</span>
          <strong>按研究设计决定方案内容</strong>
          <small>选择即按医学经理决策应用；不再增加同角色的二次批准。</small>
        </div>
        <label>
          <span>显示</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">全部 {conditionalResolutions.length}</option>
            <option value="applicable">已纳入 {counts.applicable || 0}</option>
            <option value="not_applicable">不适用 {counts.not_applicable || 0}</option>
            <option value="unknown">待确定 {counts.unknown || 0}</option>
            <option value="deferred">延后 {counts.deferred || 0}</option>
          </select>
        </label>
      </header>
      <div className="protocol-module-resolution-workspace">
        <div className="protocol-module-resolution-list" role="list">
          {visible.map((item) => {
            const meta = STATUS_META[item.status] || STATUS_META.unknown;
            const Icon = meta.icon;
            return (
              <button
                type="button"
                role="listitem"
                key={item.semantic_node_id}
                className={selected?.semantic_node_id === item.semantic_node_id ? "active" : ""}
                onClick={() => setSelectedId(item.semantic_node_id)}
              >
                <span className={`module-status ${meta.tone}`}><Icon size={13} /> {meta.label}</span>
                <strong>{item.node?.title_zh || item.semantic_node_id}</strong>
                <small>{item.node?.section_number || "动态"} · {item.rationale}</small>
              </button>
            );
          })}
          {!visible.length && <p>当前筛选条件下没有章节。</p>}
        </div>
        {selected && draft ? (
          <div className="protocol-module-resolution-editor">
            <div className="module-resolution-title">
              <span>{selected.node?.section_number || "动态章节"}</span>
              <strong>{selected.node?.title_zh || selected.semantic_node_id}</strong>
            </div>
            <label>
              <span>本研究如何处理</span>
              <select
                value={selectedOption}
                onChange={(event) => {
                  const option = STATUS_OPTIONS.find((item) => item.value === event.target.value);
                  if (!option) return;
                  setDraft((current) => ({
                    ...current,
                    status: option.status,
                    renderAction: option.renderAction,
                    rationale: defaultRationale(option.status),
                  }));
                }}
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>医学设计依据</span>
              <textarea
                rows={3}
                value={draft.rationale}
                onChange={(event) => setDraft((current) => ({ ...current, rationale: event.target.value }))}
                placeholder="简要说明为什么本研究纳入、不适用或延后该模块。"
              />
            </label>
            <div className="module-resolution-impact">
              <span>同步更新</span>
              <div>
                {(selected.affected_artifacts || []).map((item) => (
                  <b key={item}>{ARTIFACT_LABELS[item] || item}</b>
                ))}
              </div>
            </div>
            <button
              type="button"
              className="primary-button"
              disabled={!canApply}
              data-baseline-ready={baselineReady ? "true" : "false"}
              onClick={() => onApply?.(selected, draft)}
            >
              {!baselineReady
                ? "正在同步方案基线"
                : busyId === selected.semantic_node_id
                  ? "正在应用"
                  : "应用到方案"}
            </button>
          </div>
        ) : <div className="protocol-module-resolution-empty">尚无可配置的动态章节。</div>}
      </div>
      {message && <p className="protocol-module-resolution-message">{message}</p>}
      {lastResult && (
        <p className="protocol-module-resolution-result">
          已同步 {lastResult.affected_artifacts?.map((item) => ARTIFACT_LABELS[item] || item).join("、") || "正文"}
          ；新增 {lastResult.added_section_ids?.length || 0} 节，移除 {lastResult.removed_section_ids?.length || 0} 节，
          保留历史 {lastResult.quarantined_section_ids?.length || 0} 节。
        </p>
      )}
    </section>
  );
}
