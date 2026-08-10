# Protocol v3 Task 1.2 same-session repair review

## Hard boundaries

- Continue the same read-only independent review session.
- Read only the two implementation/test files listed below and your prior findings.
- Do not edit files, start services/runtimes, or perform any security/adversarial testing.
- Runner-managed output path: `runs/codex_mw_protocol_v3_phase1_task12_independent_luna.md`.
  Return the complete verdict and let the runner persist it; never write it with tools.

Read these files only:

- `services/api/app/protocol_workflow/errors.py`
- `tests/protocol_v3/test_error_codes.py`

The implementation now:

1. Stores all runtime fields privately, exposes read-only properties, and seals
   `ProtocolWorkflowError` after construction. Reassignment of public or private
   identity/owner/retryability fields raises `AttributeError`.
2. Replaced the flagged engineering copy with natural medical-writing copy:
   confirmed source version/write basis; completed content/confirmed facts;
   template chapters and their writing/review requirements; completed content.
3. Added five mutation regression cases. Focused result is now 25 passed and
   `git diff --check` passes.

Recheck only the previously reported P1/P2 causes and obvious same-cause
regression. Return exactly `READY` or `NOT_READY`, followed only by remaining
concrete P0/P1/P2 findings with file and line. Do not add optional enhancements.
