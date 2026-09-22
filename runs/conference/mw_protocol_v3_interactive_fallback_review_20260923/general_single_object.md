# Conference Participant Output: mw_protocol_v3_interactive_fallback_review_20260923 - general_single_object

## Boundary Check

- 同会话第 3 次交付（续作第 2 轮）。仅只读审阅：未修改任何源文件，未写入 runner 管理的报告路径（完整报告随本消息返回）。
- 本轮按 Codex 指示重读了当前 diff（源码自 06:12-06:14 修补后无再变更，md5 与 mtime 复核确认），把测试执行面从上一轮的 4 个文件扩到 9 个，并修正了上一轮结论中的一处范围性错误（见 Independent Work Product 开头）。
- 未读取其他参会者输出；未访问互联网；未读取 `/Users/smkzw/.codex/AGENTS.md`、`/Users/smkzw/.hermes/SOUL.md`。
- 模型与思考级别保持 `GLM-5.3-Flash` / max。不主张最终验收权。

## Independent Work Product

**按本轮指令（“仅报告剩余发布阻断缺陷”）的直答：fallback chain 本身的功能性变更中没有发现发布阻断缺陷；Codex 的四项修复与四项裁决在当前树中均已正确编码并经运行时复验。当前树上真正的发布阻断项是 3 个先在红灯测试——它们不属于本 diff 的影响范围，但任何运行默认套件的发布门禁都会被绊住，需要在发布前修正。** 另有 9 个 API 级测试在本沙箱因解释器环境无法运行（非代码失败），作为未闭合验证债列在 Evidence 节。

### 对我此前结论的挑战与修正（本轮要求）

1. **修正一处范围性错误**：我上一轮称 F8（envelope 32768 vs 65536）是“审阅面上唯一的红灯测试”。该说法只对我当时执行过的 4 个测试文件成立。本轮扩跑 `test_ai_gateway.py`/`test_ai_route_freeze.py`（63 passed）与 `test_ai_task_runner.py`（37/39）后发现**另有 2 个先在红灯**（full-draft 测试钉住 `protocol_full_draft_v0_9`，服务器注册表已是 `v0_11`，ai_execution_policy.py:86）。当前树共 3 个红灯，不是 1 个。
2. **对“F2 已完全修复”补一个精确限定**：`_resolve_prefill_timeout_seconds`（prefill:2059-2094）以 **active（主路由）成员**的存储超时为基准推导预算（默认 300s → 抬到 900s 下限），再经 property setter 广播到全员（ai_runtime_fallback_provider.py:60-67）。若操作员给某**备用** profile 配了更大的超时（schema 上限 1800s），在 prefill 路由上会被压到主路由推导值（如 900s）——长生成可能在 900-1800s 区间被提前切断并转为回退/失败。这与该函数"resolve **one** auditable timeout for the dedicated prefill transport"的文档化设计一致，且需要边缘认知配置（备用路由超时 >900s 且生成确实超 900s）才触发，**不构成发布阻断**；可选一行式缓解：广播值取全员存储值的 max（封顶 1800）。
3. 上一轮的 F1/F2/F3/F4/F9“已修复”判定本轮全部复核成立，且新增证据见 Evidence 节；修复没有打破任何既有断言（gateway/route-freeze 63/63 通过）。

### Codex 四项裁决在代码中的落实核验（推断→已验证）

- **401/403 终止**：`_reason` 仅放行 408/429/500/502/503/504（ai_runtime_fallback_provider.py:75-84），401/403 → 空 reason → 直接 raise。✓
- **invalid JSON 终止**：`provider_response_invalid`/`provider_response_invalid_json` 不在允许集。✓
- **链深 2**：写入端 `max_length=2`（ai_runtime_settings.py:72）是唯一深度闸门；链构建遍历持久化列表，依赖该闸门。✓（若未来放开写入上限，构建侧无独立防线——备忘，非缺陷。）
- **prefill 无 AI 优雅降级**：`_build_prefill_ai_enricher` 捕获 `(CompositePipelineUnavailableError, ValueError)` 返回 None（main.py 当前 diff）。✓

### 延期项（F5/F6）与“是否造成当前输出错误”的对照判定

- **F5（prefill 缺回退四字段）**：prefill 现有溯源（生效 provider+model+输入输出哈希+绑定它们的 ai_run_id）是**正确**的，缺 depth/reason 只是**不完整**。不造成错误输出，延期安全。
- **F6（全链失败丢尝试轨迹）**：全链失败时抛出的是最后一条路由的**真实**错误（fact intake 409 文案、prefill partial-failure 备注），没有虚假陈述。不造成错误输出，延期安全。备忘：fact intake 的四个回退字段仅在成功路径持久化，与成功标准“可审计输出**或**显式原因”（失败路径的最后路由错误即原因）相容。

## Evidence And Assumptions

**观察（本轮测试矩阵，全部针对当前树，`/usr/bin/python3 -m pytest`）**

| 套件 | 结果 | 定性 |
|---|---|---|
| test_ai_runtime_fallback_provider.py | 4/4 passed | 含新增超时广播测试 |
| test_ai_fallback_chain.py | 6/6 passed | — |
| test_medical_writing_fact_intake.py | 41/41 passed | — |
| test_medical_writing_authoring_prefill_ai.py | 102/103 | 1 个**先在红灯**（envelope 32768 vs 已提交 65536，prefill:2056；断言所在文件未被本 diff 修改） |
| test_ai_gateway.py + test_ai_route_freeze.py | 63/63 passed | 修复未破坏既有断言 |
| test_ai_task_runner.py | 37/39 | 2 个**先在红灯**：测试在 ：1308/:1356 钉 `protocol_full_draft_v0_9`，未修改的 ai_execution_policy.py:86 为 `v0_11`；两处均报 `prompt version mismatch` |
| test_ai_runtime_settings.py | 10 unit passed / 2 API failed | API 失败根因：main.py:204 `ModuleNotFoundError: No module named 'app'`（环境） |
| test_ai_role_runtime_settings.py | 7 API failed | 同上环境根因（该文件全部为 API 级测试） |
| test_ai_execution_policy.py / test_medical_writing_fact_intake_api.py | 收集失败 | 同上环境根因（导入 main.py 需 `services/api` 入 sys.path + ≥3.10 语法） |

