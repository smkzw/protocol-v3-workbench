# Codex Conference Review: mw_r11_snapshot_binding_review_20260921

Date: 2026-09-21

Workflow: Codex-chaired conference initialized and validated through the Hermes workflow guard; the effective participant route was Z Code as recorded below.

## Verdict

PASS after corrective follow-up for the snapshot-binding repair. Study A corpus admission remains intentionally blocked pending a new human basket re-review action; this review is not full Protocol v3 acceptance.

## Boundary Compliance

The reviewer stayed read-only, did not open runtime SQLite/backups/credentials, and did not run product models, searches, OCR, translation, services, browsers, or tests. Runtime receipt confirms `zcode/zcode/GLM-5.3-Flash:max`; no fallback occurred.

## Participant Outputs Reviewed

- `runs/conference/mw_r11_snapshot_binding_review_20260921/general_single_object.md`
- `runs/conference/mw_r11_snapshot_binding_review_20260921/general_single_object_followup.md`
- session `sess_6dbc92ce-b722-45a0-ae67-dd518c02cfe2`

## Conference Panel Review

The first pass accepted same-registry snapshot preservation and exact historical restoration, then correctly found that changed medical triage criteria could leave an old confirmation active. It also found unpersisted restore failures. The owner reproduced the concern on Study A: the stored triage material-facts hash differed from the current journey.

The corrective pass confirmed the repair: criteria changes now make the search plan `triage_pending`, clear active discovery/corpus projections, keep repository history, and block stale runs before restore/finalize. Restore exceptions are persisted. It found no new correctness regression.

## Main-Venue Codex Review

Codex rejected the apparent revision 20 to 22 success after the stale material-facts mismatch was proven, restored both runtime databases from online pre-recovery backups, retained the rejected receipt, and added a reversal receipt. No external research or model work was repeated.

The remaining product gap is explicit: the system can now block stale admission but cannot yet let the user re-review the existing basket under current criteria without a new AI triage run. That becomes the next bounded implementation batch.

## Codex Independent Verification

- Syntax and `git diff --check`: passed.
- Concentrated backend suite: 469 passed; 17 existing deprecation warnings.
- Logical rollback verification: journey DB 4 tables/1066 rows and writing-reference DB 47 tables/2389 rows exactly match their pre-recovery backups by per-table canonical content hash.
- Study A restored state: revision 20, search binding blank, corpus triage pending, confirmation `deferred_until_picos`, projection attempts 1.
- No browser/Word acceptance was needed for this backend consistency batch.

## Final Decision

Accept the code repair and rollback evidence. Do not mark Study A corpus-ready. Continue with a user-facing, explicit human re-review and controlled rebind path that reuses the existing immutable snapshot and basket without model triage, download, OCR, or translation reruns.
