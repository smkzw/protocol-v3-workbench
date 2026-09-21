# Codex Conference Review: mw_r11_v05_evidence_review_20260922

Date: 2026-09-22

## Verdict

PASS after one same-session repair verification round. This is engineering acceptance of the v0.5 evidence-persistence change only; it is not medical, UI, Word, or product-run acceptance.

## Boundary Compliance

The reviewer stayed read-only, used the declared workspace, did not invoke a product model, and did not modify source or runtime. The Hermes workflow guard and conference runner recorded actual route `zcode/zcode/GLM-5.3-Flash:max`; no fallback occurred. Both rounds used session `sess_c198002f-780f-474b-8791-a1ba6efd94ec`.

## Participant Outputs Reviewed

- Round 1: `runs/conference/mw_r11_v05_evidence_review_20260922/general_single_object.md`
- Same-session round 2: `runs/conference/mw_r11_v05_evidence_review_20260922/general_single_object_round2.md`

## Conference Panel Review

Round 1 independently reproduced one medium defect: a syntactically valid but evidence-damaged final v5 artifact was reused without chain validation. It also identified deterministic binding errors being classified retryable and two missing regression cases. Codex accepted these findings and repaired them as one batch. Round 2 independently reproduced the repair, confirmed the final artifact rebuilds from valid chunks without another model call, and verified read-time/adoption behavior. Its final low finding was the empty-list vacuous truth; Codex added the non-empty requirement and extended the damaged-final test.

## Main-Venue Codex Review

The final implementation uses one evidence-chain validator for chunk reuse, final reuse, final merge, read-time adoption readiness, and adoption. Evidence remains section-scoped, source membership is section-bound, binding locator must equal the persisted source locator, and quote hashes are verified. Legacy v3/v4 remains readable and non-adoptable. No second evidence store or security subsystem was added.

## Codex Independent Verification

- Owner and reviewer each ran the same focused backend set. Final owner result: 117 passed.
- `python -m py_compile` and `git diff --check`: passed.
- Reviewer used focused corruption probes for damaged bindings, swapped locators, empty section arrays, chunk reuse, and cross-chunk duplicate span IDs.
- The historical v0.4 artifact stayed unmodified and is now handled as legacy read-only.
- Real v0.5 model generation and medical content review remain pending by design.

## Final Decision

Accept the engineering batch and freeze it. Proceed to a new isolated Study A v0.5 job with `opencode-go/deepseek-v4.1-flash:max`; verify all 85 section evidence bindings before a fresh medical conference. Do not adopt v0.4 or any unreviewed v0.5 prose.
