# 3R3 batch 3: design and population obligations

Preparation only, not accepted registry or clinical advice. Approved TP-MA-07 v2.0
source unchanged (SHA256 018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756).
Direct XML body-child indices 340–418 reread by Codex during infrastructure work.

## Design (340–369)

- Overall design must specify actual hypothesis, phase, design, arms, duration,
  allocation, masking, centers, and applicable stratification/interim/substudy
  features. These must agree with summary, diagram, SOA and confirmed facts.
- Control and design rationale require clinical context and evidence; merely
  naming “randomized double-blind” is insufficient. Noninferiority and placebo
  choices are not defaults supplied by a template.
- Dose rationale covers actual intervention and comparator routes/regimens and
  starting/maximum doses where applicable; same drug name alone is not evidence
  for the selected regimen or population.
- Participant completion and overall study end are separate definitions. Source
  examples at 359–362 must be reconciled with follow-up, actual visits and any
  post-treatment assessments rather than merged into ambiguous “last visit”.
- Allocation and masking specify actual procedure/roles, maintenance of masking,
  relevant unblinded personnel, emergency and accidental unblinding and records.
  Do not infer IWRS, a 1:1 ratio or stratified blocks from the source example.
- Source cross-reference 364 points to statistics as section 9, while the actual
  template statistics section is elsewhere. Resolve canonical targets; copying
  a source reference is not successful cross-reference validation.
- Product template does not need secrets such as an actual randomization list to
  write an adequate protocol. This is content separation, not a new security
  engineering task. Open-label designs still require applicable bias mitigation.

## Population (371–418)

- Define clinical target population and relevant subpopulations before listing
  criteria. The absence of a separate leaf does not waive parent-content duties.
- Inclusion is an all-applicable-criteria predicate; exclusion is any-applicable-
  criterion. Preserve boolean logic, units, thresholds, assessment windows and
  exceptions in typed criteria, not only free-text numbering.
- Do not produce duplicate inverse inclusion/exclusion criteria or incompatible
  thresholds. Clinical validity of each restriction is separate from structural
  predicate validation and requires supporting rationale.
- Oral dosing, a one-month contraception period, blanket pregnancy exclusion,
  smoking restrictions and device exclusions are examples, not universal rules.
  Bind restrictions to modality, product risk, population and confirmed design.
- Explicit rationale for excluding relevant populations is an obligation; absence
  of a demographic group in a source must not be interpreted as justification.
- Lifestyle restrictions need timing, scope and actual product/design rationale;
  necessary prohibited concomitant treatment links to intervention and withdrawal
  rules, not a generic automatic whole-study termination instruction.
- Screen failure and rescreening need distinct definitions and permitted reasons,
  timing and records. The example “not randomized” cannot uncritically classify
  every consented nonrandomized person as a criterion failure.
- Recruitment and retention cover actual channels, feasibility, appropriate
  material review, contact/visit measures and compensation arrangements where
  applicable. Planned ethics review is not a completed approval receipt.
- Source cites GCP 2026 article numbers at 366/416/418. Preserve provenance but do
  not claim these specific article citations independently verified here; final
  regulated wording requires the actual applicable text, not source-template
  authority alone.

## Negative fixtures

Wrong comparator/ratio versus confirmed facts; dose evidence for another regimen;
end-of-treatment substituted for required study follow-up; inclusion/exclusion
threshold contradiction; copied sample contraception duration without project
support; phantom completed recruitment approval; stale numbered reference with
no actual target; nonspecific “per protocol” descriptions with empty parameters.

High-risk study design choices remain explicit project-instance human decisions.
Fixture truth flags cannot substitute for either scientific review or approval.

## Exact carrier and shared-fact bindings (Sep8 recheck)

Ten carriers: v2_n_4_1 through v2_n_4_5, v2_n_5_1 through v2_n_5_5.
Accepted outlined tree gives parent v2_n_5 its own body372–379. Preserve clinical
population framing in the inclusion carrier and reference it from exclusion,
without creating a fabricated extra leaf. Inclusion/exclusion remain different
predicates; denominator and rescreening logic must match the chosen design.
Known canonical facts from current legacy projection bindings:
framing.structured_design for allocation/masking, picos.study_epochs for end
conditions, framing.population_intent and picos.population_summary for population
description, picos.inclusion_modules and picos.exclusion_modules for criteria.
Do not create a second editable copy of these facts in a chapter-local namespace.
New justified detailed fields can refine these but must declare their ownership.
Contraception retained parent obligation expands into applicable inclusion,
exclusion and lifestyle carriers, plus pregnancy handling later in v2_n_10_6;
do not assign a universal period or erase it because parent v2_n_5 is not a leaf.
Scientific comparisons against registered eligibility require actual registry
identity/source/version, not the unrelated drug registration classification.

Sep8 source-update addendum: official GCP2026 article14 recruitment/compensation
scope and article45 payment scope now checked via government reproduction;
article22 supplies pre-start approval requirement. See
reviews/mw_protocol_v3_gcp2026_source_check_20260908.md. Earlier note that these
were unverified accurately describes Sep6; it no longer blocks these anchors.
