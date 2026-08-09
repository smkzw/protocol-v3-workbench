import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";

const SCHEMA_VERSION = "medical_writing_intervention_rules_v1";

const PRODUCT_ROLE_OPTIONS = [
  ["investigational_product", "试验药"],
  ["active_comparator", "阳性对照"],
  ["placebo", "安慰剂"],
  ["other", "其他"],
];
const ADJUSTMENT_POLICY_OPTIONS = [
  ["unspecified", "未指定"],
  ["no_planned_adjustment", "无计划性剂量调整"],
  ["protocol_defined", "方案规定的调整"],
];
const ACTION_KIND_OPTIONS = [
  ["planned_on_off", "计划性停药/重启"],
  ["temporary_interruption", "暂时中断"],
  ["resume", "恢复用药"],
  ["permanent_discontinuation", "永久停药"],
  ["discontinuation_taper", "减量至停药"],
  ["post_discontinuation_follow_up", "停药后随访"],
  ["other", "其他"],
];
const RULE_CLASS_OPTIONS = [
  ["background", "背景治疗"],
  ["allowed_cm", "允许的合并用药"],
  ["prohibited_cm", "禁止的合并用药"],
  ["rescue", "补救治疗"],
  ["other_non_investigational", "其他非试验用药"],
];
const NON_IP_RULE_CLASS_OPTIONS = RULE_CLASS_OPTIONS.filter(([value]) => ["background", "rescue", "other_non_investigational"].includes(value));
const CM_RULE_CLASS_OPTIONS = RULE_CLASS_OPTIONS.filter(([value]) => ["allowed_cm", "prohibited_cm"].includes(value));
const POLICY_OPTIONS = [
  ["allowed", "允许"],
  ["allowed_if_stable", "允许（病情稳定时）"],
  ["allowed_with_approval", "允许（需批准）"],
  ["allowed_with_timing", "允许（限时）"],
  ["prohibited", "禁止"],
  ["rescue_policy", "补救策略"],
];
const LINK_ACTION_OPTIONS = [
  ["hold", "暂停IP"],
  ["stop", "停止IP"],
  ["no_auto_ip_action", "不自动改变IP"],
  ["resume", "恢复IP"],
];

const PANELS = [
  ["regimen", "试验药物与给药"],
  ["ip_actions", "试验用药品调整与处置"],
  ["non_ip", "非试验用药与补救"],
  ["cm", "合并用药"],
];

const uid = (prefix) => `${prefix}_${typeof globalThis.crypto?.randomUUID === "function" ? globalThis.crypto.randomUUID() : Math.random().toString(36).slice(2, 10)}`;

function emptyRules() {
  return {
    schema_version: SCHEMA_VERSION,
    authority: "legacy",
    ip_regimens: [],
    ip_adjustment_policy: "unspecified",
    no_planned_adjustment_statement: "",
    ip_action_rules: [],
    non_ip_treatment_rules: [],
    cross_object_links: [],
  };
}

function ensureRules(value) {
  if (!value || typeof value !== "object") return emptyRules();
  return {
    schema_version: SCHEMA_VERSION,
    authority: value.authority === "structured" ? "structured" : "legacy",
    ip_regimens: Array.isArray(value.ip_regimens) ? value.ip_regimens : [],
    ip_adjustment_policy: ADJUSTMENT_POLICY_OPTIONS.some(([k]) => k === value.ip_adjustment_policy) ? value.ip_adjustment_policy : "unspecified",
    no_planned_adjustment_statement: String(value.no_planned_adjustment_statement || ""),
    ip_action_rules: Array.isArray(value.ip_action_rules) ? value.ip_action_rules : [],
    non_ip_treatment_rules: Array.isArray(value.non_ip_treatment_rules) ? value.non_ip_treatment_rules : [],
    cross_object_links: Array.isArray(value.cross_object_links) ? value.cross_object_links : [],
  };
}

