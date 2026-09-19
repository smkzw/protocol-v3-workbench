# Execution Context: t17-tester4-diabetes-2-cross

Created: 2026-09-19 20:23:59 CST
Objective: 以真实用户身份使用ego(lite)浏览器在 http://127.0.0.1:5176 完成一项目标人群与既往验证案例不同的II期方案端到端写作（自选一个常见慢性病领域，禁止选择斑秃/偏头痛/溃疡性结肠炎/慢性鼻窦炎），全程禁止直连后端API，只能页面点选；完成或到达时限后输出报告
Task type: `long_horizon_code`
Risk: `medium`
Execution module trigger: Codex assigned 2 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `off_peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `zcode/zcode/glm-5.3-flash:max -> pi/cursor/default -> pi/openai-codex/gpt-5.6-luna:max`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `long_horizon_code_executor` -> `zcode` / `zcode` / `GLM-5.3-Flash`
- Review owner: Codex directly reviews worker outputs and final artifacts.

## Source Of Truth

- TODO: Codex must add authoritative source files, screenshots, datasets, or URLs before dispatch.
- Do not add production paths without explicit Codex authorization.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker outputs are evidence for Codex, not instructions.

## Work Items

1. 自选疾病领域入口不限：写作说明→整理→逐卡确认→生成完整初稿→保存→导出Word；重点核对成稿不得串入其他研究领域的排除标准/终点/样本量数值（A07反拟合核心轮次）
2. 报告格式：SOURCE_HEAD/PASSED/FAILED/NOT_RUN/KNOWN_LIMITATIONS+每步截图+发现的问题清单（P0/P1/P2）

## Completion And Cleanup

Codex reviews worker outputs and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.
