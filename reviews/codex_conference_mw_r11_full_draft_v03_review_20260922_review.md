# Codex Conference Review: mw_r11_full_draft_v03_review_20260922

Date: 2026-09-22

## Verdict

**REVISE.** Study A v0.3 is a durable, numerically faithful partial-draft candidate, but it is not safe to adopt as a submission-bound draft. The raw artifact remains immutable and was not adopted.

## Boundary Compliance

The independent reviewer used the declared read set plus four source-of-truth files already named by the packet. It did not modify source or runtime state, did not read the secret file, and returned a complete report. Runtime identity was `codebuddy/codebuddy-cli/deepseek-v4.1-flash:max`; no fallback was used.

## Participant Output Reviewed

The report in `runs/conference/mw_r11_full_draft_v03_review_20260922/evidence_single_object.md` independently checked all 85 generated candidates against StudyDefinition revision 8 and the current review projection. It found strong numerical fidelity, two unsupported high-impact rules, repeated design facts, several generic scope paragraphs, and a chapter-level confirmation queue that does not match the user's decision-level mental model.

## Conference Panel Review

Accepted findings:

- Section 4.4 invents blinded roles and detailed individual-unblinding documentation duties although the bound StudyDefinition leaves `blinded_roles` and `blinding_details` empty.
- Section 14.1 turns an undecided contraception policy into a study requirement and conflicts with section 7.3.4.
- Section 9.5 and section 10.3 contain additional analysis or responsibility rules not established by revision 8.
- The candidate repeats design facts heavily and several background sections read as scope notes rather than usable scientific background.
- Eighteen chapter-level confirmations are not a suitable substitute for a smaller queue of explicit scientific decisions. They also consume nearly the whole product click budget.

Finding narrowed by direct verification:

- The report's “14 missing headings” is not a document-level absence. The live document session contains 105 sections. Sections 2.5, 3.2, 4.2, 5.1, 6.2, 7.2 and 9.1–9.4 already exist as substantive seeded candidates; 1.1 is structural content. Sections 1.2, 1.3 and 13 remain actionable content/structure gaps. The conference only saw the 85 blank-section fill artifact, so its missing-section inference was intentionally conservative but over-broad.

## Main-Venue Codex Review

The frozen artifact SHA-256 remains `c2e98124598aa71a2e36eedb173cd24163d8a8504f41d9996a963cf241192da9`; StudyDefinition revision 8 remains SHA-256 `3989470f61c21914c0df6910a0a80af4593ce2b08bbd31281cf44e0b069f272e`. The current read-time policy is `protocol_full_draft_review_v0_2` and projects 18 required cards. The persisted raw count of 67 is historical artifact metadata; the API deliberately recalculates the current projection without altering the raw bytes. This distinction must remain visible in evidence records.

The current batch fixes the user-facing presentation and recovery path but does not pretend to repair the medical content. The side rail now opens a full-screen two-column review workspace; generated chapters are described as a blank-section fill batch merged into the 105-section document, rather than as the whole document. A completed job locator remains in local storage across reload and is cleared only after successful adoption.

## Main-Venue Hermes Review

No separate Hermes chair was declared for this packet. The current Codex owner performed the required main-venue synthesis and retained the guarded runner receipts; this heading records that the Hermes workflow guard contract was reconciled without implying an unrun reviewer.

## Codex Independent Verification

- Live API: 105 current document sections; 85 generated blank-section candidates; 18 current review cards.
- Missing-heading reconciliation: ten alleged missing body headings are present as substantive candidates; 1.1 is structural; 1.2, 1.3 and 13 remain blocked.
- Browser at 1600×1000: 312 px chapter navigation, 1202 px review body, 85 cards, 18 required/open cards, no horizontal overflow. One checkbox changed progress to 1/18 and was then restored to 0/18. Close and reopen both worked. Adoption stayed disabled.
- Refresh recovery: the persisted completed job restored the same candidate and reopened the review workspace. The browser's test-only local-storage locator was restored through CDP because the earlier code had already deleted it; no product or study data was changed.
- Backend focused regression: 160 passed.
- Frontend authoritative inventory: 15 Vitest files / 110 tests and 48 Node files / 65 tests passed.
- Frontend production build: 1971 modules passed; existing large-chunk warning remains.
- `git diff --check`: passed.

## Final Decision

Do not adopt Study A v0.3. Preserve it as evidence and use it to implement v0.4 with: (1) explicit decision items and AI recommendations, (2) no prescriptive rule when the project fact is absent, (3) source-gap status instead of generic filler, and (4) decision-level review rather than repeated chapter-level confirmation. Re-run only the failed content-generation scope; do not repeat triage, download, OCR, translation, or the five historical failures.