function newRowRegimen() {
  return { regimen_id: uid("reg"), product_name: "", product_role: "investigational_product", dose_and_frequency: "", route: "", treatment_period: "", adherence_notes: "", source_location: "" };
}
function newRowIpAction() {
  return { rule_id: uid("ipr"), action_kind: "temporary_interruption", trigger: "", severity_or_threshold: "", confirmation_required: "", exceptions: [], study_product_action: "", retest_recovery: "", approvers: [], wait_period: "", permanent_discontinuation_condition: "", taper_steps: [], linked_non_ip_rule_ids: [], source_location: "", notes: "" };
}
function newRowNonIp() {
  return { rule_id: uid("nir"), rule_class: "background", policy: "allowed", agent_or_category: "", collection_window: "", timing_restrictions: [], washout_or_window: "", cm_dose_rule: "", phase_applicability: "", exceptions: [], source_location: "", notes: "" };
}
function newRowLink() {
  return { link_id: uid("lnk"), source_rule_id: "", source_kind: "rescue", target_kind: "ip", target_rule_id: "", action: "no_auto_ip_action", resume_condition: "", notes: "", source_location: "" };
}

export function InterventionRulesEditor({ value, onChange, panel = "", onPanelChange }) {
  const [collapsed, setCollapsed] = useState(false);
  const rules = ensureRules(value);
  const activePanel = PANELS.some(([key]) => key === panel) ? panel : "regimen";

  useEffect(() => {
    if (panel && !PANELS.some(([key]) => key === panel)) onPanelChange?.("regimen");
  }, [panel, onPanelChange]);

  const update = (patch) => {
    const next = { ...rules, ...patch };
    const hasStructuredContent = next.ip_regimens.length
      || next.ip_action_rules.length
      || next.non_ip_treatment_rules.length
      || next.cross_object_links.length
      || next.ip_adjustment_policy !== "unspecified"
      || next.no_planned_adjustment_statement.trim();
    if (hasStructuredContent && next.authority !== "structured") next.authority = "structured";
    onChange(next);
  };

  const listOps = (field, factory) => ({
    add: () => update({ [field]: [...rules[field], factory()] }),
    addWith: (override) => update({ [field]: [...rules[field], { ...factory(), ...override }] }),
    removeItem: (index) => update({ [field]: rules[field].filter((_, i) => i !== index) }),
    setItem: (index, patch) => update({ [field]: rules[field].map((item, i) => (i === index ? { ...item, ...patch } : item)) }),
  });

  const toggleCollapsed = () => setCollapsed((v) => !v);
  const setPanel = (key) => onPanelChange?.(key);

  const ipActionIds = rules.ip_action_rules.map((r) => r.rule_id);
  const nonIpIds = rules.non_ip_treatment_rules.map((r) => r.rule_id);

  return (
    <section className="intervention-rules-editor">
      <header className="intervention-rules-head" onClick={toggleCollapsed} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleCollapsed(); } }}>
        <span className="intervention-rules-toggle">{collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}</span>
        <div>
          <strong>结构化干预规则编辑器</strong>
          <small>试验药物与给药、剂量调整、非试验用药/补救、合并用药分栏维护；IP与CM边界不混用。</small>
        </div>
        <span className={`intervention-rules-authority ${rules.authority}`}>{rules.authority === "structured" ? "结构化" : "兼容模式"}</span>
      </header>
      {!collapsed && (
        <>
          <div className="intervention-rules-segments" role="tablist">
            {PANELS.map(([key, label]) => (
              <button key={key} type="button" role="tab" aria-selected={activePanel === key} className={activePanel === key ? "active" : ""} onClick={() => setPanel(key)}>{label}</button>
            ))}
          </div>
          <div className="intervention-rules-body">
            {activePanel === "regimen" && <RegimenPanel rules={rules} ops={listOps("ip_regimens", newRowRegimen)} />}
            {activePanel === "ip_actions" && <IpActionsPanel rules={rules} update={update} ops={listOps("ip_action_rules", newRowIpAction)} nonIpIds={nonIpIds} />}
            {activePanel === "non_ip" && <NonIpPanel rules={rules} ops={listOps("non_ip_treatment_rules", newRowNonIp)} linkOps={listOps("cross_object_links", newRowLink)} ipActionIds={ipActionIds} />}
            {activePanel === "cm" && <CmPanel rules={rules} ops={listOps("non_ip_treatment_rules", newRowNonIp)} linkOps={listOps("cross_object_links", newRowLink)} ipActionIds={ipActionIds} />}
          </div>
        </>
      )}
    </section>
  );
}

