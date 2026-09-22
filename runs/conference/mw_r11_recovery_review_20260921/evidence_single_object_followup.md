I'll re-read the current source state: the repaired coordinator, product.py, the new test, and the frontend/API flow.

Let me verify the owner's two claims about F2 (documented scope of `allowed_attempts`; behavioral evidence for orphan recovery) rather than rely on a function-name grep.

Verified the owner's two F2 claims directly. Now writing the review record.

# Conference Output: mw_r11_recovery_review_20260921 - evidence_single_object

## Output

### F1 — 已关闭（静态复核通过，未由我执行测试）

修复行 `manuscript_coordinator.py:102`：`'can_resume': not complete and any(item.get('can_resume') for item in applicable)`；`stopped` 仅保留给 `status`（:98-101）；早退 `:108-109` 现在只在"无任何可推进子章"时触发——与你的描述一致。

我逐条推演了 `test_nonretryable_child_does_not_prevent_untouched_sibling_from_starting`（:171-208）在修复后代码下的每个断言，**全部成立**：
- `before['status']=='blocked'`（`stopped` 仍由不可重试子章触发）与 `before['can_resume'] is True` 同时成立 —— 这正是原缺陷的判别式；
- `owner.started == ['chapter-new']`、`owner.resumed == ['chapter-new']`：已完成章与不可重试章**既未 start 也未 resume**（`_Owner.resume` 只在被调用时记录；不可重试章在 `:127` 被 guard 跳过）；
- `after['complete_candidate'] is False`、`after['status']=='blocked'`、`after['can_resume'] is False`（新兄弟章转为 `needs_content_review` 后无任何 actionable 子章）；
- `states['chapter-blocked']['status']=='blocked'` 未被改写。

状态不变式闭合：`can_resume=false` ⟺ 无 actionabl 子章；`can_resume=true ∧ status=blocked` = "有可推进兄弟 + 有不可重试子章"，`status` 语义与 `complete_candidate`（保存闸门 `manuscript_document.py:42`，409 `manuscript_document_incomplete` 在 `manuscript_drafts.py:97-98`）均未受影响。

消费点全量复核（本 pass 新增）：`manuscript_drafts.py:323,344`、`manuscript_coordinator.py:108`、`ManuscriptWorkspace.jsx:380,466,469,502`，`application/manuscript_documents.py:86` 只用 `complete_candidate`。前端 3 个测试未改动；测试 3（blocked+`can_resume:false`）现在**确实是**"无 actionable 工作"的用例，断言（只核对、不重派、不新建）仍正确，我同意不需要为它改动 resume 行为。

"不重复活跃调用"逐项确认：已完成章跳过；不可重试章跳过（不 start/resume）；未动兄弟章 start 幂等（`coordinator.py:43-56`）+ resume 一次；活跃未知章由 `coordinator.py:74-79`/`runtime.py:843-849` 拒绝；适配器每次 dispatch 只发一次 HTTP（`zhipu_api.py:330`，无内部重试循环）；客户端 `flight.current`/`disabled={busy}` + 服务端 live-shell fail-closed（`reservations.py:317-339`）阻止并发重复派发。

### 修复行带来的新回归 — 未发现正确性回归

对 `can_resume` 的唯一行为增量集合 S = {not complete, stopped, ∃可继续子章}：S 内旧为 false、新为 true。S 内所有下游均为"调度"而非"状态写入"：`/start`、`/resume` 的 `tasks.add_task`、前端 `jsx:380`、`jsx:466/469` 文案。逐项检查后无一条产生错误状态、重复派发或绕过保存闸门。

唯一新增的是**交互可用性残留（非错误状态）**：`/resume` 返回的是**工作前**状态（FastAPI BackgroundTasks 在响应之后才执行），前端只重读一次（`jsx:390`），而 `jsx:273` 在 `status !== 'running'` 时停止轮询。由于不可重试子章使聚合长期保持 `blocked`，兄弟章的完成结果可能要到用户手动点"更新研究与文档状态"（`jsx:503`）才可见。以前 S 内根本不派发，所以没有"在飞工作看不到"的问题；修复后能派发了，这个轮询门就显得不够。
- 最小选项 A（更紧）：`/resume` 成功后做**有界**重读直到 `can_resume` 翻转或 `complete_candidate` 为真。
- 最小选项 B（一行）：`jsx:273` 改为 `status === 'running' || job?.can_resume === true`（只读端点，退避上限 30s）。

另一项新增可达路径（提示，非缺陷）：`/start`（`manuscript_drafts.py:323`）对**已存在**的部分阻塞 run 现在会调度推进；与 `/resume` 同一代码路径、同样逐章 guard，且前端仅在 404 时调 `/start`（`jsx:379`），故前端不可达。

