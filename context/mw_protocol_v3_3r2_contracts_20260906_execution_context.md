# Execution Context: mw_protocol_v3_3r2_contracts_20260906

Created: 2026-09-06 02:05:17 CST
Objective: Task3R.2 explicit versioned contract extension preserving v1 serialization and hashes, as active Trellis PRD/design/implement.
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

- Read FULL .trellis/tasks/09-06-protocol-v3-3r2/{prd,design,implement}.md.
- Read FULL existing packages/contracts/workbench_contracts/protocol_v3.py and
  tests/protocol_v3/test_contract_models.py; related reducer/repository tests may
  be read as needed. Plan v2 Task3R.2 and frozenTask3.2 requirements are captured
  in PRD; source documents in ../plan-upgrade-20260905 remain read-only.
- Accepted3R1 candidate may be read for concrete examples, never modified.

## Authorized implementation and verification

- Edit ONLY packages/contracts/workbench_contracts/protocol_v3.py and create
  tests/protocol_v3/test_chapter_contract_schema.py; NEW evidence files only under
  runs/mw_protocol_v3_3r2_contracts_20260906/. Preserve all other work and history.
- Use explicit ChapterContractV2/SubstantiveContentContractV2 (or equally clear
  names) without serialized defaults added to v1 types. Preserve v1 materialhash.
- Typed small contracts, not dictionaries/free-text checklists pretending typed:
  facts/claims/source constraints, object/Word rules, conditionalapplicability,
  impact/dependency/repairsteps, CtQ, patientparticipation and registryconsistency.
- Required object-only obligations must be project-specific, not generic title/
  paragraph presence. PositiveQC required. Metadata can use genuine template/
  control provenance; do not fabricate medicalclaims/admissionrecords.
- Patientparticipation records tie to existing DecisionRecord; reason AI-prepared,
  no arbitrarylength. Do not change existing SemanticBlock/DecisionRecord consumers
  or runtime in this task. No clinical source authoring or UI here.
- First redtests; v1 serialized/hash fixtures captured BEFORE implementation;
  newv2valid+contradictory/vacuous/roundtrip tests. Do notmodifyoldexpected/xfail.
- Isolated venv runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python;
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
  PYTHONPATH=tests/protocol_v3:services/api:packages:.
  pytest -p no:cacheprovider focused newtest + test_contract_models.py,
  test_semantic_document_reducer.py,test_repository_contract.py,
  test_repository_backends.py. No main import/service/lifespan/productmodel calls.
- No security features/tests or new dependencies. Do not close task/promote source.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.

## Work Items

1. One coherent two-file schema extension: packages/contracts/workbench_contracts/protocol_v3.py and tests/protocol_v3/test_chapter_contract_schema.py; red-first, typed content/applicability/evidence/Word/dependency/CtQ/participation requirements; no runtime/production/models or task closure.

## Completion And Cleanup

Codex and fresh reviewer verify the artifact. User forbids cleanup/archive: do not
run generated cleanup commands. Return evidence and exact unresolved scope only.
