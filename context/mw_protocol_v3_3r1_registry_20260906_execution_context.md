# Execution Context: mw_protocol_v3_3r1_registry_20260906

Created: 2026-09-06 00:23:30 CST
Objective: Implement deterministic TP-MA-07 v2 candidate registry extraction and explicit actual legacy mapping under Task 3R.1, with source-bound tests; no source edits or product activation.
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

- Read `.trellis/tasks/09-06-protocol-v3-3r1/{prd,design,implement}.md`.
- Read `reviews/mw_protocol_v3_tp_ma07_v2_readonly_preflight_20260905.md`.
- External read-only source explicitly permitted: `/Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx`.
  SHA256018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756,
  reverified before dispatch. Never save/change this source. Zip/XML read only.
- Legacy source `services/api/app/medical_writing_protocol_template.py` (read-only);
  AST avoids importing its runtime. Actual company table124rows103leaves+6front
  nodes=130/109; historical124/110 is not current truth. Do not invent v1JSON.
- Read adjacent `../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md`
  Task3R1 and frozenplan Task3.1 for exact requirements, both read-only.

## Authorized implementation

Only five new files:
- `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/template.json`
- `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json`
- `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/v1_to_v2_mapping.json`
- `scripts/qc/protocol_v3/extract_tp_ma_07_v2_registry.py`
- `tests/protocol_v3/test_tp_ma_07_v2_registry.py`

New test XML/evidence allowed in `runs/mw_protocol_v3_3r1_registry_20260906/`.
Never overwrite preexisting evidence. No task status edits or candidate-current
promotion by worker. Do not edit runtime/contracts/legacy source or other tests.

Use stdlib zipfile/XML/AST plus existing pytest. Test python:
`runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python`; sanitized env -i
PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
PYTHONPATH=tests/protocol_v3:services/api:packages:.; pytest -p no:cacheprovider.
No main import/lifespan, services, models, OCR/translation, network, dependencies,
credentials, cleanup, commit or live/monitoring access. Keep worker prompt frozen.

Implement smallest complete deterministic extractor, CLI candidate generation,
source-bound tests first red then green. Hash mismatch explicit error. Candidate
outputs repeat byte-for-byte; don't include volatile timestamps/temp paths.
Hierarchy135styleheadings106leaves separate from139outlined109leaves and other
semantic objects; table17top-level18recursive; preserve Normal outlined captions,
frontmatter, unheaded content, bookmarks/fields/section/page rules with locators.
Every legacy leaf maps explicitly or is explicitly nonapplicable/retired with
rationale; every new heading leaf has reverse disposition. Similar names alone
are not evidence of implemented projection. Record actual projection logic source
locations/coverage, and remaining ambiguity as candidate findings, not fabricated
accepted mappings. PhaseI leaves retain historical identity, notII/IIIcontent.
New registry text uses source terminology; old IDs remain literal. Template
examples/instructions not project facts. Financial disclosure conditional default
not-applicable requires reason; management structure distributed across nodes.
Do not add clinical content rules from memory or claim all106contracts implemented.
Codex will independently review semantics, then fresh reviewer before current.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.

## Work Items

1. Single coherent extractor, candidate registry and legacy mapping implementation within five Plan3R1 files; red-first tests; no task closure.

## Completion And Cleanup

Codex reviews worker output and actual files. User prohibits cleanup/archive of
evidence; retain packet and all logs in place. No cleanup-execution invocation.
