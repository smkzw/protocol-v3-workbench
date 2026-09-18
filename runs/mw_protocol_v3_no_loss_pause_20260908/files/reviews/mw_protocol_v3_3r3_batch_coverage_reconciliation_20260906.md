# 3R.3 batch coverage reconciliation — implementation input

Current accepted node_tree.json queried directly using the union of
is_leaf_heading and outlined_tree.is_leaf, plus mapping-resolved cover.
No source registry modified; no chapter implementation accepted by this inventory.

|Batch|Scope|Carriers|
|---|---|---:|
|1|Front matter, cover, summary, diagram, SOA|12|
|2|Sections2–3|16|
|3|Sections4–5|10|
|4|Sections6–8|16|
|5|Sections9–10|19|
|6|Section11|13|
|7|Sections12–13|13|
|8|Sections14–16 including outline appendices|12|
|Total|110-node union plus cover|111|

The source's106heading leaves are not106semantic obligations. Appendix container
v2_n_16 is heading-only; glossary and three appendix leaves are outline-only.
Exact source identities must survive, without treating instructional titles as
finished headings or injecting source examples into project facts.

## Parent-targeted inherited obligations need explicit leaf expansion

Accepted3R1 retained_conditional_obligations includes parent targets v2_n_11_4
(statistics.pk/pd/er) and v2_n_5 (contraception). Neither is a leaf carrier.
Do not drop these because literal parent IDs are absent from the111contracts.
Author an explicit inherited-obligation crosswalk when assembling final batches:

- PK/PD/exposure-response analyses must remain distinct conditional analyses,
  with linked applicable endpoints/sampling/model assumptions. Proposed carrier
  is v2_n_11_4_6 for exploratory uses; when confirmatory, link the relevant
  primary/secondary analysis contract instead of relabeling it exploratory.
- Contraception eligibility applies to appropriate inclusion/exclusion criteria
  (v2_n_5_1/_2), ongoing restrictions to v2_n_5_3 where applicable, and pregnancy
  events to existing v2_n_10_6. This is a declared semantic expansion, not a
  claim that the accepted mapping already lists every leaf.
- Summary measure at body323 is physically inside v2_n_3_1_2_4; preserve it
  separately from ICE strategy. See batch2 preparation for exact source proof.
- Source parent narratives (drug background, overall population, SAP framing)
  require carrier/aggregation handling, not automatic deletion in leaf-only export.

Codex will verify these expansions against authored contracts and conditional
fixtures before completing3R.3. Their presence in this note is not evidence that
runtime conditional evaluation, drafting or clinical review has been implemented.
