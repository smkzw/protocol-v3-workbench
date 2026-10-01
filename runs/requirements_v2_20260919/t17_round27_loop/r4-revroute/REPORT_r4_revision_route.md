# R27 第4轮 · 医学修订路由验证报告（r4-revroute）

- 测试者角色：第4轮医学修订路由验证员（UI黑盒；sqlite3仅只读核对）
- 时间：2026-09-30 10:30–11:00 (+08)
- 环境：后端 PID 63003（09-30 10:08:24 启动），工作树含两处新改动：09:09 ai_execution_policy.py（NEW-40 白名单修复）与 **09:37 medical_writing_repository.py（引入全局回归，见P0）**

## 任务执行情况

### ① 找已有可编辑工作稿的项目 — 被环境阻断

- R26MW-SGC2101（任务书点名）：医学写作模块直接打开写作平台即报「真实方案文档会话读取失败：500」「尚未建立可编辑章节」。
- M8（第2/3轮宿主，唯一有已保存工作稿的项目）：整页刷新重进后同样 500。
- 后端日志证实 500 遍布所有项目（SGC2101 / OAB / M8 / 526a22727cc7 / 13a2759ba940 等）——**写作平台全局不可用**。

### ② 界面触发AI医学修订 — 无法进行

- 编辑会话未就绪（章节区显示「尚未建立可编辑章节」）；「提交AI修订」按钮 disabled，title=「当前历史工作版本已隔离，请先完成版本恢复。」（UI原文，截图说明见证据节）。
- 因此本轮**没有本测试者新建的修订job**；sqlite3 核对的对象不存在 ⇒ 任务的③检查项本轮未运行（无法运行），非跳过。

### ③ 路由核对 — 以只读旁证 + 静态代码核对替代端到端（明确标注非运行时验证）

- **durable DB 最新修订job**：`mwjob_43a24e73ed60d30e532bc172`（proj_user_87b350249cad，今晨08:26 +08，他人触发，failed）——其提交层路由身份已是 **https://ollama.com / independent_ai__ollama_cloud_dsv41 / ollama-cloud / deepseek-v4.1-flash**；失败原因为 NEW-22 时代的老问题：执行层白名单无 ollama-cloud → AiExecutionPolicyDenied（该job创建于09:09修复之前）。
- **静态代码核对（已读源码）**：NEW-40 已将 `_OLLAMA_CLOUD_DEEPSEEK_V41_FLASH_POLICY`（ollama-cloud @ https://ollama.com，model=deepseek-v4.1-flash）加入 `TASK_AI_ROUTE_POLICIES[MEDICAL_WRITING_REVISION]`（services/api/app/ai_execution_policy.py:186-192 定义、:217-219 入表，列于MTPLX后第二位）；NEW-22 提交层 override（:115）仍在。**提交层+执行层配置齐备**。
- **端到端结论不可得**：10:08 重启后 durable 无任何新修订job（500阻断创建）；「新job的ai_route.base_url=https://ollama.com 且真实调用ollama.com」本轮无法证明，也无需证伪——如实报 BLOCKED。

### 新P0：09:37 编辑引入写作平台全局500（阻断本轮全部验证）

- 现象：所有项目 document-session 500；UI横幅「真实方案文档会话读取失败：500」。
- 根因（AST+traceback双证）：`MedicalWritingRuntimeRepository`（medical_writing_repository.py:68-227，仅6个方法）在 `project()`(:115) 与 :225 调用 `self._with_effective_document_binding(...)`，但该方法在行4139是**模块级函数**（AST确认不属于任何类）→ 每次调用必然 `AttributeError`（traceback见 backend_5301_round27_restart.log:46639 起）。
- 影响面：医学写作模块对所有项目不可用（包括读会话），修订/初稿/目录等一切依赖文档会话的功能全部阻断。修法指向（不代改）：4139 的函数改为类方法，或调用处改用模块函数。

### ④ 医学视角产出质量评价

无法评价——本轮零修订产出（平台500阻断），不评分。

## 证据清单（本目录）

- `route_verification_sql.txt` — A:500清单+traceback+AST核验+UI提交禁用原文；B:durable最新job与43a24e73路由/错误；C:NEW-40静态核对；D:结论
- `REPORT_r4_revision_route.md` — 本报告
- 注：本轮页面截图两次均小于200KiB被工具内联返回、未生成artifact文件，UI状态以A1/A4引用的页面原文与日志为准（「真实方案文档会话读取失败：500」横幅、「尚未建立可编辑章节」、提交按钮禁用title原文）。

## 对照账本（对上轮遗留）

- 第3轮P0「修订路由修一半」→ NEW-40 静态已修（执行层白名单含ollama-cloud），**端到端未验证**（被本轮新P0阻断）。
- R26 P0①（心衰表单塌缩）→ SGC2101 本轮已表现为500新症（建稿流程被document-session 500覆盖，原8项blockers提示不再出现——修复状态无法透过500判断）。
