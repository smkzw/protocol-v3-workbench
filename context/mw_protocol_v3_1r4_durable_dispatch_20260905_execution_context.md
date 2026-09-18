# Execution Context: mw_protocol_v3_1r4_durable_dispatch_20260905

Created: 2026-09-05 19:23:01 CST
Objective: Repair real SQLite reservation coordinator transaction boundary: durable reservation before physical dispatch, no takeover of active ownership, retain unknown reconciliation and explicit retry history. Current direct UoW composition fails independent-connection probe. Minimal factory/runtime wiring, not a new platform. No security-specialist work or product model calls.
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex assigned 1 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `off_peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `zcode/glm-5.3-flash:max -> opencode-go/muse-spark-1.3-contributor:xhigh -> mtplx/qwen3.8-flash-next-mtplx-optimized-speed:medium -> openai-codex/gpt-5.6-luna:max`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. Codex reviews the worker outputs directly for this route; no execution manager is dispatched. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor` -> `zcode` / `zcode` / `GLM-5.3-Flash`
- Execution manager: none (Codex reviews the worker outputs directly)
- Execution-manager fallback: none

## Source Of Truth

- Read .trellis/tasks/09-05-protocol-v3-1r4/checkpoint.md and PRD; plans/mw_protocol_v3_review_amendment_20260905.md; assigned source/test files; existing test_execution_reservations.py and storage/ports callers. Do not read prior reviewer reasoning; reproduce actual defect from test_sqlite_reservation_lifecycle.py. Test1 passes recovery/restart; Test2 fails independent-connection visibility at physical dispatch (None instead of running1). Source typed contracts and ports are readonly; report any required extra source ownership before editing it.
- A raw UoW reservation repo must retain its business-transaction semantics; do not autocommit arbitrary caller events. Add minimal committed-operation runtime/factory entrypoint for physical dispatch; update new lifecycle test construction to this real supported entrypoint if needed, keeping its independent-connection assertion and all old tests/fixtures unchanged. No fake transport commit hooks as a fix.
- A second live caller must not turn an active RESERVED owner into FAILED; distinguish explicit orphan recovery from live ownership. Do not silently delete append-only attempts or change unknown into retryable. Include before/after-dispatch crash checks using synthetic child processes only, plus concurrent active-owner and explicit retry checks. Preserve superseded-result repair in sqlite.py.
- Allowed writes exactly four assigned files and new evidence runs/mw_protocol_v3_1r4_durable_dispatch_20260905/. No other source, fixture, task or report writes. No services/models/OCR/translation/Word/network/installs/global/live/monitoring/cleanup/security-specialist work. This executor is separate from prior reviewer; later verification must remain independent.
- Exact test env: env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest. First use tests/protocol_v3/test_sqlite_reservation_lifecycle.py, test_durable_reservation_dispatch.py, test_execution_reservations.py, test_result_storage_consolidation.py, test_superseded_result_migration.py. Full protocol_v3 allowed; separate new test_compact_dependency_contract.py currently has5expectedWIPfailures due absentcompact_dependencies, Codex owns that disjoint contract slice. Do not edit/exclude that file to make a green claim; report knownWIP separately. Historical full-repo collection debt out of scope.
- Do not add production paths without explicit Codex authorization.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.

## Work Items

1. Own only services/api/app/protocol_workflow/runtime/reservations.py, services/api/app/protocol_workflow/storage/sqlite.py, tests/protocol_v3/test_sqlite_reservation_lifecycle.py, and new tests/protocol_v3/test_durable_reservation_dispatch.py. Read current1R.4 checkpoint for reproducible failure and context. Implement committed-operation coordinator factory without committing arbitrary caller business transactions; preserve shared UoW API. Add genuine crash and concurrent live-owner tests; retain old fixtures/expected, do not hide new failures. No product calls/live changes/cleanup/task closure.

## Completion And Cleanup

Codex reviews worker outputs and final artifacts. User prohibits cleanup/archive; retain all evidence in place. Worker cannot close task. Report red/green evidence and actual crash/concurrency limitations without calling partial proof complete.
