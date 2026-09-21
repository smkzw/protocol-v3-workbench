# Study A full-draft v0.3 stage record

Date: 2026-09-22

## Scope and authority

This batch continued F12 on the existing isolated Study A runtime. It did not touch live ports 8910/5186/5285 and did not repeat triage, retrieval, download, OCR, translation or the five historical failed items. The work mode was execution plus independent conference because product-model output and submission-bound medical text required both implementation and a fresh challenge pass.

## Identities

- Project: `proj_user_8a5a00cb014a`
- StudyDefinition: `mwdefinition_1ded2281210281a3b8a0`, revision 8
- StudyDefinition SHA-256: `3989470f61c21914c0df6910a0a80af4593ce2b08bbd31281cf44e0b069f272e`
- Durable job: `mwjob_ccfa294601420a96bd660cf9`
- Immutable raw artifact SHA-256: `c2e98124598aa71a2e36eedb173cd24163d8a8504f41d9996a963cf241192da9`
- Product route: provider `opencode-go`, model `deepseek-v4.1-flash`, thinking `max`
- Current read-time review policy: `protocol_full_draft_review_v0_2`

## What was built

- Product AI defaults and runtime identity checks now use the exact requested `opencode-go/deepseek-v4.1-flash:max` route and OMP-compatible authentication headers.
- The generator persists and resumes chunk output, uses a bounded same-model structural correction, and no longer overflows the durable artifact locator.
- The review projection reduced historical incidental keyword escalation from 67 raw flags to 18 current chapter cards without changing the raw artifact.
- The former 413 px side-rail review became a full-screen two-column workspace with a dense chapter navigator and a wide reading surface.
- A completed draft locator now survives page reload; it is removed only after successful adoption.
- User-facing copy now says that 85 blank sections were filled and merged with the current 105-section document. It no longer presents 85/85 as document-level completeness.

## Actual model run

The same durable job completed 85/85 target sections. Recovery reused persisted chunks. The run encountered and recovered from: missing exported provider key, malformed evidence-quote repair, and two empty provider responses. No key material was written to registry, prompt, checkpoint, trace or durable product logs.

## Independent content review

Conference `mw_r11_full_draft_v03_review_20260922` completed with `deepseek-v4.1-flash:max` and returned REVISE. Numeric fidelity to revision 8 was strong. Adoption remains blocked because section 4.4 invents blinded roles and unblinding duties, section 14.1 invents a contraception rule, and several sections hide missing source classes behind generic prose. The current 18 confirmations are still chapter-based rather than scientific-decision-based.

The review's initial claim that 14 headings were absent was reconciled against the live 105-section document. Ten body headings already exist as substantive seeded content and 1.1 is structural. Study schema, schedule of activities and references remain real actionable gaps.

## Browser acceptance

At a 1600×1000 viewport the modal measured 1552×952 px. The chapter column was 312 px and the reading column 1202 px. All 85 candidates were present; 18 required cards were open; body scroll width equalled client width. Checking one card changed progress to 1/18, unchecking restored 0/18, and adoption remained disabled. Closing and reopening the workspace worked. A visible screenshot was inspected in the browser session; no durable screenshot file was produced by the available capture API.

The test session inserted only the completed job locator into browser local storage to reconstruct the state deleted by the old code. It did not adopt content or mutate the study. That locator remains to support continued browser verification.

## Concentrated validation

- Backend affected suite: 160 passed, 17 existing deprecation warnings.
- Frontend authoritative inventory: 15 Vitest files / 110 passed; 48 Node files / 65 passed.
- Frontend production build: 1971 modules passed; existing chunk-size warning only.
- `git diff --check`: passed.

## Decision and next action

Study A v0.3 is preserved as review evidence and is not adopted. The next implementation batch is v0.4: add explicit decision items with recommended and alternative choices; classify source gaps separately from completed prose; prohibit unsupported prescriptive rules in generation and validation; and replace repeated chapter confirmation with the smallest decision-level queue. Re-run only affected generation chunks after those contracts are complete.
