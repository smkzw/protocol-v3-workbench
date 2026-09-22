# Codex Conference Review: mw_protocol_v3_interactive_fallback_review_20260923

Date: 2026-09-23

## Verdict

PASS for the bounded synchronous interactive fallback implementation and its deterministic regression evidence. This is not final Protocol v3 product acceptance and does not verify live MTPLX output quality.

## Boundary Compliance

The reviewer remained read-only, used the declared `zcode / GLM-5.3-Flash / max` route, retained one session across three conference passes, did not modify source, and did not invoke product models, OCR, translation, browser, or Word workflows. Codex performed all repairs and final verification.

## Participant Outputs Reviewed

Codex reviewed `runs/conference/mw_protocol_v3_interactive_fallback_review_20260923/general_single_object.md` and the runner receipts. The reviewer initially found five material defects: empty HTTP-200 responses could be misclassified as model mismatch; timeout assignment did not reach wrapped providers; unavailable prefill configuration could become HTTP 500; wrapper construction could elevate an untrusted provider into the trusted path; and repeated runs could retain stale fallback state. All five were repaired before the final same-session review.

## Conference Panel Review

The final panel pass found no remaining release-blocking defect in the fallback chain. It confirmed that user-selected provider/model/thinking/effort reaches the selected route, each route performs one adapter attempt, only the declared retryable failure classes advance the chain, effective provider/model are captured after fallback, and production chain construction admits only `OpenAICompatibleAiProvider` members. The reviewer classified incomplete prefill fallback-depth metadata and aggregate all-route failure history as nonblocking follow-up work because they do not falsify the effective provider/model or generated output.

The panel also identified three pre-existing stale assertions: one 32768-token expectation after the accepted 65536 budget and two full-draft prompt pins at v0.9 after server authority moved to v0.11. Codex upgraded those assertions and added the v0.11-required `gap_items` fixture.

## Main-Venue Codex Review

Codex independently checked the source paths, test contracts, and exception mappings. The repaired gateway classifies a truly empty completion before model-identity mismatch while retaining the observed response model in diagnostics. The runtime wrapper broadcasts timeout values, resets active-route state per run, and records the actual successful route. `main.py` preserves deterministic prefill when no usable chain is configured and restricts production wrapper members to the validated OpenAI-compatible implementation.

Known nonblocking limitations are retained in the handoff: prefill records effective provider/model but not the same four fallback-detail fields as fact intake; an all-route failure exposes the final explicit cause rather than a complete attempt history; and live MTPLX behavior remains unverified while the local endpoint is unavailable.

## Codex Independent Verification

- Focused matrix covering gateway, wrapper, fact intake, API, prefill, task runner, runtime settings, role settings, and execution policy: **297 passed**, 17 deprecation warnings.
- Complete `tests/protocol_v3`: **2608 passed**, 1 Python tar extraction deprecation warning.
- Conference runner evidence: three completed passes in the same ZCode session, requested and returned model `GLM-5.3-Flash`, no fallback.
- No browser, native Word, clinical-content, or live-provider acceptance was claimed for this bounded backend batch.

## Final Decision

Accept and commit this batch. Hermes conference evidence and Codex deterministic checks agree that the synchronous fact-intake and authoring-prefill fallback chain is fit to become the current implementation baseline. Resume product-level WP6 acceptance separately, beginning with current endpoint availability and the outstanding real-model, browser, Word, and medical acceptance work.
