# C03 Followup 01 — F-1 / O-1 Repair Verification (2026-09-13, same session GLM-5.3:max)

Review-only continuation of sess_edee5114. No repairs, no task closure, no recursive
agents, no services/models/OCR/Word/live/external writes. Writes confined to
`owner_followup_01/reviewer_scratch`. First-pass report and probes untouched
(mtime-verified). Owner decides acceptance.

## Verdict: **PASS — scoped finding closure (F-1 and O-1)**

Both repairs verified against the original MG-K10 source and fresh independent
counterexamples. No new defect found in the frozen scope. Residual notes below are
observations, not conditions.

## Scope integrity

- Frozen followup scope: the 7 files in `owner_followup_01/artifact_manifest.json`
  (docx_parse.py, research_seed.py, their two test files — repaired; plus
  writing_reference_docx.py, contracts protocol_v3.py, test_writing_reference_docx.py —
  byte-identical to first pass). Snapshot = manifest = live repo for all 7, before and
  after my probes (7/7, zero drift).
- The original 267-file snapshot is preserved untouched and was used as the historical
  baseline for the repair delta. Unfrozen adapter/runtime/input files may advance in
  owner work; nothing outside the frozen 7 was reviewed or accepted here.

## F-1 repair — bare-field TOC recognition: VERIFIED

Repair shape (diff old→new snapshot): `_paragraph_field_role` threads a shared field
stack through every paragraph in document order — `fldChar begin` pushes, split
`instrText` fragments accumulate onto the open field, `fldChar end` pops; `fldSimple`
TOC checked directly; classification `^\s*TOC(\s|$)` case-insensitive; stack cleared per
story root; `field_structure_pending` diagnostic when a story ends with an open field;
role assignment happens before the empty-text early return, so textless control
paragraphs still advance state.

### Real-document delta (logs/followup01_delta_real_doc.log, 10/10 checks)

Old-code mirror (first-pass snapshot docx_parse + frozen-identical dependencies, under
`reviewer_scratch/oldmirror/old_app`) parsed side-by-side with the repaired code on the
original MG-K10 bytes (SHA-256 re-verified `73024713…4199`):

- 2,608 blocks (incl. nested cells) in both; identical object ids, locators, texts,
  kinds — element-for-element, in order.
- Exactly 4 role deltas: `word/document.xml/body/124:p`, `…/125:p`, `…/128:p`,
  `…/129:p`, each `body → derived_toc` — precisely the four paragraphs identified in
  the first pass, and they are the bare-field list entries (text heads “表 1 研究流程表
  31”, “表 2 不良事件…”, “图 1 MG-K10…”, “图 2 研究流程图 54”).
- Role counts shift only body −4 / derived_toc +4 (flat totals 2459→2455 / 126→130;
  top-level equivalents 1126→1122 / 126→130 as first-pass recorded). Heading/header/
  footer untouched.
- Diagnostics unchanged: `visual_objects_pending` 1, no `field_structure_pending`
  (the document's fields are balanced). Hash, status, story parts, page-count-None,
  and deterministic re-parse all unchanged.

### Fresh counterexamples (mine, not the owner's tests; 13/13 pass —
logs/followup01_field_counterexamples.log)

- K1 begin/separate in a textless paragraph and a fully empty paragraph inside the
  range: state tracked, entries derived_toc, end-in-entry closes, following body clean.
- K2 unclosed TOC field: paragraphs inside the open range are labeled derived_toc AND
  `field_structure_pending` fires — over-labeling is visible, not silent.
- K3 story reset: an unclosed document field does not leak into `word/header1.xml`
  (header block stays role `header`); diagnostic pinned to `word/document.xml`.
- K4 PAGE field and K5 bare PAGEREF cross-reference: stay `body` (no over-claim).
- K6 `fldSimple` with lowercase ` toc ` → derived_toc; `fldSimple REF` stays body.
- K7 TOC field entirely inside a table cell: cell entry derived_toc, field closed
  inside the cell, following body paragraph unaffected, no diagnostic. (Table block
  itself keeps kind/role `table/body` — role tracking is paragraph-level, consistent
  with first-pass design.)
- K8 nested PAGEREF inside the TOC range (standalone end marker): entries stay
  derived_toc until the outer end.
