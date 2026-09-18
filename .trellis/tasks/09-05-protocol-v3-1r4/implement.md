# Execution preparation

Dependency met:1R.3 fresh recheck accepted; see reviews/codex_conference_mw_protocol_v3_1r3_fresh_20260905_review.md. Proceed with bounded implementation.

1. Audit current ports/callers and fix exact migration representation; add
   failing real-SQLite migration/replay checks. One worker owns storage changes.
2. Implement result-store consolidation with compatibility, then verify. Keep
   historical rows and existing negative fixtures; do not weaken source integrity.
3. Simplify result presentation/contract dependency serialization with versioned
   compatibility and exact-input-change checks. Assign disjoint ownership only.
4. Run full protocol_v3 plus integration suite. Fresh independent verifier checks
   actual migration and recovery, then Codex records completion without pausing.

Use latest workflow guard, no Trellis auto-dispatch. Do not initialize/launch
workers until predecessor reviewed and write ownership assigned. No cleanup.
