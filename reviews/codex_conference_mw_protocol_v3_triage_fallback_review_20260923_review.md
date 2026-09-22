# Codex Conference Review: mw_protocol_v3_triage_fallback_review_20260923

Date: 2026-09-23

## Verdict

PASS after owner repairs. The first pass found one P0 and one P1; the same-session continuation found one additional P1. All three were reproduced and repaired before acceptance. No P0/P1 remains in the reviewed scope.

## Boundary Compliance

The reviewer stayed read-only in the authorized workspace, used the declared `zcode/zcode/GLM-5.3-Flash:max` route, retained the same session `sess_82ae012a-46fe-4070-892e-ef95716339ff`, and used no fallback. It did not modify product source or claim final acceptance. A temporary review venv was outside the workspace; a PEP 668 refusal prevented user-site modification.
The Hermes workflow guard and conference runner receipts were preserved and validated; they are orchestration evidence, while Codex remains the final integrator.

## Participant Outputs Reviewed

- Initial report: `runs/conference/mw_protocol_v3_triage_fallback_review_20260923/general_single_object.md`.
- Same-session repair review: `runs/conference/mw_protocol_v3_triage_fallback_review_20260923/followup_01/general_single_object.md`.
- Runner receipts: corresponding stdout JSON files under `logs/conference/mw_protocol_v3_triage_fallback_review_20260923/`.

## Conference Panel Review

The initial review decisively found that v1 frozen route identities could parse but could not resume, and that changed route-chain hashes surfaced as an unhandled durable conflict. It also found provenance and observability gaps. Owner repairs rebuilt identities under the frozen route's schema, mapped create/retry conflicts to the existing 409 domain exception, tracked attempted and active routes separately, hashed the complete frozen chain, logged unavailable fallback routes, and labelled cross-provider successful runs `mixed`.

The same-session continuation found one remaining P1: HTTP triage creation used role-binding thinking/effort while the frozen and resumed job used profile thinking/effort. Owner changed HTTP provider construction to use the same profile environment, propagated thinking/effort through the verified wrapper, and included both in identity mismatch diagnostics.

## Main-Venue Codex Review

Codex accepted the product semantics that v1 jobs resume with their original identity, route-chain changes are explicit 409 conflicts, and a durable triage run may use fallback on later chunks as long as chunk provenance is exact and a multi-provider result is labelled `mixed`. Remaining P2 items are non-blocking: a rare missing-ID repair can combine content from two routes inside one chunk without a separate repair-route field; rollback from v2 code to pre-v2 code requires cancelling/re-submitting pending v2 jobs; unavailable fallback routes are logged and skipped rather than blocking a healthy primary.

## Codex Independent Verification

- Python compilation and `git diff --check` passed.
- Four focused route/profile/legacy/conflict checks passed.
- Full competitor-triage family: 460 passed.
- Full `tests/protocol_v3`: 2608 passed, with the pre-existing Python 3.14 tar future warning only.
- MTPLX port 11234 had no listener and `/v1/models` returned proxy-level 502, so local MTPLX generation quality remains unverified. No browser or Word acceptance was required for this backend routing batch.

## Final Decision

Accept and commit the reviewed batch. It adds fallback to the legacy durable competitor-triage path while preserving old v1 jobs, logical-work conflict semantics, exact model identity, and per-chunk audit provenance. This does not complete the separate corpus-analysis direct-provider migration or MTPLX quality acceptance.
