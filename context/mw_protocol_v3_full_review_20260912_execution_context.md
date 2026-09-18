# Execution Context: mw_protocol_v3_full_review_20260912

Created: 2026-09-12 21:00:35 CST
Objective: READ-ONLY full engineering review and actionable planning input. Do not implement product changes. Read the source-of-truth and delegated work-item boundary below; return concrete evidence-backed findings, not a restatement of prior reports.
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex assigned 2 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `off_peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `zcode/glm-5.3-flash:max -> opencode-go/muse-spark-1.3-contributor:xhigh -> mtplx/qwen3.8-flash-next-mtplx-optimized-speed:medium -> openai-codex/gpt-5.6-luna:max`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. Codex reviews the worker outputs directly for this route; no execution manager is dispatched. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor` -> `zcode` / `zcode` / `GLM-5.3-Flash`
- Execution manager: none (Codex reviews the worker outputs directly)
- Execution-manager fallback: none

## Source Of Truth

- Read `.trellis/tasks/09-12-protocol-v3-review-replan/checkpoint.md`, current assigned source modules/tests, `handoff/2026-09-11/HANDOFF_PROTOCOL_V3_3R4_20260912.md`, `runs/MW_PROTOCOL_V3_3R4_NO_LOSS_PAUSE_20260912_2322.md`, `plans/mw_protocol_v3_review_amendment_20260905.md`, and `../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md` as read-only context. Prior owner assertions are evidence to challenge, not authority to mark completed.
- Worker01 owns only NEW diagnostics under `runs/mw_protocol_v3_full_review_20260912/worker_backend/`; worker02 only NEW diagnostics under `runs/mw_protocol_v3_full_review_20260912/worker_frontend/`. Source files and existing tests stay READ-ONLY. Use skim structure then complete affected definitions/tests; report reviewed file coverage and material gaps.
- Existing interpreter: `runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python`. For isolated checks use env -i with PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. and -p no:cacheprovider. Importing old main can create artifacts: do not import main without explicit temp runtime env using existing integration test fixtures. No actual model/server/Word/browser startup. No package install.
- User excluded pure security engineering/tests; do not introduce it under renamed gates. Preserve genuine scientific, data-loss, stale-version and duplicate-call semantics. This review does not reinstate excluded scope.
- Do not add production paths without explicit Codex authorization.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.

## Work Items

1. Backend review: read all product protocol_workflow canonical, storage, events, runtime, graph, application, api, ports, artifacts and agent5 modules and adjacent tests; trace actual main composition. Exclude registries/chapters.py and registries/dependency_graph.py owned by parent review. Identify reachable correctness, persistence, recovery, versioning, integration gaps and useful simplifications. Product sources/tests read-only. No services, product models, OCR, translation, web, credentials, cleanup or recursive agents. Return file:line, concrete trigger, existing test gap and smallest repair; distinguish absence of future features from implemented bugs. Optional isolated pytest only; no existing evidence writes.
2. Frontend/user-flow review: read current frontend/AGENTS, App.jsx WritingPage actual wiring and all frontend/src/features/medical-writing components/hooks/CSS, protocolWorkspaceApi, corresponding tests and backend medical-writing endpoints only as needed. Trace actual user paths from intake/recommendations/adoption/edit/save/export; verify previous claims and retract unreachable ones. Identify reachable failures and practical AI-led UX/visual changes for senior medical writer (20click/5text/8 risk confirmations). Read-only sources; no servers, browser production, models, credentials, cleanup, nested agents. New diagnostics only in runs/mw_protocol_v3_full_review_20260912/worker_frontend. Return evidence file:line plus precise proposed fixes and test targets.

## Completion And Cleanup

Codex reviews worker reports and verification evidence. No cleanup/archival is authorized; preserve all prompts, reports, logs and manifests in place. No worker closes tasks, commits, writes plans, or starts peers. Always return the required report schema even if an input cannot be checked.
