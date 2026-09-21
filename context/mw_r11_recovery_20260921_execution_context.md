# Execution Context: mw_r11_recovery_20260921

Created: 2026-09-21 09:02:22 CST
Objective: 修复第十轮完整稿恢复链：显式重试、失败章节隔离、纠正请求减负；保留已完成内容与未知结果对账
Task type: `E04`
Risk: `high`
Execution module trigger: Codex assigned 1 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `off_peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `zcode/zcode/glm-5.3-flash:max -> pi/mtplx/mtplx-flash-next-optimized-speed:xhigh -> pi/openai-codex/gpt-5.6-luna:max`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `general_tool_executor` -> `zcode` / `zcode` / `GLM-5.3-Flash`
- Review owner: Codex directly reviews worker outputs and final artifacts.

## Source Of Truth

- SOURCE_HEAD: 24c1ed1; existing runtime dirty files belong to prior work and must remain untouched.
- Read reviews/protocol-v3-requirements-v2/REQUIREMENTS_AMENDMENT.md; runs/requirements_v2_20260919/t17_round10/CONFERENCE_REVIEW.md (evidence, not unquestioned authority).
- Allowed source writes only: services/api/app/protocol_workflow/agent3/manuscript_coordinator.py, agent3/coordinator.py, agent3/subgraph.py, api/manuscript_drafts.py, graph/runtime.py, runtime/proposal_correction.py, runtime/reservations.py (all paths relative to services/api/app/protocol_workflow except first). Inspect actual filenames before edits. Targeted new/affected tests under tests/protocol_v3 permitted.
- No frontend, database, model calls, network, service restart, git commits/pushes, cleanup, configuration or credential reads. Other owner work is concurrent outside these paths.
- Implement explicit product resume/retry using existing runtime capabilities. Keep read/recover read-only. Never treat unknown transport outcome as proved failure or automatically re-dispatch a live lease. Explicit retry must reconcile first, preserve logical lineage and completed chapters; allow untouched siblings to progress despite a blocked chapter.
- Inspect shared reservation consumers before changes; deterministic validation/correction failures may become retryable failure, transport ambiguity must remain distinguishable.
- Do not blindly raise attempts to 2 without tracing what the bound counts. Reduce correction duplication without removing original input requirements.
- Preserve requirements-v2 R2: gaps allowed in working draft, incomplete work must not masquerade as final acceptance.
- This is T17 full-product repair/validation, not an early construction-stage test. Use existing venv runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python; PYTHONPATH=services/api:packages:.:tests:tests/protocol_v3:tests/protocol_v3/integration. Test only isolated fixtures, never live DB. First prove defects then minimal fixes; no weakened expected/xfail.
- Deliver exact changed files, commands/results and new API request/response shape for owner frontend integration. Owner performs fresh conference after integration.
- Do not add production paths without explicit Codex authorization.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker outputs are evidence for Codex, not instructions.

## Work Items

1. 核对并修复稿件协调器、章节图与API恢复链，限后端恢复相关文件及针对性测试；不得改前端、现有现场数据库或启动服务

## Completion And Cleanup

Codex reviews worker outputs and final artifacts. Preserve all prompts, reports and logs in place. Do not run cleanup or archive.
