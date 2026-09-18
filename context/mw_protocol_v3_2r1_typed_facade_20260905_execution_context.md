# Execution Context: mw_protocol_v3_2r1_typed_facade_20260905

Created: 2026-09-05 21:40:06 CST
Objective: Implement Task2R.1 typed facade and product OrchestratorPort using accepted immutable cases, real SQLite committed reservations and v1_1 contracts. Offline synthetic three-case process-kill/replay/concurrent-decision matrix; preserve originals and no real models/services/live writes.
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

- .trellis/tasks/09-05-protocol-v3-2r1/prd.md and design.md and implement.md.
- plans/mw_protocol_v3_review_amendment_20260905.md (2R.1 launch/contract amendments).
- runs/MW_PROTOCOL_V3_TASK21_NO_LOSS_PAUSE_20260812_0708.md; seven source hashes
  were reverified by Codex before dispatch. Preserve those seven files unchanged.
- pocs/protocol_v3/orchestrator/{__init__.py,fakes.py,cases/,tests/test_case_contracts.py}.
- Read product packages/contracts/workbench_contracts/protocol_v3.py and
  services/api/app/protocol_workflow/{runtime,storage,ports,events,canonical,application,artifacts}/
  as needed; corresponding tests/protocol_v3 are read-only examples.
- Frozen Task2.2 remains inherited except Planv2 explicitly authorizes product
  graph/runtime.py and fixes production route typed facade (not LangGraph).

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.
- Allowed NEW implementation files only: pocs/protocol_v3/orchestrator/typed_facade.py,
  pocs/protocol_v3/orchestrator/tests/test_typed_facade.py,
  services/api/app/protocol_workflow/graph/ (new runtime.py and small supporting
  modules only), tests/protocol_v3/test_graph_runtime.py and
  tests/protocol_v3/test_graph_runtime_recovery.py. Evidence may be written under
  runs/mw_protocol_v3_2r1_typed_facade_20260905/ only. Runner owns worker report.
- Existing core/storage/contracts/case files READONLY; if a necessary missing port
  cannot be adapted without editing them, identify exact minimal need in report.
  No unrelated legacy tests/monitoring/main/frontend/config edits, no Trellis
  task closure, no cleanup/archive, no package installation, no subprocess models,
  no real product GLM/OCR/translation/network/service/database operations.
- Tests may create and force-kill ONLY their own synthetic subprocesses using
  temporary SQLite/artifact stores; never find/kill other processes. Do not import
  legacy main. env -i PATH=/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/
  LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
  PYTHONPATH=services/api:packages:. and explicit temporary WORKBENCH_RUNTIME_DIR.
  Python: runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python.
  pytest -q -p no:cacheprovider --tb=short with unique XML evidence filenames.

## Work Items

1. Implement one coherent typed facade with product runtime and three-case recovery tests; no legacy or protected changes

## Completion And Cleanup

Codex reviews worker output and final artifacts, then fresh verifier. No automatic
cleanup/archive; retain all evidence in place per user instruction.
