# F05 执行包：完整结构且有实质正文的工作初稿

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F02, F03, F04。
覆盖需求：R1, R2, R4, R5；验收：A04, A05, A06, A07, A13, A14, A23。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
准备度、章节合同、提示与初始内容生成，不修改人工Office快照。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [services/api/app/protocol_workflow/agent3/draft_readiness.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/draft_readiness.py)
- [services/api/app/protocol_workflow/agent3/manuscript_plan.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/manuscript_plan.py)
- [services/api/app/protocol_workflow/agent3/manuscript_request.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/manuscript_request.py)
- [services/api/app/protocol_workflow/agent3/chapter_draft.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/chapter_draft.py)
- [services/api/app/protocol_workflow/agent3/chapter_facts.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/chapter_facts.py)
- [services/api/app/protocol_workflow/agent3/manuscript_document.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/manuscript_document.py)
- [services/api/app/protocol_workflow/agent3/synopsis_projection.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/synopsis_projection.py)
- [services/api/app/protocol_workflow/agent3/soa_matrix.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/soa_matrix.py)
- [services/api/app/protocol_workflow/registries/fact_bindings.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/fact_bindings.py)
- [config/medical_writing/protocol_v3/templates/tp_ma_07_v2](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/config/medical_writing/protocol_v3/templates/tp_ma_07_v2)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 对照CLINICAL_CONTENT_CONTRACT和真实registry逐载体建立输入/输出/适用性/缺口清单，不用111数值替代充分性。
2. 关键设计决定准备度，非关键组织信息显式缺口；三态条件不把未知当false。
3. 解决合法事实路径未传入chapter prompt/校验器的丢失或命名漂移；类型保持boolean/number/list/object而非全字符串。
4. AI写实质文字/结构化表；摘要和SOA初始生成根据事实推荐，后续人工所有权不反转。
5. 把工程身份放元数据，用户正文显示可读缺口与最小下一步；表格、脚注、附录与章节标题同样检查，不能下载时删整段。
6. 跨章核对目的/终点/estimand/统计/人群/干预/SOA主线，只有有依据的不适用才写相应状态。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
PYTHONPATH=services/api:packages:.:tests:tests/protocol_v3:tests/protocol_v3/integration runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_draft_readiness.py tests/protocol_v3/test_all_chapter_contracts.py tests/protocol_v3/test_compact_dependency_contract.py -q
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
将实际完整工作稿及来源/研究hash交F07/F08/F10；医学未审部分标明。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
