# R27 第5轮 · 医学修订路由验证报告（r5-revroute）

- 测试者角色：第5轮医学修订路由验证员（UI黑盒；sqlite3只读核对+无认证路径探针）
- 时间：2026-09-30 15:30–15:55 (+08)
- 环境：后端 PID 14256（09-30 15:27:52 起，含 14:28 仓储修复——第4轮P0的500已修复，见下）

## 修复确认（对第4轮P0）

- 第4轮的写作平台全局500已修复：`MedicalWritingRuntimeRepository` 现含 `_with_effective_document_binding` 方法（AST核验：类范围162-5642，hasMethod=True），后端15:27重启后 M8 写作平台正常打开（版本2编辑中，无500）。

## 任务执行路径（全部经浏览器）

1. R26MW-SGC2101（任务书点名）：500已消失、回到建向导，但点「进入写作平台」仍被阻断，本轮新阻断语：「建立工作稿失败：StudyDefinition changed; the prior plan and confirmation are not current」（研究定义更新后装配计划未重新确认；与第3轮的「8项设计事实」是不同形态的阻断）。
2. 改用 M8（唯一有已保存工作稿的项目）→ 目录 → **随机化** 节（实质正文，前几轮未用过的节）。
3. 编辑器选中分层随机化整句（93字符）→ 修订意图=`medical_writing_revision` → 用户指令（数据管理与统计视角：分层因素规范句式+随机分配表保密保存/设盲原则句+保留既有事实+统一「受试者」称谓）→ 提交AI修订。
4. job `mwjob_437ad40206a3f143ff0c6789` 运行后 failed（attempt 3/3，07:46:42→07:47:27Z，约46秒）；UI显示「AI修订失败：ValueError: 独立AI输出未通过医学写作校验：AI provider request failed: HTTP 404」。

## ③ 路由核对结论（证据 route_verification_sql.txt）

- **字面核对（任务③原话）：durable最新job（本测试者UI新建）的 ai_route.base_url = https://ollama.com ✓**（payload.ai_policy + route_identity_snapshot 一致；identity_sha256=010d9243…0f7f）——提交层路由真实生效，且本轮 **gateway 已发起真实外呼 ollama.com**（ai_task_runs 3条 medical_writing_revision 记录，route_base_url=https://ollama.com）——这是前4轮从未到达的一步（R2走错网关、R3被白名单拒、R4平台500）。
- **但功能性路由错误（P0）**：3次调用全部 `HTTP 404`。根因：客户端拼接 `f"{base_url}/chat/completions"`（ai_gateway.py:1312），而 ollama profile 的 base_url=`https://ollama.com`（无`/v1`）→ POST 打到 `/chat/completions`。无认证探针实锤：`/chat/completions`→404（不存在），`/v1/chat/completions`→401（存在仅缺认证），`/v1/models`→200。其余所有云profile的base_url均含`/v1`。
- **修法指向（不代改，owner决策文档转录值本身缺后缀）**：将 `independent_ai__ollama_cloud_dsv41` 的 base_url 改为 `https://ollama.com/v1`（isolated_runtime/ai_provider_settings.json），或网关对缺/v1的base_url做规范化。
- 判定：base_url 字面符合 owner 决策转录、路由身份与外呼均真实发生，但**修订端到端仍不可用（每次404）⇒ P0 路由配置错误**。

## ④ 医学视角产出质量评价

无法评价——3次尝试均404于网关路径层，模型未产生任何候选输出（零产出，不评分；等base_url修正后下一轮评价）。

## 其他观察

- P2：UI将404网络错误包装为「独立AI输出未通过医学写作校验」——归因误导（校验层并未失败），应区分「网络/路由失败」与「输出校验失败」。
- P2（备注）：SGC2101新阻断「StudyDefinition changed…」对医学经理不可读（英文原文直出），且无界面引导重新确认装配计划。

## 证据清单（本目录）

- `01_randomization_section_before_revision.png` — 修订前随机化节与选中句
- `02_revision_failed_http404_ollama.png` — UI失败提示（HTTP 404 原文）
- `route_verification_sql.txt` — durable job状态+payload路由快照+gateway三条404记录+无认证探针+代码定位（ai_gateway.py:1312）
