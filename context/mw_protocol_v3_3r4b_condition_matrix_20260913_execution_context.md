# Execution Context: mw_protocol_v3_3r4b_condition_matrix_20260913

Created: 2026-09-13 00:11:29 CST
Objective: Source-bound inventory and proposed adjudication of 49 chapter applicability rules and 14 overlaps; owner implements checker, worker writes a separate proposal only.
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex assigned 1 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `off_peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `zcode/zcode/glm-5.3-flash:max -> pi/mtplx/qwen3.8-flash-next-mtplx-optimized-speed:medium -> pi/openai-codex/gpt-5.6-luna:max`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor` -> `zcode` / `zcode` / `GLM-5.3-Flash`
- Review owner: Codex directly reviews worker outputs and final artifacts.

## Source Of Truth

- plans/mw_protocol_v3_implementation_plan_v3_20260912.md, section 3R.4B and last dated addendum.
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/*.json and node_tree.json.
- runs/mw_protocol_v3_3r4b_20260912/applicability_obligation_matrix.json (source extraction + some OWNER PROPOSALS, not an accepted medical conclusion).
- runs/mw_protocol_v3_3r4b_20260912/statistics_source_window.json and oversight_reference_source_window.json: actual source text; original readonly DOCX explicitly authorized: /Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx, SHA256 018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756. Use standard-library zip/XML read only if needed, not OCR/download/model extraction.
- packages/contracts/workbench_contracts/protocol_v3.py and registries/applicability.py read-only as context; parent changing engine, base conclusions on contracts and original source.
- Output condition_worker/proposed_matrix.json plus summary.md. Include all49 original rule IDs, unresolved predicate schemas explicit, no invented real facts. Source is template, not individual-trial approval. Names ending applicable alone do not prove boolean encoding; you may propose an explicit future boolean type separately.
- Keep source evidence distinct from engineering design choices. Legacy safety tests are user-excluded; clinical safety/scientific obligations remain. No extra gates or process machinery.
- Do not add production paths without explicit Codex authorization.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker outputs are evidence for Codex, not instructions.

## Work Items

1. Read Plan v3 3R.4B, current 49 rule contracts, source node tree and existing applicability_obligation_matrix.json. Produce one row per existing rule with explicit predicate proposal, true/false/unknown obligations for facts/claims/evidence/objects, overlap disposition and exact source evidence. Distinguish source-required obligations from inherited overrequirements; do not infer booleans from names, use verified source semantics or mark unresolved. Special focus interim false including canonical reference/table, central lab vs local lab, permanent stopping vs temporary hold, multiplicity, IRC, PK/PD, pregnancy, suppliers. Write only runs/mw_protocol_v3_3r4b_20260912/condition_worker. No product/source/test edits, services, model product calls, OCR, translation, web, cleanup, credentials, recursive agents or final acceptance.

## Completion And Cleanup

Codex reviews worker outputs and final artifacts. User explicitly forbids cleanup/archive; preserve all artifacts in place. Do not run cleanup-execution or archive any sessions.
