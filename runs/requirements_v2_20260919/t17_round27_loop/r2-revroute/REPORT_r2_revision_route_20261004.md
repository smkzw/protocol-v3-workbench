# R27 第2轮（20261004恢复后）· 医学修订路由验证报告（r2-revroute）

- 测试者角色：第2轮医学修订路由验证员（UI黑盒；sqlite3只读核对路由）
- 时间：2026-10-04 23:47 – 2026-10-05 00:05（机器本地时钟；DB时间戳为UTC，下同）
- 环境：前端 http://127.0.0.1:5186（vite PID 61928，进程env实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`——脚枪未复发）；后端 5301 PID 18213，2026-10-04 21:42:22 自正确 repo root 启动（晚于 ai_gateway.py/ai_execution_policy.py 10-01 mtime 与全部本日代码 mtime——部署新鲜度核过）。
- 本文件与 9月29日同名旧报告（REPORT_r2_revision_route.md）并存：旧轮发现路由走 opencode.ai（P0）；本轮为 1003-1004 修复批+八节点自检后的复验。

## 任务执行路径（状态推进全部经浏览器完成）

1. 项目总看板 → 下拉选择任务书点名项目 **R26MW-SGC2101（口服sGC激动剂）· 慢性心力衰竭（HFrEF）· II期 · MW-II-064699A9** → 医学写作。
   - **写作平台直接打开，无任何阻断**（工作副本版本2、编辑中、已保存2026/9/30）。对比：9/29轮「建立工作稿失败：8项设计事实缺失」、9/30轮「StudyDefinition changed」两类阻断均已消失——**R26 P0①（心衰场景表单塌缩致无法建工作稿）在"进入写作平台"路径上已修复**（注：本项目工作副本目前仅含方案首页表格，全文初稿仍"待生成"，完整框架修复深度未在本轮验证范围）。
2. 该项目工作副本可编辑对象为「方案首页信息」结构化表格 → 点击「全屏编辑当前表格结构与附注」→ 表格设计器中点选 **第3行第2列「方案标题」单元格**（AI修订面板随即解锁，提示"当前目标：第3行/第2列，AI只生成该单元格的完整替换候选"）。
3. 修订意图=`medical_writing_revision`（界面名"改写"）；用户指令=按中国方案标题惯例以"评价+药物+在+人群+中的+有效性、安全性与药代动力学"为主干改写语序、修正"受试者中有效性"缺"的"的语法、保留NYHA II-III级人群限定、不新增未确认事实（全文见 1004r2_revision_candidates.txt）→ **提交AI修订**（21:52:46Z）。
4. UI进度：「处理中 正在调用综合AI 40% 步骤3/5」→ **21:58:31Z 完成：4个候选**（推荐版+精炼版+结构重排版+保守版，均"待处置"，未写入工作副本；旧线程遗留的4个待处置候选仍在，本轮未动它们、未选用写入任何候选）。
   - 全程 **5分45秒，attempt 1/3，无校验重试**（9/29轮同链路曾因术语溯源重试整轮重跑耗时约26分钟）。

## ③ 路由核对（sqlite3 只读，证据 1004r2_route_verification_sql.txt）

- durable job：`mwjob_c733fb4e4a5ea9bebbb4712f`（section_ai_candidate，**completed**，provider=ollama-cloud，model=deepseek-v4.1-flash，21:52:46→21:58:31Z）。
- `payload.generation_context.descriptor.ai_policy.base_url` = **https://ollama.com/v1**（host=https://ollama.com；`/v1` 为第5轮404缺陷修复所加端点后缀）；`route_profile_id`=`independent_ai__ollama_cloud_dsv41`；route_identity_snapshot 与之一致（identity_sha256=84324d70…77909）。
- gateway 侧（ai_task_runs.jsonl 行700，run_id=airun_20261004215250_32e877bb，时间戳=提交后4秒）：task_type=medical_writing_revision，**route_base_url=https://ollama.com/v1**，route_profile_id=independent_ai__ollama_cloud_dsv41，status=**completed**，`actual_response_model=deepseek-v4.1-flash`（与期望一致，真实外呼返回），`output_validation_status=passed`，无错误。
- **判读：owner决策20260928 的 ollama-cloud deepseek-v4.1-flash 新路由真实生效，且首次在本轮达到"提交→外呼→校验→候选提交"端到端完成**（前四轮分别为走错网关/白名单拒/平台500/404）。字面上 base_url 含 `/v1` 后缀与决策文档转录值 `https://ollama.com` 不逐字相等，属第5轮裁定的必要端点修正，host 与 profile 身份均符合决策；本报告按"路由正确"判定。
- ⚠ 前四轮缺陷（走错网关/白名单拒/500/404）本轮全部复验通过。

## ④ 医学视角产出质量评价（1-2句）

4个候选均逐字保真全部设计事实（药物与类别、HFrEF适应症、NYHA II-III级人群、多中心/随机/双盲/安慰剂对照、II期、三评价维度），推荐版严格按指令以"评价+药物+在+人群+中的+维度"主干改写并修正了"受试者中有效性"的语法缺失，且在理由中显式声明"参考语料仅用于措辞参照、未用于确认项目事实、未使用forbidden来源"——术语溯源与证据边界控制到位，无幻觉，符合中国临床试验方案标题撰写惯例，可直接供医学经理选用。小瑕疵：备选1以"且"连接人群限定（"慢性心力衰竭（HFrEF）且NYHA II-III级受试者"）在方案标题文体中略显生硬，属可接受的风格差异而非事实问题。

## 其他观察（非本轮主诉）

- **P2（环境提示）**：写作平台顶部横幅"前端开发服务早于当前后端代码（vite启动时 api-0bee035a…，当前源码树 api-9e5511fbd…）——请重启vite后刷新页面"。实测代理仍指向5301且后端为当前代码（进程env+cwd+启动时间核过），功能未受影响，但该横幅对医学经理不可操作（测试者无权重启vite），建议纳入集成人例行收尾（重启vite或校准指纹比较口径）。
- 修订完成候 **右侧面板不自动刷新**，停留"AI修订仍在后台进行，请稍后查看或刷新页面恢复"，需手动刷新页面+重进医学写作才见到新候选（9/29轮同类观察延续，P2）。
- 本项目旧线程（9/30）4个待处置候选与新候选并存于同一单元格，UI无"属于哪次指令"的区分标记，多次修订后易混淆（P2建议：候选卡片标注提交时间/指令摘要）。
- 修订时长5分45秒，UI在"正在调用综合AI 40%"停留全程无细分进度（既有P2"长任务无进度提示"在修订链路的体现）。

## 证据清单（本目录，20261004本轮新增）

- `1004r2_01_sgc2101_writing_platform_before.png` — 进入SGC2101写作平台（无阻断）+方案首页表格+旧4候选待处置
- `1004r2_01b_revision_submitted_processing.png` — 提交后「处理中 正在调用综合AI 40% 步骤3/5」
- `1004r2_02_revision_completed_4candidates.png` — 完成后新4候选（推荐+3备选）待处置
- `1004r2_03_ai_panel_candidates.png` — AI面板候选卡近景
- `1004r2_route_verification_sql.txt` — durable job+payload ai_policy+gateway记录 只读核对输出
- `1004r2_revision_candidates.txt` — 用户指令+4候选全文（UI逐字转录）
- 旧轮文件（9/29-9/30）未删除，按红线保留历史。
