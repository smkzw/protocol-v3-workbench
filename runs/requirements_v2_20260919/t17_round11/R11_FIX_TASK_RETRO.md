# T17 第十一轮 · 修复批任务记录与复盘（2026-09-23）

## 本批任务范围
LOOP = 测试 → QC → 会商 → 修复提交 → 清理 → 重派。本批承接 R11 四测试者报告（tester1 COPD / tester2 MS / tester3 MDD / tester4 膝OA），目标是修掉两位测试者共同命中的两条 P0 并落 GitHub。

## 已完成（按时间序）
1. **R11 聚合归档**（5d7a239 → 已在 07b6164 收尾）：4 份报告 + R11_AGGREGATE.md 落 runs/t17_round11/。
2. **P0-A 根因链完整闭合**（这是本批最有价值的成果）：
   - 表象：tester1 分诊进度 5/25 → 24/25 → **回退到 5/25 并永久冻结**，全按钮 disabled；tester3"近完成时失败回退"。
   - 证据（只读查询 live DB + 后端日志）：父 research_pipeline durable job（mwjob_ebef05ffda）attempt 2 failed"分诊超时：子任务已完成但分诊结果未达到可审核状态"；子 triage job 已 completed/partial_failed；**run 记录 created_at=07:34:01 = 父 job attempt 2 重放瞬间**，4 个确定性 chunk provenance 时间戳同秒——run 被整体重建覆盖，21 个 AI chunk 回到 attempt=0。
   - 因果：子 job 完成时父层读 run → 终态未持久化读到"queued"假象 → 判超时失败 → durable 重试重放 execute_stages → **create_run 用初始态覆盖同一 run_id 的既有进度** → 复用已终态的子 job 永不再执行 → 永久冻结。tester1 看到的"24→5 回退"正是覆盖瞬间。
3. **P0-A 修复**（2c0f52b，已推送）：
   - `create_run` 幂等防覆盖：确定性 run_id 已存在时复用既有 run，绝不重置进度。
   - durable executor finalize 后**无条件**持久化 run 终态（原先只在 attribution 缺失分支才落盘）。
   - 新增回归测试（重放 create_run 不得回退 partial_failed）；重写过时校验门测试（b14a56a 有意改为连续排水，旧测试自基线未更新且先以桩签名错误存在）。
   - 验证：triage 三套件 + 流水线三套件 105 passed；triage 全表面 563 passed + 42 subtests。
4. **P0-B 根因闭合 + 修复**（0bc92fb，已推送）：
   - 反转认知：入口A"解析失败"**不是文档内容问题**，是 AI 执行策略拒绝——V04 死端点测试把 MTPLX profile 留在 127.0.0.1:9，intake 冻结了坏路由，策略白名单要求 8002 → chunk 0 必败。配置已在此前 e584515 修复。
   - 产品缺陷仍在：UI 只显示通用"解析失败"+"继续处理"，resume 返回 200 但再撞同一堵墙 = 无反馈死循环；且路由变更后 resume 被冻结身份校验挡死，唯一出路是重新导入。
   - 修复：前端把路由/策略类失败翻译成大白话（"检查 AI 设置后重新选择文件重新导入"），该类失败隐藏"继续处理"按钮；瞬时失败保留 resume。新增 2 个渲染测试。
   - 验证：文件套件 7/7；前端全量 113/113。
5. **环境核对**：live 后端 5301 无 --reload，**仍在跑旧代码**；前端 5186 同理。下一轮开跑前必须重启后端 + 重建前端。

## 未完成（明确留待下窗口）
- **P1 批未动**：分诊人工标记三按钮 disabled 无原因（tester1）；文献手动确认与 DOI 输入耦合无说明（tester1）；文献卡卷期页疑似被 DOI 解析覆盖（tester1）；"继续处理"死路的其他变体未逐一排查。
- **第十二轮未派**：未删旧项目、未重派测试者（纪律：修复需先经 UI 实测验证，故本轮修复全部只过了单测/组件测试关）。
- **docx QC / 会商审阅**：R11 无任何测试者产出可导出初稿（全部被 P0 拦截在分诊/框架阶段），无 docx 可 QC，会商暂无素材。
- **tester4 静默死亡**未再追（omp 进程消失，日志仅 90B，无 EXIT 标记；重派时观察即可）。

