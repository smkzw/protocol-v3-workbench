# F08 执行包：真实Word对象的局部AI修订与目标重生成

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F05, F07。
覆盖需求：R3, R4；验收：A13, A14, A15, A16, A17。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
复用object_revision与Office映射；自然语言编辑只在授权目标内。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [services/api/app/protocol_workflow/agent3/object_revision.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/object_revision.py)
- [services/api/app/protocol_workflow/application/manuscript_documents.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/application/manuscript_documents.py)
- [services/api/app/protocol_workflow/api/manuscript_drafts.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/api/manuscript_drafts.py)
- [frontend/src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.jsx)
- [frontend/public/genoffice/bridge-shim.js](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/public/genoffice/bridge-shim.js)
- [tests/protocol_v3/integration/test_object_revision_scope_and_recovery.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3/integration/test_object_revision_scope_and_recovery.py)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 核对现有replace_object/patch_object是否仅作用语义块；标明真实Office未接线处。
2. 输入目标锚点/选区、base snapshot/hash、预期目标内容、operation和自然语言；目标不明时让用户少量点选，不猜整稿。
3. AI返回候选diff或授权范围内结果，保留旧版本和撤销；仅改一格时其他单元格和正文对象保持。
4. 准备期间用户继续编辑目标：检测旧基线，不强制应用；可重算/展示差异，非目标新编辑不被丢掉。
5. 显式重生成摘要/SOA只更新用户要求对象，不自动同步所有章节；确有关键事实变化交F07与对应人审。
6. 实际Office字段、表格合并、脚注等通过serializer保留，无法支持的对象说明并保留原件。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
PYTHONPATH=services/api:packages:.:tests:tests/protocol_v3:tests/protocol_v3/integration runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/integration/test_object_revision_scope_and_recovery.py -q
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
把实际修订前后DOCX、对象diff、模型receipt交验收，不只交后端模拟回执。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
