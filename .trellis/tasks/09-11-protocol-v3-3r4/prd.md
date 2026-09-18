# 3R.4 PRD — 事实、适用性、影响与一次采用

2026-09-12 Codex接回。用户已激活新版Goal恢复实施；本任务尚未验收，按本PRD连续推进。

## 用户结果
修改一个科学决定时，只重新检查/修改确实受影响的内容；不适用的期中/非劣效/供应商内容无需填假参数；刷新/重复点击不重复采用、不丢当前稿。完成后尽早串起Ⅱ/Ⅲ期完整资料到Word路径。

## 权威与范围
计划权威：plans/mw_protocol_v3_implementation_plan_v3_20260912.md第3节的A–D，详细Files/Micro-steps/验收以该节为准；设计v1.4，review同日期。原Task3R.4编号保留。最新全局AGENTS决定工程执行/独立review方法，不复制旧固定路线或人数。
允许恢复后按计划修改registries、必要版本化contract、对应canonical/application/graph消费者及其功能测试。共享定义串行一owner；不新建事实DB/规则平台/安全专项。live/医学监查/8910、外部源、plan-upgrade和历史证据只读。

## 串行子项（状态仅在本Trellis任务跟踪）
- [x] A：typed canonical事实解析、724路径登记、按类型旧版本转换、显示文字/typed表格绑定分离。
- [x] B：49源规则/14交集已逐项裁定，现行70规则，true/false/unknown与实际输入输出验证；验收及当前矩阵见task.json meta。
- [x] C：事实标签/via_paths传播，unknown候选保留，真实派生和调度扇出，确认失效独立判断，错误图不可执行。
- [x] D：复用SQLite/UoW/ledger真实采用，历史精确回放零新效果、当前确认新鲜度、并发/unknown对账；API真实缺失错误正确归类；冻结后独立review并由Codex验收。

## 直接起点证据
runs/mw_protocol_v3_full_review_20260912/conditional_probe.json、source_and_graph_summary.json、missing_aggregate_probe.json；源位置见reviews/mw_protocol_v3_full_review_20260912.md。
3R.3的111载体结构成果不推倒重写。558fixture为结构且医学判断延期，不以其通过替代真实正文。当前baseline1860；将来数字非固定expected。

## 验收及退出
使用计划中的具体反例和实际SQLite行为；修改共享合同后再跑受影响回归。history bytes/原接受runs不改写。图hash仅投影身份。No interim与unknown不能用缺字段静默兜底。worker不自行关闭；Codex整合所需独立review后更新状态。
本项完成后继续3R.5A/3R.6问题卡/3R.7A与V1，Ⅰ期未决只限制依赖其决定的工作。恢复时如其他Agent已经完成某项，先核对当前证据再跳过，不能重复派发。

## Canonical projections

3R.4A实现决定：13个synopsis行依合同rationale均为正文事实投影，不再读取第二份synopsis可编辑值。已有重复值与规范值矛盾时报告，不自动覆盖。映射为数据地址声明，不代表已取得真实研究资料或批准科学参数。

| 汇总路径 | 单一canonical来源 |
|---|---|
| synopsis.registration_classification | framing.registration_classification |
| synopsis.sponsor | contact.sponsor_organization |
| synopsis.principal_investigator | contact.principal_investigator |
| synopsis.trial_institutions | contact.trial_institutions |
| synopsis.design | framing.structured_design |
| synopsis.population_eligibility | picos.inclusion_modules |
| synopsis.investigational_drug | intervention.product_identity |
| synopsis.comparator_drug | picos.intervention_dose_regimen.comparator_regimen |
| synopsis.interventions | picos.intervention_dose_regimen |
| synopsis.sample_size | statistics.sample_size.reproducible_result |
| synopsis.statistical_methods | picos.statistical_strategy |
| synopsis.overall_duration | framing.study_overall_duration |
| synopsis.participation_duration | picos.participation_duration |

framing.registration_classification、contact.sponsor_organization、contact.trial_institutions、framing.study_overall_duration、picos.participation_duration是本次新声明的单一事实键，分别对应模板汇总表的注册分类、申办机构、实际机构清单、整项研究周期、单个参与者时长；由资料准入/事实确认填入，缺失时报告，不从相似字段猜值。它们仍在现有StudyDefinition.facts内，不建新库。
其余目标已存在于正文合同；picos.comparator_summary在背景竞品概述中使用，不能拿来代替本研究对照药，因此对照药投影使用4.3章本研究comparator_regimen。总体/个体时长分开，不凭framing.structured_design.duration未细化语义自动混同。
人口/入选和统计行将完整结构化来源交给写作层呈现，绑定层不拼凑医学摘要或丢弃字段。C阶段必须经affected_chapter_fact_paths把规范事实变更映射至含synopsis投影的合同路径。


## 2026-09-13 A审阅处置与D接线义务
A的机械读取范围：724路径的direct/projection/unsupported逐项表见runs/mw_protocol_v3_3r4a_20260912/resolution_registration.json；没有缺解析器的native字面键，不等于已具备全部临床资料。generic JSON旧字符串类型仍未决，不能伪装已迁移。
新声明五canonical键由资料准入提供，与所有其他fact一样缺失即报告；StudyDefinition.facts不是受chapter vocabulary限制的封闭字典。111真实合同已用合成canonical值完整读取，仍非真实医学/产品验收。
别名只有投影读法，不建立反向可编辑来源：canonical缺失但legacy alias存在时，不自动将后者升级为已确认事实。冲突不静默采用，不以canonical-wins隐藏用户数据。D必须实现一次新的显式事实修订/投影别名退役（保留历史版本/事件、CAS与ledger回执）及资料准入类型校验；缺失或冲突呈现可恢复诊断。最终V1前必须验证冲突修复到重新绑定的实际SQLite链。
事实确认写入前按目录验证native JSON类型；legacy转换显式声明来源格式，不能根据字符串内容猜格式，旧事件不得改写。只读取时校验是A边界，不是完整写入产品的验收。


2026-09-13 Codex A–D工程范围验收完成，见reviews/codex_mw_protocol_v3_3r4_acceptance_20260913.md；顶端旧未验收描述为历史起点，当前task.json为准。不归档、不提交，连续下一任务。
