# R27 第2轮（20261005）· 医学修订路由验证报告（r2-revroute）

- 测试者角色：第2轮医学修订路由验证员（UI黑盒；sqlite3只读核对路由）
- 时间：2026-10-05 13:01 – 15:35 机器本地（UTC 11:01 – 13:35；DB/网关时间戳均为UTC）
- 环境：前端 http://127.0.0.1:5186（代理5301）；后端5301 PID 19473（2026-10-05 12:17本地启动，lsof核实其DB=runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime/，与本报告核对对象同库）。
- 本报告与既有旧报告（9/29、20261004两份）并存，旧文件未删。

## 任务执行路径（状态推进全部经浏览器完成）

1. 项目总看板下拉选择 **R26MW-SGC2101（口服sGC激动剂）· 慢性心力衰竭（HFrEF）· II期 · MW-II-064699A9**（proj_user_1fb1fb310f86）→ 医学写作：工作副本（版本2、编辑中）直接打开，无阻断（与1004轮一致，R26 P0①在"进入写作平台"路径维持已修）。
2. 「全屏编辑当前表格结构与附注」→ 表格设计器中点选 **第4行/第2列「适应症」值单元格**（mwcell_greenfield_c99018d9a78fc455_3_value，现值"慢性心力衰竭（HFrEF）"）——**与上轮（第3行/第2列方案标题·语序改写）不同的单元格与任务视角：术语规范化改写**。AI修订面板解锁（"当前目标：第4行/第2列"）。
3. 修订意图=改写；用户指令（201字，DB逐字核对一致）：按中国注册方案术语规范补全"射血分数降低的慢性心力衰竭"+括注英文全称与HFrEF缩写、不得新增LVEF/NYHA等未确认限定 → 提交AI修订（11:04:27Z建job）。注：提交按钮第一次坐标点击未注册（面板无响应），以页面内按钮click提交成功——界面点击可靠性小瑕疵，记录不动大状。
4. UI进度：「处理中 正在调用综合AI 40% 步骤3/5」持续约40分钟 → 60%「正在校验AI候选 步骤4/5」约99分钟（期间attempt 1→2→3，UI完全不可见）→ **13:23:18Z 终态 failed（3/3次尝试，0候选交付）**。运行期间本测试者浏览器tab两次自行消失（camofox "Tab not found"，约12:0x/13:2x各一次，疑似外部清理；重进平台续看，durable任务不受影响）——环境观察，非子系统缺陷。

## ③ 路由核对结论（sqlite3只读，证据 1005r2_route_verification_sql.txt）

- durable job：`mwjob_9b3f6a90d41cc08735daf421`（section_ai_candidate，failed 3/3，11:04:27→13:23:18Z，共2小时18分51秒）。
- **声明路由（任务③字面对象）**：`payload.generation_context.descriptor.ai_policy.base_url` = **https://ollama.com/v1**（host=https://ollama.com，`/v1`为R5轮裁定的端点后缀）；`route_profile_id`=independent_ai__ollama_cloud_dsv41；provider=ollama-cloud；model=deepseek-v4.1-flash；route_identity_snapshot与之一致（identity_sha256=84324d70…77909，与1004轮相同）→ **owner决策20260928的ollama-cloud新路由在提交层真实生效**。
- **实际网关流量（ai_task_runs.jsonl，本项目今日4条新记录）**：
  1. airun_20261005110428：ollama-cloud https://ollama.com/v1 —— failed，"retry ladder budget exhausted after 2 attempt(s) within 2400s (last TimeoutError)"（两次HTTP调用均1200s超时，无模型输出）。
  2. airun_20261005114446：ollama-cloud https://ollama.com/v1 —— 模型有返回（actual_response_model=deepseek-v4.1-flash）但 output_validation=failed。
  3. airun_20261005122900：**provider=opencode-go，https://opencode.ai/zen/go/v1**（independent_ai__opencode_go_deepseek_v41_flash）——主路耗尽后回退链外呼，模型有返回但校验失败。
  4. airun_20261005124317：ollama-cloud https://ollama.com/v1 —— failed，2400s预算再耗尽（TimeoutError）。
- **判读**：指定路由已生效（3/4条流量打ollama.com），但**修订链路端到端失败**；且**1/4条流量在主路失败后回退到了opencode.ai**——决策文档明确医学修订走ollama-cloud且"不再泛取fallback链第一个云profile"，运行时跨provider回退把修订内容（含方案上下文）送往owner未指定的外部网关，按决策字面判读记路由违规（P0，见下）。

## ④ 医学视角产出质量评价

本轮修订**未产出任何候选**（3次尝试全部失败），无产出可评——无法像1004轮那样评价保真度与措辞。可评的是链路行为本身：对医学撰写者而言，一次单元格级术语规范化修订等待2小时19分钟后静默失败、界面无任何失败反馈与原因，修订工作完全无法推进；且两次超时之间唯一拿到模型输出的尝试（airun_20261005114446，deepseek-v4.1-flash真实返回）倒在输出校验层而校验明细不可见，医学经理既看不到候选也看不到"为什么不行"，该链路在本轮运行窗口内不可用。

## 缺陷入账（供账本汇总）

- **P0-A 修订链路本次运行端到端失败**：单次提交→4条网关运行全败（2×主路超时耗尽、1×主路输出校验失败、1×回退路输出校验失败）→job failed，0候选；对照1004轮同链路5分45秒一次通过，本轮主路ollama.com响应性恶化（两次2400s预算纯超时）需排查（云侧/网络/负载）。
- **P0-B 运行时回退破坏路由决策（路由完整性）**：主路失败后gateway沿fallback链把medical_writing_revision送往opencode-go（https://opencode.ai/zen/go/v1）。决策20260928指定修订=ollama-cloud且明言不泛取fallback链；"永不拒绝服务"的回退设计越过owner指定供应方，涉及数据出境边界与供应方一致性，需owner/实现师裁定：任务级指定路由失败时应快速失败并明示，而非跨provider续跑。
- **P1-A 失败零反馈**：job failed后重进写作平台、重选同一单元格，无失败提示、无线程痕迹、无原因；durable error_summary在运行期为空、终态才填，且UI不展示。医学经理无法得知2小时前的修订已失败（加重既有P2"面板不自动刷新"）。
- **P1-B 候选面板跨单元格错位**：目标锁定第4行/第2列（适应症）时，面板仍显示第3行/第2列（方案标题）线程的4个旧候选（含"选用并写入"按钮）——若误点将把方案标题候选写进适应症单元格的风险（未实测写入，不动共享状态），显示作用域与"当前目标"不一致。
- **P2**：2小时19分全程UI只有40%/60%两档进度，attempt 1→3不可见、无失败中间态；提交按钮首次坐标点击未注册（需二次点击）；本测试者tab两次被外部清理影响连续观察。

## 证据清单（本目录，20261005本轮新增）

- `1005r2_01_writing_platform_before.png` — 进入SGC2101写作平台（无阻断）+方案首页表+旧4候选（快照近景）
- `1005r2_01b_writing_platform_full.png` — 同期全页截图
- `1005r2_02_revision_processing.png` — 提交后「处理中 正在调用综合AI 40% 步骤3/5」（11:04Z档）
- `1005r2_04_after_failure_no_trace.png` — 13:23Z终态failed后重进平台：同一单元格面板无失败痕迹、仍显示旧方案标题线程候选
- `1005r2_route_verification_sql.txt` — durable job+payload ai_policy+4条网关运行 只读核对输出（含终态与判读）
- 旧轮文件（9/29、9/30、1004）未删除，按红线保留历史。
