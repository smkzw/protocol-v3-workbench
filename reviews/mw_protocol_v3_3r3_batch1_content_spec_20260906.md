# 3R.3 batch1 — source-bound content obligations

Preparation for registry authoring, not generated protocol or accepted fixtures.
Source: approved TP-MA-07 v2.0, SHA256
018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756.
Locators below are zero-based **body-child indices**, not paragraph ordinals.
Direct XML reread:0–98 and240–265, including nested summary table and SOA text.
Source is unchanged. Source anchors and later schema property names are separate.

## Common rules

All clinical values come from the current confirmed study facts; documents are
projections, not second fact stores. Preserve existing framing.protocol_id,
framing.version, framing.document_title, framing.study_phase, picos primary/etc.
where mapping exists. Additional metadata (version date, parties, registration
classification) needs explicit vocabulary/admission, not guessed legacy fields.
Missing metadata should be collected from existing material/settings first, not
converted into extra compulsory typing that violates the20click/5text budget.

Exclude source instructions0–13, bracketed example tokens and duplicate drawing
fallback text. Keep actual document fields/structure, update them natively later.
No fake confirmation receipt, signature, date or project-specific medical source.
Unsigned signature lines are intentional Word signing controls, not invented
completed signatures or literal <姓名>/<日期> placeholders. Signing status remains
internal; document-readiness must not be claimed as actual signing completion.

## Node obligations and distinct counterexamples

| Node | Source | Required substance / objects | Specific negative fixture |
|---|---|---|---|
| Unheaded cover carrier |23,25,28–36,40–42|Protocol title/id/version/date and actual applicable parties; sponsor-bound confidentiality statement; exact header/footer metadata; remove instructions|Correct format but another project's protocol ID, copied XXXXXX title, or invented party|
|v2_n_front_1|44–46|Version/date/change/rationale table bound to genuine revision history; initial-version treatment explicit; no invented amendments or approval|Rows present but wrong version/change source; blank change shell when amendment exists|
|v2_n_front_2|49,51,54,56,58|Investigator commitment linked to same protocol/version/date and actual institution; native signature/date controls, no synthetic signature|Commitment refers to stale protocol revision or substituted institution|
|v2_n_front_3|66,67,70,72,74,77|Sponsor commitment and representative signing controls, same current metadata; additional signatory pages only if applicable|Old sponsor or copied signed date without receipt|
|v2_n_front_4|84,87–93|Applicable sponsor/investigator/service-party contact tables with genuine roles and locations; retain table cell obligations|Table present but role/address cells missing or borrowed from competitor|
|v2_n_front_5|94–96|Used-only abbreviation table: abbreviation, sourced expansion, Chinese meaning; preserve correct medical distinctions|Unused template abbreviations, source misspellings or conflicting expansions|
|v2_n_front_6|99–231|Generated TOC from actual heading hierarchy and bookmarks, current targets and native field update|Copied cached labels/page numbers with missing targets|
|v2_n_front_7|232–234|Table index from actual captions and ordered table identities; native refresh|Old AE/SAE-only cached list omits estimand/SOA table|
|v2_n_front_8|236|Figure index from actual figure captions/identities; explicit no-figure applicability if relevant|Index points to removed or different figure|
|v2_n_1_1|240–243, table242|Summary table with all applicable17source rows, nested objective/estimand/endpoint mapping; exact canonical design/population/intervention/statistical identity|Generic disease/drug description without objective/endpoints; dose, N or eligibility differs from正文|
|v2_n_1_2|245–258|Project diagram with phases/arms/allocation/timepoints and transitions agreeing with SOA; referenced vector asset may guide style, not supply project facts|Template Parkinson/titration timeline or unsupported escalation inserted into unrelated design|
|v2_n_1_3|259–265|Structured SOA with visits, windows, relevant procedures, contacts, early-exit assessment, applicable follow-up; typed cells and linked footnotes; landscape Word section|Cell IDs exist but values empty; wrong exit visit in footnote; irrelevant disease scale; missing window|

## Summary table selectors to preserve in schema-specific form

protocol ID; title; version/date; phase; registration classification; sponsor;
principal investigator; trial institutions; objectives/estimands/endpoints; design;
population/eligibility; investigational/comparator drug; interventions; sample size;
statistical analysis; overall trial duration; individual participation duration.
Not all require an independent external evidence citation: confirmed project facts
and genuine metadata provenance are valid. New clinical assumptions still need
source support and the relevant human decision, not a copied template value.

The source's “estimand only for pivotal” instruction is not a universal rule.
Use the already recorded E9(R1)/M11 applicability disposition. Multiple objectives,
estimands and analysis strategies remain separately linked, not flattened into one
unqualified outcome sentence. Registration consistency uses the actual applicable
registration source and version, not automatic assertion that a record exists.

## SOA/diagram details

- Visits and windows carry units/reference events; PK timing cannot be silently
  rendered as a generic day window. Applicable phone contacts are actual visits.
- Required assessment cells are checked for content and applicable visit identity,
  not merely a displayed X. Footnotes resolve to existing procedures/visits.
- Early-exit and safety follow-up must match discontinuation/withdrawal rules.
- Do not hardcode the example V6/V7 labels,42/30day windows, Parkinson scales,
  laboratory panels or sample handling. Source265 is an example, not project fact.
- Diagram is offered by default for AI-led usability; source246 allows omission
  for suitable simple studies. Dose-escalation diagram instruction250 is applicable
  only where the confirmed design actually contains escalation.
- Native Word landscape/headers/field updates remain7R obligations, not asserted
  successful by passing JSON fixtures here.

## Follow-up dependencies

Used-only glossary expands with3R.7 terminology. Summary depends on clinical facts
and relevant content obligations, not competing editable facts. Cross-consistency
links are not automatically ordering edges (3R.4 resolves graph behavior). Each
declared upstream dependency requires a bounded repair owner under3R.2.
