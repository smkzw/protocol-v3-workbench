# F06 执行包：当前Office稿、候选、未保存输入与历史

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F00。
覆盖需求：R3, R4；验收：A09, A10, A11, A12, A13, A14, A20, A21, A24, V05, V08。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
真实Office宿主/bridge、现有快照API与持久层；不恢复简化编辑器作为主库。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [frontend/src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.jsx)
- [frontend/public/genoffice/bridge-shim.js](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/public/genoffice/bridge-shim.js)
- [frontend/src/features/medical-writing/protocol-workbench/ManuscriptWorkspace.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/ManuscriptWorkspace.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs)
- [services/api/app/protocol_workflow/application/manuscript_documents.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/application/manuscript_documents.py)
- [services/api/app/protocol_workflow/api/manuscript_drafts.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/api/manuscript_drafts.py)
- [tests/protocol_v3/integration/test_office_working_copy_closure.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3/integration/test_office_working_copy_closure.py)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 复用本轮快照/历史/专注/失败备份/导航修复，核对最新源码和实际隔离运行版本。
2. 验证currentOffice→打开→保存回执→下载→重开始终同源；无snapshot才初始semantic导出，读取失败不静默回退。
3. 新候选与当前Word共存，用户可继续旧Word或明确采用候选；历史可下载，恢复覆盖如新增必须显式且保留旧版。
4. 真实IME/表格编辑/未提交输入，在关闭、切项目、刷新、断网和回执丢失下不误标clean；旧简化编辑缓冲保留并提供必要可读取恢复方式。
5. 快照save与metadata同事务，首次base0双窗口只一者成功；n回执不得清n+1输入，冲突给最新版本与本次备份。
6. 保存不被科学分析失败阻挡；未知对象/parts不静默删除；研究基线hash与文档hash不同。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
cd frontend && ./node_modules/.bin/vitest run src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.test.jsx src/features/medical-writing/protocol-workbench/ManuscriptWorkspace.test.jsx --environment jsdom
```
```sh
node --test frontend/src/features/medical-writing/protocol-workbench/office/bridge-shim.test.mjs
```
```sh
PYTHONPATH=services/api:packages:.:tests:tests/protocol_v3:tests/protocol_v3/integration runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/integration/test_office_working_copy_closure.py -q
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
冻结快照回执/读取合同交F07；原生编辑/完整Word接受仍独立记录。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
