# F11 执行包：桌面宽屏、信息密度与全状态交互收口

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F01, F02, F05, F06, F07, F08, F09。
覆盖需求：R2, R3, R5；验收：V01, V02, V03, V04, V05, V06, V07, V08, A21, A24。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
仅医学写作视觉/交互；保留产品能力，不动医学监查或其他模块布局。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [frontend/src/features/medical-writing/protocol-workbench/ProtocolWritingDesk.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/ProtocolWritingDesk.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.css](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.css)
- [frontend/src/features/medical-writing/protocol-workbench/ManuscriptWorkspace.css](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/ManuscriptWorkspace.css)
- [frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.css](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.css)
- [frontend/src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.css](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.css)
- [frontend/src/features/medical-writing/protocol-workbench/ResearchInformationCard.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/ResearchInformationCard.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/RegimenProposalCard.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/RegimenProposalCard.jsx)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 读康哲design技能及本PRD；复用当前双栏，不回到maxwidth1100单流；按真实长研究信息设计布局，运行验收集中F12。
2. 对所有等待/空/缺信息/已确认/失败/冲突/历史/新候选状态列screen inventory。
3. 压缩重复标题、嵌套卡片padding和说明横幅；AI信息分需确认/推荐依据/下一步，关键事项不能藏折叠里。
4. 保持字体14/12底线，主文稿按纸张可读缩放，避免页面整体横滚；工具带必要时局部滚动/折叠。
5. 实现1440/1920/2560响应布局及focus同iframe、导航/IME/历史保持；F12使用ego逐项操作、截图并取得computed dimensions/style。
6. 优化重复确认而不删科学判断；F12完整记录点击/必填自由文本数，手机只做灾难性遮挡/不可达检查。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
cd frontend && npm run build
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
任何视觉/交互修改引发实际产品缺陷回原责任包修复，完成后再F12，不为单屏截图提前验收。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
