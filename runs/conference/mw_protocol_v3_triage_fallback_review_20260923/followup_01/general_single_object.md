P1 实证成立，聚焦测试 3/3 复现。所有核查完毕，输出本轮完整报告。

# Conference Participant Output: mw_protocol_v3_triage_fallback_review_20260923 - general_single_object

## Boundary Check

- 同会话第三轮(continuation round 2)。工作树与本会话上一轮复审时**逐字节一致**(diff stat +381/+126/+5,HEAD 仍 `52f6654`,全部修复锚点行号未动)——即 repair batch 就是上轮已审的那批，本轮为对抗性复核，重点攻击“修复自身引入的新缺陷”。
- 全程只读；未写入报告路径；未读其他参会者输出；未联网；模型/思考级别未切换。复用上轮 `/tmp/triage_review_venv` 测试环境，无新环境改动。
- 更正一处我自己的取证瑕疵：前几轮我误用 `rg -rn`(`-r` 是替换标志)，导致一次输出出现 `n(` 伪影；本轮已用正确的 `rg -n` 重新取证相关调用点，结论未受影响。

## Independent Work Product

### 六项意图修复的核验结论

| 修复项 | 结论 | 关键证据 |
|---|---|---|
| P0-1 v1 路由可恢复 | **达成** | `_route_from_profile(profile, *, schema_version)`(`medical_writing_competitor_triage.py:4510-4532`)+ resume 按路由自身 schema 重建(`:4690-4693`);上轮实证：真实 profile 派生的 v1 fixture resume OK,负向对照(base_url 变更)仍拒绝；专项测试 `tests/…durable.py:2234-2256` 通过 |
| P1-1 冲突包装全覆盖 | **达成**(残余 P2-A 见下) | 三个 `create_or_reuse` 调用点全部改走包装(`:4411/:5163/:5202`;原始调用仅存于 `:4638`);包装器 `:4633-4640` 转 `CompetitorTriageConflictError`;端点映射 409(`main.py:8805-8806` 创建、`~8901` 重试);`store.retry` 按 job_id 重排不涉 hash |
| P2-1 attempted/active 分离 | **达成** | `_attempted_index`(`:439/:498/:509`),`_active` 返回最后尝试路由(`:470`);探针：链耗尽时归属 = B |
| P2-2 wrapper 携带 thinking/effort | **达成，但引入新 P1-A**(见下) | 转发 `:293-296`;v2 校验/v1 豁免不变(`:4571-4577`) |
| P2-3 chain_id 冻结源 + 丢弃留痕 | **达成** | `frozen_route_hashes`(`:433-446`;执行器传完整冻结链 `:3858-3864`);丢弃 warning 带 profile+hash(`:3850-3856`);专属话术(`:3820-3828`);探针：B 不可构建时 chain_id 不变 |
| mixed 标记 + 分片精确 provenance | **达成，残余 P2-B**(见下) | `:4761-4805`;AI 分片 provenance 排除确定性分片(`:4779-4783`) |

聚焦修复测试 3/3 复现通过(本轮实跑 OK);durable 文件 45/45 为上轮同树实证，仍然有效。

### 新发现 P1-A(由 P2-2 修复引入)：角色绑定 thinking/effort 与 profile 分歧时，triage 创建路径必然失败且报错误导

**证据链(每步均已核实)：**

1. 创建端点的 provider 来自角色环境:`_resolve_triage_provider`(`main.py:8764-8781`)用 `_runtime_role_context(INDEPENDENT_AI_ROLE)[2]` = `role_env` 构建,而 `role_env` 在 profile 基础上**用 binding 值覆盖** thinking/effort(`ai_role_runtime_settings.py:652-656`),并只强校验 model 一致(`:646-648`),不校验 thinking/effort。
2. 修复后 wrapper 转发 `default_thinking/default_reasoning_effort`(`medical_writing_competitor_triage.py:293-296`),创建期断言(`:4477-4478` 冻结 → `:4565-4577` 比较)从此**真实生效**：比较的是 binding.thinking vs route 冻结的 profile.thinking。
3. 分歧可达且属受支持配置:(a) `sync_independent_from_active` **仅在 activate 时调用**(`main.py:3630-3631` 的 `if request.activate`、`:3641-3643` 显式激活)——对已激活 profile 的普通编辑(请求默认 `activate=False`)修改 thinking/effort 后 binding 保持旧值;(b) `independent_ai` 本就在 `THINKING_CONFIGURABLE_ROLES` 中(`ai_role_runtime_settings.py:49-51`),公开载荷还广告 `thinking_configurable=true`(`:741`),角色级覆盖是设计内能力;(c) 次生触发:`normalized_binding` 对**所有角色**的空 effort 落 `"low"`(`:169`),与 profile 默认 `"max"` 分歧。
4. **实证**(真实 `_assert_provider_matches_route` + wrapper 形状对象)：binding thinking=`disabled` vs profile thinking=`enabled` → `create FAILS -> resolved provider identity does not match the frozen durable route...`。
5. 加重因素：该错误信息不打印 thinking/effort(仅 provider/model/base_url/transport/expected,`:4579-4587`),用户无法自诊；执行器路径用的是 `profile_env`(profile 语义,`:4707-4711`),所以这是创建断言与执行语义**源头不一致**，而非执行真的需要 binding 值。
6. 测试盲区：三个修复测试都经 `profile_provider_factory` 直调 service,不经过端点的 role wrapper,捕获不到此缺陷。

