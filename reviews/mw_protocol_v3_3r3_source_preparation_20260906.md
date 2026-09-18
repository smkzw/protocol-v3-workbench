# 3R.3 source preparation — not chapter acceptance

Read-only preparation while the single 3R.2 contract worker owns its two files.
No product calls, source-document edits, runtime activation or chapter completion.

## Source and scope

ICH M11 final template, adopted 19 November 2025:
https://database.ich.org/sites/default/files/ICH_Step4_M11_Final_Template_2025_1119.pdf

Selected sections inspected through the official PDF text: objectives/estimands,
assessments, events, statistical considerations and oversight. This is not a
claim of full-document or native-rendered review. The company TP-MA-07 v2 remains
the approved layout authority; M11 supplies separately identified content checks.

## Contract implications

- Separate pregnancy testing (8.4.5) from pregnancy and postpartum events (9.3).
- Separate immunogenicity (8.7) from a generic immune-related assay reference.
- Statistical methods, intercurrent-event data handling, missingness, sensitivity
  and supplementary analyses have distinct obligations (10.4.1.1–10.4.1.5).
- Interim analysis, multiplicity and sample-size assumptions must agree with the
  estimand and analysis; retain enough information to reproduce calculations
  (10.9–10.11). Do not reuse template example assumptions as project facts.
- Committee and quality-management obligations have explicit carriers
  (11.4, 11.6); a heading count does not establish substantive coverage.

These observations guide 3R.3 fixtures and source anchors, not regulatory sign-off.

## Engineering follow-up discovered during preparation

The current skill_registry.json still lists deepseek-v4-flash in product-llm
tool_versions, whereas the approved product default is GLM. The mount composition
loads this registry, and SkillEntry retains tool_versions as metadata. This
establishes stale metadata, NOT proof that the live transport invokes DeepSeek.
Before new chapter skills are integrated, inspect the runtime consumer and use a
declared versioned correction; do not rewrite historical run identities or repeat
the already successful 1R.6 product probe.

Follow-up source inspection: runtime/product_profiles.py defaults to
role_registry.json and only selects the alternative on explicit confirmation.
runtime/harness.py validates node_contract.model against role.target_profile.model
and constructs the request from that contract, not SkillEntry.tool_versions.
Thus the finding remains metadata consistency, not observed transport fallback.

3R.3 must cover accepted 106 heading leaves plus separately tracked front matter,
outline-only appendix/glossary and unheaded obligations. Do not discard those
obligations to make the leaf count look complete.

Exact current inventory check: heading leaf selection uses `is_leaf_heading`,
not `is_leaf` (the latter describes full-outline leaves even on shared heading
node records). This yields 106 heading leaves and 109 outline leaves. Their union
is 110 IDs: heading-only `v2_n_16` (appendix container), and outline-only glossary
`v2_n_front_5` plus `v2_n_16_x1/x2/x3`. The unheaded cover is additional. This is
not the legacy plan's 110-leaf count and must not be conflated with it. Model the
appendix container's aggregation/Word obligation without inventing clinical
claims, and give the concrete applicable appendices separate obligations.

Consumer boundary: canonical/document.py `_unbound_paths` verifies exact keys in
StudyDefinitionV3.facts. It does not establish that a value is clinically adequate
or satisfies a chapter's positive content criteria. 3R.3 fixture evaluation must
therefore distinguish key existence from substantive fulfillment; do not claim
the existing reducer already performs chapter QC. No reducer change made here.

## 3R.3 acceptance inputs from contract review

The registry linter must check declared fact/claim vocabularies, conditional
required-versus-forbidden contradictions, CtQ anchors, dependency targets and
content/chapter identity together. The v2 schema alone cannot prove these external
references resolve. Never count optional/allowed/qualified-only permissions as a
positive content requirement. Each candidate chapter must bind its substantive
content and positive QC; cells must carry stable selectors when the object needs
cell-level obligations. Actual cell existence/value checks belong to fixture and
document validation, not merely accepting a serialized selector.

Use exact OOXML style identifiers when binding source styles. Do not blindly
casefold identifiers; the accepted source registry retains style IDs and names
separately. Per-project patient decision receipts must not be prefilled as actual
approval in a reusable template registry. Cross-references to such decisions are
only evidence once the matching project decision exists and is confirmed.
