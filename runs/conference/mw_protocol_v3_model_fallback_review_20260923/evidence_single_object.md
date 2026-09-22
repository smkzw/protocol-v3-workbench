I'll start by reading the assigned context files.

Bash is denied in this session; I'll work from Read/Grep/Glob. Reading the core source files.

Now the task runner, which owns the fallback chain.

我已完成源码级只读审阅。以下为完整会议输出。

---

# Conference Output: mw_protocol_v3_model_fallback_review_20260923 - evidence_single_object

## Output

### 0. 交付边界与自述

- 角色：`evidence_single_object`（重要证据审阅），advisory，非最终验收。
- 全程只读。**未修改任何源码、测试、配置或运行产物**。未写 runner 管理的报告路径。
- 会话工具限制：本会话 `Bash` 被权限拒绝，因此**无法执行 `git diff`、`pytest`、前端 build**。所有结论来自对指定 source-of-truth 文件的静态阅读与交叉引用；**无法确认每行属于"本次改动"还是既有代码**，也无法复现运行期行为。这直接限制了"接受性证据"等级，已在下文逐项标注 evidence / inference。
- 未（按委派要求）启动会议、未联网、未阅读 `/Users/smkzw/.codex/AGENTS.md` 或 Hermes SOUL；未查阅初始 read set 之外的项目 `AGENTS.md`。

### 1. 结论摘要

主体设计方向正确且比常见做法严谨：主路由身份在策略解析时一次性冻结（`_capture_dynamic_route`），provider 只从冻结身份构造，回执逐 run 落盘，内容/合同校验失败不换模型（`_fallback_reason` 只认 `provider_http_error` 的 408/429/5xx、`provider_transport_error`、`provider_response_empty`），fallback 重建走 canonical request 且不转发上一模型输出。这些都能在代码里直接证实。

但我找到 **3 个 P1（其中一个会让 2+1 静默退化成 1）**，以及一组 P2 与明确测试缺口。最高影响的一条是：**某个备用槽"不适用"时，整条链被放弃，后续合规的备用槽永远不会被尝试**——这与"2+1 自动降级"的用户承诺直接冲突，且没有任何用户可见的原因说明。

### 2. 发现（按严重度）

#### P1-1 [控制流] 备用路由不适用 → 整条链被放弃，而不是跳过该槽

**证据**
- `services/api/app/ai_task_runner.py:2317-2318`（internal 路径）与 `:2359-2360`（registered 路径）：`except (AiExecutionPolicyDenied, ValueError): return parent`。
- 同循环内 `:2300-2302` 对"profile 不存在"用的是 `except KeyError: continue`。**同一段代码里两种跳过语义不一致**：缺失 profile 继续，不适用 profile 直接终止。
- `AiExecutionPolicyDenied(ValueError)`（`ai_execution_policy.py:35`）意味着任何策略拒绝（`_enforce_task_ai_route_policy` / `_enforce_deployment_profile` / registered 来源过期）都会命中该分支。
- 可达路径（不是理论值）：`App.jsx:2176-2178` 的备用槽下拉框只过滤 `profile_id !== form.profile_id`，即把**所有**连接都列为可选，包括 `ocr_local_omlx`、`ocr_paddle_official`、`translation_body_local_omlx`、`deepseek_translation_support`。而 `ai_runtime_settings.py:591-607` 的 `set_fallback_chain` 只校验"存在 + enabled + 非当前主路由"，不校验该连接是否是本任务允许的产品路由。选"本机 oMLX OCR"作为第 1 备用会保存成功。

**推演（inference，基于上述代码）**：主路由 MTPLX 不可达（`provider_transport_error`，可降级）→ 第 1 备用 `ocr_local_omlx` 进入 `resolve_internal_for_profile` → `provider="omlx"` 不在 `TASK_AI_ROUTE_POLICIES[PROTOCOL_FULL_DRAFT]` → 抛 `AiExecutionPolicyDenied` → `return parent`。第 2 备用 CMS Router（Study B 证明可用）**从未被调用**。用户看到的是主路由失败的任务 + 校验/传输错误文案，无从知道"第 1 槽不适用导致整链放弃"。