**严重级 P1 的理由**：回归由本批修复引入(修复前 wrapper 不带属性，断言为 no-op,创建成功)；经由受支持的配置流程可达；fail-closed 无数据损坏，但命中时 triage 功能整体不可用且报错误导。

**修复方向(供 Codex 裁决，推荐第 1 项)：**
1. triage 创建路径改用与冻结/执行同源的 env:在 `_resolve_triage_provider` 用 `profile_env(active_profile)`(或 `_independent_ai_profile` 语义)构建 provider,而非 `role_env`——模型/base_url/密钥本就来自 profile(binding.model==profile.model 被强制)，仅 thinking/effort 换源即可对齐三方(创建断言=冻结=执行)；其他角色/功能不受影响。
2. 保守替代：保留 role_env 预检，但创建断言对 profile_env 构建的影子 provider 执行。
3. 最弱替代：把分歧在 `role_env` 提前显式报错——把误导失败变清晰失败，但配置仍不可用，不推荐单独采用。
无论选哪项，应同时把 thinking/effort 加进 `:4579-4587` 的 mismatch 消息(顺带解决 P2-C)。

### 新发现 P2(修复引入或放大，均有行号)

**P2-A 遗留 job 行使创建端点对同输入永久 409(升级窗口内)。** `create_or_reuse` 按 (project, job_type, business_key) 匹配**任意状态**行(`medical_writing_durable_jobs.py:319-332`,无状态过滤)；跨版本遗留行(v1 hash,无 fallback hash)与新请求 hash 结构性恒异 → 同 snapshot+input 重经创建端点永远 409("business key reused with a different request hash"),取消/完成都不清除行。缓解现实：可操作状态都有工作路径(重试端点终态分支用不同 business_key,`:5124-5163`);已完成的遗留运行本就无需重建。建议：发说明注明升级后同输入请走重试端点，或后续加一次性的 v1 行迁移/放行策略。不升级为 P1 的原因：有逃生通道且影响限于跨版本重复提交。

**P2-B 跨提供方 repair 使 mixed 低报。** 分片初始响应来自 A、验证发现可修复缺 ID、repair 调用经链落到 B(`:4971-4973`)→ 分片 provenance.provider=最后尝试者 B(`:4998-5000`),但最终 results 同时含 A 的 present_results 与 B 的 repaired_results(`:4981-4985`)。run 收尾 `route_identities` 只见 provenance(`:4795-4799`)→ 该 run 不标 mixed,尽管 A 贡献了部分最终结论(其材料仍在分片 canonical_output_hash 内，`:5004` 审计链完整)。影响：混合标记在 repair×fallback 交叠的低频场景下低估混用；建议在 provenance 增补 repair 路由字段或在 `route_identities` 计入 repair 来源(窄改)。

**P2-C 身份不匹配信息缺 thinking/effort**(`:4579-4587`)——独立成 P2 是因为它同时加重 P1-A 与任何 v2 thinking 漂移的诊断成本；修复代价一行。

**P2-D(沿用上轮，未变)**：升级回滚边界(v2 行在 HEAD 代码 parse 即拒)需发布说明；链耗尽失败分片 `fallback_depth` 取最后成功路由索引而 reason 非空的软语义(`:488-490` vs `:505`)。

**P0 清单：空。P1 清单：仅 P1-A。**

### 逐项回答 Codex 点名的三个高危区

- **legacy hash 重建**：未发现新缺陷。v1 重建经真实 profile 字段派生(上轮修正探针后 OK + 负向对照拒绝)；v1 payload 混入 thinking 字段被身份排除、字段校验仍拦越界值(`:231-234`);revision 漂移在 `:4678` 先于身份报错(信息更准)。
- **request-conflict 覆盖**：三个调用点全覆盖、端点 409、`store.retry` 无此异常面；仅余 P2-A 的遗留行锁死(有逃生通道)。
- **mixed-run 收尾**：确定性分片正确排除、全确定性 run 走 `deterministic_registry_rules` 身份(与 `:4063` 消费一致)、复合哈希按 chunks 稳定序、PARTIAL_FAILED 同样正确标记；唯一缺口是 P2-B 的 repair 低报。

