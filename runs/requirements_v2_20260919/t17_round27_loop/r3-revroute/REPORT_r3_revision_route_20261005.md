# R27 第3轮（20261005）· 医学修订路由验证报告（r3-revroute）

- 测试者角色：第3轮医学修订路由验证员（UI黑盒；sqlite3只读核对路由）
- 时间：2026-10-05 19:21 – 20:05 机器本地（UTC 17:21 – 18:05；DB/网关时间戳为UTC）
- 环境：前端 http://127.0.0.1:5186（代理5301）；后端5301 PID 61866（2026-10-05 17:58本地启动；ai_task_runner.py 当日16:09有修订批次改动并已随重启生效——本轮实测即其结果）。
- 本报告与9/29旧轮同名报告并存，旧文件未删；r2轮（今日下午）的失败报告见 r2-revroute/REPORT_r2_revision_route_20261005.md。

## 任务执行路径（状态推进全部经浏览器完成）

1. 项目总看板下拉选择 **R26MW-SGC2101（口服sGC激动剂）· 慢性心力衰竭（HFrEF）· II期 · MW-II-064699A9**（proj_user_1fb1fb310f86）→ 医学写作：工作副本v2直接打开，无阻断。
2. 「全屏编辑当前表格结构与附注」→ 点选 **第6行/第2列「研究药物」值单元格**（mwcell_greenfield_c99018d9a78fc455_5_value，现值"R26MW-SGC2101（口服sGC激动剂）"）——**第三种任务视角：药名表述规范+跨栏剂型一致性+sGC术语括注**（r1=方案标题语序、r2=适应症术语规范，均不同）。
3. 修订意图=改写；用户指令226字（与方案标题栏"片"剂型一致、sGC括注中英文全称、不得新增规格/剂量/频次，payload逐字核对一致）→ 提交AI修订（17:24:18Z）。提交按钮本轮一次点击即注册（r2轮首次点击未注册未再现）。
4. UI进度「处理中 正在调用综合AI 40%」→ 17:54:33Z **完成：4个候选（推荐+精炼+结构重排+保守，均待处置）**，attempt 1/3 单次成功，全程30分15秒。浏览器tab在本测试者等待期间再次被外部清理一次（今日累计第3次，环境观察），重进平台后正常查看候选。

## ③ 路由核对结论（sqlite3只读，证据 1005r3_route_verification_sql.txt）

- durable job：`mwjob_77c0fb773768dc5a1851e3b5`（section_ai_candidate，**completed 1/3**，17:24:18→17:54:33Z）。
- `payload.generation_context.descriptor.ai_policy.base_url` = **https://ollama.com/v1**（host=https://ollama.com，`/v1`为R5轮裁定端点后缀）；route_profile_id=independent_ai__ollama_cloud_dsv41；provider=ollama-cloud；model=deepseek-v4.1-flash；route_identity_snapshot一致（identity_sha256=84324d70…77909，与r1/r2轮相同身份）。
- gateway 侧唯一运行记录 airun_20261005172419_013c6227（提交后1秒建）：task_type=medical_writing_revision，**route_base_url=https://ollama.com/v1**，profile=independent_ai__ollama_cloud_dsv41，status=**completed**，`actual_response_model=deepseek-v4.1-flash`（真实外呼返回），`output_validation_status=passed`，无错误。
- **判读：owner决策20260928的ollama-cloud新路由真实生效，本轮端到端单次成功**；r2轮的"主路超时→回退opencode.ai→3次全败"本轮未再现（当日16:09修订批改动+17:58后端重启后链路健康；同窗口17:13另一项目同链路5分钟成功互证）。**r2 P0-A/P0-B在本轮复验未复发，但其根因（主路响应性波动、回退链设计）本轮样本不足以判定已根治，账本保持open**。

## ④ 医学视角产出质量评价（1-2句）

4个候选事实保真到位：药物代号、口服途径、机制类属逐字保留，"片"剂型按方案标题栏既有事实补入、sGC中文全称按项目作用机制栏既有表述括注，并逐字保留"NYHA II-III级"人群分级；指令中要求的英文全称 soluble guanylate cyclase 因未见于allowed_sources被明确拒补并在理由中声明——证据边界控制严格、无幻觉，医学上可直接选用。小瑕疵：4候选均把已确认研究人群附加进首页"研究药物"栏（医学无错但超出该栏通常只写药名的最小惯例，属风格差异），且语料缺标准英文术语导致规范英文名无法补入（术语库缺口，建议实现师补充常用缩写-中英文全称对照语料）。

## 其他观察（非本轮主诉）

- 候选面板跨单元格显示问题（r2 P1-B）本轮已自然消解——完成后面板显示的是本单元格线程的4个新候选；但修订完成后仍需重新进入/刷新页面才能看到候选（"AI修订建议已生成"在重进后才出现，面板不自动刷新的P2延续）。
- 30分15秒的单次修订时长仍偏长（对照同日17:13另一项目5分钟），"正在调用综合AI 40%"无细分进度（P2延续）。
- 测试者浏览器tab今日三次被外部清理（12:0x/13:2x/17:5x），环境问题影响长任务观察连续性，建议编排侧排查。

## 证据清单（本目录，20261005本轮新增）

- `1005r3_01_writing_platform_before.png` — 进入SGC2101写作平台（工作副本v2无阻断）
- `1005r3_02_revision_processing.png` — 提交后「处理中 正在调用综合AI」
- `1005r3_03_revision_completed_4candidates.png` — 完成后本单元格4候选（推荐+3备选）待处置
- `1005r3_route_verification_sql.txt` — durable job+payload ai_policy+gateway运行记录 只读核对输出（含三轮对照与判读）
- `1005r3_revision_candidates.txt` — 用户指令+4候选全文（UI逐字转录）+医学速记
- 旧轮文件（9/29）未删除，按红线保留历史。
