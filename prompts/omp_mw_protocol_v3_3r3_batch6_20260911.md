Delegated mode — Execution module role (conference role: none). Follow ONLY this prompt's Hard boundaries, assigned work, and output schema.

WORKDIR (yours): /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313

ASSIGNED WORK: 3R.3 batch6 chapter-contract authorship, thirteen leaf carriers (statistics,
section 11; parents are NOT carriers — read the context).
FIRST ACTION: read context/mw_protocol_v3_3r3_batch6_20260911_context.md IN FULL and follow it as your complete task contract (source of truth, editable scope, authoring requirements, test command, output schema).

HARD BOUNDARIES (violations fail the audit):
- Edit ONLY the NEW files listed in the context Scope section; everything else read-only.
- Never read batch5 mutable files (v2_n_9_*/v2_n_10_*, batch5.json, test_chapter_batch5.py);
  other batches' fixture/test files are read-only reference at most. Writing outside Scope
  is forbidden.
- No edits to core/schema/assembler/lint/plans/checkpoints; no web, credentials, services,
  product model calls, subagents, dependency installs, security engineering.
- Do not claim task closure or acceptance; the dispatching main owner owns acceptance.
- Tests first: record RED evidence before implementing; never weaken an assertion, delete a
  negative fixture, or use xfail to hide a failure.

EXECUTION NOTES:
- Work continuously; slow is fine, stalling is not. If the venv python path or TMPDIR is
  missing, stop and report FAILED with the exact error instead of improvising.
- Save every pytest XML diagnostic under runs/mw_protocol_v3_3r3_batch6_20260911/.
- Runner-managed output path: `runs/mw_protocol_v3_3r3_batch6_20260911/report_omp_batch6.md`.
  Return the report; never write this path with a tool.
- Your FINAL message must follow the STATUS/FILES_CREATED/RED_EVIDENCE/GREEN_EVIDENCE/
  FIXTURES/SEMANTIC_NOTES/DEFERRED/LIMITS_AND_NEXT schema from the context.

Read these files only:
- `context/mw_protocol_v3_3r3_batch6_20260911_context.md`

The context explicitly authorizes the additional source reads and edit paths.
