# WP2 成组决定、恢复与局部重组
**依赖WP1；不引入新队列或通用事务平台。**

文件范围：medical_writing_full_draft.resolve_decision/build_descriptor/run_job/adopt；main.py writer；authoring_journey composite adoption；durable store和现有UoW/receipts；manuscript接收服务；前端决定卡。

步骤：
1. 盘点已有复合采纳和持久操作回执，选一个真实事务入口承载相关决定组。组内选项写typed values；目的/终点对应；不以循环两个单写称原子。
2. 幂等lookup位于同操作恢复的基线拒绝之前；新请求仍校验当前身份。记录确认已提交/待入队/入队已完成的可恢复结果，复用现有事件或操作表，不额外审批状态系统。
3. writer成功、enqueue失败：重试返回已确认事实并补续写；不让用户重选、不再执行同一次事实更新。unknown_outcome查实际回执，不自动换key新派。
4. 用依赖确定影响章；局部生成完成后在同一整稿manifest组合未变旧章与新章。引用原artifact与来源hash，明确原基线、继承理由和需重新确认的内容。不要全局revision变一次就废掉所有正常正文。
5. 接收工作稿前完整预校验所有目标；使用现有文档UoW原子保存/激活。若跨制品与DB，先写不可变候选、事务切当前指针，可恢复多余制品，不能报告失败却留下部分当前正文。
6. 修正前端poll观察预算耗尽将running显示生成失败：复用现有hook/locator，显示仍在运行或可恢复观察，不新派job、不只把轮数乘十。覆盖首次生成、决定后局部重生成、页面重开/切项目返回三个消费者。区分仍运行、暂不可查询、completed但/result读取失败；继续查询同job，不因busy=false回到重生成。refreshStudyConsistency失败不能将事实已提交写成“本次决定未写入”。用可控时间验收，不等57分钟或重跑模型。
7. 保留人工Word不动，生成后给明确候选更新；只更新受影响对象，冲突给差异和可恢复出口。

WP6验收：B03/B04/B05、A11/A12/A17/A25。故障注入覆盖事实提交后入队失败、入队回执丢失、重启、同key不同payload、两相关选项、第二章节冲突、无变化章节继承、用户人工改稿并存。必须用真实SQLite/UoW，不只mock Repo。失败能判断写入范围且不重复用户确认。
