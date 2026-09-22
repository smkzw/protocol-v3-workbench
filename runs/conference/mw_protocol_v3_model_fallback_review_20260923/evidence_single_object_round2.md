Read-only verification round. Reading the current versions of the authorized files.

Verified. Writing the round-2 verdict to the plan file (the only file I may write).

## Round 2 Verdict — repairs verified by static review (no shell; no files edited)

**Closure status**

| # | Finding | Verdict | Evidence |
|---|---|---|---|
| P1-1 | 不适用备用槽终止整链 | **运行时已关闭**；可审计性仅部分 | `ai_task_runner.py:2322-2323`、`:2366-2367` 改为 `continue`（两条路径一致） |
| P1-2 | 已停用连接仍被执行 | **已关闭** | `:2306-2307`、`:2353-2354` 新增 `if not profile.enabled: continue`；UI 侧 `App.jsx:2176-2177` 过滤 `enabled !== false` |
| P1-3 | 降级范围仅 5 类任务 | **部分关闭** | 集合已扩展（`:79-88`），且 `PICOS_DESIGN_COACH` 确有 runner 路径（`evidence_ai_revision.py:235`）；但 `COMPETITIVE_INTELLIGENCE`、`PROTOCOL_DESIGN_SYNTHESIS` 的实际生产入口不走 runner（见下） |
| P2-1 | 备用槽强制 `enabled`/`max` | **UI 已关闭 / API 残留** | `App.jsx:2195-2196` 继承连接配置、`:2209-2240` 同时提供思考模式与强度；契约默认值 + 无条件 `replace`（`ai_runtime_settings.py:65-66,81-88`；`ai_task_runner.py:2308-2312,2355-2359`）在客户端省略字段时仍覆盖 |
| P2-2 | 回执缺模型/端点身份 | **已关闭** | `medical_writing_full_draft.py:1093-1099` 补 `route_base_url`、`expected_response_model`、`actual_response_model`；来源是已脱敏的 run 字段（`ai_task_runner.py:2480`），无凭据泄漏 |
| P2-6 | API 上限 4 vs UI 2 槽 | **已对齐** `ai_runtime_settings.py:72 max_length=2`；**逐路由可达性/资格反馈仍缺** |

**新发现问题（P2）**

- **P2-A 本轮新增的三个回执字段在 legacy 分支恒为空**：`medical_writing_full_draft.py:1253-1268` 从 `ai_policy`（即 `_policy_identity()`，`medical_writing.py:2519-2537`）取值，但该 dict **没有顶层 `thinking`/`reasoning_effort`/`profile_id`**，因此 `thinking`、`reasoning_effort`（本轮新增）与 `route_profile_id`（旧有）在复用的 Study A chunk 上均为 `""`；完整快照只存在于嵌套的 `route_identity_snapshot` 且未被读取。`actual_response_model: ""` 属诚实留空。修法是三处查表先取嵌套快照或直接删除这三个键，不需要升 schema。
- **新测试是同义反复**：`tests/test_ai_fallback_chain.py:363-368` 只断言集合成员，缺乏 run 级验证。
- **我在第 1 轮的 P1-3 证据存在误报**：`main.py:3716` 是 `/api/ai-gateway/probe` 的合成探针信封，不是真实方案设计调用。竞价分析两个生产入口（`medical_writing_competitor_triage.py:354-367`+`:4428-4433`、`medical_writing_corpus_analysis_ai.py:786-794,891`）直接调用 provider，**仍无自动降级**；`PROTOCOL_DESIGN_SYNTHESIS` 只在该探针出现。新增这两类仅在通用 `POST /api/projects/{id}/ai-runs/from-sources`（`main.py:4508-4524`）可达。`AI_FALLBACK_TASKS` 仅在 `ai_task_runner.py:2387` 被消费，故扩展本身无回归风险。

**未发现新的 P0/P1**（不涉及生成内容、路由安全或降级契约）。剩余项均为 P2：跳过无记录（`:2322-2323` 无任何痕迹，而 `_fallback_chain_id` 仍列出被跳过的 profile）、UI/载荷无逐路由资格与可达性提示（`:597-605` 与 `App.jsx:2176-2177` 仍允许选入不适用连接后被静默跳过）、API 省略字段仍强制 `enabled/max`、以及第 1 轮未处理的停用连接返回 404（`:598-600` → `main.py:3659-3660`）与失败诊断被 audit-safe 投影替换（`:2176-2184`、`:3448-3467`）。

**验证边界**：Bash 被拒，无法复现 `git diff --check`／pytest 集／前端 build，217 passed 与 5304 状态输出按所有权人报告采信；结论全部来自当前文件静态阅读。另：为确认跨模块分发与冻结策略键名，我窄幅阅读了授权清单外的 `medical_writing.py:2519-2537` 与 `evidence_ai_revision.py:231-239`，已在计划文件中标注。

plan file: `/Users/smkzw/.codebuddy/plans/blazing-vortex-darwin-tHuScYnB.md`

ExitPlanMode 被本会话权限拒绝（非交互模式无法弹窗授权），因此无法用它收尾；这不影响本轮交付：完整裁决已在上文返回，并已写入计划文件。

本轮结论无新增 P0/P1；待办为 6 项 P2（其中 P2-A 为本轮补丁引入的 legacy 回执空字段问题，`medical_writing_full_draft.py:1253-1263`）。若需要正式结束 plan 模式，请在交互终端确认退出，或由 Codex 直接按上述清单继续。