**影响**：2+1 静默退化为 1；这与 `runs/.../MODEL_ROUTING_2PLUS1_ACCEPTANCE_20260923.md:12` 的规则描述不符。

**修复建议（择一）**
1. 改为 `continue`，并在链上记录跳过原因（例如子 run 增加 `fallback_skipped_reason`，或写一条 `fallback_route_skipped` artifact），使"跳过"可审计；或
2. 保留 fail-closed 语义但**必须可见**：至少把"第 N 槽不适用"作为 run 的 validation/error 附加信息返回给调用方，并在任务详情中显示。
3. 源头治理：在保存入口校验资格。注意 **`set_fallback_chain` 位于 `ai_runtime_settings.py`，而 `ai_execution_policy.py` 反向 import 它**，直接在该函数里 import 策略会形成环；建议把资格校验放在 `main.py` 的 `PUT /api/ai-gateway/fallback-chain`（`main.py:3652-3666`）或一个可同时导入两侧的轻量 helper，并在 `public_payload` 里给每个 profile 增加 `fallback_eligible` 标记，UI 据此禁用不可选连接。

#### P1-2 [正确性] 被停用（`enabled=False`）的连接放进备用槽后仍会被真实调用

**证据**
- `ai_task_runner.py:2298-2307` 与 `:2343-2352`：`store.profile(route.profile_id)` → `replace(profile, thinking=..., reasoning_effort=...)`，**全无 `.enabled` 判断**；在 `ai_task_runner.py` 内 grep `.enabled` 无任何命中。
- 主路由路径是有判断的：`ai_execution_policy.py:325` `if profile is None or not profile.enabled` → 关闭（`_disabled_env`）。
- 保存期只校验一次：`ai_runtime_settings.py:599` `if profile is None or not profile.enabled: raise KeyError`。

**影响**：先入链、后停用（API 或历史配置）的连接会被继续当作备用模型使用；"停用"对备用路径不生效，属于安全/合规向的语义缺口。

**修复**：循环内与保存期使用同一规则；建议 `continue` + 记录跳过原因（与 P1-1 的修复合并实现）。

#### P1-3 [范围] 自动降级只覆盖 5 个 task_type；"综合AI"的竞品分析/方案设计/PICOS 不降级

**证据**
- 闸门：`ai_task_runner.py:79-85` `AI_FALLBACK_TASKS` = `MEDICAL_WRITING_REVISION / PROTOCOL_FULL_DRAFT / PROTOCOL_SYNOPSIS_STRUCTURING / DOCUMENT_SECTION_EXTRACTION / REGULATORY_TRANSLATION_ZH`；`:2379-2384` 不在集合内直接 `return []`。
- 同属"综合AI"职责但**不在**该集合的调用点（实测命中）：
  - `medical_writing_competitor_triage.py:361` → `COMPETITIVE_INTELLIGENCE`
  - `medical_writing_corpus_analysis_ai.py:883` → `COMPETITIVE_INTELLIGENCE`
  - `main.py:3716` → `PROTOCOL_DESIGN_SYNTHESIS`
  - `medical_writing_fact_intake.py:441` → `PICOS_DESIGN_COACH`
- 用户可见口径没有这个限定：`ai_role_runtime_settings.py:131` 角色建议"限流或服务不可用时按已设置顺序切换备用模型"；`App.jsx:2168` 备用区文案"仅在限流、服务暂不可用或空响应时依次切换"；验收文档 `MODEL_ROUTING_2PLUS1_ACCEPTANCE_20260923.md:10-12` 的"运行规则"也未限定任务类型。

**影响**：用户在设置里配好 2+1，却发现竞品分析/方案设计/PICOS 完全不降级；文档与实现口径不一致。

**决策点/有界问题**：见 §5 Q2。若确认要扩展，逐个 task_type 需要先证明"可由原始 request 确定性重建"（PICOS/竞品任务的 `task_context` 与来源集合是否可重放）——不能只加集合成员。

