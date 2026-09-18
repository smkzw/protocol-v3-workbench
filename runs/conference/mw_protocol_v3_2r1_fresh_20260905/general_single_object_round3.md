# Conference Participant Output: mw_protocol_v3_2r1_fresh_20260905 - general_single_object_round3

## Boundary Check

- Read-only revalidation; zero source edits. No services, models, network, OCR/translation, live or monitoring access. No `main` import (not needed for this surface; readiness delta was covered in round 2). Sanitized env throughout (`.local/bin`-first PATH, venv Python, fresh `WORKBENCH_RUNTIME_DIR`, `-p no:cacheprovider`).
- New evidence: none written as files this round (inline checks only); all round-1/round-2 evidence preserved and re-used, notably `r2_concurrent_receipt_probe.py` re-run verbatim against the repaired code.
- Identity unchanged (`pi / opencode-go / muse-spark-1.3-contributor / xhigh`). No Trellis closure, no product/clinical/Word acceptance.

## Revalidation Findings

Read `runtime.py` receipt path in full (`:607-728`, `_append_node_result` guard `:1368-1395`, transition handling `:702-722`) and all of `tests/protocol_v3/test_graph_receipt_atomicity.py`. Codex's choices (identical→success/idempotent, different→typed `graph_node_completed`; in-tx guard on the receipt path; transition collision accepted only on actually-COMPLETED matching hash) are implemented as specified.

### R2-1 (concurrent receipt recoveries commit conflicting results) — FIXED, verified with my own original driver

- Repair: `_append_node_result(..., recovered_receipt=True)` now appends through `_append_events_tx` with an in-tx `receipt_guard` (`:1368-1395`) — same node+sha+reservation+recovered → reuse (`False`, no second event); any other pre-existing result for the node → typed `graph_node_completed`. Transition collision (`:714-722`) is absorbed only when the row is actually `COMPLETED` with the matching hash; otherwise typed `graph_reservation_contended_retryable`. No raw `RepositoryStateTransitionError` can escape either overlap shape.
- Evidence: re-ran round-2 `r2_concurrent_receipt_probe.py` (barrier-forced, different payloads) verbatim — before: `n_draft_results: 2`, loser raw `RepositoryStateTransitionError`; now: `outcomes: {A: GraphRunError:graph_node_completed, B: ok:completed}`, `n_draft_results: 1`, single COMPLETED attempt. Committed tests agree (`test_overlapping_receipts_commit_one_result`, both params): identical → `["ok","ok"]`, different → `["graph_node_completed","ok"]`, exactly 1 result event, reservation hash equals event hash.

### Challenge (changed payload + old hash falsely acked) — CONTRACT CORRECTED, verified

- Validation now precedes completed-state reuse: hash recompute + mismatch raise at `:631-637`, reuse check at `:643-657`. `test_reused_receipt_checks_supplied_payload` covers it, and I confirmed directly: changed-payload+old-hash → `GraphRunError graph_receipt_hash_mismatch`, stored event count unchanged (1→1, no overwrite). Hash-only reuse on a completed node (output=None + matching sha) returns the snapshot with no new event — honest read, no new content claimed or acknowledged, so the hole stays closed.

### F4 gap (concurrent start untested) — CLOSED

- `test_overlapping_starts_commit_one_binding` parks two overlapping callers before the transaction (Barrier inside the `_append_events_tx` wrapper): identical → `["ok","ok"]`, different → `["graph_run_binding_conflict","ok"]`, exactly one `graph_run_started` event. This is the executional test round 2 asked for; combined with the `_start_guard` code already reviewed, F4 is now both constructed and executed.

### F1–F6 carryover — all hold

- 75 focused tests green in 12.9 s (70 prior + 5 new), no regressions. Nearby windows re-checked: reservation-repair path creates no result events (no interaction with the receipt guard); kill-after repair is reservation-only; decision result events ride inside the already-guarded decision tx (no split-window); orphan/retry contention translations unchanged.
- Offline-only QC limitation stands as scoped in round 2 (provenance evidence only, activation deferred).

## Evidence And Assumptions

- Observed: 5/5 new atomicity tests pass; full 75-set green; original receipt-race driver before/after transcripts; direct reuse-contract edge transcript; exact code ranges above.
- Inference (minor): hash-only-on-completed honesty follows from "no event written, snapshot returned" — grounded in the 1→1 event count observed, not just reading.

## Remaining Risks

1. None new found on the revalidated surfaces. Residual, previously noted: `flock` liveness assumes local FS; QC/model activation remains a named later gate.
2. The receipt guard keys reuse on (node, sha, reservation, recovered-flag). A pathological caller reusing one reservation id across two genuinely different recoveries with identical bytes is indistinguishable from idempotent retry — acceptable (same content, same lineage) and consistent with the identical→success choice.

## Recommended Next Step

Accept R2-1, F4-gap, and the reuse-contract correction as verified; close the review loop on these three items only. Suggested Codex acceptance checks: 75-focused green + the two committed overlap tests + the reuse-payload test (all already in-tree, no new harness needed). Still no Trellis task closure or product acceptance from this role — F6's activation gate and any non-graph scope remain with Codex.
