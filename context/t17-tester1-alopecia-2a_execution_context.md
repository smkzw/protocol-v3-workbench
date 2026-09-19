# Execution Context: t17-tester1-alopecia-2a

Created: 2026-09-19 20:22:39 CST
Objective: 以真实用户身份使用ego(lite)浏览器在 http://127.0.0.1:5176 完成中重度斑秃II期方案的端到端写作（入口A：上传竞品调研摘要docx作为公司风格参考+写作说明），全程禁止直连后端API，只能页面点选；完成或到达时限后输出报告
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

1. 场景1入口A：上传摘要文件+说明→整理→逐卡确认关键设计（随机双盲安慰剂对照/12周/SALT评分主要终点）→设计要素确认→生成完整初稿→保存→导出Word→在浏览器Office中打开并做一处编辑保存
2. 报告格式：SOURCE_HEAD/PASSED/FAILED/NOT_RUN/KNOWN_LIMITATIONS+每步截图+发现的全部问题清单（按P0/P1/P2）

## Completion And Cleanup

Codex reviews worker outputs and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.

## 补充（主线程注入）

- 场景1需上传的"竞品调研摘要docx"可使用现成夹具：`runs/mw_protocol_v3_v1_1_20260913/browser_functional/synthetic-reference.docx`（合成资料，仅作上传通道与来源角色验证用）。
- 前端 5176 的 /api 已代理到隔离后端 5275；禁止绕过页面直接 curl 后端。
- 项目建项时的项目名自定（含"斑秃"字样便于辨识）。
- 若"生成完整初稿"因模型耗时较长，等待页面完成即可，不要超时打断；如实记录各步骤实际耗时。