#### P2-1 [UI/语义] 备用槽的思考模式与思考强度被静默改写为 `enabled`/`max`，且不继承连接配置

**证据**
- 契约默认：`ai_runtime_settings.py:81-82, 87-88`（`thinking` 缺省 `"enabled"`、`reasoning_effort` 缺省 `"max"`）→ `:90-95` 归一化 → `AiFallbackRoute` 默认值 `:62-66`。
- 运行时无条件覆盖：`ai_task_runner.py:2303-2307` `replace(profile, thinking=route.thinking, reasoning_effort=route.reasoning_effort)`。
- UI 默认与硬编码：`App.jsx:2171-2175` 空槽默认 `{thinking:"enabled", reasoning_effort:"max"}`；`:2204-2209` 每次改强度都写死 `thinking: "enabled"`；备用行**没有"思考模式"控件**（对比主角色有，`App.jsx:2110-2136`）。

**推论（inference）**：把 MTPLX（内置 profile `reasoning_effort="medium"`，`ai_role_runtime_settings.py:257`；preset 同为 `medium`，`ai_runtime_settings.py:218`）拖进备用槽，实际会以 `max` 运行；用户若为主路由关掉了思考，同一连接作为备用仍会以 `enabled` 发送 `thinking` 参数（`ai_gateway.py:1191-1196` 会写入请求体）。

**测试缺口证据**：`tests/test_ai_fallback_chain.py:154` 让备用 profile 的 effort 恰好是 `"max"`，与 route 默认值相同，因此 `replace` 覆盖行为**根本没有被测试区分**（`:206-209` 断言 `("independent_ai__opencode","max")`，两种语义都会通过）。这是一个"看似覆盖、实际未覆盖"的假阳性测试。

**修复**：槽位缺省从所选连接继承（保存时把 profile 的 thinking/effort 写入 route，或运行时把"未指定"视为继承而非 `enabled/max`）；UI 增加思考模式控件并显示连接自带强度。

#### P2-2 [回执] chunk 路由回执缺 `expected_response_model` / `actual_response_model` / base_url

**证据**：`medical_writing_full_draft.py:1086-1098` `_run_route_receipt` 采集 provider/model/route_profile_id/identity_hash/thinking/effort/chain/depth/reason；而 run 上已有 `expected_response_model`（`ai_task_runner.py:2474`）与 `actual_response_model`（`:2955`），契约也定义了二者（`packages/contracts/workbench_contracts/models.py:505-506`），却未进回执。

**影响**：回执声称了路由身份，却缺少"观测到的模型身份"这一最强证据，无法证明 `_enforce_actual_response_model` 真的通过；chunk 级也无法从回执区分 loopback 与云端端点。**修复成本极低**：从 run 对象补三字段，无需新增采集。

#### P2-3 [provenance] `legacy_inferred` 回执以"冻结策略"代替观测，下游 `_result_route_identity` 不加区分

**证据**：`medical_writing_full_draft.py:1229-1255` 当旧 chunk 缺 `ai_route` 时，用 `expected["ai_policy"]` 推断 provider/model 并标 `legacy_inferred: true`；`:1100-1117` 汇总时只看 `(provider, model)`，不区分推断与观测。

**为什么当前仍然基本安全（inference，非代码强制）**：引入 ai_route 之前的构建根本没有 fallback，冻结主路由就是唯一可能产出该 chunk 的路由；Study A 的 18 个 OpenCode chunk 与此一致（`study_a_v10_route_receipt_reconciliation.json:19-24`）。

**残余风险**：同一 `schema_version`（`protocol_full_draft_chunk_v10`）下新增了 `ai_route` 字段而没有升版（见 P2-5），任何后续字段级演进都可能让"推断"输出一个从未运行的模型名，而任务结果仍以事实口吻报单一 provider/model。

**修复**：`ai_route` 契约变化时升 chunk schema；或在结果汇总里对含 `legacy_inferred` 的回执降级标注（如 `provider="mixed"` 或 `provider_unverified`），不要把推断当作单一身份。

