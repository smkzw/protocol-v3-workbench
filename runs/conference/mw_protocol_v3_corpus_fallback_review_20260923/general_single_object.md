两个执行检查均已通过。旧的 no-options 分支在新的 resolve logic 下保持了 identity 和 dedupe 完好无损，并且 tampered chain 因错误被拒绝关闭。我正在撰写最终的 round-3 报告。

# 会议参与者输出：mw_protocol_v3_corpus_fallback_review_20260923 - general_single_object

## 边界检查

- 与本次会议的第 1–2 轮在同一 runner 绑定的工作区内工作。本次的证据来源：当前的未提交 diff（确认自第 2 轮验证以来未变更 — corpus 模块 diff sha256 前缀 `d85345ce91867d84`），上述重点测试，以及两个新的执行检查（`/tmp/mwca_legacy_tamper_repro.py`，只读 vs 仓库源码）。没有生产/运行时数据文件，没有参与者输出，没有互联网，没有源码修改，没有写入 runner 管理的报告路径。
- 环境副作用未变：一次性的 `/tmp/mwca_review_venv`。Codex 保留最终权限；本报告未声明最终验收。

## 独立工作产物

**结论：Codex 的修复按照描述确切地关闭了我之前报告的两项高严重性发现以及两个中/低严重性缺口，我在这轮工作中通过执行（而不仅仅是阅读）验证了它们没有引入旧版兼容性或身份漏洞。剩下零个可操作的缺陷。还有两个可选的加固项（失败时的中间尝试溯源；三个失败关闭的拒绝路径仍未被测试套件覆盖 — 尽管我现在已经亲自执行了其中最重要的一个，并且它正确地失败了）。**

### 修复验证（每一项都有确切证据）

1. **通过 frozen-route 选项进行的 `_resolve_frozen_provider` 重建 — 已关闭，已通过执行验证。** medical_writing_corpus_analysis_ai.py:988–996 构建了 `effective_profile = replace(profile, thinking=route.thinking or profile.thinking, reasoning_effort=route.reasoning_effort or profile.reasoning_effort)`，只要路由声明了选项，就会从中构建提供程序；身份比较和 `_assert_provider_matches_route` 随后将提供程序固定到 frozen 路由。第 2 轮的复现（配置文件 `enabled`/`max`，路由声明为 `disabled`/`low`，主要 429）：`analyze OK; effective route: independent_ai__cms_router` — 此前它会跳过回退并失败。升级后的 `test_corpus_analysis_uses_frozen_fallback_after_primary_429` 驱动了相同的场景（覆盖为 `reasoning_effort="low"`，而存储的配置文件默认为 `"max"`），并断言 frozen 链路由和 `effective_ai_route` 都带有 `"low"`。
2. **冻结跳过重复/不可用的可选回退 — 已关闭，已通过执行验证。** 第 528–535 行的 `seen_profile_ids` 去重，加上第 546–567 行每个条目的 `try/except CorpusAnalysisAiError → continue`。我修正后的复现（健康的主服务；云回退缺少凭据）：`freeze OK; chain routes: []`。新测试 `test_route_freeze_skips_unavailable_optional_fallback` 断言主服务正常冻结，`routes == []`，`fallback_chain_id == ""`。
3. **结果中持久化的完整链负载 — 已关闭。** 结果现在嵌入了 `fallback_chain`（模式 + 每个路由的审计），以及 `fallback_chain_id`/`depth`/`reason`（第 693–704 行），通过 `result_json` 持久化；运行记录是自包含的，解释了审计详情的 `route_identity_hash`（主）与 `provider`/`model`（有效）的划分。
4. **测试：** 429 测试已升级以进行覆盖，新的跳过测试已落地，400 非回退测试未变且通过。完整文件：`59 passed`。

### 漏洞检查（任务要求：无旧版兼容性或身份漏洞）

每一项候选漏洞要么经过代码验证，要么经过执行验证：