### 覆盖残留（需新测试，非缺陷）

- 修复后的 `applicable` 过滤（`kept_as_gap` / `not_applicable`）在协调器层**无测试**：`_prepared_payload()` 只含两个 facts_ready 章（两个既有测试同样如此）。
- 新增 UI 条目 `jsx:465` 的 `kept_as_gap` 排除**无测试**：3 个前端测试均传 `chapters: []`。建议补：协调器层"gap + 不可重试 + 未动兄弟"的混合用例；前端层"gap 不出现在需要处理列表、blocked 章出现"的用例。

### 已按你的处置记录的限制（不再作为缺陷）

- **F2**：`graph/plan.py:134` 明确写 `allowed_attempts` 是 *explicit retry attempts* 的上界——我确认该文本，接受零 transport 孤儿路径不在其契约范围内，也确认单 shell 的恢复身份是确定且幂等的（`runtime.py:1260` + `reservations.py:682-692`），同一 shell 不会重复恢复。记录限制：`reserve`→RUNNING 窗口内的**反复**崩溃可每次新增一次 attempt（新 shell id），此限制在本修复中未变更。同时更正我上一轮的措辞：我**不**声称"没有函数名测试等于没有行为覆盖"——我实际核到 `test_graph_runtime.py:956-1038` 是把 RESERVED shell 手工推进到 RUNNING 后才验证"不自动重派"，因此该分支（transport_attempts==0 且保持 RESERVED）的**图级后果**我在已读文件中未见覆盖；协调器层由 `test_execution_reservations.py:649`、`test_durable_reservation_dispatch.py:211-242` 覆盖。此为覆盖观察，不是契约违规。
- **F3**：现契约为原始 1 次 + 显式重试 1 次 = 2，无第三次承诺；仅记录未来 `allowed_attempts>2` 时 `coordinator.py:101` 固定 `:retry:1` 使其不可达，本轮不做投机性提额。
- **F4**：mkdir/flock 探测属幂等文件系统维护，非领域变更、非模型派发；不为建目录另起只读架构。
- **F6/F7**：`resolution_id`/`reason` 未持久化（`runtime.py:642-666`）、RESERVED 行在 repairs 列表被过滤（`runtime.py:1050-1054` vs `:1845-1848`）——均为既有内务，保留为**未被接受的更广关注点**，不新增审计引擎。

### U1 — 已判定为"有界活跃"，非幻影 running（静态）

`REQUEST_TIMEOUT_SECONDS = 600`（`zhipu_api.py:83`，"long by design"），实际生效于 `:192` 的 `opener.open(request, timeout=...)`；生产走 stdlib opener（`agent3/product.py:41-42` 不传 `http_opener` → `:169`），`timeout` 同时约束连接与读取；超时经 `:201-204` → `ZhipuTransportError` → `reservations.py:613-622` 归类 `UNKNOWN_OUTCOME` → 进程内 claim 与 flock 释放 → 节点 blocked 且可显式重试。故不会无限空转。残留：600s 静默窗口较长；若部署注入忽略 `timeout=` 的自定义 opener 则该约束不由本模块保证（本仓库生产绑定未注入）；无端到端超时证据（本 pass 无网络、无执行）。

### 边界

未执行任何测试（Bash 仍被拒绝，未改工具策略）、未执行模型调用/网络/浏览器/子代理/清理；未做最终产品、临床、视觉或用户验收；U3（agent2 同形复核）本 pass 未要求，未做。

审阅记录已写入计划文件 `/Users/smkzw/.codebuddy/plans/blazing-nebula-tesla-5EdypFYJ.md`（本 pass 唯一允许的写入，不含任何实现授权）。

ExitPlanMode 被拒绝（非交互模式无权限）。这不影响本次任务：本轮是只读审阅，我并未申请实现授权，也没有任何待执行的实现动作。

审阅交付已完成：
- 报告已在上方按 conference schema 完整返回（F1 关闭 / 无正确性回归 / 三项残留 / F2-F7 与 U1 处置）。
- 记录文件已写入 `/Users/smkzw/.codebuddy/plans/blazing-nebula-tesla-5EdypFYJ.md`（本 pass 唯一写入，明确标注"不含实现授权"）。

若你希望我在同一会话继续，两个明确可选方向：
1. 补验 U1 的端到端超时行为（需要你授权读取部署侧 opener 绑定或允许执行受限探测；当前无网络约束下无法取证）。
2. 若要把残留 1（轮询门）与残留 2（`kept_as_gap` 过滤覆盖）纳入下一轮有界修复，请给出修复边界与允许改动的文件清单，我按新契约重新进入计划流程。

否则本轮到此为止：未执行测试、无模型调用、无产品/临床验收。