#### P2-4 [审计] 持久化的失败诊断被 audit-safe 投影替换，运行期无法再机器化读取

**证据**：`ai_task_runner.py:2176-2184` `append` 写入的是 `audit_safe_ai_run(run)`；`:3448-3467` 只要 payload 不是 `SAFE_ARTIFACT_KEYS` 子集就整体替换为 `{output_hash, top_level_keys, finding_count, evidence_span_count}`。`provider_failure_diagnostics` 的 payload 形状是 `{"diagnostics": {...}}` → 被替换。

**影响**：落盘的 `http_status` / `failure_code` / `exception_type` 丢失；只剩子 run 顶层的 `fallback_reason`（如 `"provider_http_error:429"`）与自由文本 `error_message`。**运行期决策不受影响**（`_fallback_reason` 用的是 `_execute` 返回的内存对象），因此这不是功能缺陷，而是审计完整性缺口——验收文档"每次尝试持久化失败原因"的机器可读性被削弱。

**修复**：把 `failure_code` / `http_status` 这类已按构造可公开的字段加入安全投影白名单，或为其写一个专用脱敏投影。

#### P2-5 [兼容] chunk 产物无 legacy 通道；"旧任务兼容"只对最终工件成立

**证据**：`medical_writing_full_draft.py:49-60` 存在 `LEGACY_FULL_DRAFT_ARTIFACT_SCHEMAS`（v3–v9）供最终工件只读兼容；`_read_reusable_chunk:1004-1012` 要求 chunk 的 `schema_version` **精确等于** `protocol_full_draft_chunk_v10`，**没有** chunk 级 legacy 列表。

**影响**：v10 之前写出的 chunk 永不复用（会整批重算）。方向上是保守的（不信任缺回执的旧 chunk 路由），但与"旧任务兼容"的表述不完全一致；Study A 之所以能复用 18 个 chunk，是因为它们已是 v10 但**缺 `ai_route` 字段**——即"同 schema 加字段"，这正是需要 `legacy_inferred` 兜底的原因。

**修复**：明确写出契约（"旧版 chunk 一律重算"是合理政策，但应在文档/UI 说明）；若确实要跨版本复用，加 chunk legacy 集合并走已有的"无回执 → 推断 + 标注"分支。

#### P2-6 [UI] 备用槽不显示可达性/资格；API 允许 4 条而 UI 只呈现 2 槽

**证据**：`App.jsx:2170` 渲染 `[0, 1]`；`ai_runtime_settings.py:72` `max_length=4`；`main.py:3549-3560` 的 settings 载荷里 `fallback_chain` 原样透传，**没有任何逐路由健康信息**，而同一载荷对角色绑定是计算了 `availability`/`blocked_reason` 的（`ai_role_runtime_settings.py:686-764` 的 loopback 库存探测）。

**影响**：用户无法在真正生成前知道"第 1 备用没配 Key / 本机端口未监听 / 该连接不适用于医学写作任务"；只能靠跑失败来发现（`MODEL_ROUTING_2PLUS1_ACCEPTANCE_20260923.md:19` 正是这样发现的）。另外，若有人用 API 写了 3–4 条路由，UI 只显示前 2 条（状态里仍保留其余项，保存时不会丢，但用户看不见、也无法调整）。

**修复**：为每条 route 复用现有 loopback 探测与 key 配置检查，返回 `route_status`（reachable / api_key_missing / task_ineligible），并在 UI 第 2 槽之后按需渲染（或明确只支持 2 槽并把 API 上限对齐为 2）。

#### P2-7 [UX] 对"已停用连接"返回 404

`ai_runtime_settings.py:598-600` 对 missing 与 disabled 都抛 `KeyError` → `main.py:3659-3660` 统一映射为 `404 "fallback AI profile not found"`。连接其实存在，只是被停用；应是 422 并给出"该连接已停用"。低风险但会误导排障。

### 3. 逐项对照审阅目标

