# F00 执行包：接管源码、权威、运行与Trellis

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：无。
覆盖需求：R1, R2, R3, R4, R5；验收：A01。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
只读接管；仅更新当前Trellis记录与本轮新证据，不改产品源码。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md)
- [AGENTS.md](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/AGENTS.md)
- [frontend/AGENTS.md](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/AGENTS.md)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 读00_START_HERE、HANDOVER_STATUS、SOURCE_STATE、原Goal/新Goal；核对实际模型gpt-5.6-sol:medium，不改产品路由。
2. 核对pwd、git status/HEAD、source_overlay与每个dirty代码hash；有不同先判断后续改动，不reset。
3. 父任务设计卡worker已terminal，读取原报告、actual identity和实际diff，不重新派发。若接手发现新的在途写入，先按实际句柄对账；禁止同范围第二个worker。
4. 只读确认5186/5285、8910及当前隔离端口、实际runtime/DB路径；不连接共享DB执行写动作。
5. 将本包F任务索引加入现有Trellis任务；保留旧暂停历史并注明9月21日恢复。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
以下接管所需只读身份、源码、资料包和任务状态检查立即执行，不属于产品运行测试，不推迟到F12。其余产品测试仍遵守BUILD_DISCIPLINE。
```sh
git status --short
```
```sh
git rev-parse HEAD
```
```sh
python3 plans/protocol_v3_fork_execution_20260921/validate_package.py
```
```sh
python3 .trellis/scripts/task.py current
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
完成接管后继续F01，F03/F04/F06可在互不占用文件时安排有界并行。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
