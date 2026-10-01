# R27 第3轮 · 医学修订路由验证报告（r3-revroute）

- 测试者角色：第3轮医学修订路由验证员（UI黑盒推进状态；sqlite3仅只读核对）
- 时间：2026-09-30 03:30–03:50 (+08)
- 环境：后端 PID 54795（09-29 23:47 启动，晚于 22:40 的路由代码修改 → 运行为当前工作树代码），WORKBENCH_RUNTIME_DIR 指向 wp6 isolated_runtime（与第2轮同一runtime）；前端 5186→5301 正常

## 与第2轮的差别（任务包区分）

- 第2轮：M8项目·总体设计节·补安全性指标（ICH E3视角）。本轮：同项目换节 **盲法与揭盲**（与修订主题直接相关），指令改为注册/QA法规表述视角（GCP破盲管理表述、三段式重排、原则性揭盲表述、不新增事实）。
- 任务书点名的 R26MW-SGC2101 心衰项目先行尝试：**建稿仍被阻断**——UI status「建立工作稿失败：方案装配仍有未决设计事实（8项），请逐项补齐后再进入写作平台」（R26 P0①未修的下游后果；该提示只报数量、不报字段名——第2轮在status区还能看到字段名清单，本轮toast仅计数，退步或两种提示并存）。其余UI在列项目中：OAB项目（proj_user_e068895908c9）正被今日在跑的retest-r2协调员使用（有2026-09-30现场决策记录），MSC-201潮热项目仅有绿地基线无已保存工作稿（在其上建稿=改动他人项目，违反红线）→ 系统内唯一"已有可编辑工作稿"的可用项目仍为 M8（proj_user_97189da36a75，工作副本v2编辑中），故复用之，特此说明。

## 执行路径（全部经浏览器）

1. 项目总看板 → R26MW-SGC2101 → 医学写作 → 进入写作平台 → 建稿失败（见上）。
2. 改选 M8 项目 → 医学写作（直接进入写作平台，版本2 编辑中）→ 目录 → 盲法与揭盲（含实质正文）。
3. 编辑器内选中句子「双盲状态维持至安全随访期结束（第28周）。」→ 修订意图=`medical_writing_revision` → 用户指令（GCP视角三段式重排+原则性揭盲表述）→ 提交AI修订。
4. UI：提交后短暂「正在调用综合AI 40% 步骤3/5」→ 约1分钟后显示失败。

## ③ 路由核对结论（sqlite3 只读，证据 route_verification_sql.txt）

- 本次UI触发的最新 durable job：`mwjob_859f40557a06ba6735d29e91`（section_ai_candidate，attempt 3/3，19:43:16→19:44:06 UTC，50秒内三连拒，最终 **failed**）
- **提交时冻结的路由身份（payload.ai_policy + route_identity_snapshot）：base_url = https://ollama.com，profile=independent_ai__ollama_cloud_dsv41，provider=ollama-cloud，model=deepseek-v4.1-flash ✓ 与 owner 决策20260928 一致（对比第2轮的 opencode.ai）**
- 但执行层：`TASK_AI_ROUTE_POLICIES[MEDICAL_WRITING_REVISION]`（services/api/app/ai_execution_policy.py:204-212）批准路由白名单（mtplx/opencode-go/cms-router/alibaba_token_plan/deepseek）**不含 ollama-cloud** → `_enforce_task_ai_route_policy`（ai_execution_policy.py:1325）每次尝试抛 `AiExecutionPolicyDenied`（UI可见原文：「AI修订失败：AiExecutionPolicyDenied: … provider must be one of …」）
- ai_task_runs.jsonl 在修订窗口内 **0 条修订运行** —— 请求从未到达任何网关（ollama.com 一次都没被真正调用）
- **判定：路由修了一半——身份对了、执行被拒；医学修订功能当前完全不可用 ⇒ P0**（修法指向：在 TASK_AI_ROUTE_POLICIES 的 MEDICAL_WRITING_REVISION 元组中加入 ollama-cloud 路由策略项，与 NEW-22 override 对齐）

## ④ 医学视角产出质量评价

**无法评价**——3次尝试均被执行层策略拒绝，零候选产出（本轮不评分；待路由白名单补齐后下一轮重测再评）。

## 其他观察

- 修订失败在UI有中文可读提示（含被拒原因与允许路由清单），但面向医学经理暴露了内部provider枚举与端点清单，建议转为行动指引（P2，非本轮主诉）。
- 窗口内一条 19:40:51 的 protocol_full_draft 运行走了 opencode.ai（非MTPLX主路）——属并行会话的邻面现象，未核实其fallback链路，不作为本轮缺陷。

## 证据清单（本目录）

- `01_blinding_section_before_revision.png` — 修订前盲法与揭盲节正文与AI修订面板
- `02_revision_failed_policy_denied.png` — UI失败提示（AiExecutionPolicyDenied 全文）
- `route_verification_sql.txt` — durable job 状态 + payload 路由快照 + 拒绝原因 + 网关运行窗口核对
- 代码定位：services/api/app/ai_execution_policy.py:115（override表）、:204-212（修订白名单缺ollama-cloud）、:407-426（override优先解析）、:1325（执行层拒绝点）
