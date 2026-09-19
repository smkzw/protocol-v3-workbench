# Execution Context: t17-tester2-migraine-3b

Created: 2026-09-19 20:23:28 CST
Objective: 以真实用户身份使用ego(lite)浏览器在 http://127.0.0.1:5176 完成慢性偏头痛预防性治疗III期方案的端到端写作（入口B：零附件，仅写作说明），全程禁止直连后端API，只能页面点选；完成或到达时限后输出报告
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

1. 场景2入口B：不传任何文件，写作说明输入（合成药M CGRP单抗/随机双盲/24周/主要终点每月偏头痛天数较基线变化）→整理→AI设计选项逐卡点选确认→生成完整初稿→保存→导出Word；注意样本量假设不得出现其他疾病数值
2. 报告格式：SOURCE_HEAD/PASSED/FAILED/NOT_RUN/KNOWN_LIMITATIONS+每步截图+发现的问题清单（P0/P1/P2）

## Completion And Cleanup

Codex reviews worker outputs and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.
