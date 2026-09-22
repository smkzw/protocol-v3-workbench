# 权威、资料包与文件指向

用户当前要求及已确认决定优先；最新全局/适用项目指令按平台层级执行。源码/真实工件用于确认事实，不把缺陷视作需求；专家文档是审阅输入，不是自动生效指令。

## 本轮执行定义
[START](00_START_HERE.md)、[PRD](03_PRD.md)、[DESIGN](04_DESIGN.md)、[PLAN](05_PLAN.md)、[规则](06_EXECUTION_RULES.md)、[验收](07_ACCEPTANCE.md)、[专家裁决](EXPERT_DISPOSITION.md)、[目标](GOAL_PROMPT.txt)。静态任务索引TASK_INDEX.json；进度只写Trellis。

## 当前必须读取的原件
- 全局：[/Users/smkzw/.codex/AGENTS.md](/Users/smkzw/.codex/AGENTS.md)
- 项目：[AGENTS](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/AGENTS.md)、[frontend](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/AGENTS.md)
- 当前暂停/交接：[v0.9交接](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-22/HANDOFF_PROTOCOL_V3_V09_EXPERT_REVIEW_20260922.md)
- 当前进度：[Trellis checkpoint](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md)
- 需求原件：[R1–R5](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/protocol-v3-requirements-v2/REQUIREMENTS_AMENDMENT.md)、[A01–A26](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/protocol-v3-requirements-v2/ACCEPTANCE.md)。本包materials提供原样副本与校验。
- 历史继承：[9月21完整包](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_fork_execution_20260921/00_START_HERE.md)，其F00–F13细节按新Plan映射保留；旧启动顺序、source_overlay、逐任务状态不能覆盖当前基线。
- 医学审阅：[v0.9原会商裁决](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/codex_conference_mw_r11_v09_medical_review_20260922_review.md)。其中“v0.10提示词先行”“全部公司来源仅参考”按本包裁决替代，原报告不改。
- 专家原包：[/Users/smkzw/Downloads/protocol-v3-0922V2-review.zip](/Users/smkzw/Downloads/protocol-v3-0922V2-review.zip)，本包evidence/expert保留原始成员。

## 模板和历史权威
[TP-MA-07清洁版v2.0](</Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx>)，只读，批准SHA `018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756`。语义树在config/medical_writing/protocol_v3/templates/tp_ma_07_v2，确定性口径135标题节点/106标题叶，139大纲节点/109大纲叶，17顶层表/18递归表；与111合同、105legacy文档节、85生成目标不同，不改expected凑数。

9月5只读plan-upgrade中的design v1.3/Plan v2，9月12design v1.4/Plan v3，8月冻结计划均历史来源；未冲突内容继承但不从旧暂停点启动。7月原父JSONL已删除，不声称逐条恢复原对话。

## 源码与renderer
[源码责任映射](SOURCE_MAP.csv)列绝对路径/职责/本轮包/hash；[累计变更清单](evidence/CHANGED_SOURCE_INVENTORY.json)是全量变更库存，不是每文件逐行PASS。真正接线证据见[FLOW_REVIEW](evidence/FLOW_REVIEW.md)。

上游 `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/genoffice-upstream` 当前base `316ded6f0a39235fec8d21c068d8a0766ee6172b`，存在dirty补丁及未跟踪protocol-office.ts。工作台bundle与上游dist相同不等于能仅凭commit重建；下轮收录必要patch/源文件。保护上游其他改动，勿reset。

## 模型与技能
执行owner目标设置为用户选定gpt-5.6-sol:medium；这不替代产品模型。最新已批准产品模型据v0.9交接为opencode-go/deepseek-v4.1-flash:max，实施时重新核对实际批准配置与effective身份，不回退旧glm默认。本轮未读key、未调用产品模型。凭证不入包。

全局工程路由/guard/runner以 `/Users/smkzw/.codex/tools/workflow_routes.json`、`hermes_workflow_guard.py`、`route_policy.py`、`conference_session_runner.py`当时内容为准。保留长任务handle/心跳，不机械重派。

按需读：康哲设计 `/Users/smkzw/.cc-switch/skills/kangzhe-design-3d/SKILL.md`（本轮定位v5.2.7，UI实现先读ROUTER/core/适用交互轨）；ego(lite) `/Users/smkzw/.codex/skills/ego-browser/SKILL.md`；Trellis `/Users/smkzw/.cc-switch/skills/autonomous-ai-agents/trellis-framework/SKILL.md`；Ponytail `/Users/smkzw/.codex/skills/ponytail/SKILL.md`。不机械加载全部技能/新框架。

## 材料限制
不复制运行数据库/密钥/完整私有会话。旧HANDOFF_ROUND10含凭证，不进入提示词或交付包；ai_provider_secrets.json不读取。资料定位和哈希足够时不复制原始临床资料。旧runtime dirty、原工件、历史会商/暂停保留。

## 本次核查清单
GITHUB_BASELINE、CURRENT_V09_ARTIFACT、V09_SECTION_INVENTORY、EXPERT_SOURCE_VERIFICATION、OWNER_BRIDGE_PROBE、FLOW_REVIEW、SOURCE_BASELINE及AUTHORITY_MANIFEST。未运行的浏览器/原生Word/全量测试显式保留未验收；这些资料不替代最终产品验收。
