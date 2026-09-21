# F09 执行包：真实文献插入、引用编号与文献表

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F04, F06。
覆盖需求：R3, R4；验收：A22。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
当前Office中的引用实体和交互；复用已有literature实体/库接口，第三方动态插件另列。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [frontend/src/features/medical-writing/MedicalWritingLiteraturePanel.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/MedicalWritingLiteraturePanel.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.jsx)
- [frontend/public/genoffice/bridge-shim.js](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/public/genoffice/bridge-shim.js)
- [services/api/app/protocol_workflow/api/manuscript_drafts.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/api/manuscript_drafts.py)
- [services/api/app/protocol_workflow/agent3/word_export_production.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/word_export_production.py)
- [plans/reference_interop_scope_20260919.md](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/reference_interop_scope_20260919.md)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 先读已有文献模块的数据/API/消费者，确定可复用实体；不要因为旧T16说明写已实现就跳过。
2. 形成稳定reference身份及真实来源书目元数据；用户能检索/选择/插入当前光标或目标对象引用，AI建议引用保持来源可核对。
3. 维护文内数字引用顺序、去重、删除引用与文献表联动；多处同引、新增前置引文、移段后重新排序都有规则。
4. 将实际引用对象及字段保存在Office版本，下载重开保留；识别已有未知第三方域并报告，不静默转成无身份文本。
5. 补必要UI和接口，不新建外部文献平台；EndNote/Zotero目标未选时只声明本系统基础能力。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
rg -n 'citation|reference|文献|引用' frontend/src/features/medical-writing/MedicalWritingLiteraturePanel.jsx services/api/app/protocol_workflow
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
新回归需绑定实际reference数据合同后命名，不能编造已有test路径；交真实插入操作录像/快照及DOCX。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