function DenseRow({ index, onDelete, deleteLabel, children }) {
  return (
    <div className="intervention-rules-row">
      <span className="intervention-rules-row-index">{String(index + 1).padStart(2, "0")}</span>
      <div className="intervention-rules-row-fields">{children}</div>
      <button type="button" className="icon-button intervention-rules-row-delete" onClick={onDelete} title={deleteLabel}><Trash2 size={14} /></button>
    </div>
  );
}

function MiniInput({ label, value, onChange, placeholder, span }) {
  return (
    <label className={`intervention-rules-mini ${span ? `span-${span}` : ""}`}>
      <span>{label}</span>
      <input value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </label>
  );
}
function MiniSelect({ label, value, onChange, options, disabled = false }) {
  return (
    <label className="intervention-rules-mini">
      <span>{label}</span>
      <select value={value || ""} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {options.map(([val, lbl]) => <option key={val} value={val}>{lbl}</option>)}
      </select>
    </label>
  );
}
function MiniArea({ label, value, onChange, placeholder, rows }) {
  return (
    <label className="intervention-rules-mini span-full">
      <span>{label}</span>
      <textarea rows={rows || 2} value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </label>
  );
}

function MiniListInput({ label, value, onChange, span = 2 }) {
  return <MiniInput label={label} value={(value || []).join("；")} onChange={(text) => onChange(text.split(/[;；\n]+/).map((item) => item.trim()).filter(Boolean))} span={span} />;
}

function PanelAddButton({ label, onClick }) {
  return <button type="button" className="intervention-rules-add" onClick={onClick}><Plus size={14} /> {label}</button>;
}

function EmptyHint({ text }) {
  return <p className="intervention-rules-empty">{text}</p>;
}

function RegimenPanel({ rules, ops }) {
  return (
    <div className="intervention-rules-panel">
      <p className="intervention-rules-panel-hint">试验药物常规给药方案（IP）。CM剂量调整不在此处。</p>
      {rules.ip_regimens.length === 0 && <EmptyHint text="尚未登记试验药物给药方案。" />}
      {rules.ip_regimens.map((row, i) => (
        <DenseRow key={row.regimen_id} index={i} onDelete={() => ops.removeItem(i)} deleteLabel="删除给药方案">
          <MiniInput label="产品名称" value={row.product_name} onChange={(v) => ops.setItem(i, { product_name: v })} />
          <MiniSelect label="产品角色" value={row.product_role} onChange={(v) => ops.setItem(i, { product_role: v })} options={PRODUCT_ROLE_OPTIONS} />
          <MiniInput label="用法用量" value={row.dose_and_frequency} onChange={(v) => ops.setItem(i, { dose_and_frequency: v })} span={2} />
          <MiniInput label="给药途径" value={row.route} onChange={(v) => ops.setItem(i, { route: v })} />
          <MiniInput label="治疗时期" value={row.treatment_period} onChange={(v) => ops.setItem(i, { treatment_period: v })} />
          <MiniInput label="依从性说明" value={row.adherence_notes} onChange={(v) => ops.setItem(i, { adherence_notes: v })} span={2} />
          <MiniInput label="来源定位" value={row.source_location} onChange={(v) => ops.setItem(i, { source_location: v })} span={2} />
        </DenseRow>
      ))}
      <PanelAddButton label="新增给药方案" onClick={ops.add} />
    </div>
  );
}

