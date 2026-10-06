# R27 第5轮（20261006晨）· 医学修订路由验证报告（r5-revroute）

- 测试者角色：第5轮医学修订路由验证员（UI黑盒；sqlite3只读核对路由）
- 时间：2026-10-06 06:49 – 08:35 机器本地（UTC 04:49 – 06:35；DB/网关时间戳为UTC）
- 环境：前端 http://127.0.0.1:5186（代理5301）；后端5301 PID 46041（2026-10-06 04:08本地启动）。
- 本报告与9/30旧轮同名报告并存，旧文件未删；r2-r4轮报告见 r2/r3/r4-revroute/。

## 任务执行路径（状态推进全部经浏览器完成）

1. 下拉选择 **R26MW-SGC2101（口服sGC激动剂）· 慢性心力衰竭（HFrEF）· II期 · MW-II-064699A9**（proj_user_1fb1fb310f86）→ 医学写作：工作副本v2直接打开无阻断。
2. 「全屏编辑当前表格结构与附注」→ 点选 **第7行/第2列「版本日期」值单元格**（mwcell_greenfield_c99018d9a78fc455_6_value，现值"2026-09-30"）——**第五种任务视角：注册格式日期本地化（ISO→中文日期，数值不动）**（r1标题语序/r2适应症术语/r3研究药物药名/r4方案编号规范，均不同）。
3. 修订意图=改写；用户指令129字（payload逐字核对一致）→ 提交AI修订（04:51:00Z建job），一次点击注册成功。
4. UI进度「处理中 正在调用综合AI 40%」→ attempt1约40分钟超时 → attempt2约48分钟再超时+回退 → **06:19:10Z 终态 failed（2/3），0候选交付**，全程1小时28分10秒。等待期间测试tab再次被外部清理一次（累计第5次），重进平台完成核对。

## ③ 路由核对结论（sqlite3只读，证据 1006r5_route_verification_sql.txt）

- durable job：`mwjob_5ba2f545af45bb809f00e405`（section_ai_candidate，failed 2/3，04:51:00→06:19:10Z）。
- **声明路由（任务③字面对象）**：`payload.generation_context.descriptor.ai_policy.base_url` = **https://ollama.com/v1**（host=https://ollama.com）；profile=independent_ai__ollama_cloud_dsv41；identity=84324d70…（与r1-r4一致）→ **提交层路由核对通过，owner决策路由声明生效**。
- **实际网关流量（3条运行）**：
  1. airun_20261006045101（attempt1）：ollama-cloud https://ollama.com/v1 —— "retry ladder budget exhausted after 2 attempt(s) within 2400s (TimeoutError)"，**纯超时，无模型输出**。
  2. airun_20261006053115（attempt2）：ollama-cloud https://ollama.com/v1 —— "request failed after bounded retries: TimeoutError"，**再次纯超时无输出**。
  3. airun_20261006061115（回退）：opencode-go https://opencode.ai/zen/go/v1 —— completed，模型真实返回且校验通过。
- **终态**：job再次被 **post_ai_pre_commit 路由身份门**拦截（expected=84324d70…ollama，got=66d6af5b…opencode）→ failed，0候选——身份门连续第二轮（r4、r5）实证拦截非授权路由产出，r2 P0-B修复行为稳定。
- **判读：声明路由正确、身份门保护正确；但主路ollama.com连续两轮不可用**（r4：有返回但输出校验失败；r5：两次纯超时零输出）——本测试者五轮提交三败（r2/r4/r5）一成一空转，**主路可用性是当前医学修订链路的卡点（r2 P0-A连续复现且恶化）**；回退流量仍出网到opencode.ai（数据出境面未变）。

## ④ 医学视角产出质量评价（1-2句）

本轮修订0候选交付，无产出可评：主路两次纯超时连模型输出都没有，回退路的已验证产出被路由身份门正确拒绝——系统宁可失败也不交付非授权路由产出，这一边界守住了；但对医学撰写者，把一个日期格式从ISO改写成中文格式这样的一行小改动等了1小时28分后静默无果、界面无任何失败提示与原因，本链路在本轮窗口内实际不可用，主路稳定性（网络/云侧/超时窗口）已连续三轮成为修订功能可用的前置阻塞项。

## 其他观察（非本轮主诉）

- **失败零反馈（r2 P1-A）仍未修复**：job failed后重进平台无任何失败痕迹（面板停留在r3线程候选）。
- **候选面板跨单元格显示（r2 P1-B）仍在**：未选单元格/选其他单元格时面板显示r3研究药物线程候选。
- 1h28m全程UI仅40%一档进度，attempt轮次不可见（P2延续）。
- 测试tab累计第5次被外部清理（环境观察）。

## 证据清单（本目录，20261006本轮新增）

- `1006r5_01_writing_platform_before.png` — 进入SGC2101写作平台（工作副本v2无阻断）
- `1006r5_02_revision_processing.png` — 提交后「处理中 正在调用综合AI」
- `1006r5_04_after_failure_no_trace.png` — 终态failed后重进平台：无失败痕迹、面板显示r3线程候选
- `1006r5_route_verification_sql.txt` — durable job+payload ai_policy+3条网关运行 只读核对输出（含身份门错误原文与判读）
- 旧轮文件（9/30）未删除，按红线保留历史。
