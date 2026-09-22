审阅完成。以下为完整会议输出。

# Conference Participant Output: mw_protocol_v3_triage_fallback_review_20260923 - general_single_object

## Boundary Check

- 工作目录限定在 runner 绑定的 workspace 内；全部操作为只读(读文件、`git diff`、`rg`、`python -c` 探针、unittest 运行)。未修改任何源码、配置或 runner 管理的产物。
- 未读取其他参会者输出;未启动会议;未联网。仅读取初始清单两份文件 + 源真相当中列出的代码/契约/测试文件及 `medical_writing_durable_jobs.py`、`ai_gateway.py`、`ai_role_runtime_settings.py`、`main.py`(均为目标的直接调用面)。
- 未写入 `runs/conference/mw_protocol_v3_triage_fallback_review_20260923/general_single_object.md`,本报告完整返回由 runner 持久化。
- 模型/思考级别保持 `GLM-5.3-Flash` / `max` 未切换。不主张最终验收，Codex 保留最终权威。
- 临时 venv `/tmp/triage_review_venv` 仅用于运行测试，装了 xlrd/pytest/python-multipart;未触碰项目文件。为运行测试向用户级 site-packages 安装 xlrd 的尝试被 PEP 668 拒绝后改走 venv,宿主 Python 未被改动。

## Independent Work Product

审阅对象：HEAD `52f6654` + 未提交 diff(`services/api/app/medical_writing_competitor_triage.py` +292,`tests/test_medical_writing_triage_durable.py` +76,`packages/contracts/workbench_contracts/models.py` +5)。按五个审阅维度逐项给出结论，严重级按 P0(目标未达成/必须修复后才能提交)、P1(可达回归)、P2(准确性/可观测性)。

### P0-1 旧 v1 冻结路由 100% 无法恢复执行 —— “冻结路由与旧 v1 兼容” 目标未达成

- 位置:`services/api/app/medical_writing_competitor_triage.py:4649-4653`(`_build_provider_for_durable_run` 身份复核),根因在 `:4483-4500`(`_route_from_profile` 固定产出 v2 身份)与 `:155-175`(`identity_payload` 仅 v2 含 thinking/effort)。
- 机制:存量 v1 路由的 `identity_hash` 是对 v1 payload(`schema_version="competitor_triage_ai_route_v1"`、无 thinking/effort 字段)的 sha256;升级后 resume 时 `current_route = self._route_from_profile(effective_profile)` 必然生成 v2 payload(`schema_version` 变为 v2、新增两字段)，哈希结构性不同，`current_route.identity_hash != route.identity_hash` 恒成立 → 抛 `"frozen independent-AI profile identity changed"`,`DurableJobResult(retryable=False)`。与数据无关，所有 v1 路由无一幸免。
- 讽刺的是兼容意图处处可见:`parse()` 接受 v1(`:219-242`)、v1 跳过 thinking 断言(`:4539-4545`)、`TRIAGE_LEGACY_ROUTE_SNAPSHOT_VERSION` 专门定义(`:104`)——但 v1 路由唯一被消费的路径(resume)全灭。
- 次生问题：失败信息误导。既有迁移话术 `TRIAGE_LEGACY_ROUTE_ERROR`("cancel it and submit an explicit retry",`:107-110`)只在 payload 不可解析时触发(`:5046-5054`);v1 任务会先通过 parse、再死在执行期，用户看到的是"identity changed"而非迁移指引。
- **实证**(真实代码路径，非哈希代数推测)：构造 v1 payload + 匹配 profile,调用真实 `CompetitorTriageService._build_provider_for_durable_run` → `1) legacy v1 route parse: accepted` / `2) resume of legacy v1 job: REJECTED -> frozen independent-AI profile identity changed`。探针脚本为一次性 `python3 -c`,未落盘。
- 修复方向(择一，需 Codex 定夺语义，见问题 Q1):
  1. resume 时按路由自身 schema 版本复核：v1 路由用 v1 payload 语义重建哈希(镜像 `identity_payload` 的条件分支)；
  2. 或执行入口显式拦截 v1 → 抛 `TRIAGE_LEGACY_ROUTE_ERROR` 风格的迁移错误(取消+显式重试)，fail-fast 且话术正确；
  3. 不论选哪种，补一个 v1 fixture 回归测试——现有 457 个测试全部用新代码造路由，覆盖不到此路径。