function IpActionsPanel({ rules, update, ops, nonIpIds }) {
  const policy = rules.ip_adjustment_policy;
  return (
    <div className="intervention-rules-panel">
      <div className="intervention-rules-policy-bar">
        <label className="intervention-rules-mini">
          <span>剂量调整策略</span>
          <select value={policy} onChange={(e) => update({ ip_adjustment_policy: e.target.value })}>
            {ADJUSTMENT_POLICY_OPTIONS.map(([val, lbl]) => <option key={val} value={val}>{lbl}</option>)}
          </select>
        </label>
        {policy === "no_planned_adjustment" && (
          <label className="intervention-rules-mini span-full">
            <span>无计划性调整说明（必填）</span>
            <input value={rules.no_planned_adjustment_statement || ""} onChange={(e) => update({ no_planned_adjustment_statement: e.target.value })} placeholder="说明本研究无计划性常规剂量调整，可包含安全中断/永久停药/减量/随访规则" />
          </label>
        )}
      </div>
      {rules.ip_action_rules.length === 0 && <EmptyHint text="尚未登记试验药物剂量调整规则。" />}
      {rules.ip_action_rules.map((row, i) => (
        <DenseRow key={row.rule_id} index={i} onDelete={() => ops.removeItem(i)} deleteLabel="删除IP调整规则">
          <MiniSelect label="调整类型" value={row.action_kind} onChange={(v) => ops.setItem(i, { action_kind: v })} options={ACTION_KIND_OPTIONS} />
          <MiniInput label="触发条件" value={row.trigger} onChange={(v) => ops.setItem(i, { trigger: v })} span={3} />
          <MiniInput label="严重程度/阈值" value={row.severity_or_threshold} onChange={(v) => ops.setItem(i, { severity_or_threshold: v })} span={2} />
          <MiniInput label="确认要求" value={row.confirmation_required} onChange={(v) => ops.setItem(i, { confirmation_required: v })} span={2} />
          <MiniArea label="试验药物处置" value={row.study_product_action} onChange={(v) => ops.setItem(i, { study_product_action: v })} />
          <MiniArea label="复测/恢复条件" value={row.retest_recovery} onChange={(v) => ops.setItem(i, { retest_recovery: v })} />
          <MiniInput label="等待期" value={row.wait_period} onChange={(v) => ops.setItem(i, { wait_period: v })} span={2} />
          <MiniListInput label="例外条件" value={row.exceptions} onChange={(v) => ops.setItem(i, { exceptions: v })} />
          {row.action_kind === "permanent_discontinuation" && (
            <MiniArea label="永久停药条件" value={row.permanent_discontinuation_condition} onChange={(v) => ops.setItem(i, { permanent_discontinuation_condition: v })} />
          )}
          {row.action_kind === "discontinuation_taper" && <MiniListInput label="递减步骤" value={row.taper_steps} onChange={(v) => ops.setItem(i, { taper_steps: v })} span={4} />}
          <MiniInput label="审批人" value={(row.approvers || []).join("、")} onChange={(v) => ops.setItem(i, { approvers: v.split(/[、,;，；\n]+/).map((s) => s.trim()).filter(Boolean) })} span={2} />
          <MiniInput label="来源定位" value={row.source_location} onChange={(v) => ops.setItem(i, { source_location: v })} span={2} />
          <MiniArea label="备注" value={row.notes} onChange={(v) => ops.setItem(i, { notes: v })} />
        </DenseRow>
      ))}
      <PanelAddButton label="新增IP剂量调整规则" onClick={ops.add} />
      {nonIpIds.length > 0 && rules.ip_action_rules.length > 0 && (
        <p className="intervention-rules-panel-hint">非试验治疗或 CM 对试验用药品的影响，请在对应规则面板建立显式关联。</p>
      )}
    </div>
  );
}