## Evidence And Assumptions

**本轮实证：**
1. 探针(真实类方法，一次性 `python3 -c`):分歧 binding thinking → `create FAILS -> resolved provider identity does not match the frozen durable route...`(P1-A 决定性证据)。
2. 聚焦修复测试 3/3 OK(实跑)。
3. 工作树一致性：diff stat 与全部锚点行号同上轮(498/509/3860/4510/4633/4692/4802/4808)。
4. 代码行证据：wrapper 转发 `:293-296`;role_env 覆盖与 model-only 校验 `ai_role_runtime_settings.py:646-656`;sync 仅 activate(`main.py:3630-3643`);THINKING_CONFIGURABLE_ROLES `ai_role_runtime_settings.py:49-51`;effort "low" 兜底 `:169`;create_or_reuse 任意状态匹配 `medical_writing_durable_jobs.py:319-332`;repair/mixed `:4971-5010/:4795-4806`。

**推断与不确定性(分列)：**
- **推断**:P1-A 的触发路径 (a)(激活后普通编辑)基于端点代码语义推断，未在真实服务端复现 HTTP 422 全链路(需要起服务，超出本角色边界)；断言层失败已实证，端点映射(`CompetitorTriageError→422`,`main.py:8812-8813`)为直读代码。
- **不确定**：前端编辑已激活 profile 时是否惯例性发送 `activate=true`(前端不在读集)——若总是发送，触发路径 (a) 被关闭，剩余触发为角色级 thinking 覆盖与遗留空 effort 绑定，P1-A 严重级可复议降 P2;请 Codex 结合前端行为裁决。
- **假设**：合并 triage 家族(457+2=459)与 Protocol v3 全回归由主会场负责，本环境仅实证 durable 文件 45/45。

## Risks, Gaps, And Verification Needs

1. **P1-A 修复前，任何 binding/profile thinking/effort 分歧的部署都无法发起新 triage**,且报错误导。最可能的实际暴露面：激活 profile 后改 thinking 不重新激活、或用户设置角色级 thinking 覆盖。
2. **验证需求**:(a) 修复 P1-A 后补一个“角色 wrapper vs profile 路由”的创建路径测试(现有测试绕过端点层，正是漏网原因);(b) mixed 标记的出口呈现(前端/API 字段消费)确认;(c) durable worker 租约 vs 链满配最坏时延(连续第三轮提出，仍未有答案，建议纳入验收清单而不是继续挂在会话问题里)。
3. **测试缺口(维持)**：资格白名单负向用例(invalid_json/400/非 AiProviderRuntimeError 不切换)仍未建；这是未来改 `TRIAGE_FALLBACK_HTTP_STATUSES`/`_fallback_reason` 时的唯一回归防线。
4. 若 Codex 采纳 P1-A 修复方向 1,注意连带：角色 thinking 覆盖对 triage 将不再生效(与 durable 执行现状一致)，需在角色设置 UI 文案上说明，避免用户以为覆盖对 triage 有效。

## Recommended Next Step

1. **先修 P1-A 再提交**(推荐方向 1:`_resolve_triage_provider` 改用 profile_env 语义构建 triage provider),同时把 thinking/effort 加入 `:4579-4587` 的 mismatch 消息(解决 P2-C);补一个经过端点层 wrapper 的创建测试。若 Codex 判定前端恒发 activate、角色覆盖不存在，可降级处理，但请给出该前提的依据。
2. 同批可带 P2-B(provenance 记录 repair 来源或 route_identities 计入)与 P2-A 的发布说明；负向资格测试建议同批(窄改、独立)。
3. 修复后主会场复跑：聚焦 3 例 + triage 家族全量(预期 459+新增) + Protocol v3 全回归。
4. 验收清单请纳入：mixed 出口呈现确认、durable 租约预算核对(第三轮提出)。

**有界问题(同会话可答)：**
- **Q5(裁 P1-A 走向)**：前端/工具链编辑已激活 profile 时是否恒发 `activate=true`?角色设置是否存在 independent_ai thinking 的直写入口？答案决定 P1-A 是“必修”还是“降 P2 + 文档约束”。
- **Q6**:triage 的 thinking/effort 语义源应统一为 profile(我的推荐)还是 binding?若统一为 binding,执行器(`:4707-4711` profile_env)也要换源，属于更大语义变更，需要产品确认。

**阻塞与恢复点**：无阻塞。本报告完整，可由 runner 直接持久化。合并 459 例与 v3 全回归留待主会场(见 Risks §2)。