- **通过新解析逻辑的旧版无选项路由（思维时代之前的身份形态）。** 重要性：修复程序在每个已声明选项的路由上添加了 `replace(...)` 分支；旧版有效负载没有选项，绝对不能被干扰。已执行（检查 A）：无选项提供程序 → 冻结产生一个**没有** `thinking`/`reasoning_effort` 键的负载；`analyze` 通过未更改的 `base_route.identity_hash` 分支成功；第二次分析去重到**相同**的 `analysis_id`，只有一个提供程序调用。
- **部署前冻结的链式与无链式有效负载。** 字段选择性 `parse` + 空链 → `""` 链 id → `analysis_id` 公式与部署前字节相同（第 1 轮验证，本报告未更改；59 个测试套件主要是部署前的测试，且全部通过）。
- **主路由上的选项覆盖分支。** 无操作（No-op）：现代主路由冻结时其选项等于提供程序默认值；任何配置文件更改（包括思考/努力）都会在构建提供程序之前，在 `medical_writing_corpus_analysis_ai.py:983–986` 处增加被检查的修订版本。选项覆盖仅对回退条目有效 — 正好是预期的范围。
- **篡改的冻结链。** 已执行（检查 B）：在冻结负载中翻转已声明的回退努力 → 每个路由的标识哈希检查在 `_parse_fallback_routes` 内部触发，并在任何提供程序调用之前以关闭失败的方式引发 `frozen corpus-analysis fallback route is malformed`。（单独篡改链 id 会产生 `identity mismatch` 变体；两者都以关闭失败的方式失败。）
- **保留修订/非选项身份检查。** 已确认：删除/修订检查在选项处理之前；`_assert_provider_matches_route` 仍然固定提供程序/模型/base_url/传输/预期响应模型，以及在声明时固定选项。
- **由冻结时间跳过引入的新方差。** 现在的冻结链取决于冻结时刻的凭据可用性，因此瞬时密钥中断会产生一个较短的链（以及给定输入的不同 `analysis_id`），直到下一次冻结。这是代码注释中所述的文档权衡（"later credential repair applies to newly frozen work"） — 语义，而非缺陷。
- **附加结果键。** `fallback_chain` 在 `result_json` 中是附加的；没有任何消费者破坏性地读取它，旧的不可变行只是缺少该键；将该结果字典重新解析为路由负载的假设路径将无法关闭（KeyError → `CorpusAnalysisAiError`），并且没有代码路径这样做。

### 决策接受

记录为已解决：支持路由级覆盖（修复与我的建议 1 完全匹配）；语料库配置文件级冻结选项是有意的（R1 已关闭 — `main.py` 移除保持原样，预填充适配器保留绑定级选项，故意拆分）；401/403 仍为非回退配置/认证失败（R2a 已关闭）；408 直接进入下一个冻结的提供程序，没有同一提供程序的重试（R2b 已关闭 — 这是补充网关重试集 `{429,500,502,503,504}` 的正确语义）。

## 证据与假设

**本次运行的证据：** diff 签名未变 `d85345ce91867d84`（语料库 +226，主 `main` 11 行未更改，测试 +243）；`59 passed in 0.44s`；`/tmp/mwca_legacy_tamper_repro.py` 输出 — 检查 A：`frozen thinking/effort keys present: False False` / `analyze OK; dedupe: True ; provider calls: 1`；检查 B：`tamper rejected: frozen corpus-analysis fallback route is malformed`。修复区域本报告早些时候已阅读并引用（medical_writing_corpus_analysis_ai.py:528–567, 693–704, 988–996; tests:517–541, 549–612）。第 1–2 轮的证据库（网关诊断分类，存储合约，生产连接）未重新审阅，因为其区域未更改（diff 哈希值相同）。

**不确定（已标记，非阻塞）：** 我没有运行更广泛的 Protocol v3 套件或端到端流水线回归（主会议清单项目）；我没有对修复后的冻结/分析对进行并发冻结测试；前端限制路由级覆盖未重新检查（存储/API 契约允许它们，修复程序支持它们，这是重要的问题）。

## 风险、差距与验证需求

**剩余的可操作缺陷：无。**

可选加固，两者都不阻塞：
1. **中间尝试溯源（之前为 R3）。** 在总链失败时，只有最后一个路由的错误诊断持久化到流水线 `analysis_context` 中；中间的每个路由失败（例如，路由 1 为 429，路由 2 为 400）没有留下持久的追踪记录。确切位置：`_run_with_fallback` 丢弃了除最后一个 `last_error` 之外的所有内容；流水线只持久化引发异常的异常诊断。证据：medical_writing_corpus_analysis_ai.py:929–950；medical_writing_research_pipeline.py:4838–4850。修复（如果需要）：在引发异常前，将 `[(depth, profile_id, reason)]` 的列表附加到引发的异常的诊断信息中。
2. **拒绝路径测试覆盖率（之前为 R4，现为信息性）。** 篡改/重复/格式错误的链拒绝路径未涵盖在测试套件中（grep 计数为 0），但篡改路径现在已被我执行，并以关闭失败的方式失败；重复创建在结构上被冻结时去重阻止；格式错误的路径通过检查验证为关闭失败。如果 Codex 需要回归锁定，检查 B 可原样转换为 pytest。

**提交前的主会议验证需求（根据计划，我未运行）：** 完整的 Protocol v3 套件和重点关注的语料库/流水线回归；一个针对真实存储的可选临时集成检查（通过 `AiFallbackChainUpdateRequest` 设置 → 冻结 → 主要 429 → 回退服务 → 持久化 `fallback_reason`/`effective_ai_route`）。

## 建议的下一步

提交已准备就绪，在我的授权范围内没有任何遗留问题：所有四项修复均已验证关闭并带有执行证据，所有四个决策均已合并，且漏洞检查（旧版标识、篡改、修订保留）通过。Codex 按照清单运行更广泛的套件并提交；如果需要上述两个可选项，它们是小的、独立的添加项，可根据要求在此会话中进行规范（此会话可恢复；复现脚本位于 `/tmp/mwca_fallback_repro.py` 和 `/tmp/mwca_legacy_tamper_repro.py`）。