### P1-1 `request_hash` 公式变更 + 端点不捕获冲突 → 升级后幂等重提交变成 500

- 位置:`medical_writing_competitor_triage.py:4580-4599`(`_durable_request_hash` 新增 `fallback_route_identity_hashes`,主路由哈希本身 v1→v2 亦变);`medical_writing_durable_jobs.py:303-339`(`create_or_reuse` 同 business_key 不同 hash 抛 `DurableJobRequestConflict`);`medical_writing_competitor_triage.py:4384`(create 路径无前置去重，business_key = `snapshot:run_id` 内容稳定,`:4335/:4365`);`main.py:8803-8813、8898-8908`(triage 两端点只捕获 `CompetitorTriage*` 家族;`DurableJobRequestConflict` 仅 full-draft 端点处理，`main.py:7863`)。
- 可达场景:(a) 升级前创建过 job 的同一 snapshot+input,升级后重新 POST 创建端点 → hash 不同 → 未捕获异常 → 500(升级前该路径是幂等 reuse);(b) 同一提交之间用户编辑了 fallback 链 → hash 不同 → 500;(c) 终态重试分支(`:5089-5112`)在相同 `retry_business_key`(同幂等键+同失败分片集)下两次重试之间编辑链 → 500。
- 链变更算不算“新请求”可以辩论，但无论政策如何，当前表现是未捕获 500 而非 409,这是回归。
- 修复方向：两端点补 `except DurableJobRequestConflict → 409`;并显式决定链变更的重用政策(见 Q3)。

### P2-1 链耗尽时失败分片 provenance 自相矛盾(depth=0 却有 fallback_reason)

- 位置:`FallbackTriageProvider.triage_run` `:483-500`;provenance 读取点 `:4843-4860`(route_fields)+ `:4903/:4950/:4968`。
- 实证(真实类探针)：链 [A, B],A 抛 429(合格切换)→ B 抛 `provider_response_invalid_json`(不合格，重抛)→ 结束时 `fallback_depth=0`、`route_profile_id=A`、`fallback_reason="provider_http_error:429"`。`_active_index` 仅在成功时前移(`:498`),故 B 上的真实失败被归因到 A,且 depth=0 与非空 reason 并存。暴露面：校验失败带 provenance 的路径(`:4890-4907`)及这些字段的任何下游消费；纯 provider 异常路径(`:4863-4873`)不记 provenance,不受影响。
- 修复：切换时记录 last_attempted 路由(或失败时前移只读游标，不动 `_active_index` 语义)。

### P2-2 thinking/effort 断言在包装层退化为 no-op,getattr 默认值不对称

- `_assert_provider_matches_route`(`:4522-4532`)用 `getattr(provider, "default_thinking", route.thinking)`,但创建路径传入的是 `VerifiedTriageProvider` 包装器(类只复制 provider/model/base_url/transport/expected,`:283-300`,无 thinking 属性)→ getattr 落到默认值 = route 自身 → 创建期断言恒真，形同虚设。真正的强制点只在执行期对 raw provider 的断言(`:4668`),生产链路有效(freeze 来自 profile → `profile_env` 写 `WORKBENCH_AI_THINKING/REASONING_EFFORT`(`ai_runtime_settings.py:727-728`;`ai_role_runtime_settings.py:652`)→ gateway 消费(`ai_gateway.py:1148-1156/1191-1192/1721-1722`)→ 保真闭环成立)。
- 隐患：freeze 侧默认是 `""`(`:4433/:4436`),断言侧默认是 `route.thinking`——不对称；若某 raw provider 显式 `default_thinking=None`(env 缺失时 gateway 即如此)，`None or ""` → `""` ≠ route 值 → 误报 identity 不匹配。当前生产路径 env 必非空，属 latent trap,建议对称化默认值并注明创建期断言不覆盖 thinking。