function NonIpPanel({ rules, ops, linkOps, ipActionIds }) {
  const filtered = rules.non_ip_treatment_rules.map((row, originalIndex) => ({ row, originalIndex })).filter(({ row }) => ["background", "rescue", "other_non_investigational"].includes(row.rule_class));
  const sourceRuleIds = filtered.map(({ row }) => row.rule_id);
  return (
    <div className="intervention-rules-panel">
      <p className="intervention-rules-panel-hint">背景治疗、补救治疗及其他非试验用药。合并用药（允许/禁止）请在"合并用药"面板维护。</p>
      {filtered.length === 0 && <EmptyHint text="尚未登记非试验用药/补救治疗规则。" />}
      {filtered.map(({ row, originalIndex }, displayIndex) => (
        <DenseRow key={row.rule_id} index={displayIndex} onDelete={() => ops.removeItem(originalIndex)} deleteLabel="删除非IP规则">
          <MiniSelect label="规则类别" value={row.rule_class} onChange={(v) => ops.setItem(originalIndex, { rule_class: v, policy: v === "rescue" ? "rescue_policy" : row.policy === "rescue_policy" ? "allowed" : row.policy })} options={NON_IP_RULE_CLASS_OPTIONS} />
          <MiniSelect label="策略" value={row.policy} onChange={(v) => ops.setItem(originalIndex, { policy: v })} options={POLICY_OPTIONS} />
          <MiniInput label="药物/类别" value={row.agent_or_category} onChange={(v) => ops.setItem(originalIndex, { agent_or_category: v })} span={2} />
          <MiniInput label="采集窗口" value={row.collection_window} onChange={(v) => ops.setItem(originalIndex, { collection_window: v })} />
          <MiniListInput label="时间限制" value={row.timing_restrictions} onChange={(v) => ops.setItem(originalIndex, { timing_restrictions: v })} />
          <MiniInput label="洗脱/时间窗" value={row.washout_or_window} onChange={(v) => ops.setItem(originalIndex, { washout_or_window: v })} span={2} />
          <MiniInput label="阶段适用性" value={row.phase_applicability} onChange={(v) => ops.setItem(originalIndex, { phase_applicability: v })} span={2} />
          <MiniInput label="CM剂量规则" value={row.cm_dose_rule} onChange={(v) => ops.setItem(originalIndex, { cm_dose_rule: v })} span={2} />
          <MiniListInput label="例外条件" value={row.exceptions} onChange={(v) => ops.setItem(originalIndex, { exceptions: v })} />
          <MiniInput label="来源定位" value={row.source_location} onChange={(v) => ops.setItem(originalIndex, { source_location: v })} span={2} />
          <MiniArea label="备注" value={row.notes} onChange={(v) => ops.setItem(originalIndex, { notes: v })} />
        </DenseRow>
      ))}
      <PanelAddButton label="新增非IP规则" onClick={ops.add} />
      <CrossObjectLinks rules={rules} linkOps={linkOps} ipActionIds={ipActionIds} sourceRuleIds={sourceRuleIds} defaultSourceKind="rescue" />
    </div>
  );
}

function CmPanel({ rules, ops, linkOps, ipActionIds }) {
  const cmRows = rules.non_ip_treatment_rules.map((row, originalIndex) => ({ row, originalIndex })).filter(({ row }) => ["allowed_cm", "prohibited_cm"].includes(row.rule_class));
  const sourceRuleIds = cmRows.map(({ row }) => row.rule_id);
  return (
    <div className="intervention-rules-panel">
      <p className="intervention-rules-panel-hint">合并用药允许/禁止规则。CM剂量变更不会生成IP剂量调整规则。</p>
      {cmRows.length === 0 && <EmptyHint text="尚未登记合并用药规则。新增非IP规则后选择允许的合并用药或禁止的合并用药类别即可。" />}
      {cmRows.map(({ row, originalIndex }, displayIndex) => (
        <DenseRow key={row.rule_id} index={displayIndex} onDelete={() => ops.removeItem(originalIndex)} deleteLabel="删除CM规则">
          <MiniSelect label="规则类别" value={row.rule_class} onChange={(v) => ops.setItem(originalIndex, { rule_class: v, policy: v === "prohibited_cm" ? "prohibited" : row.policy === "prohibited" ? "allowed" : row.policy })} options={CM_RULE_CLASS_OPTIONS} />
          <MiniSelect label="策略" value={row.policy} onChange={(v) => ops.setItem(originalIndex, { policy: v })} options={POLICY_OPTIONS} />
          <MiniInput label="药物/类别" value={row.agent_or_category} onChange={(v) => ops.setItem(originalIndex, { agent_or_category: v })} span={2} />
          <MiniInput label="CM剂量规则" value={row.cm_dose_rule} onChange={(v) => ops.setItem(originalIndex, { cm_dose_rule: v })} span={2} />
          <MiniInput label="采集窗口" value={row.collection_window} onChange={(v) => ops.setItem(originalIndex, { collection_window: v })} />
          <MiniListInput label="时间限制" value={row.timing_restrictions} onChange={(v) => ops.setItem(originalIndex, { timing_restrictions: v })} />
          <MiniInput label="洗脱/时间窗" value={row.washout_or_window} onChange={(v) => ops.setItem(originalIndex, { washout_or_window: v })} span={2} />
          <MiniInput label="阶段适用性" value={row.phase_applicability} onChange={(v) => ops.setItem(originalIndex, { phase_applicability: v })} span={2} />
          <MiniListInput label="例外条件" value={row.exceptions} onChange={(v) => ops.setItem(originalIndex, { exceptions: v })} />
          <MiniInput label="来源定位" value={row.source_location} onChange={(v) => ops.setItem(originalIndex, { source_location: v })} span={2} />
          <MiniArea label="备注" value={row.notes} onChange={(v) => ops.setItem(originalIndex, { notes: v })} />
        </DenseRow>
      ))}
      <PanelAddButton label="新增CM规则" onClick={() => ops.addWith({ rule_class: "allowed_cm" })} />
      <CrossObjectLinks rules={rules} linkOps={linkOps} ipActionIds={ipActionIds} sourceRuleIds={sourceRuleIds} defaultSourceKind="cm" />
    </div>
  );
}

