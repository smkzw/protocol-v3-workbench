# R27 第6轮（20261006午后）· 医学修订路由验证报告（r6-revroute）

- 测试者角色：第6轮医学修订路由验证员（UI黑盒；sqlite3只读核对路由）
- 时间：2026-10-06 13:46 – 15:55 机器本地（UTC 11:46 – 13:55；DB/网关时间戳为UTC）
- 环境：前端 http://127.0.0.1:5186（代理5301）；后端5301 PID 92982（2026-10-06 10:07本地启动，r6修复批后；注：ai_gateway.py/ai_task_runner.py mtime分别为10-01/10-05，本批未改动这两个文件）。
- r6-revroute 目录为本轮新建（无旧轮文件）；r2-r5轮报告见各自目录。

## 任务执行路径（状态推进全部经浏览器完成）

1. 下拉选择 **R26MW-SGC2101（口服sGC激动剂）· 慢性心力衰竭（HFrEF）· II期 · MW-II-064699A9**（proj_user_1fb1fb310f86）→ 医学写作：工作副本v2直接打开无阻断。
2. 「全屏编辑当前表格结构与附注」→ 点选 **第4行/第2列「适应症」值单元格**（mwcell_greenfield_c99018d9a78fc455_3_value，现值"慢性心力衰竭（HFrEF）"）。
3. **本轮性质=r2缺陷回归复测**：r2轮该单元格同类的"术语规范化+英文全称括注"指令三次全败0候选；本轮指令245字在r2基础上扩展"若项目语料中的标准术语对照另有权威写法以其为准并注明出处"（payload逐字核对一致）→ 提交AI修订（11:48:02Z建job），一次点击注册成功。
4. UI进度「处理中 正在调用综合AI 40%」→ **12:51:18Z 终态 failed（attempt 1/1，不重试），0候选交付**，全程1小时3分16秒。等待期间测试tab再次被外部清理一次（累计第6次），重进平台完成核对。

## ③ 路由核对结论（sqlite3只读，证据 1006r6_route_verification_sql.txt）

- durable job：`mwjob_41e0b87caa39c317aea7a6b3`（section_ai_candidate，failed 1/3）。
- **声明路由（任务③字面对象）**：`payload.generation_context.descriptor.ai_policy.base_url` = **https://ollama.com/v1**（host=https://ollama.com）；profile=independent_ai__ollama_cloud_dsv41；identity=84324d70…→ **提交层路由核对通过——owner决策路由声明六轮（r1-r6）一致生效**。
- **实际网关流量（2条运行）**：
  1. airun_20261006114803（主路）：ollama-cloud https://ollama.com/v1 —— 模型真实返回（deepseek-v4.1-flash）但 output_validation=failed（约57分钟）。
  2. airun_20261006124518（回退）：opencode-go https://opencode.ai/zen/go/v1 —— completed 且校验通过。
- **终态**：job 再次被 **post_ai_pre_commit 身份门**拦截（expected=84324d70…ollama，got=66d6af5b…opencode）→ failed，0候选。身份门连续第三轮（r4/r5/r6）实证拦截非授权路由产出，r2 P0-B修复行为稳定。
- **回归判读：r2缺陷在r6修复批后未收敛**——含英文全称括注的术语规范化指令在主路再次输出校验失败（r2同类败、r4编号败、r5纯超时、r6同类再败；六轮中仅r3药名规范类成功一次）。主路（ollama.com）输出校验稳定性问题是医学修订链路当前的核心卡点，且本轮r6修复批未触及（ai_gateway/ai_task_runner mtime未变）。

## ④ 医学视角产出质量评价（1-2句）

本轮0候选交付，无产出可评：主路唯一一次真实模型返回再次未通过服务器输出校验，回退路的已验证产出被身份门正确拒绝——"宁可失败不交付非授权路由产出"的边界第三次守住了；但对医学撰写者，这条"适应症术语规范化"指令从r2到r6两轮实跑均无果（合计等待超3小时），该单元格的修订工作在现有链路上完全无法完成，主路输出校验稳定性（尤其对含英文术语括注类指令）已成为修订功能的实际阻断项。

## 其他观察（非本轮主诉）

- **失败零反馈（r2 P1-A，连续第四轮复验未修）**：job failed后重进平台无失败痕迹（面板仍显示r3线程候选）。
- **候选面板跨单元格显示（r2 P1-B，仍在）**。
- 1h3m全程UI仅40%一档进度（P2延续）。
- 测试tab累计第6次被外部清理（环境观察）。

## 证据清单（本目录，20261006本轮新建）

- `1006r6_01_writing_platform_before.png` — 进入SGC2101写作平台（工作副本v2无阻断）
- `1006r6_02_revision_processing.png` — 提交后「处理中 正在调用综合AI」
- `1006r6_04_after_failure_no_trace.png` — 终态failed后重进平台：无失败痕迹、面板显示r3线程候选
- `1006r6_route_verification_sql.txt` — durable job+payload ai_policy+2条网关运行 只读核对输出（含身份门错误原文与回归判读）