- K9 instruction split as `TO` + `C \h` across runs: still recognized (accumulation).
- K10 gallery-SDT TOC behavior from pass 1 unchanged alongside the new tracker.
- K11 `TOCX`, `NOTOC`, `TOCIOUS` prefixes: not classified as TOC.

## O-1 repair — source-basis raw binding: VERIFIED

Repair: for `basis='source'`, `raw` must be non-blank and a substring of at least one
*referenced* unit's text, else `seed_source_raw_not_found` (research_seed.py:141–145).

Checks (12/12 pass, logs/followup01_seed_checks.log):

- TOC-entry quotes under `project_primary` now land `reference_only`, not
  `project_material` (S0/S1) — the F-1 downstream interaction is closed at the label
  level because the unit role is `derived_toc`, not `body`.
- Invented raw beside a valid reference rejected; whitespace-only raw rejected; raw
  present in a different, non-referenced unit rejected (S3–S5); raw genuinely inside a
  referenced unit accepted (S6); with multiple references, raw found in any referenced
  unit accepted (S7).
- Existing semantics intact: body-quote candidate still `project_material` (S8);
  user basis still checked against the brief only (S9); recommendation basis unaffected
  (S10); quote-per-(source, locator) binding still enforced before the raw rule (S11).
- `canonical` stays empty, `requires_confirmation` always set, quote presence remains
  provenance-only (no entailment/admission claim anywhere).

## Declared evidence reconciled

- Owner green log `runs/mw_protocol_v3_v1_1_20260913/toc_raw_followup_green.log`: 21
  passed in 0.75 s. Of those, 19 are the frozen docx/seed files — I re-ran exactly
  those myself: 19/19 passed (logs/pytest_frozen_docx_seed.log). The remaining 2 are
  the mounted source-import API tests, which run against unfrozen runtime files; per
  this followup's constraints I did not re-run them and I do not treat that portion as
  independently re-verified here (first pass verified the mounted chain against the
  then-frozen code). No unrelated runtime/transport changes are accepted by this
  review.

## Residual observations (no action required)

- Unclosed fields over-label the remainder of their story as derived_toc. This is the
  safe direction (never mistaken for primary body evidence) and is always accompanied
  by the explicit `field_structure_pending` diagnostic, so it is visible, not silent.
- `field_structure_pending` fires per story part with an open field; on the real
  document it does not fire.
- Harness transparency: two of my probe expectations were initially self-wrong and were
  corrected against frozen code (K7 expected a block for a textless control paragraph;
  S11 passed `quote` at candidate level). Final logs reflect the corrected checks; all
  product-behavior outcomes above passed on the frozen code as-is.

## Limitations

- Verification used the original MG-K10 DOCX (path and SHA-256 per original prompt,
  re-hashed, read-only) plus synthetic documents; the CMS-D008 EndNote capability was
  re-exercised via the frozen suite (passed).
- No model normalization/generation/admission is implemented in this scope, and none
  was demanded, consistent with the pending E0–E3 pipeline.
- Broad API/runtime/identity suites were intentionally not re-run (frozen in pass 1,
  out of followup scope).

## Artifact hashes (sha256)

- logs/followup01_delta_real_doc.log `7e42f7bb…bd8d1`
- logs/followup01_field_counterexamples.log `1038e63e…07ec`
- logs/followup01_seed_checks.log `9a078848…db31`
- logs/pytest_frozen_docx_seed.log `3789ffb3…bc91`
- followup01_delta_real_doc.py `843c807f…fc35`
- followup01_field_counterexamples.py `7e3fc9a5…daff6`
- followup01_seed_checks.py `fbfdf809…fb4a`

## Closure statement for owner decision

F-1: closed by repair — bare complex TOC fields (begin/instrText/separate/end across
paragraphs, split instructions, nested PAGEREF, fldSimple) are recognized as
derived_toc with story-scoped state, empty control paragraphs track state, and the
real-document delta is exactly the four previously mislabeled entries with all other
2,604 objects byte-stable. O-1: closed by repair — source-basis raw is now bound to
referenced unit text. Both repairs preserve prior verified semantics (hashes, locators,
proposal-only seed state, Chinese envelopes untouched in frozen files). PASS, scoped to
the frozen seven files.