function CrossObjectLinks({ rules, linkOps, ipActionIds, sourceRuleIds, defaultSourceKind }) {
  const links = rules.cross_object_links.map((link, originalIndex) => ({ link, originalIndex })).filter(({ link }) => sourceRuleIds.includes(link.source_rule_id));
  if (!sourceRuleIds.length || !ipActionIds.length) return null;
  const nonIpById = new Map(rules.non_ip_treatment_rules.map((rule) => [rule.rule_id, rule]));
  const ipActionById = new Map(rules.ip_action_rules.map((rule) => [rule.rule_id, rule]));
  const sourceKind = (ruleId) => {
    const ruleClass = nonIpById.get(ruleId)?.rule_class;
    if (ruleClass === "rescue") return "rescue";
    if (ruleClass === "background") return "background";
    if (["allowed_cm", "prohibited_cm"].includes(ruleClass)) return "cm";
    return "other_non_ip";
  };
  const sourceOptions = sourceRuleIds.map((id) => {
    const rule = nonIpById.get(id);
    return [id, `${rule?.agent_or_category || "未命名规则"} (${id})`];
  });
  const targetOptions = ipActionIds.map((id) => {
    const rule = ipActionById.get(id);
    const actionLabel = ACTION_KIND_OPTIONS.find(([value]) => value === rule?.action_kind)?.[1] || "试验用药品处置";
    return [id, `${actionLabel}${rule?.trigger ? ` · ${rule.trigger}` : ""} (${id})`];
  });
  return (
    <div className="intervention-rules-links">
      <header><strong>跨对象关联</strong><span>明确非试验治疗或 CM 是否触发试验用药品暂停、停止或恢复；不会把两类规则合并。</span></header>
      {links.map(({ link, originalIndex }, displayIndex) => (
        <DenseRow key={link.link_id} index={displayIndex} onDelete={() => linkOps.removeItem(originalIndex)} deleteLabel="删除关联">
          <MiniSelect label="来源规则" value={link.source_rule_id} onChange={(v) => linkOps.setItem(originalIndex, { source_rule_id: v, source_kind: sourceKind(v) })} options={sourceOptions} />
          <MiniSelect label="来源类型" value={sourceKind(link.source_rule_id)} onChange={() => {}} options={[["rescue", "补救治疗"], ["cm", "合并用药"], ["background", "背景治疗"], ["other_non_ip", "其他非试验治疗"]]} disabled />
          <MiniSelect label="目标试验用药品规则" value={link.target_rule_id} onChange={(v) => linkOps.setItem(originalIndex, { target_rule_id: v })} options={[["", "—无—"], ...targetOptions]} />
          <MiniSelect label="动作" value={link.action} onChange={(v) => linkOps.setItem(originalIndex, { action: v })} options={LINK_ACTION_OPTIONS} />
          <MiniInput label="恢复条件" value={link.resume_condition} onChange={(v) => linkOps.setItem(originalIndex, { resume_condition: v })} span={2} />
          <MiniInput label="来源定位" value={link.source_location} onChange={(v) => linkOps.setItem(originalIndex, { source_location: v })} span={2} />
          <MiniArea label="补充说明" value={link.notes} onChange={(v) => linkOps.setItem(originalIndex, { notes: v })} />
        </DenseRow>
      ))}
      <PanelAddButton label="新增跨对象关联" onClick={() => linkOps.addWith({ source_rule_id: sourceRuleIds[0], source_kind: sourceKind(sourceRuleIds[0]) || defaultSourceKind, target_rule_id: ipActionIds[0] })} />
    </div>
  );
}
