# Execution Context: mw_protocol_v3_ordered_draft_20260913

Created: 2026-09-13 18:03:05 CST
Objective: 实现V1完整初稿所需有序章节候选载体，复用既有StructuredTable，保留对象顺序与证据身份，不修改已确认事实或声称医学/Word验收。
Task type: `finite_code_task`
Risk: `medium`
Execution module trigger: Codex assigned 1 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `pi/cursor/default -> codebuddy/codebuddy-cli/deepseek-v4.1-flash:max -> pi/openai-codex/gpt-5.6-luna:max`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor` -> `pi` / `cursor` / `default`
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

1. 实现services/api/app/protocol_workflow/registries/ordered_draft.py及tests/protocol_v3/test_ordered_chapter_draft.py；读取Plan有序章节产物要求和现存ChapterSkillOutput/StructuredTable，先反例后最小实现。只改这两个新文件，纯候选结构和确定性校验，不接模型、存储、router或改变旧合同。段落A→2x2表1→段落B→同kind表2的JSON往返顺序、身份、各格、来源保真；拒绝重复块ID/表身份错配/悬空引用，不能将occurrences当实例，不能生成医学准入或分数。复用既有表格模型并保持原表格语义；必要时只提出后续接口建议。

## Completion And Cleanup

Codex reviews worker outputs and final artifacts. After acceptance, run `cleanup-execution` to archive prompts, worker reports, logs, and the manifest under `archives/execution/`; do not delete evidence by default.
