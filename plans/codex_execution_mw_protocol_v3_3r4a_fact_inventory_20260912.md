# Codex Execution Plan: mw_protocol_v3_3r4a_fact_inventory_20260912

Objective: Read-only factual inventory for Task3R.4A; Codex owns all product/type edits. Determine current chapter fact paths and binding evidence without guessing clinical values or types.

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | Read current Planv3 3R.4A and accepted assembled registry, all chapter fact declarations and canonical StudyDefinition schema. Produce complete inventory of distinct fact paths, source contracts and rationale, explicit type evidence if present, and evidenced aliases or conflicts. Do not infer type from a path suffix alone. Mark unsupported or ambiguous mappings explicitly. Write only new artifacts under runs/mw_protocol_v3_3r4a_20260912/fact_inventory_worker and return a concise evidence report. No product/source/test edits, services, model product calls, OCR, translation, credentials, web, cleanup or recursive agents. Input authoritative current source; model routing only current immutable runner manifest. | `runs/execution/mw_protocol_v3_3r4a_fact_inventory_20260912/worker_01.md` |

## Manager

No execution manager is dispatched for this route; Codex reviews the worker outputs directly.

## Codex Acceptance

Inventory accepted with explicit owner corrections; see linked Codex execution review. No product task closure, no rendered surface in this read-only assignment, no archive/cleanup.
