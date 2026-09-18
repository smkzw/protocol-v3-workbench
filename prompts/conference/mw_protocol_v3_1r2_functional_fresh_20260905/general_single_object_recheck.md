Same-session functional follow-up, not a new discovery round.

Hard boundaries:
- Work only inside the original authorized workspace, read-only source review.
- Runner-managed report path: `runs/conference/mw_protocol_v3_1r2_functional_fresh_20260905/general_single_object_recheck.md`. Return report in final response; never write it using tools.

Initial read set:
- `context/mw_protocol_v3_1r2_functional_fresh_20260905_conference_context.md`
- `tests/protocol_v3/test_protocol_v3_1r2_mount.py`

Retain the original bounded reviewer role and all read-only/no-live/no-model/no-service boundaries. Do not edit source, create sibling reports, or close the task. Return the complete updated report for the runner to persist.

Re-read the current tests/protocol_v3/test_protocol_v3_1r2_mount.py and services/api/app/protocol_workflow/api/{__init__,router}.py. Verify whether your F1 and F2 are now resolved. You may run the same isolated focused pytest command authorized by the original context. Do not infer PASS from this request.

Actual-main OFF now compares a child with absent flag against another fresh child with the mount call replaced by a no-op. Check whether this actually tests no added v3 routes/database/threads. Initial zero-thread assertion failed on pre-existing durable-mw-sweeper; inspect main.py:2496 and its DurableJobWorker constructor to attribute this rather than assume main import is pure. Do not require altering that legacy worker or adding security engineering. Missing fitz/xlrd now fails, not skips. ON child remains.

Codex dispositions: F5 error mapping belongs to1R.3; process replay/backup remain1R.3. Full repository collection has separate historical asset and import gaps, so report functional review status separately from full-repository or final task acceptance. No claim of full gate closure is requested.

Return concrete remaining defects or state that F1/F2 are resolved, actual checks, residual limitations and scoped recommendation. Original report remains immutable; output goes to the new runner report path.
