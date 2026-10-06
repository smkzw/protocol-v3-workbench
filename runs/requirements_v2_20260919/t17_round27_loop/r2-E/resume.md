# R2-E 续跑指令（前一个进程被外力中断，不是你的失误）

你仍是 **R2-E 号**外部测试者（注册及QA视角）。你上一个进程在等待全文初稿生成期间被外部中断，现场原封未动。现在换了个新会话的你接手收尾。

## 接手三步（按顺序）

1. **先完整读一遍任务书**：`/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round27_loop/r2-E/prompt.md`——它仍然是你的最高约束（铁律、红线、Q1–Q10、报告格式、收尾纪律全部不变）。
2. **再读你自己留下的现场记录**（同一目录）：`notes.md`、`qa-checkpoint.md`、`writing-checkpoint.md`。这些是你亲手写下的进度与证据，接手后以此为准，**不得改写已记录的结论、不得伪造没做过的事**。
3. **重挂你的浏览器任务空间**：任务空间 46，名称 **loop27-r2-e**（ego-browser，先读 `/Users/smkzw/.agents/skills/ego-browser/SKILL.md`；skill 支持按 spaceId 恢复）。挂上后先看屏幕现状再动手，别凭记录瞎点。

## 中断时你停在哪（writing-checkpoint.md 末尾的状态）

- 已进入写作平台，全文初稿正式请求发生在本地 2026-10-05 00:19:10（bg_4，最长 30 分钟等待）。中断发生在等待期间。
- 未完成：初稿确认、三处实质改稿、导出 Word、Q7/Q8/Q9 导出件体检、report.md、收尾。

## 接下来要做完的（都按任务书原文标准执行）

1. 核实初稿状态：若已生成，逐章看一眼成稿状态并继续；若仍无结果，按任务书等待规则继续等（界面有推进迹象可宽限到 45 分钟，数字如实记）。
2. 对初稿做**至少 3 处实质修改**并保存成功（记改了哪三处、保存后还在不在）。
3. 走**导出 Word**：能导正式 Word 就导正式的；若"正式 Word"仍被逐章冻结挡住，按界面能走的最远路径导出（预览导出也算），**把逐章冻结这条路亲手探一下**（能不能批量冻结、还是必须逐章点，点几个实测几个，如实计数——这正是 Q10 的核心素材）。确认文件真实生成后**复制归档**为：
   `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round27_loop/r2-E/export.docx`
4. 对归档的 export.docx 做 **Q7（ICH-M4 章节齐备清点）/ Q8（格式合规细节）/ Q9（法规要点抽查）**，逐条给结论+截图。
5. 把 Q10 人工负担量统计收全（你 checkpoints 里已数了大半：导入确认/建议采用/例外逐项/竞品整体确认/复杂计划下拉……把没到达的环节补上或如实标 NOT_RUN）。
6. 写报告：`/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round27_loop/r2-E/report.md`，按任务书第10条的九项必含结构写全（含中断续跑这件事本身也如实写一笔），末尾单独一行 `EXIT=OK`。
7. 收尾纪律照任务书第11条执行：报告写全 → `task.finish({ keep: [] })` 关你的空间 → 清临时缓存 → 报告里写 cleaned=true/false。

## 依旧不变的红线（再念一遍）

只经浏览器操作；不碰 8001/8002、不碰后端 5301、不碰医学监查与共享运行时；不动别人的项目；只写你自己这个 r2-E 目录；反拟合清单与等待规则照旧。
