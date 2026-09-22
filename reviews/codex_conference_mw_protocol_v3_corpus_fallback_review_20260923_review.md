# Codex Conference Review: mw_protocol_v3_corpus_fallback_review_20260923

Date: 2026-09-23

## Verdict

PASS after owner repairs. The initial independent review found two high-impact defects: fallback-level thinking/effort overrides were frozen but not honored during execution, and an unavailable optional fallback prevented a healthy primary route from freezing. Both were reproduced, repaired, and independently rechecked in the same session. No actionable defect remains in the reviewed scope.

## Boundary Compliance

The reviewer stayed read-only in the authorized workspace, used `zcode/zcode/GLM-5.3-Flash:max`, retained session `sess_aa7ce14d-eeba-45d2-af67-42f549e3b528`, and used no fallback. Temporary review scripts and a venv were created only under `/tmp`; no product source was modified by the reviewer.
The Hermes workflow guard and conference runner receipts are preserved as orchestration evidence; Codex remains the final integrator.

## Participant Outputs Reviewed

- Final participant report: `runs/conference/mw_protocol_v3_corpus_fallback_review_20260923/general_single_object.md`.
- Runtime receipts: `logs/conference/mw_protocol_v3_corpus_fallback_review_20260923/general_single_object_stdout.txt` and `general_single_object_stdout_round2.txt`.

## Conference Panel Review

The first pass found that per-route fallback thinking/effort was recorded during freeze but lost during execution, and that an unavailable optional fallback could block a healthy primary. The owner repaired both. Same-session follow-up independently verified the repairs, legacy no-option identity and deduplication, unavailable fallback skipping, and tampered-chain rejection.

## Main-Venue Codex Review

- Execution rebuilds a fallback provider from the exact frozen route thinking/effort overrides while retaining revision and provider/model/base URL/transport/response-model checks.
- New work skips duplicate or currently unavailable optional fallbacks during freeze; the immutable job retains only routes resolvable at freeze time.
- Results persist the full frozen chain, chain id, actual effective route, fallback depth, and reason. Completion audit uses the provider/model that actually returned the accepted result.
- Fallback remains limited to 408, 429, 500, 502, 503, 504, transport failures, and empty responses. Authentication/configuration errors, invalid content, and identity mismatch remain terminal.

## Codex Independent Verification

- Compilation and `git diff --check` passed.
- Reviewer focused corpus-analysis suite: 59 passed, plus independent legacy/tamper reproductions.
- Owner concentrated model/settings/corpus/pipeline regression: 216 passed.
- Owner full `tests/protocol_v3`: 2608 passed with one pre-existing Python 3.14 tar deprecation warning.
- One separate top-level preparation-stage test is stale against already committed automatic stage draining and is not part of this diff.
- Local MTPLX generation quality remains unverified because port 11234 had no listener. This backend batch does not claim live model acceptance.

## Final Decision

Accept the corpus-analysis fallback batch. It preserves legacy frozen jobs and immutable work identity, honors user-selected provider/model/thinking/effort, prevents optional fallback outages from taking down the primary route, and records declared versus effective route provenance truthfully.
