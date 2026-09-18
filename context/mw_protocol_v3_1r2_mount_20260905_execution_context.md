# Execution Context: mw_protocol_v3_1r2_mount_20260905

Created: 2026-09-05 16:14:47 CST
Objective: Implement approved Protocol v3 Task 1R.2 only in isolated checkout: actual main router default-off, durable project allowlist, real isolated entrypoint regression, no live or product model calls. Read .trellis/tasks/09-05-protocol-v3-1r2/{prd,design,implement}.md and .trellis/spec/protocol-v3.md. Preserve prior dirty work and all historical evidence. Do not close own task.
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex assigned 1 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `opencode-go/muse-spark-1.3-contributor:xhigh -> cursor/default -> openai-codex/gpt-5.6-luna:max`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. Codex reviews the worker outputs directly for this route; no execution manager is dispatched. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor` -> `pi` / `opencode-go` / `muse-spark-1.3-contributor`
- Execution manager: none (Codex reviews the worker outputs directly)
- Execution-manager fallback: none

## Source Of Truth

- Read `.trellis/tasks/09-05-protocol-v3-1r2/prd.md`, `design.md`, `implement.md` in that same task directory and `.trellis/spec/protocol-v3.md`.
- Read `plans/mw_protocol_v3_review_amendment_20260905.md` and `reviews/codex_mw_protocol_v3_1r1_storage_gate_20260905.md`.
- Plan v2 Task1R.2 is recorded in those artifacts; original Task1.9 contract in `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md` remains API authority where not superseded.
- Read relevant actual source/tests. Product code may never import pocs. Main has pre-existing global repository side effects. Do not import actual main in the parent/unisolated runtime.
- Do not add production paths without explicit Codex authorization.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.

## Work Items

Allowed tests: focused protocol_v3 existing/new tests with temporary SQLite and
fakes, using /opt/homebrew/bin/python3.12 with PYTHONPATH=services/api:packages:.
The separate existing dependency venv is owned by Codex and being restored; do not
install dependencies or run full-repository/main tests until its isolation closure
is established. Write real-main integration tests but report missing environment
precisely if they cannot yet run. Main PROJECT_ROOT points above checkout;
sanitize inherited WORKBENCH_AI_SETTINGS_PATH, WORKBENCH_AI_ROLE_SETTINGS_PATH and
WORKBENCH_ELIGIBILITY_ARTIFACT_DIR in test children, plus explicit temporary
WORKBENCH_RUNTIME_DIR. Never run real model, OCR, translation, Word or service.
Persist new red/green test evidence only under
`runs/mw_protocol_v3_1r2_20260905/`. No historical files altered.

1. Task 1R.2 composition and persistent allowlist; red-first tests then minimal implementation; allowed services/api/app/main.py narrow wiring, protocol_workflow/api composition/router, storage/sqlite.py versioned migration, relevant new tests/protocol_v3 only. Main owns dependency environment and Trellis. No monitoring/live/8910/model/OCR/translation/Word, no global env changes, no commits or cleanup. Output compact evidence and remaining limitations.

## Completion And Cleanup

Codex reviews output then fresh verifier independently checks frozen changes.
User forbids cleanup/archive: do not run generated cleanup-execution.
