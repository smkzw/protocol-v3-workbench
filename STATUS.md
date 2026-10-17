# STATUS — protocol-v3-workbench（mw_reboot_20261017 基线）

仓库可见性：待用户后续指令。

## 当前阶段：M0 止血与基线

| 工作包 | 状态 | 备注 |
|---|---|---|
| M0-1 敏感资料止血 | 完成 | runs/ 等移出 git 跟踪（.gitignore + untrack，本地保留 13G）；新提交不再带入运行产物 |
| M0-2 停用 dwfrun LOOP | 完成 | dwfrun-a0f22d14 已停止（2026-10-17）；不再启动多测试者 LOOP |
| M0-3 三个 dev 项目全文基线 | A/B完成，C在跑 | A=覆盖率50%/619min；B=覆盖率22.2%/93.6min |
| M0-4 全量测试状态记录 | 完成 | 失败族已记录（见fulltest_result.txt） |
| M0-5 STATUS/DECISIONS 建立 | 完成 | 本文件 + DECISIONS.md |
| M4 决定卡与设计步骤 | 样本量计算器完成 | 四设计33测试绿；决定卡/前端未开始 |
| M1 eval 基建 | 骨架+fixture抽取完成 | 3 fixture（129/141/160节）落盘runtime；dev/held-out划分与基线全量出分待做 | WP-M1-EVAL合入：对齐/指标/报告链路，MY009产物实测覆盖率38.6%；泄漏与事实冲突待补 |
| M2 竞品语料（轨道B） | 检索分类管线完成 | TopK用户确认/StyleKit/ClauseBank生成待做；专病函数替换未动（B05在M2后续包） | schema 定稿后开工 |
| M3 写作引擎（轨道C） | lint+SectionCard生成器骨架完成 | 74卡(D26/C39/N9)+needs_review37；lint抓旧提示4类违规；逐节生成主路径未动（待M1度量+M2语料） |

## 已失效的历史机制（不再执行）

多模型会商路由、多测试者无上限 LOOP、自检硬门/判绿口径（含"≥3章即绿"）、107 章逐章冻结、durable 会商派发。详见 plans/mw_reboot_20261017/00_START_HERE.md。
