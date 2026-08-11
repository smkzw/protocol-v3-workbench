# Protocol v3 Task 1.7 fresh independent acceptance

MODE=CONFERENCE. You are a fresh-context, read-only verifier. Do not modify files.

## Hard boundaries

- Work only inside the current workspace root `.`.
- Do not edit source, tests, configuration, records, or generated artifacts.
- Do not perform security testing, start services, or invoke live model, OCR,
  translation, network, or medical-monitoring workflows.
- Runner-managed report path:
  `runs/conference/mw_protocol_v3_phase1_task17_acceptance_20260811/fresh_luna_acceptance.md`.
  Return the complete report; do not write this path with tools.

## Read these files only at intake

- `AGENTS.md`
- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`
- `context/mw_protocol_v3_phase1_task17_20260811_context.md`

This intake list does not prohibit bounded inspection of the Task 1.7 source,
registries, adapters, canonical contracts, and tests needed for verification.

## Source of truth

- `/Users/smkzw/.codex/AGENTS.md`
- `AGENTS.md`
- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.7 only
- `context/mw_protocol_v3_phase1_task17_20260811_context.md`
- the current uncommitted Task 1.7 registries, Harness, adapters, and tests

## Scope

Independently challenge the unified Harness boundary, strict role/skill registries,
Direct API/local oMLX/Codex/OMP adapters, probe policy, fallback policy,
same-session recovery, shared OCR/translation gate, and typed receipts.

Pay special attention to these repaired claims:

1. `same_session_recovery=false` plus a non-null provider session id fails closed
   before preflight, probe, or transport; the true polarity still resumes.
2. OCR/translation declared and effective model identities require exact,
   case-sensitive equality.
3. A lease context `__exit__` failure cannot escape or overwrite the physical
   dispatch fact; it returns a stable typed outcome. A simultaneous transport
   and release failure preserves the transport failure classification.
4. Adapter/package documentation correctly assigns lease acquisition/release
   and probe caching to the common Harness/gate client rather than an adapter.

## Verification

Run focused or full deterministic tests and static checks as useful. Inspect real
source, not prior reviewer conclusions. Also verify the frozen plan hash and that
no medical-monitoring file is changed.

Forbidden: security testing, service startup, network/model/OCR/translation calls,
medical-monitoring changes, or any file modification.

## Return contract

Return `READY` only if every P0-P4 finding is zero. Otherwise return `NOT_READY`.
For every finding give severity, exact file/line, reproduction/evidence, impact,
and smallest repair. Include commands and observed results, residual uncertainty,
and the next safe action. Worker self-reports are not acceptance evidence.