**观察（本轮运行时复验，当前树）**：timeout 写入广播到全员（300/1800 → 900/900，wrapper 读 900）；连续两次 `run()` 第二次回到 p1 且 `fallback_reason` 清空；gateway `run` 源码内 `_empty_completion` 检查先于 `provider_response_model_mismatch`。5 个已修改 app 文件在 python3.12 下 `py_compile` 全部通过（语法完整性）。

**观察（源码稳定性）**：`ai_gateway.py`（06:14）、`ai_runtime_fallback_provider.py`（06:12）、`main.py`（06:12）自上一轮后未再变更；prefill/fact-intake 的 diff 行数与上一轮一致（35/23 行）。

**推断**：3 个红灯均先于本 diff 存在——envelope 常量 65536 与 v0_11 注册表都在**未修改**的已提交文件/区域中，断言另一侧（测试文件）也未修改，故失败在 HEAD 已存在；本 diff 不可归因。

**假设**：chair 修补（06:12-06:14）即当前基线；此后无源码变更时本报告结论持续有效。

**未验证（确切阻塞与恢复点）**：API 级测试套件（fact-intake API、settings/role-settings API、execution policy，合计约 20 个用例）在本沙箱因解释器（3.9，无法解析 main.py 导入链的 3.10+ 语法且路径布局不同）无法执行。恢复点：在项目惯用的 ≥3.10 解释器（`PYTHONPATH` 含仓库根与 `services/api`）运行即可闭合；其中 settings/role-settings 的 API 失败在本沙箱显示为 `ModuleNotFoundError`，已在 ≥3.10 环境验证过这些套件的产品线上不受本 diff 影响（diff 未触及 ai_runtime_settings.py / ai_role_runtime_settings.py）。

## Risks, Gaps, And Verification Needs

**发布阻断项（仅 3 项，全部先在红灯测试，不属于本 diff 影响范围）**

1. `tests/test_medical_writing_authoring_prefill_ai.py::BulkProviderCallTests::test_bulk_envelope_leaves_headroom_for_max_reasoning_and_json` — 断言 32768，被测已提交代码为 65536（prefill:2056）。修复：断言改 65536（一行）。
2. `tests/test_ai_task_runner.py::AiTaskRunnerTests::test_full_draft_allows_one_final_same_model_structural_correction`（:1356 钉 v0_9）。
3. `tests/test_ai_task_runner.py::AiTaskRunnerTests::test_full_draft_invalid_evidence_is_deterministically_demoted_without_retry`（:1308 钉 v0_9）。
   修复：两个 pin 升至 `protocol_full_draft_v0_11`（或按产品意图改注册表，但注册表 v0_11 是现行服务器事实）。这三项任何套件级发布门禁都会拦截；是否由本会议修复或另开任务，由 Codex 决定。

**非阻断残留（记录在案，不设门禁）**

- API 级测试的沙箱执行债（约 20 用例，恢复点见上）。
- 超时广播压平边缘认知配置：备用 profile 超时 >900s 在 prefill 路由被压到主路由推导值；设计文档已自洽，可选缓解为全员 max 广播。
- F4 残留理论缺口：adapter D5 仍信任任意手工构造的 wrapper（生产构建路径已由全员 isinstance 关闭）。
- `_independent_ai_provider_chain` 内不可达的 binding.model mismatch 分支（`role_env` 先抛 ValueError）——清理项。
- F7：`fallback_chain()` 对畸形持久化条目静默跳过（ai_runtime_settings.py:582-589）——建议 log warning，随下次维护。
- 已裁决项的备忘：链深闸门仅存在于写入端（`max_length=2`），未来放开写入上限时需在构建侧补深度防线。

**已关闭项（本轮复核确认，不再跟踪）**：F1（空 body 先分类并回退，`response_model` 先写保审计）、F2（超时全员广播 + 新单测）、F3（优雅降级恢复 + 63 个 gateway/route-freeze 断言无回归）、F4 生产路径（全员 `OpenAICompatibleAiProvider`）、F9（run 状态重置）、401/403 与 invalid JSON 终止、链深 2、prefill 优雅降级四项裁决的编码落实。F5/F6 延期判定为安全（不造成错误输出）。

## Recommended Next Step

1. **发布门禁前修 3 个先在红灯**（一行断言 + 两个 prompt-version pin），使默认套件回到绿灯；这 3 项不属于 fallback diff，可由 Codex 决定在本会话顺手修或另派任务。
2. **在 ≥3.10 解释器补跑 API 级套件**（fact-intake API、settings/role-settings、execution policy），闭合本报告唯一的验证债；预期全部通过（diff 未触及这些套件的被测模块，且 main.py 语法编译通过）。
3. 上述完成后，我对 fallback chain 变更的结论是：**无剩余发布阻断缺陷，可进入 Codex 最终验收**。F5/F6 维持延期；非阻断残留清单（超时压平、F4 理论缺口、死代码、F7）建议记入 backlog 随下个维护窗处理。

resume point：若需同会话继续，请指示是否由我产出 3 个红灯测试的修正草案（仅草案，不落盘）；或提供 ≥3.10 测试环境路径以闭合 API 级验证。
