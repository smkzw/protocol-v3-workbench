# Codex Conference Review: mw_r11_editor_verification_20260921
Date: 2026-09-21

## Verdict
PARTIAL ACCEPTANCE / CONTINUE IMPLEMENTATION. Scoped editing identity, layout and loss prevention repairs have source and runtime evidence. Whole clinical product and current-Word scientific reconciliation remain unaccepted. No stage pause.

## Boundary Compliance
Reviewer codebuddy/deepseek-v4.1-flash, same review session across three passes, Read/Grep/Glob only; no independent browser/test execution. This is source review, not native Word acceptance. Owner retains final integration and rendered verification. No GPT Pro review was performed this round.

## Participant Outputs Reviewed
runs/conference/mw_r11_editor_verification_20260921/evidence_single_object.md
evidence_single_object_followup.md
evidence_single_object_word_followup.md (same directory).

## Main-Venue Decisions
- F1 old saved semantic document auto-graft: removed fallback effect. Component verifies a new completed candidate is not silently replaced by an older saved manuscript.
- F2 first Office window concurrency: bridge passes base0; head check and snapshot save share SQLite transaction. Real parallel integration verification proves one writer wins.
- F3 dirty navigation: existing App guard receives actual renderer state; actual ego typing→leave→continue retains temporary text; explicit discard removes only our unsaved synthetic edit. Main page history/new draft actions disabled while editor open.
- F5 download identity: current Office head is both saved-file source and reopen source, meaningful filename in frontend. Historical downloads do not replace current editor.
- F6 failed/uncertain save: immutable original operation/payload retained for reconciliation, local backup available. Directed bridge tests; full transport-failure browser injection still pending.
- N1 new semantic candidate is explicit, never silently overwrites current Word. Existing-old-Word editing choice remains an interaction improvement; old version is downloadable and retained.
- F4 actual Office content vs study facts: OPEN. Old semantic reconciliation must not be labeled a check of current Word bytes.
- Word P1 accepted: two confidentiality textbox alternatives now explicitly checked. Whole source template has36 textboxes, only2 belong to retained confidentiality front matter; requiring36 in export would wrongly retain template example body.
- Word P3/P4 probes: real Heading 1 names are capitalized; instruction deletion excludes section carrier42. Preserve exact first-section XML and pin front-heading cache in tests. Do not relocate sections based on hypothetical risk.
- Word P5 accepted: placeholder spans replaced across runs without flattening breaks/tabs/styles. Newlines/tabs verified by meaningful example.
- Header render defect resolved: template space padding replaced across run spans with native width-aware tabs; inherited Header-style tab positions explicitly cleared. Native Word and GenOffice both show full date and correctly aligned left/center/right header.
- Receipt now records cover anchor, added template signature pages, retained instruction candidates; not a claim that all template sample material is appropriate for this study.

## Independent Owner Evidence
- Actual ego TaskSpace199, widths1440/1920/2560, no outer overflow; focus mode same iframe ~1398×910 at1440.
- Real renderer+API isolated Chinese edit/save/download/reopen: before/after OOXML compare; one table and header/footer bytes preserved. Snapshot artifacts in runs/requirements_v2_20260919/t17_round11/office_browser_isolated.
- Latest actual React GenOfficeFrame served5193 against isolated real API5293: history versions2/1 returned200, SHA256 matched original respective artifacts; clicking version1 download left currentversion2/editor saved marker intact. Not a full application/model E2E.
- Latest narrow frontend batch24pass, production buildpass (existing large JS chunk warning). Latest Word+recovery+Office API batch18pass.
- Native Word header-layout-aligned.docx sha858d01456caf02c40dbb412b81149978415af9fb24f9f13e7803257d4a27c98d visually opened, title/notice/header correct. Native TOC runtime updates seen; persisted field cache and full protocol pagination not accepted.

## Final Decision
Keep these repairs, continue remaining T17 defects. Actual Word reconciliation, all template sample/abbreviation/signature applicability, full scientific manuscript adequacy, production service loading and full model E2E are outstanding. Existing5285/5186 services and shared data were not restarted or modified by validation. Do not report product completion from test counts.
