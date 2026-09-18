# Execution Context: mw_protocol_v3_3r4a_fact_inventory_20260912

Created: 2026-09-12 23:26:23 CST
Objective: Read-only factual inventory for Task3R.4A; Codex owns all product/type edits. Determine current chapter fact paths and binding evidence without guessing clinical values or types.
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

- plans/mw_protocol_v3_implementation_plan_v3_20260912.md, section3R.4A; plans/mw_protocol_v3_design_v1.4_20260912.md sections4–5.
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/*.json, and runs/mw_protocol_v3_full_review_20260912/current_assembled_registry.json (same chapter data, readonly).
- packages/contracts/workbench_contracts/protocol_v3.py (canonical StudyDefinition facts) and .trellis/tasks/09-11-protocol-v3-3r4/prd.md.
- Parent currently edits registries/chapters.py and tests/test_chapter_fact_binding.py; do not modify either or use parent in-flight changes as inventory authority.
- Only write runs/mw_protocol_v3_3r4a_20260912/fact_inventory_worker/*.json or *.md; no external paths, product calls, model/OCR/translation, dependency installation or cleanup.
- Inventory each fact path with contract/rationale locator, conditional membership and any explicit type/alias evidence. Include all724 declared paths; mechanically compare set coverage, explain if current count differs. Separate key lookup (canonical facts is a flat dictionary) from clinical semantic type. No guessed values/type inference based only on suffix.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.

## Work Items

1. Read current Planv3 3R.4A and accepted assembled registry, all chapter fact declarations and canonical StudyDefinition schema. Produce complete inventory of distinct fact paths, source contracts and rationale, explicit type evidence if present, and evidenced aliases or conflicts. Do not infer type from a path suffix alone. Mark unsupported or ambiguous mappings explicitly. Write only new artifacts under runs/mw_protocol_v3_3r4a_20260912/fact_inventory_worker and return a concise evidence report. No product/source/test edits, services, model product calls, OCR, translation, credentials, web, cleanup or recursive agents. Input authoritative current source; model routing only current immutable runner manifest.

## Completion And Cleanup

Codex reviews and preserves all outputs. User explicitly forbids cleanup and automatic archive; do not run cleanup-execution. Return report; runner persists it.
