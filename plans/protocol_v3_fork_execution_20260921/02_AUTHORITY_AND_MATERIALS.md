# 权威、资料与加载顺序

## 优先顺序
系统/开发者约束 → 当前用户命令 → 最新全局/适用项目AGENTS → 用户已明确业务决定 → 当前事实与工件证据 → 本包工程实施建议 → 历史设计/计划。
本包继承R1–R5与未被取消的产品义务；不改写历史批准记录。遇到源码与交接报告冲突，以实际源码和运行证据记差异，不能把缺陷当新需求。

## 必须读
- [最新全局AGENTS](/Users/smkzw/.codex/AGENTS.md)；[项目AGENTS](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/AGENTS.md)；[frontend AGENTS](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/AGENTS.md)。
- [R1–R5](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/protocol-v3-requirements-v2/REQUIREMENTS_AMENDMENT.md)、[原验收A01–A26](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/protocol-v3-requirements-v2/ACCEPTANCE.md)、[实施建议与接口边界](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/protocol-v3-requirements-v2/AGENT_NEXT_TASK.md)。
- [第十一轮当前证据](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round11/TAKEOVER_REVIEW.md)、[Trellis checkpoint](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md)。
- [第十轮会商纠正](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round10/CONFERENCE_REVIEW.md)。先读此纠正，再解释tester/AGGREGATE意见。
- [本轮编辑独立审阅裁决](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/codex_conference_mw_r11_editor_verification_20260921_review.md)。

## 源模板
[TP-MA-07清洁版v2.0](/Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx)，只读，SHA256=018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756。
当前确定性登记：[template.json](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/config/medical_writing/protocol_v3/templates/tp_ma_07_v2/template.json)、[node_tree.json](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json)。
135标题节点/106标题叶；139大纲节点/109大纲叶；17顶层表/18递归表；8节。试验参与者218直接段落+22表格=240全文，受试者0。与111合同/载体数不是同一统计口径。不要修改预期使这些数字表面相等。

## 历史继承与禁止误用
- plans/mw_protocol_v3_design_v1.4_20260912.md、plans/mw_protocol_v3_implementation_plan_v3_20260912.md。
- implementation/plan-upgrade-20260905 中design v1.3/Plan v2/执行交接：只读历史，不覆写。
- .hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md：冻结历史。
- 9月12/13暂停、原Goal、9月19tasks.json：保留出处，不能用过时起点覆盖本包。
- runs/requirements_v2_20260919/t17_round10/HANDOFF_ROUND10.md **含凭证**：受限原件，仅本机必要时定向脱敏读取；不复制进prompt、压缩包、报告或新日志。其工程结论由本包及CONFERENCE_REVIEW提供。

## 技能按需读
- 康哲设计：/Users/smkzw/.cc-switch/skills/kangzhe-design-3d/SKILL.md（若路径迁移，读取当前技能目录的同名权威，记录实际版本）。
- ego(lite)：/Users/smkzw/.codex/skills/ego-browser/SKILL.md。
- Trellis：/Users/smkzw/.cc-switch/skills/autonomous-ai-agents/trellis-framework/SKILL.md。
- Ponytail：/Users/smkzw/.codex/skills/ponytail/SKILL.md。
- 原生Word/临床方案审阅等在对应包真正需要时使用；不用一次加载全部技能。
- 工程路由：/Users/smkzw/.codex/tools/workflow_routes.json、hermes_workflow_guard.py、route_policy.py、conference_session_runner.py。按当时文件与配额运行，本包不冻结旧模型表。

## 对外资料查证
实际医学/统计/监管规则升级时再核查当前ICH/CDE/NMPA及当前项目来源；记录版本和定位。该包不是医学指南更新证书。患者/研究参数来自当前项目或用户确认，不从外部范例抄成事实。

本包AUTHORITY_MANIFEST.json记录上述存在原件的hash；不存在/迁移明确标记，不默默补造。源码索引用SOURCE_MAP.csv，逐任务只读相关组件与完整受影响定义。