### P2-3 可观测性：静默丢弃 fallback 路由 + 错误话术错位

- 执行期对每条冻结 fallback 重建 provider,失败即 `continue`(`:3834-3835`),不记录丢掉了哪条、为何丢;`fallback_chain_id` 只对幸存链哈希(`:427-431`,构造入参是已构建链)，同一冻结配置可因瞬时构建失败产生不同 chain_id,削弱其分析维度价值。建议：记录丢弃事件，chain_id 改为对 payload 冻结链哈希。
- 链元素非 dict 时 `parse` 抛 `TRIAGE_LEGACY_ROUTE_ERROR`(`:193-194`),该话术("legacy … no frozen AI route")用于 fallback 条目是错误描述。

### P2-4(观察)回滚边界

部署后产生的 v2 job 回滚到 HEAD 将在 parse 处被拒(旧代码只认 v1)。schema bump 的预期行为，但需在发布说明中写明：回滚前须取消并重提 v2 期任务。

### 合规维度结论(按目标逐项)

- **仅允许的切换条件：合规。** `TRIAGE_FALLBACK_HTTP_STATUSES = {408,429,500,502,503,504}`(`:106`)与基准 `ai_task_runner.AI_FALLBACK_HTTP_STATUSES`(ai_task_runner.py:89)完全一致;`provider_transport_error`/`provider_response_empty` 同基准(ai_task_runner.py:2436-2437);`invalid_json`/`model_mismatch` 正确不可切换；非 `AiProviderRuntimeError` 不切换；探针确认 501 不切换且 B 未被调用、transport/empty 正常切换、单元素链等价旧行为。
- **logical work/断点恢复不重复：本次 diff 未引入重复。** `chunks_to_run` 过滤 SUCCEEDED(`:3855-3859`);queued/retry_wait 复用原 job 不刷新(`:5042-5063`);终态重试按幂等键+失败分片键控(`:5071-5080`);新测试断言 [A,B] 各恰好调用一次。注意:P1-1 是“恢复身份”问题而非重复执行。
- **分片 provenance 兼容性：兼容**，新增 5 字段全带默认(models.py:8167-8171),无 provenance 完整性哈希，旧记录可解析;`route_fields()` 对旧 `VerifiedTriageProvider` 安全降级为空串。准确性问题见 P2-1。

## Evidence And Assumptions

**实证记录**(均为只读探针或测试运行，未改源码)：

1. v1 resume 拒绝：真实 `_build_provider_for_durable_run` + 真实 `FrozenTriageAiRoute.parse`/`AiProviderProfile`,输出 REJECTED(见 P0-1)。
2. 切换资格四例：501→重抛且未调 B;transport_error→切到 B;empty→切到 B;429+invalid_json 耗尽→depth=0/reason=429(见 P2-1)。
3. 聚焦测试 `test_frozen_fallback_chain_uses_next_route_only_for_retryable_provider_failure` 在本机临时 venv(Python 3.12 + system-site + xlrd/pytest/python-multipart)经 unittest 运行 **OK**,与 runner 记录“focused fallback test 1 passed”一致。合并 457 例未在本环境复跑(系统 Python 依赖拼装成本高于增量价值)，该项以 runner 记录为准、本会话未独立验证。
4. 代码行证据:`ai_task_runner.py:89/2436-2437`(基准资格集)、`medical_writing_durable_jobs.py:303-339`(冲突语义)、`main.py:7863/8803-8813/8898-8908`(异常处理面)、`ai_gateway.py:1148-1156/1721-1722`、`ai_runtime_settings.py:62-93/582-589/727-728`、`ai_role_runtime_settings.py:652`。

**假设**(已尽量验证，列明残余)：

