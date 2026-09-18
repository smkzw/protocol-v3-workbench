export const SOURCE_ROLE_OPTIONS = [
  { value: "project_primary", label: "本方案文件（项目方案/研究者手册）" },
  { value: "regulatory_or_guideline", label: "法规或指导原则" },
  { value: "competitor_full_protocol", label: "竞品完整方案" },
  { value: "registry_only", label: "仅试验登记信息" },
  { value: "peer_reviewed", label: "同行评审文献" },
  { value: "company_style_only", label: "公司历史方案或模板" },
  { value: "endpoint_or_instrument", label: "终点定义或评估工具" },
];

export const ROLE_LABELS = Object.fromEntries(
  SOURCE_ROLE_OPTIONS.map((option) => [option.value, option.label]),
);

// Localize known internal category names in explanatory copy only. Source
// quotations and the immutable model receipt are never rewritten.
export function sourceRoleDisplayText(text) {
  return String(text).replace(/\b(?:project_primary|regulatory_or_guideline|competitor_full_protocol|registry_only|peer_reviewed|company_style_only|endpoint_or_instrument)\b/g,
    token => ROLE_LABELS[token]);
}
