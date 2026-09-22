# Execution Output: mw_r11_recovery_20260921 - worker_01

## Boundary And Context Check

- Fallback active: `openai-codex/gpt-5.6-luna`.
- Runner contract still declares Z Code/GLM-5.3-Flash; this pass used the available repository tools only.
- Scope respected: backend recovery sources and targeted `tests/protocol_v3` tests only.
- No frontend, live database, service, network, credential, or production acceptance work performed.

## Work Performed

- Enabled two total attempts for original and correction chapter-generation nodes.
- Added explicit chapter retry handling:
  - Safe retry only for `failed` or non-live `blocked_unknown`.
  - Live dispatch leases remain blocked.
  - Dead `RESERVED`/`RUNNING` shells require explicit failure reconciliation.
  - Retry preserves append-only attempt lineage.
- Added persisted-plan compatibility for monotonic retry-budget expansion, allowing old one-attempt runs to resume under the new two-attempt plan without accepting structural graph changes.
- Removed dead manuscript failure handling.
- Isolated failed chapters during manuscript aggregation; completed siblings remain retained and are not redispatched.
- Added explicit manuscript `POST .../manuscript-draft/resume` endpoint while preserving read-only `/recover`.
- Reduced correction request payloads:
  - Removed duplicated source-material evidence.
  - Compacted validation errors.
  - Bounded large previous outputs to error-local excerpts.
  - Preserved provider/model/reasoning and artifact lineage.
- Added regression coverage for:
  - Unknown correction outcome followed by one explicit retry.
  - Completed manuscript sibling retention.
  - Large correction-output excerpts and duplicated evidence removal.
  - Persisted run retry after retry-budget expansion.

## Artifacts And Evidence

Modified source files:

- `services/api/app/protocol_workflow/agent3/subgraph.py`
- `services/api/app/protocol_workflow/agent3/coordinator.py`
- `services/api/app/protocol_workflow/agent3/manuscript_coordinator.py`
- `services/api/app/protocol_workflow/api/manuscript_drafts.py`
- `services/api/app/protocol_workflow/graph/runtime.py`
- `services/api/app/protocol_workflow/runtime/proposal_correction.py`

Modified or added tests:

- `tests/protocol_v3/test_chapter_product_factory.py`
- `tests/protocol_v3/test_graph_runtime.py`
- `tests/protocol_v3/test_manuscript_recovery.py`

The new manuscript resume route was smoke-checked as:

`POST /api/projects/{project_id}/protocol-workflow/study-definitions/{study_definition_id}/manuscript-draft/resume`

## Commands And Observations

- Pre-fix red-first correction regression:
  - Expected `can_resume=True`.
  - Observed `can_resume=False`.
- Source compilation completed without errors.
- Focused correction and manuscript tests: `8 passed`.
- Persisted retry-budget compatibility test: `1 passed`.
- Final bounded suite:

  `94 passed in 7.59s`

- Final suite covered:
  - Chapter product factory
  - Chapter draft workflow
  - Graph runtime
  - Graph runtime recovery
  - Execution reservations
  - Manuscript recovery
  - Seed workflow integration

## Blockers Or Missing Environment

No blocker remains within the bounded backend implementation and test scope.

Not exercised:

- Live GLM/Zhipu transport or wire-shape acceptance.
- Frontend resume-button wiring and click-count evidence.
- Live service/database integration.
- Fresh Codex conference/integration acceptance.

## Rerun Requests Or Next Step

Run the fresh Codex-owned conference/integration acceptance pass against the recovery contract, then separately verify frontend resume interaction and live provider transport behavior.
