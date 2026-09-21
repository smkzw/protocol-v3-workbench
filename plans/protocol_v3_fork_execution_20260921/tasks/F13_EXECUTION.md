# F13 执行包：可重现交付、经验复盘与激活决策

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F12。
覆盖需求：R1, R2, R3, R4, R5；验收：A23。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
交付文档/版本清单/回退方案；未经授权不push、生产激活、真实项目切换或历史清理。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md)
- [plans/protocol_v3_fork_execution_20260921](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_fork_execution_20260921)
- [runs/requirements_v2_20260919](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 汇总来源版本、代码hash、依赖版本、真实model/effort、测试与文档工件、通过/未验收/范围排除。
2. 复盘长期停滞根因和本轮有效方法，只保留可复用结论，不重复制备第二记忆库。
3. 写本地启动与隔离数据配置说明：无明文凭证、端口归属可核对、服务使用匹配build。
4. 准备生产/真实项目cutover的具体变更清单、备份/回退和演练证据；此时才问用户最终激活决定。
5. 用户要求暂停才执行无损暂停；保留所有immutable记录、dirty与会话/日志，不执行旧cleanup命令。
6. 产品Goal完成必须满足真实交付定义；资料包或阶段报告完成只关闭对应文档任务。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 交付资料与F12已取得证据对应；产品变化或证据漂移明确列出，不把资料完整等同产品完成。

## 可复用检查命令
以下交付资料的只读检查在F13执行，不重新运行产品测试。只有产品代码变化或验收证据漂移才回到F12的受影响范围。
```sh
git diff --check
```
```sh
python3 plans/protocol_v3_fork_execution_20260921/validate_package.py
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
达到用户可审阅激活点再问；否则按当前授权持续修复，不能普通阶段停下。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
