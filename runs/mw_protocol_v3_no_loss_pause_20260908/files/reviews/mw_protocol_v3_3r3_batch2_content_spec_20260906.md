# 3R3 batch 2 source-to-content obligations

Preparation, not registry acceptance. Source: approved TP-MA-07 v2.0 DOCX
SHA256 018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756.
Codex reread OOXML body children 270–339 directly. Indices below are body-child
indices, not paragraph numbers. Source unchanged; infrastructure worker owns its
three code/test files independently.

## Background

- 2.1 / 273–274: actual indication, clinical problem, standard care, unmet need,
  and reason this specific study resolves a meaningful uncertainty. A generic
  disease introduction or registry keywords alone do not satisfy the obligation.
- 2.2 / 275–282: preserve relevant nonclinical and human exposure evidence,
  clinical pharmacology and epidemiologic context; parent narrative must not
  disappear merely because only leaf contracts are counted.
- 2.2.1 / 283–284: product-specific identity and applicable characteristics,
  grounded in current IB/product authority. Chemical structure/formula is not a
  universal requirement for every modality; applicability must be explicit.
- 2.2.2.1 / 287–294: source places toxicology, PK and general pharmacology under
  the pharmacodynamics heading without heading styles. Preserve these separate
  semantic obligations; a pharmacodynamics paragraph cannot satisfy all four.
- 2.2.3 / 297–299: separate competitor evidence from this product's own earlier
  clinical evidence, despite physical co-location of paragraph 299. Clinical
  results require a matching study/source context, not merely an IB file ID.
- 2.3 / 300–306: known and potential risks, anticipated benefits, uncertainty,
  mitigation, and an actual justified risk-benefit assessment. Compensation is
  not therapeutic benefit. Source 306 is problematic wording, not approved
  project rationale: do not reproduce a blanket justification for risks being
  greater than information value. Regulatory interpretation remains source-based
  medical review, not a deterministic linter claim.

## Objectives, endpoints and estimands

- 3.1.1 / 309–312: concrete clinical question linked to the primary endpoint and
  treatment comparison. The example's discontinuation/rescue-treatment strategy
  is not a project default and requires explicit high-risk confirmation.
- 3.1.2 / 313–325: account for all five estimand attributes. Source 314's
  pivotal-only instruction must not silently suppress estimand design elsewhere.
- 316–319 are headings containing instructional/example text. Preserve source
  identity while producing clean project headings; never export “状况/疾病” or
  explanatory placeholders as literal finalized headings.
- 316: target population is not automatically identical to a post-randomization
  analysis set or the example's at-least-one-dose population.
- 317: variable must include measurement, aggregation and time point/window
  sufficient to distinguish it from a label such as “efficacy”.
- 318: treatment conditions, including relevant background/rescue treatment;
  clarify the source's label “治疗效应” rather than losing this attribute.
- 319–321: each relevant intercurrent event has definition, chosen strategy,
  rationale and compatible handling. Nonempty table shells and “事件1” fail.
- 323: population-level summary is its own semantic obligation although there
  is no independent leaf heading. It is not interchangeable with the name of a
  statistical method. Preserve its actual mapped carrier rather than adding a
  fabricated source heading.
- 324: example contains potentially conflicting rescue-treatment wording;
  cannot be adopted wholesale. Cross-check strategy against follow-up, analysis,
  missing data and sensitivity analysis contracts and confirmed project facts.
- 327–331: each secondary objective maps to a defined secondary endpoint, not
  numbered placeholders. Confirmatory multiplicity versus exploratory intent
  must remain visible to later statistical contracts.
- 333–335: safety objectives and endpoints use actual product risks, observation
  periods and assessment definitions; injection reactions are conditional, not
  mandatory for every route of administration.
- 337–339: exploratory objectives/endpoints are conditional on the study, with
  explicit disposition if absent. PopPK, exposure-response, immunogenicity and
  biomarker objectives are examples, not automatic project commitments.

## Required negative-fixture distinctions

1. Present headings with no study-specific obligation values fail.
2. A competitor source presented as own-product clinical evidence fails.
3. Empty ICE rows or placeholder attribute text fail.
4. A method name alone does not discharge the population-summary obligation.
5. A valid source locator with incompatible study/claim context fails admission.
6. Five attribute keys are not medical coherence: deterministic checks report
   their limited scope; scientific consistency needs separate review.
7. Reusable registry fixtures must not fabricate actual human confirmation or
   ethics/approval receipts. High-risk review remains project-instance state.

This is an authorship specification for subsequent registry batches; no clinical
project content, new model call, source rewrite or completed QC is claimed.

## Exact carrier reconciliation (current accepted tree, 03:44 reread)

Sixteen heading-leaf carriers: v2_n_2_1, v2_n_2_2_1, v2_n_2_2_2_1,
v2_n_2_2_3, v2_n_2_3, v2_n_3_1_1, v2_n_3_1_2_1 through _4,
v2_n_3_2_1/_2, v2_n_3_3_1/_2 and v2_n_3_4_1/_2.
The accepted tree physically assigns body323 (population-level summary) to
v2_n_3_1_2_4, with320/324/325, despite that leaf's ICE heading. This carrier
must separately require population-summary content; do not invent a fifth
source heading or count four attribute headings as five fulfilled attributes.
The parent v2_n_3_1_2 owns314/315 and the prior primary semantic mapping, but
is not a leaf. Preserve parent framing through the leaf skill contract and
later projection, without inventing an extra expected coverage ID.

Legacy background.mechanism remains partially carried: own-product mechanism
was not explicit in source284; preserve the obligation in v2_n_2_2_1 as a
declared substantive addition from the inherited contract, not falsely quote
the source as already containing it. Competitor mechanism/evidence stays in
v2_n_2_2_3 alongside separately identified own-product clinical evidence299.
No accepted3R1 mapping/source file modified by this disposition.

Vocabulary collision to avoid: accepted projection reconciliation uses
`picos.population_summary` for population.selection alongside
`framing.population_intent`; this means a description of the study population,
not the estimand population-level summary measure. Do not repurpose that legacy
fact path to mean treatment-effect summary. Declare a distinct estimand-specific
path and retain both meanings; a future adoption/migration must be explicit.

Evidence-floor authoring: the accepted checker requires at least one conforming
unit per EvidenceSourceRequirement group. Multiple admission claim types inside
one group are alternatives, not an all-claims requirement. Independently required
own-product, competitor, nonclinical and risk-benefit evidence therefore need
separate groups (and distinct missing-evidence counterexamples where relevant).
Do not place all types into one permissive group then claim each was supported.
ContentEvidence is a fixture/skill-check payload, not the durable EvidenceUnit /
MedicalAdmissionUnit / ClaimEvidenceLink chain. Real source IDs, hashes and claim
bindings must be resolved by the later admitted-evidence consumer; a self-supplied
quality score or locator text alone is not verified clinical provenance.