| 目标项 | 结论 | 依据 |
|---|---|---|
| 路由档案持久化与用户自选 provider/model/thinking/effort | 成立 | `App.jsx:2069-2136`；`main.py:3598-3698`；`ai_role_runtime_settings.py:550-585`（角色 upsert 会激活 profile 并隔离 role-scoped 副本） |
| 降级资格判定 | **有缺陷** | P1-1（不适用即终止）、P1-2（忽略 enabled） |
| canonical request 重建（不喂上一模型输出） | 成立 | `ai_task_runner.py:2309-2316 / 2354-2358` 用原始 `request`；repair envelope 仅限单次 attempt 内 |
| 逐次尝试审计血缘 | 基本成立 | `:2478-2481` 记录 chain/parent/depth/reason；缺口见 P2-2、P2-4 |
| registered / internal parity | 成立（含一处额外触发） | 两条路径共用 `_fallback_routes` 与同一闸门；registered 路径每次重解析注册来源，链路中途来源过期会触发 P1-1 的终止 |
| chunk/最终 provenance 与 `mixed` 摘要 | 实现成立，证据强度不足 | `medical_writing_full_draft.py:1086-1117, 1319-1345, 1439`；缺口 P2-2/P2-3/P2-5 |
| 旧任务兼容 | 契约层成立，chunk 层受限 | `models.py:502-513` 新字段均有默认值（旧 JSONL 可解析）；`test_ai_execution_policy.py:533` 覆盖旧库重写；缺口 P2-5 |
| UI 可理解性 | 部分不成立 | P2-1、P2-6、P1-3（无任务范围说明） |
| 错误分类（哪些失败该换模型） | 成立 | `ai_task_runner.py:2411-2431`；`ai_gateway.py:1293-1297` 身份不符用 `provider_response_model_mismatch`，**不在**降级集合内 ✔ |

### 4. 测试缺口（可直接落成用例）

1. 第 1 备用不适用、第 2 备用可用 → 期望链继续（当前会失败）。对应 P1-1。
2. 链中含 `enabled=False` 的连接 → 期望跳过/拒绝（当前会调用）。对应 P1-2。
3. `provider_transport_error` 与 `provider_response_empty` 触发降级（现有 3 个测试只覆盖 429/503）。
4. **不该降级**的反例：HTTP 400/401/403、`provider_response_model_mismatch`、内容/合同校验失败 → 断言 `fallback_depth == 0` 且只产生 1 个 run。身份不符这一条是验收文档明确承诺的行为，目前 runner 层无用例。
5. 备用的 thinking/effort 覆盖语义：把备用 profile 的 effort 设为 `medium`、route 设为 `max`（或反之），断言最终生效值；现 fixture 让两者相等，测试形同虚设。对应 P2-1。
6. chunk 级 `ai_route` 回执、`legacy_inferred` 回执、`_result_route_identity` 的 `mixed` 汇总——`tests/test_medical_writing_full_draft.py` 共 33 个用例，**零覆盖**。
7. 两槽（2+1）真实链：现有测试只有 1 个备用槽，无法证明 `fallback_depth=2` 与逐槽 reason 正确（该行为仅在 Study B/C 的真实运行 JSON 中体现）。
8. 旧 chunk（同 schema、缺 `ai_route`）被复用并标 `legacy_inferred`（Study A 只给了运行产物，没有回归用例）。

### 5. 我的反对意见、决策点与给 Codex 的有界问题

**最需要 Codex 决策的一点**：P1-1 到底是"有意的 fail-closed 策略"还是"漏写 continue"？我的判断是**当前形态不可接受**，理由不是"拒绝"本身，而是：同一循环里 `KeyError` 用 continue、策略拒绝用 return，两种语义无文档说明；并且拒绝原因对用户完全不可见。即使保留 fail-closed，也必须让原因可见。（安全兜底路径：若本轮不改控制流，至少在保存入口拒绝不适用的备用连接，使该状态无法产生。）

