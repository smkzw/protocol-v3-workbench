# Task 1.7 independent repair verification

MODE=CONFERENCE. Continue the same independent Luna session. The prior report
was `NOT_READY` with P1=3, P2=4, P3=1. Verify the repairs, do not trust this
summary, and do not modify files.

## Hard boundaries

- Work only inside `.` and remain read-only.
- Do not perform security testing, start services, or call any live model, OCR,
  translation, network, or medical-monitoring workflow.
- Runner-managed report path:
  `runs/conference/mw_protocol_v3_phase1_task17_acceptance_20260811/fresh_luna_acceptance_followup.md`.
  Return the report; do not write it through tools.

## Read these files only at intake

- `services/api/app/protocol_workflow/runtime/harness.py`
- `services/api/app/protocol_workflow/runtime/adapters/`
- `services/api/app/protocol_workflow/registries/loader.py`
- `tests/protocol_v3/test_harness_policy.py`
- `tests/protocol_v3/test_registry_loading.py`

## Required contradiction checks

Reproduce each prior finding against current files:

1. dispatcher session-polarity bypass;
2. adapter/request harness mismatch;
3. fallback prior logical-call/idempotency/input-hash binding;
4. whitespace/case variants in gate model identity;
5. non-`DispatchReceipt` transport return;
6. tool/path allowlists surviving into the physical request payload;
7. Windows/backslash path rejection;
8. nested `tool_versions` immutability.

Also check for regressions caused by these repairs and run deterministic focused
or full tests and static checks as useful. The current Codex-owned anchor is 197
focused and 867 full tests passing, but rerun rather than trusting it. Preserve
the frozen plan hash and medical-monitoring isolation.

Return literal P0/P1/P2/P3/P4 counts and `READY` only when all are zero. For any
finding give exact file/line, reproduction, impact, and smallest repair. State
environment-only limitations separately from product defects.
