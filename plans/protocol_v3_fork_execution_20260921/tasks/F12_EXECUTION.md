# F12 执行包：独立跨研究端到端、医学与Word验收

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F03, F04, F05, F07, F08, F09, F10, F11。
覆盖需求：R1, R2, R3, R4, R5；验收：A01, A02, A03, A04, A05, A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A16, A17, A18, A19, A20, A21, A22, A23, A24, A25, A26, V01, V02, V03, V04, V05, V06, V07, V08。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
冻结产品的完整独立验收；只在隔离合成项目运行，repair则解冻具体范围并重新验证。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [reviews/protocol-v3-requirements-v2/ACCEPTANCE.md](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/protocol-v3-requirements-v2/ACCEPTANCE.md)
- [plans/t17_multitester_e2e_plan_20260919.md](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/t17_multitester_e2e_plan_20260919.md)
- [frontend/tests/protocol_v3_test_inventory.mjs](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/tests/protocol_v3_test_inventory.mjs)
- [tests/protocol_v3](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3)
- [runs/requirements_v2_20260919/t17_round11](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round11)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 冻结source hashes/运行build/模板/数据；以本包A/V矩阵建立独立预期，旧四测试者编队不硬套。
2. 指定两个差异研究和一个盲测；每例独立产物目录与project/study/run/hash，杜绝旧tmp glob误取。
3. 依次跑源码/必要全回归、真实HTTP/SQLite、ego用户旅程、实际产品模型、原生Word；模型按批准路线，无随意fallback。
4. 从资深医学作者视角逐章检查实质内容、源证据、数值复算、跨章关系和缺口处置；真实科学判断独立会商，不用单元测试代替。
5. 故障矩阵验证保存/恢复/并发/模型失败/分析失败/导航输入；未运行明确列出。
6. 汇总P0/P1/P2问题按可复现原因回责任包，修复后重验影响范围；原失败工件保留。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 按34项场景保存实际分层验收证据、未运行范围与owner接受结论；此任务本身执行集中验收。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
PYTHONPATH=services/api:packages:.:tests:tests/protocol_v3:tests/protocol_v3/integration runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3 -q
```
```sh
cd frontend && npm run test:inventory
```
```sh
cd frontend && npm run test:unit
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
只有产品必做范围真实闭合才进入F13；无法完成的科学决定交用户具体问题，其他独立项继续。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
