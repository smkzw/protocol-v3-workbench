# F02 执行包：给药推荐就地补答与确认事实收敛

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F01。
覆盖需求：R1, R2, R5；验收：A02, A04, A05, A08, V04。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
给药建议、研究信息确认、Agent2输入/采用与准备度；不改无关研究或预置疾病值。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [frontend/src/features/medical-writing/protocol-workbench/RegimenDesignWorkspace.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/RegimenDesignWorkspace.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/RegimenProposalCard.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/RegimenProposalCard.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/RegimenAdoptionCard.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/RegimenAdoptionCard.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/ResearchInformationCard.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/ResearchInformationCard.jsx)
- [services/api/app/protocol_workflow/agent2/clinical_worker.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent2/clinical_worker.py)
- [services/api/app/protocol_workflow/agent2/recommendations.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent2/recommendations.py)
- [services/api/app/protocol_workflow/agent2/study_input.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent2/study_input.py)
- [services/api/app/protocol_workflow/agent2/design_coordinator.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent2/design_coordinator.py)
- [services/api/app/protocol_workflow/application/adoption.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/application/adoption.py)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 从第十轮CONFERENCE_REVIEW重建补答只进候选、confirmed_study不变的因果链；核对当前代码是否已有部分修复。
2. 建立问题到事实路径、当前值、来源、确认含义的最小映射；用户答复保留真实输入版本，不伪造source_artifact/quote。
3. 问题卡给推荐、可选答案及必要自由输入；确认值进入StudyDefinition已有采用事务。
4. 原文证据、用户明确设计和AI建议分别校验，不要求用户意图必须具有外部原文quote。
5. 模型questions只作候选问题，准入从当前事实/关键依赖算；已答与重复问题不再次阻挡，真正新冲突可见。
6. 修复blocked按钮只recover同run的假重试，复用现有resume图语义；实际新输入形成有前序关联的新请求，旧运行保留。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
PYTHONPATH=services/api:packages:.:tests:tests/protocol_v3:tests/protocol_v3/integration runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_regimen_confirmed_study_input.py tests/protocol_v3/integration/test_regimen_fact_adoption.py tests/protocol_v3/integration/test_regimen_adoption_api.py -q
```
```sh
cd frontend && ./node_modules/.bin/vitest run src/features/medical-writing/protocol-workbench/RegimenDesignWorkspace.test.jsx src/features/medical-writing/protocol-workbench/RegimenAdoptionCard.test.jsx --environment jsdom
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
先闭合确认→事实→输入，再进入F05；新的科学取舍不足时给具体选项，不把实现问题交给用户。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
