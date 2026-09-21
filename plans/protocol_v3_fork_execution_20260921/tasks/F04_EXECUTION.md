# F04 执行包：双入口、来源身份、模型路径与反拟合

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F00。
覆盖需求：R1, R5；验收：A01, A02, A03, A07, A08, A26。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
医学写作双入口与资料链；产品模型配置只读对账，改变批准路线另走用户决定。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [frontend/src/features/medical-writing/MedicalWritingSynopsisProjectIntake.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/MedicalWritingSynopsisProjectIntake.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/StudyContextWorkspace.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/StudyContextWorkspace.jsx)
- [services/api/app/protocol_workflow/api/research_intake.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/api/research_intake.py)
- [services/api/app/protocol_workflow/api/sources.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/api/sources.py)
- [services/api/app/protocol_workflow/agent1/docx_parse.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent1/docx_parse.py)
- [services/api/app/protocol_workflow/agent2/research_intent.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent2/research_intent.py)
- [services/api/app/protocol_workflow/agent3/chapter_facts.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/chapter_facts.py)
- [services/api/app/protocol_workflow/runtime/product_profiles.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/product_profiles.py)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 复用StrictMode与无文字层修复；沿legacy摘要API真实调用到provider定位401来源，不只改前端等待状态。
2. 只读对账最新允许的产品route/profile/endpoint/declared/expected/effective；不把fork sol模型作为产品替代。
3. 两入口同等信息归并相同类型/路径的StudyDefinition，来源轨迹独立；无附件用户意图有正式输入身份。
4. 拆分解析失败、无文字层需OCR、已完成、候选待确认；OCR走共享gate，无必要不重跑旧资料。
5. 扫描残余病例常量/提示示例/固定数值，逐条判定通用格式还是案例规则；移出不适用生产默认，不删除真实依据。
6. 存量污染只读建立来源→采用事件→稿件关联，疑似数值相同不直接定罪；改正经新版本候选。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
PYTHONPATH=services/api:packages:.:tests:tests/protocol_v3:tests/protocol_v3/integration runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_dual_entry_unification.py tests/protocol_v3/test_source_identity_product.py tests/protocol_v3/integration/test_source_import_api.py -q
```
```sh
cd frontend && ./node_modules/.bin/vitest run src/features/medical-writing/MedicalWritingSynopsisProjectIntake.test.jsx src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.test.jsx --environment jsdom
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
确认F05输入事实路径、来源选择与模型能力；未验证实际调用明确标记。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
