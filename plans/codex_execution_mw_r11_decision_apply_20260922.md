# Codex Execution Plan: mw_r11_decision_apply_20260922

Objective: Implement the smallest one-confirmation path from a v0.4 full-draft decision card into the existing authoritative medical-writing StudyDefinition and targeted affected-section regeneration, preserving current CAS and audit semantics.

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | Inspect current authoring journey mutation APIs, full-draft artifact/job contracts, and frontend study-design flow. Implement a bounded decision-resolution command and UI: recommended choice preselected, user may select an alternative, one explicit confirmation persists the answer through an existing authoritative StudyDefinition field/update path, invalidates the old artifact, and submits a new full-draft job scoped only to affected sections. Do not create a second decision store or generic form. Add focused tests but run them only after the coherent batch is complete. | `runs/execution/mw_r11_decision_apply_20260922/worker_01.md` |

## Codex Acceptance

TODO: verify artifacts, tests, source claims, rendered surfaces, blockers, and user-facing completeness.