- 假设 runner 的“457 passed”基于与本工作树一致的代码——未复跑，置信中。
- 假设 UI 在失败后可能走创建端点重提交(而非专用 retry 端点)——P1-1 场景 (a) 的可达性依赖此；即使不成立，场景 (b)/(c) 仍纯后端可达。
- 假设 durable worker 的租约/心跳预算未按 3×provider 超时(链满配最坏 ~15 分钟/分片)校准——未验证，列入验证需求。

## Risks, Gaps, And Verification Needs

**最重要的反对意见(挑战前提)：**

1. **目标与实现直接矛盾(P0-1)**:会议目标第一条就是“冻结路由与旧 v1 兼容”，而 v1 resume 是结构性全灭。在 P0-1 修复+回归前不应提交。
2. **与已接受基准的粒度分歧未被声明**:`ai_task_runner` 的 fallback 是 run 级(新 run 记录 + `fallback_parent_run_id`/`fallback_depth`,ai_task_runner.py:2293-2377);triage 改成了 run 内逐分片静默混用两个模型，仅靠分片 provenance 区分。若产品语义是“降级才允许跨模型”，现设计可接受但应在计划/文档里显式声明；若要求 run 内同模型，需要 run 级切换。Codex 需明确裁决(见 Q2)。
3. **幂等保证被静默削弱(P1-1)**:创建端点原本对同输入天然幂等(reuse),现在是跨版本 500。这属于用户可直接感知的回归。

**测试缺口(验证需求)：**

- 无 v1 fixture 的 resume 测试(可捕获 P0-1)。
- 资格集只测了 429 的正面用例：缺 5xx/408 正面、以及 400/401/`provider_response_invalid_json`/`model_mismatch`/非 AiProviderRuntimeError 的**负向不切换**断言。
- 无同 business_key 重提交的幂等/冲突测试；无链编辑后重试的冲突测试。
- 无多分片混合 provenance 测试(分片1落 A、分片2落 B 时各分片 route 字段正确)。
- 无 fallback 路由在执行期被删/改 profile 后静默丢弃的测试。
- 运维验证：durable worker 租约时长 vs 链满配最坏分片时延(3×timeout,300s 默认 → ~15min)是否安全，心跳粒度是否覆盖链内多次 provider 调用。

## Recommended Next Step

给 Codex 的行动建议(按序)：

1. **先复现 P0-1 再修**：用上述真实调用探针(或等价 pytest)确认后修复；推荐修复形态取 Q1 答案的分支，并补 v1 fixture 测试 + `invalid_json`/400 负向资格测试。
2. P1-1:两端点补 `except DurableJobRequestConflict → 409`,并按 Q3 决定链变更语义(建议：链变更 = 新请求，但必须以 409+指引呈现，不得 500)。
3. P2 三个小修(provenance last_attempted、getattr 对称化、丢弃记录/chain_id 来源)可与上述同批提交，均为窄改。
4. 提交后按主会场计划跑 triage 家族 457 例 + Protocol v3 全回归。

**有界问题(同会话可答)：**

- **Q1**:v1 任务 resume 的目标语义是“按 v1 身份继续跑”还是“fail-fast + 取消重提迁移指引”？决定 P0-1 修复形态(重建 v1 哈希 vs 显式迁移错误)。
- **Q2**:run 内逐分片跨模型混用是否为已批准的产品语义(与 `ai_task_runner` 的 run 级 fallback 有意分歧)？若是，是否需要在任何 depth>0 分片存在时向前端/结果页显式标注？
- **Q3**:fallback 链配置变更(主路由不变)应当被视为同一请求(reuse 旧 job)还是新请求(409)?当前实现是事实上的“新请求但以未捕获异常呈现”。
- **Q4**:durable worker 租约/心跳预算是否已按链满配最坏时延校准？若未测，建议在验收清单加一项。

**阻塞与恢复点**：无工具阻塞。合并 457 例回归未在本会话复跑(环境缺依赖，详见 Evidence §3)——恢复点为在该环境装齐依赖后执行 `tests/test_medical_writing_triage_durable.py` 全量。本报告完整，可由 runner 直接持久化。
