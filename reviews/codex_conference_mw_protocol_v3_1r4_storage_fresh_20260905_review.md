# Codex Conference Review: mw_protocol_v3_1r4_storage_fresh_20260905

Date: 2026-09-05

## Verdict

REVISE for complete1R.4 storage/runtime acceptance. Consolidation/projection
review returned fit, but Codex follow-up reproduced a real dispatch durability gap.

## Boundary Compliance

Isolated sources and synthetic data only; reviewer reports stopping its own
deadlocked probe after a barrier-design error, then fixing it. No product failure
or live/model invocation inferred from that probe incident.

## Participant Outputs Reviewed

general_single_object.md read fully; original report and raw receipt retained.

## Conference Panel Review

Actual ZCode/GLM-5.3-Flash:max, sessionsess_ec127744-fb0d-4fa6-987d-41851876b71b,
1004.53s,39toolcalls. Legal new-session schedule reconciliation at19:00 changed
the created Grok route to off-peak ZCode; no fallback.149tests+15probes reported.

## Main-Venue Codex Review

R1 superseded adoption reproduced and repaired: same-sha replay preserves the
terminal historical row without adopting it as RECEIVED. R2 lifecycle coverage
added; normal unknown/recover/reopen/reuse passes, but independent-connection
probe at dispatch sees no durable reservation in raw-UoW composition. This is
not closed by the reviewer's original piecewise checks. R3 failed-message receipt
remains explicit/manual resolution, not an automatic retry path.

## Codex Independent Verification

1r4_superseded_red.xml reproduces reactivation; green19passed0.41s.
1r4_sqlite_reservation_lifecycle.xml1passed0.34s.
1r4_dispatch_durability_red.xml1fail1pass0.35s proves the unresolved boundary.
All under runs/mw_protocol_v3_1r_integration_20260905/. No UI/Word/clinical acceptance.

## Final Decision

Continue bounded repair packet mw_protocol_v3_1r4_durable_dispatch_20260905.
Do not close1R.4/P1R or rerun completed reviewer handle74596. Preserve evidence.
New repair uses the same model as this reviewer, so its later independent
acceptance must use a fresh eligible different route, not this reasoning session.
