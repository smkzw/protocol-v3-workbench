# F03 执行包：整稿与设计图的真实可恢复运行

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F00。
覆盖需求：R2, R3；验收：A11, A12, A25, V04。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
已有恢复修复验证及剩余故障分类；runtime/graph共享变更须检查全部消费者。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [services/api/app/protocol_workflow/agent3/coordinator.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/coordinator.py)
- [services/api/app/protocol_workflow/agent3/manuscript_coordinator.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/manuscript_coordinator.py)
- [services/api/app/protocol_workflow/agent3/subgraph.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/subgraph.py)
- [services/api/app/protocol_workflow/graph/runtime.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/graph/runtime.py)
- [services/api/app/protocol_workflow/runtime/proposal_correction.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/proposal_correction.py)
- [services/api/app/protocol_workflow/runtime/reservations.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/reservations.py)
- [services/api/app/protocol_workflow/api/manuscript_drafts.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/api/manuscript_drafts.py)
- [frontend/src/features/medical-writing/protocol-workbench/ManuscriptWorkspace.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/ManuscriptWorkspace.jsx)
- [tests/protocol_v3/test_manuscript_recovery.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3/test_manuscript_recovery.py)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 读本轮worker/fresh会商/owner F1修复，复用有效结果，不重实现resume。
2. 明确running/live claim、unknown需对账、已确认失败可重试、已完成不可重跑；两个总attempt的当前合同与旧图兼容保持可解释。
3. 确认recover/read无派发，显式resume复用原图；一个不可重试章不阻挡其余可执行章。
4. 纠错输入去重复证据、保留原任务约束与具体错误码/定位；共享消费者只删真重复字段，不截断为不可恢复片段。
5. 实现重启/断回执、首轮/纠错派发、同run恢复所需闭环；F12在隔离复制状态或合成故障中取得运行证据，不直接修改第十轮现场immutable状态。
6. 错误分类保留足够定位，不记凭证；timeout是实际机制证据，不能把socket timeout宣称全任务绝对hardwall。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
PYTHONPATH=services/api:packages:.:tests:tests/protocol_v3:tests/protocol_v3/integration runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_manuscript_recovery.py tests/protocol_v3/test_graph_runtime.py tests/protocol_v3/test_chapter_product_factory.py -q
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
完成实现与源码核查后继续依赖已实现的任务。HTTP及真实模型恢复案例集中到F12按先确定性后模型的顺序执行；不得宣称第十轮所有真实失败已修复。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
