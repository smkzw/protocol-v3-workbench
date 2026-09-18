# TP-MA-07 v2 readonly structural preflight

Scope: source inspection while2Rworker runs; NOT3R.1 registry implementation or
template/Word visual acceptance. No source write/open-save/render performed.

Source: /Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx
SHA256 before/after inspection:
018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756.

Methods: officecli1.0.147 `view ... outline` (read-only), independent stdlib
ZipFile/ElementTree document.xml/styles.xml inspection; resolve style inheritance
and paragraph-local outlineLvl. No model, OCR, translation or external network.

| Quantity | Exact observed scope | Result |
|---|---|---:|
| Direct body paragraphs | body/w:p |940|
| Heading-style paragraphs | nonblank body paragraphs with heading/标题 style and outlinelevel0–8 |135|
| Leaves of heading-style tree | next heading level <= current or final node |106|
| All outlined paragraphs | includes local outline levels on Normal/caption |139|
| Leaves of all-outlined tree | same hierarchy rule |109|
| Top-level tables | body/w:tbl (officecli count) |17|
| Recursive tables | document.xml descendant w:tbl |18|
| 试验参与者 in direct body paragraphs | excludes tables |218|
| 试验参与者 in top-level table descendants | each text node counted once |22|
| 试验参与者 in all document.xml w:t | body plus tables |240|
| 受试者 in all document.xml w:t | not only body paragraphs |0|
| Tracked insert/delete/move elements | document.xml |0|
| Sections | descendant sectPr |8|

The supplied135/106/17/218baseline is reproducible with the narrower scopes;
it was NOT a file drift. The word “全书218” in the handoff is imprecise:240 includes
table text. Source hash is unchanged; never alter source to force a count.

Four additional outlined paragraphs excluded by heading-style-only count:
- direct body paragraph81: 缩略语表, local outlinelevel0, no explicit headingstyle.
- paragraph919: 附录1 ECOG体力评分, caption style, outlinelevel1.
- paragraph922: 附录2 纽约心脏学会（NYHA）心功能分级, caption, outlinelevel1.
- paragraph925: 附录3 中心实验室信息和样本销毁公司信息, no headingstyle, level1.
Top-level table6 (方案摘要) contains the one nested table.

3R.1 extraction implications:
1. Publish separate heading-style, outlined-node, semantic-obligation and table
   counts, with explicit algorithm. Preserve approved135/106 baseline as that
   specific metric, not a forced semantic registry size.
2. Abbreviations and three appendices remain required coverage/mapping candidates;
   do not silently drop them because their styles are Normal/caption. Appendix
   applicability is a content decision, not exclusion by style.
3. Retain nested table in synopsis object/provenance mapping.17top-level does not
   license loss of its nestedobject.
4. Terminology QC scans all relevant package text including tables/headers/footer;
   direct-paragraph-only218 is insufficient as “whole-book” coverage evidence.
5. Source is a TEMPLATE and intentionally contains form instructions/tokens.
   Final generated protocol must replace/remove applicable guidance without
   deleting source or treating source template as ready project output.

No new clinical assertion or user decision required for this counting clarification.
Scientific content, actual Word pagination and semantic leaf contracts remain due.

Further bounded paragraph inspection (direct body paragraph ordinal, not text
view line number):273毒理学研究、275药代动力学研究、277一般药理学研究 have
content but are absent from heading-style outline;279/280 are empty numbered
paragraphs in text view.306群体层面汇总 is the fifth estimand attribute outside
the four heading4 attributes300–303. These are explicit examples proving heading
leaf count alone is insufficient semantic coverage.307 is labeled示例 and must
not become confirmed project population/treatment/ICE facts by copying it.
No clinical correctness conclusion on example wording has yet been verified
against E9(R1); such verification belongs to3R chapter/QC contracts.

OfficeCLI text --start/--end counts text-stream positions that include other
elements; they are NOT interchangeable with outline/direct body paragraph indices.
Use semantic paraId or XML structural locator for registry provenance.

## Bounded primary-source QC preparation

Separate from the local structural inspection above, official guideline text was
consulted online. These are implementation implications, not clinical approval of
the template or a replacement for the approved company template.

- [ICH E9(R1), final 20 November 2019](https://database.ich.org/sites/default/files/E9-R1_Step4_Guideline_2019_1203.pdf),
  A.1/A.6: applicability is not limited to pivotal trials; requirements distinguish
  primary/regulatory-relevant secondary objectives from exploratory objectives.
  Do not blindly convert a template applicability note into a universal exclusion.
  A.5.2/A.5.3: sensitivity analysis addresses the same estimand; supplementary
  analysis is distinct. A.4 links sample-size assumptions to the estimand.
  Product implication: preserve the objective–estimand–analysis–sample-size links
  and fifth attribute even when heading styles omit them; flag inconsistencies
  for clinical disposition, never silently rewrite approved project facts.
- [ICH M11 final guideline, 19 November 2025](https://database.ich.org/sites/default/files/ICH_Step4_M11_Final_Guideline_2025_1119.pdf),
  sections1.3/2: structured content and exchange do not replace other clinical
  design/content guidance. Product implication: structural validity alone cannot
  certify scientific adequacy or submission approval.
- [ICH M11 final template](https://database.ich.org/sites/default/files/ICH_Step4_M11_Final_Template_2025_1119.pdf),
  section0.3 only: distinguish instructions from protocol content. Use a semantic
  crosswalk with TP-MA-07, not automatic substitution of its layout or headings.
  Full M11 template review and jurisdiction-specific applicability remain due.

No new product files, registry, source DOCX edits or clinical decisions were made.
The Phase I template choice remains the explicit Task3R.6 user decision.

## Legacy source location reconnaissance

`services/api/app/medical_writing_protocol_template.py` embeds `_COMPANY_CHAPTERS`
(line398), `_company_nodes` (line798), and versioned `definition` (line2654).
Its company authority metadata names historical D017/D001/MG-K10 protocols,
not the newly approved TP-MA-07 v2. This is a legacy migration surface, not proof
that the planned124/110 v1 registry is this exact tree. Locate and identify that
specific registry before assigning a mapping count; no guessed equivalence.
The same module has explicit confirmed-fact body projection and applicability
logic. Later mapping must reconcile these independently of title similarity.
Keep historical version replay intact; new-project authority must be explicit.
These are source-code observations only; no live service behavior was tested.

Further AST-only count (no module/main imports): `_COMPANY_CHAPTERS` contains124
rows and103 hierarchy leaves. `_company_nodes()` prepends six unparented front
matter nodes then appends these rows and returns:130nodes/109leaves total.
Frozen Task3.1 explicitly points to this Python module for its124/110 identity
comparison, but those stated totals do not match this current implementation.
Git last-touch baseline commit is05b7d5b. Do not invent a missing v1 JSON registry
or force the old count; Task3R.1 must publish the actual source identity inventory
and reconcile plan terminology/counts before declaring full mapping coverage.
