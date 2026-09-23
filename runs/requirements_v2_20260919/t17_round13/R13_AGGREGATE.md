# T17 第十三轮聚合（2026-09-23 深夜 · 无损暂停点）

## 本轮验证成果（修复实战确认）
1. **竞品分诊层问题全部解决**：af87ee(COPD) confirmed 25/25（失败→重试→全成→人工确认全闭环）；903264(MS) review_ready 19/19；两个 partial_failed(18+1F/19+1F) 诚实落盘可重试。8fbcaca(effort) + 9c565fc(5xx回退) 实战生效。
2. **durable 冷恢复实战通过**：23:5x 同步重启后 4 个在途分诊 job 全部被新 worker 重新拾起继续跑，进度无损。
3. **版本门根因补记**：孤儿 vite 进程占 5186 端口导致指纹过期（tester1 R13 初派被拦）。修复=重启必须 kill 全部 vite + --strictPort + 重启后验证 /runtime-build.json 与 /api/runtime-readiness 的 build id 一致（本轮已这样做）。

## 四个新前沿（下一会话修复队列，按阻断面排序）
- **F-A fact-intake 确定性枚举校验失败**（tester4 P0-1，膝OA）：免疫原性相关性字段枚举校验必败 → "完成第一步"永久禁用。阶段=研究框架。疑似 AI 提议值不在枚举白名单且无自由输入出口。
- **F-B 语料翻译计划谱系硬失败**（tester1，COPD 走到语料层）：`document_plan_contract_source_missing_or_ambiguous`（writing_reference_translation_batch.py:2300/2381/2441），重试无法重建谱系。疑似中断的规划任务留下无谱系 item；修法=无谱系时允许重新规划而非硬失败。
- **F-C 分诊运行期冻结影响确认**（tester2 F-02）：分诊 in-flight（本地模型 19 批约 40 分钟）期间"完成第一步"的影响确认被"研究流水线当前处于 triaging"拒绝。需要真实等待态而非死路报错（或加速分诊）。
- **F-D grok/cursor 会话耐心 ~10 分钟**：omp 会话在长 AI 等待中提前收尾（EXIT=0 且报告终止于状态叙述）。续作提示必须写进 prompt 本身（本次误写进 log 文件模型看不到）。muse-spark/deepseek/gemini 无此问题。

## 其他记录
- tester1 P1-5：COPD 项目可导入特应性皮炎文献且无相关性警示（跨适应症文献警示缺失，连续两轮出现）。
- tester2 R13 完整报告（22KB）含 14 项 PASSED 明细——分诊抽屉/人工标记/单字段建议/文献库全部实测可用（0874ab3 的提示修复实战可见）。
- 会商审阅进程静默死亡（opencode-go/deepseek，日志 2.4KB 无输出）——下会话重派，材料合并 R12+R13。
- 测试窗口内两次同步重启（21:00 违规单侧、23:5x 合规双侧+验证）：F-C/F-B 部分成因可能是重启打断在途任务，下一轮测试窗口内零重启为纪律。

## 环境状态（交班即用）
- 5301 后端（PID 83876，含 9c565fc）+ 5186 前端（83877）指纹一致 api-8a34dc34；MTPLX 8002 存活（负载下 507 由回退吸收）；OmniRoute 20128 存活。
- R13 项目仍在库（bd314e 已 stale；952c0f 分诊 12/23 进行中——下会话开工前照例清理）。
