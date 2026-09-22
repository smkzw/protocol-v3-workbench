# Codex Conference Review: Protocol v3 WP6 final review

## Verdict

**INCORPORATED_WITH_OPEN_ITEMS**. Frozen source `e8966d5`; reviewer route `zcode/zcode/GLM-5.3-Flash:max`, one completed session, no fallback.

## Boundary Compliance

The participant remained read-only, did not inspect secret runtime files, did not call product models or alter source/Word/SQLite, and did not claim final clinical or product acceptance. Codex retained final integration authority.

## Hermes Participant Output

The guard/runner persisted `runs/conference/mw_protocol_v3_wp6_final_review_20260923/general_single_object.md`; runtime identity was verified as GLM-5.3-Flash:max. One round completed after the same 7200-second hard-wait handle; no latency redispatch or fallback occurred.

## Codex Independent Verification

The reviewer found no P0/P1 and independently reproduced 14 focused tests. Codex independently confirmed the Study C sample-size contradiction: delta 3, SD 8, two-sided alpha .05 and 90% power require about 149 evaluable participants per arm before attrition; 170 total with 15% attrition yields about 62% power under the simple two-sample approximation. This is a P2 medical-content defect in a synthetic working draft, not a product-runtime crash. It prevents formal-readiness claims and is recorded in the acceptance checkpoint.

Accepted findings: sample-size contradiction and qualifier loss (P2); current V01 screenshot gap, route-wide font coverage limitation, inferred Study A receipts, and unverified local MTPLX quality (P3); minor cleanup observations (P4). The claimed mixed terminology refers to the preserved older Office head; the newly exported Study C candidate r2 is normalized to 58 `试验参与者` and 0 `受试者`. Keeping the older Word head is expected no-silent-overwrite behavior, so no source change is required.

Owner conclusion: A/V/B remain a mixture of PASS and PARTIAL as itemized in `ACCEPTANCE_CHECKPOINT_20260923.md`; Protocol v3 is not finally delivered and the work drafts are not submission-ready.
