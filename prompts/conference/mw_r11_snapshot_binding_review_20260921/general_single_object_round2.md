This is corrective verification in the same session. Do not restart the task.

Re-read the current diff only for:
- `services/api/app/medical_writing_authoring_journey.py`
- `services/api/app/medical_writing_competitor_triage.py`
- `tests/test_medical_writing_authoring_journey.py`
- `tests/test_medical_writing_competitor_triage.py`
- `runs/requirements_v2_20260919/f12_20260921/study_a_snapshot_binding_recovery/recovery-reversal-result.json`

Owner acted on your report before accepting the batch:
1. Same-filter snapshot reuse now treats changed triage criteria as `triage_pending`; framing commit clears active discovery projection and corpus triage while preserving repository history.
2. Projection retry checks `_stale_reason` before historical restore; a stale run cannot be rebound or finalized.
3. Restore failures persist as `deferred_until_picos` with `projection_error`.
4. Study A revision 20 to 22 recovery was rejected after proving the run material-facts hash differs from the current journey. Both runtime SQLite databases were restored from pre-recovery online backups to revision 20. The old receipt remains rejected-attempt evidence; `recovery-reversal-result.json` records the reversal.
5. Owner ran the concentrated suite after these changes: 469 passed; syntax and `git diff --check` passed.

Independently decide PASS, FAIL, or UNVERIFIED for each item and look for a new regression. Do not open runtime SQLite/backups/credentials, modify files, or run tests. Return a concise corrective verification with file:line evidence. Distinguish source repair from real Study A status: Study A must remain blocked from corpus admission until a human explicitly re-reviews the existing basket against current criteria, without rerunning AI triage.