## 踩坑与教训（复盘）
1. **"测试通过"曾经是假阴性**：既有测试 `test_failed_ai_chunk_is_not_mislabeled...` 断言 run==PARTIAL_FAILED 且通过，因为它恰好走了 attribution 缺失分支（该分支顺手落盘）。生产路径 provider 已设值 → 分支不触发 → 终态丢失。教训：一个断言通过的测试可能只因走了旁路；写测试要对"哪条代码路径被走到"有意识。
2. **确定性 run_id + 幂等复用 job 是把双刃剑**：防重设计（同输入同 run_id、business_key 复用 job）在"父层重试"场景下变成了覆盖+永不再执行的组合拳。任何"幂等"设计都要回答：**重放时已提交的进度哪去了？**
3. **配置漂移跨轮传播**：上一轮 V04 死端点测试把 profile 留在端口 9，直接造成本轮 tester1/3 的分诊回退和 tester1 的入口A失败。教训：每轮测试开跑前应核对冻结路由快照的 base_url 是当前可用值（本轮已在聚合里记录，未固化为 checklist 条目——下轮补）。
4. **两层看同一数据，一层必须落盘终态**：父 pipeline 依赖读 run 记录做对账，executor 却把终态当内存态处理。跨层契约的字段（status）必须显式持久化，不能依赖"最后的中间写入恰好带着它"。
5. **排查路径上浪费的时间**：先怀疑 MTPLX 空响应 fallback、再怀疑 chunk 持久化缺失，最后靠 chunk provenance 时间戳（created_at=重建瞬间）才定案。教训：**时间戳先于代码路径**——先确认"这条记录是谁、何时写的"，再读代码。

## 下一步（按优先级）
1. 重启 5301 后端 + 重建 5186 前端，加载 2c0f52b/0bc92fb。
2. 用 Ego 浏览器做一轮**修复验证迷你测试**（COPD 从零开始链：建项目 → 竞品检索 → 分诊跑完/部分失败可恢复 → 框架解锁；入口A重导一份真摘要文件验证新文案与按钮）。
3. P1 批修复（标记按钮原因提示 / 文献 DOI 耦合说明 / 卷期页来源）。
4. 删旧项目（备份后，保留出厂 demo）→ 重派第十二轮（四场景 lineup 不变）。
5. 会商审阅与 docx QC 等第十二轮产出初稿后再启动。

---

## 追记（同日 21:0x）：R12 已派发
1. P1 批三项已修并推送（0874ab3）：分诊标记/锁定按钮 disabled 原因提示；文献手动确认与上方来源输入的耦合说明+步骤提示；DOI 解析记录与手动题名冲突时不再把他刊卷期页混入确认卡（后端 + 2 回归测试）。
2. 环境已重启载入全部修复：后端 5301（PID 变更，含 P1 文献修复）、前端 5186（vite 重启）。四服务 200。
3. 旧项目已清理：5 个测试项目（银屑病/MS/MDD/COPD/膝OA）外科手术删除，三库备份 .pre-cleanup-20260923_204421，保留 9 个出厂 demo 种子；durable jobs、writing_reference、审计 jsonl 全部保留为证据。
4. 第十二轮已按锁定编队派发（r12 prompt=r11 场景复用+轮次/截图目录更新）：
   - tester1 COPD/入口A = opencode-go/muse-spark-1.3-contributor (max)
   - tester2 MS/入口B = google-antigravity/gemini-3.8-flash (high)
   - tester3 MDD/盲测 = cursor/cursor-grok-4.6 (high)（首派遭 harness 空消息，杀掉重派后正常）
   - tester4 膝OA/入口B = opencode-go/deepseek-v4.1-flash (max)
   日志 /tmp/t17_r12_testerN_report.md，尾部 EXIT= 标记。
5. 坑：bash heredoc 未加引号导致 $() 被外层 shell 提前展开，首轮四进程拿到空 prompt 即退——重派修复；grok 首消息被 harness 丢弃一次，重派自愈。两坑都已记录。
