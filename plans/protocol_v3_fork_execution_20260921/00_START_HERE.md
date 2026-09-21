# Protocol v3：fork 连续实施入口
日期：2026-09-21。接手负责人模型：**gpt-5.6-sol，reasoning effort=medium**。这仅指定 fork 主执行模型，不改产品模型或工程会商路由。

## 这是什么
本包是用户要求的新一轮完整实施规格与交接资料，覆盖当前剩余产品建设、执行纪律及验收。它不是“全产品已完成”的证明。当前父任务转为交付资料包；已启动的有界设计卡执行结果以 [移交状态](evidence/HANDOVER_STATUS.md) 为准。接手前必须读它，不重复派发。

唯一实施区：[工作区](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313)。Git main HEAD 的记录在 SOURCE_STATE.json；**HEAD 加本地未提交改动才是本轮实际代码**。不要 reset/pull 覆盖。GitHub 同步不包括本轮尚未提交成果。

## 最短完整启动路径
1. 读最新 [/Users/smkzw/.codex/AGENTS.md](/Users/smkzw/.codex/AGENTS.md)、适用项目/前端AGENTS；当前用户命令高于历史暂停、旧方法学与旧模型表。
2. 读 [移交状态](evidence/HANDOVER_STATUS.md)、[当前状态](01_STATE_AND_HISTORY.md)、[权威索引](02_AUTHORITY_AND_MATERIALS.md)。核对当前目录、HEAD、dirty、运行句柄、源文件哈希。
3. 读 [PRD](03_PRD.md)、[架构](04_ARCHITECTURE_DESIGN.md)、[Plan](05_IMPLEMENTATION_PLAN.md)、[执行规范](06_EXECUTION_RULES.md)、[构建节奏约束](BUILD_DISCIPLINE.md)。
4. 读 [验收总包](07_ACCEPTANCE_PLAN.md)、[风险与选择](09_DECISIONS_AND_RISKS.md)，从 [F00执行包](tasks/F00_EXECUTION.md) 开始。任务定义见 TASK_INDEX.json，唯一动态状态留在 Trellis，不改历史 tasks.json。
5. 将 [fork启动指令](08_FORK_PROMPT.txt) 发给 fork。原生旧Goal全文见 [原文](evidence/ORIGINAL_GOAL.txt)，新目标见 [GOAL_PROMPT](GOAL_PROMPT.txt)。新提示覆盖旧3R.4起点、单流/简化编辑器和草稿零缺口假设。
6. 当前任务实现后直接选择实现依赖已满足的下一包，运行验收集中F12；普通阶段不结束回合等用户说“继续”。

## fork 与工作树
推荐手动 fork 到**同一目录**，父任务在本包完成后不继续写代码，fork成为唯一owner。这样可保留尚未提交源码。若选择新worktree，必须先按 SOURCE_STATE.json 搬入并核对本轮变更；不能假定fork自动复制dirty。本包不自动创建fork、不启动新模型、不改用户模型配置。
- SOURCE_STATE.json：Git与代码状态快照；不含秘密运行配置内容。
- SOURCE_MAP.csv：当前模块/组件/测试入口与哈希，供定向加载，不要求每轮全量阅读。
- AUTHORITY_MANIFEST.json：权威原件位置/哈希/用途。
- source_overlay.tar.gz：仅获准代码范围的本轮未提交源码；不是完整仓库、运行数据库或凭证备份。使用前先比较目标工作树，逐文件整合，禁止盲覆盖。
- PACKAGE_MANIFEST.json：本包交付时文件校验表；启动前运行 `python3 validate_package.py`。

## 不要重复
不返回7月r42/9月3R.4或重新初始化Trellis；不重跑旧分诊/下载/OCR/翻译及五失败项；不重建已完成图节点；不再次把第十轮撤销的TED/IgAN“串染”误报当真；不清空数据库换取绿灯；不把模型输出视为用户批准。

## 交付审阅
见 [独立审阅与最终裁决](10_REVIEW_AND_RELEASE.md)。独立审阅提出的5项资料/任务定义问题已最小修订；不表示待实施代码问题已修复。新包不要求每项F完成一次测试，严格按BUILD_DISCIPLINE连续构建。
