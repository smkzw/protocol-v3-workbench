# F01 执行包：设计卡真实选项与原确认意图恢复

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F00。
覆盖需求：R2, R3, R5；验收：A05, A11, A12, V06。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
接收已结束的mw_r11_design_choices_20260921（实际最终pi/openai-codex/gpt-5.6-luna:max，worker报告3项组件测试通过，未完成真实后端验收）；其后仅设计卡与既有采用合同必要修复。不要重派原worker。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.jsx)
- [frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.css](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.css)
- [frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.test.jsx](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.test.jsx)
- [services/api/app/protocol_workflow/agent2/design_adoption.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent2/design_adoption.py)
- [services/api/app/protocol_workflow/api/design.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/api/design.py)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 先读worker terminal报告和diff；本轮owner已加入主要终点红tag、确认后保留内容，不回退。
2. 多primary objective展示为可选控件，首个推荐默认预选但不自动确认；chosen index进入实际adopt payload。
3. 从已有localStorage intent恢复原operation/payload；网络未知不能创建新operation重新确认；终态拒绝可按真实合同转下一动作。
4. 已确认显示真正选择的内容；旧记录缺选择信息明确未知，不能伪装为第0项。
5. actorId/runId缺失时禁用并说明，避免点得动但无响应；上游变更只重开受影响卡。
6. 检查事实revision后继不被历史回执倒退；在F12集中独立核对选择→保存关系；不作为进入F02的前置测试门。

## 已定位、必须修复的真实断缝
- 后端 `_objectives_writer` 仍写入全部候选；`prepare_design_card_adoption` 校验selections却不给writer使用，decision也只有整卡option哈希。必须使最终事实/可恢复决策精确对应用户选择；localStorage显示第二项不能证明数据库已选第二项。选择身份生成、adopt前回执查询与recover必须使用一致规则；保留旧operation与旧回执的可恢复解释，不重写历史。无法证明旧选择时显示未知，不推断第0项；无需新建身份框架。
- 前端非劣效卡当前生成 `non_inferiority_margin_confirmed`，后端明确要求 `ni_margin_confirmed`。对齐真实合同，不能只测前端mock。
- `_sample_size_writer`未落 `planned_n`，需追踪当前canonical样本量路径及后续正文消费者；确认展示的数值不能在生成时丢失。存在独立推导时必须明确关联，而非机械新增冗余字段。
- 恢复404只代表未找到回执，不足以确认未执行；当前按钮可能永久“再次核对”。复用现有operation状态合同区分已提交/仍在运行/明确未执行，并给出真实可继续动作；不新造第二套队列或状态仓库。
- `acceptReceipt` 的最低revision判断仍可能使旧回执更新当前state为较旧revision。按实际最新事实对账，不用旧回执倒退研究。

- 核对后端是否真正要求主要终点明确确认；当前校验中的and分支可能放过有文本但确认标记缺失/false的请求。条件卡适用性未知不得仅因proposal存在就视为可采用，沿既有事实/确认链解决；其他层是否已阻止错误落盘仍需查清，不把源码疑点写成已发生事件。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
cd frontend && ./node_modules/.bin/vitest run src/features/medical-writing/protocol-workbench/DesignElementsCards.test.jsx --environment jsdom
```
历史审计定位参考：`audit-execution --task-id mw_r11_design_choices_20260921 --task-type E04` 已退出1，原因见HANDOVER_STATUS。无需重跑或要求它退出0，不修写历史以造通过；接管检查已有终态、实际身份与产物。新派发按新合同审计。
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
记录owner接受范围；若worker仅部分完成写出剩余，不标产品完成。继续F02。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