- **Q1**：备用槽"不适用"时的目标语义是 skip+记录，还是 abort+显式告警？若选后者，是否接受"以保存期资格校验防止状态产生"？
- **Q2**：`AI_FALLBACK_TASKS` 是否应扩展到 `COMPETITIVE_INTELLIGENCE` / `PROTOCOL_DESIGN_SYNTHESIS` / `PICOS_DESIGN_COACH`？若是，请对每个 task_type 先确认"能由原始 request 确定性重建（含 task_context 与来源集合）"。若否，请在 UI 与验收文档中写明范围，避免用户按"综合AI 一律降级"预期配置。安全暂定路径：维持现状代码，先修文档/UI 口径。
- **Q3**：备用槽的 thinking/effort 语义是"槽位独立"还是"继承连接"？若要槽位独立，UI 必须暴露思考模式控件（现在不能设置 disabled）；若要继承，需把缺省值语义从 `enabled/max` 改为"未指定=继承"。安全暂定路径：UI 选中连接时预填该连接已配置的 thinking/effort。
- **Q4**：`enabled=False` 的连接在备用槽应被拒绝还是跳过？（我建议跳过并记录，与 Q1 一致。）
- **Q5**：是否升 `protocol_full_draft_chunk` schema 以区分"带/不带 ai_route 的 v10"？若不升，请给 `legacy_inferred` 的推断合法性留一条可验证的约束（例如断言旧 chunk 的 run 无 `fallback_chain_id`）。

**另外两条挑战性意见**
- 验收文档把"chunk 与最终工件均有路由回执"表述为已完成能力，但 `legacy_inferred` 分支说明**旧 chunk 的回执是推断而非观测**；文档应显式区分，否则第三方审阅者会把它当作观测证据。
- 云端回退的边界说明缺失：以本机 MTPLX 为主路由的用户，其临床文档在 429 时会自动送往 OpenCode Go 与 CMS Router，而 UI 文案只讲"依次切换"、未讲"会离开本机"。这在单机私有部署语境下属于需要产品明确确认的口径（我未发现违反现有策略检查的地方：`_enforce_deployment_profile` 只比对 deployment_profile 字符串，主/备一致），因此列为**待 Codex 判定的口径问题而非代码缺陷**。

### 6. 不确定性 / 未验证

- **无法执行**：`git diff --check`、受影响 pytest 集、前端 production build——Bash 被拒，因此"这些行为在当前分支是否已被新测试覆盖"只能靠静态阅读判断。
- **无法证明"本次改动引入"**：我未取得 diff，P1-1/P2-1 等可能是既有行为。Codex 的 checklist 里"Reproduce each P0/P1/P2 finding directly from current code"必须逐条复核；若某条属既有行为，仍建议按上表修复，但归类应改为存量问题。
- **推测成分**：P1-1 的端到端后果（"第 2 槽从未被调用"）是基于代码路径的推演，未在真实服务上复现；建议 Codex 用一条最小复现（链 = [非适用连接, CMS Router]，主路由注入 429）确认。
- **未验证**：Study A/B/C 的 JSON 与代码生成逻辑是否完全一致（我逐字段比对了 `_run_route_receipt`、`_result_route_identity` 与三份 JSON 的形状，形状一致；但未验证这些 JSON 是由当前版本代码生成）。
- 未做临床/医学内容的实质判断（明确在 scope 之外）。

### 7. 建议的下一步（供 Codex 排序，非授权执行）

1. 复核并（若确认）修 P1-1 + P1-2：合并为"备用槽资格与启用状态在运行期按同一规则处理，且跳过原因可审计"，附带 2 个回归用例。
2. 决策 Q2，同步修 UI/文档口径（成本最低、消除用户预期落差）。
3. 修 P2-1（槽位默认值语义 + UI 思考模式控件），并把 §4.5 的假阳性测试改成能区分两种语义的版本。
4. 补 P2-2（回执三字段）——纯增益、零采集成本。
5. 决策 Q5 与 P2-3/P2-4/P2-5 的治理口径，再决定是否动 schema 与安全投影白名单。

---

以上为 `evidence_single_object` 的一次完整有界建议回合。未修改任何源码；最终代码、临床与用户可见验收由 Codex 持有。如需我就任一条（推荐 P1-1 的最小复现或 P2-1 的语义修正方案）做同会话定向补充，请指明条目。
