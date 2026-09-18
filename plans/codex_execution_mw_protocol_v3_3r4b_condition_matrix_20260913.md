# Codex Execution Plan: mw_protocol_v3_3r4b_condition_matrix_20260913

Objective: Source-bound inventory and proposed adjudication of 49 chapter applicability rules and 14 overlaps; owner implements checker, worker writes a separate proposal only.

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | Read Plan v3 3R.4B, current 49 rule contracts, source node tree and existing applicability_obligation_matrix.json. Produce one row per existing rule with explicit predicate proposal, true/false/unknown obligations for facts/claims/evidence/objects, overlap disposition and exact source evidence. Distinguish source-required obligations from inherited overrequirements; do not infer booleans from names, use verified source semantics or mark unresolved. Special focus interim false including canonical reference/table, central lab vs local lab, permanent stopping vs temporary hold, multiplicity, IRC, PK/PD, pregnancy, suppliers. Write only runs/mw_protocol_v3_3r4b_20260912/condition_worker. No product/source/test edits, services, model product calls, OCR, translation, web, cleanup, credentials, recursive agents or final acceptance. | `runs/execution/mw_protocol_v3_3r4b_condition_matrix_20260913/worker_01.md` |

## Codex Acceptance

Bounded inventory accepted with explicit owner corrections; report hash and 49-rule/14-overlap identity verified. See corresponding review and source adjudication. B implementation is not accepted; continue ruleset and functional checks. No archive/cleanup.
