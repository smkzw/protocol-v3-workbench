# Execution report: 3R.3 batch8 (codebuddy/deepseek-v4.1-flash:max)

Saved by dispatching ZCode main owner from the runner stream.

---

All checks complete. Final report below (the runner-managed report path was intentionally not written).

STATUS: COMPLETED (assigned batch8 authorship; acceptance remains with the dispatching main owner)

FILES_CREATED
- 12 chapter contracts (new): config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/{v2_n_14_1, v2_n_14_2, v2_n_14_3, v2_n_14_4, v2_n_14_5, v2_n_14_6, v2_n_14_7, v2_n_15, v2_n_16, v2_n_16_x1, v2_n_16_x2, v2_n_16_x3}.json
- 12 chapter skills (new): same 12 node ids under chapter_skills/
- 1 fixture/vocabulary document (new): tests/fixtures/protocol_v3/chapter_content_v2/batch8.json (74 fixtures, 78 fact paths, 44 claim types, 12 coverage roles)
- 1 test file (new): tests/protocol_v3/test_chapter_batch8.py (28 tests)
- Diagnostics (new, run dir runs/mw_protocol_v3_3r3_batch8_20260911/): red_stage1_missing_test.{txt,xml}, red_stage2_assertions.{txt,xml}, green_batch8.{txt,xml}, green_batch8_final.{txt,xml}, assembled_all8_registry.json, assembled_all8_stderr.txt, lint_full_all8.txt. Runner files (dispatch.json, stderr.txt, stdout_stream.jsonl) untouched.
- No writes outside the authorized NEW files; no core/schema/assembler/lint/plan/checkpoint edits; no web/model calls/subagents/installs. A scratch generator used for pre-validated fixture generation lived in TMPDIR (outside the repo); the py_compile .pyc it/verification produced was removed.

RED_EVIDENCE (two-stage, both preserved)
- Stage 1: runs/.../red_stage1_missing_test.txt (+.xml) — pytest exit 4, "ERROR: file or directory not found: tests/protocol_v3/test_chapter_batch8.py", "no tests ran".
- Stage 2: runs/.../red_stage2_assertions.txt (+.xml) — "17 failed, 11 errors in 0.98s"; all failures are missing batch8.json / missing authored contracts (FileNotFoundError, AssemblyInputError), i.e. source-obligation failures, not identity noise.

GREEN_EVIDENCE
- Exact command: `env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_chapter_batch8.py -q -p no:cacheprovider --junitxml=runs/mw_protocol_v3_3r3_batch8_20260911/green_batch8_final.xml`
- Tail summary: "28 passed in 1.78s" (PYTEST_EXIT=0; same result on the prior run: "28 passed in 2.54s").
- XML: runs/mw_protocol_v3_3r3_batch8_20260911/green_batch8_final.xml (earlier green_batch8.xml kept).
- Final-batch integration (authorized all-eight assemble): `lint_full_all8.txt` → mode: full / status: complete / coverage: expected=111 covered=111 leaf_union=110 cover=v2_front_block, exit 0; `assembled_all8_registry.json` = 111 chapters / 556 fixtures (482 pre-existing + 74 batch8).
- Iteration note: first green attempt was 23 passed / 5 failed; fixes were (a) test lookup of outline-only x3 via outlined_tree, (b) bare-boolean exemption from the synthetic-marker value check, (c) fixture-kind mapping for forbidden-material negatives in the generator. No assertion was weakened, no negative fixture deleted, no xfail.

FIXTURES
- Total 74, all bound to the 12 batch8 contracts: positive 14 (incl. 2 conditional-inactive positives for x1/x2), missing_control 33, missing_claim 3, wrong_source 12, skeleton 12; 6–7 per node (floor: 4 families × 12 = 48). All positives pass, all negatives fail, and every source-specific negative asserts its exact expected code.
- Source-specific negatives (suffix → asserted code):
  v2-n-14-1 generic-ctq-slogan → forbidden_claim_present; placeholder-plan-name → forbidden_fact_present
  v2-n-14-2 inferred-completed-training, inferred-signed-acceptance → forbidden_claim_present
  v2-n-14-3 universal-source-verification-promise → forbidden_claim_present; copied-company-name → forbidden_fact_present
  v2-n-14-4 inferred-completed-training, inferred-signed-acceptance → forbidden_claim_present
  v2-n-14-5 tp-ma-15-title-as-integrated-content, audit-inspection-conflated → forbidden_claim_present
  v2-n-14-6 urgent-hazard-blanket-waiver → forbidden_claim_present; important-deviation-undefined → missing_required_fact
  v2-n-14-7 incompatible-committee-roles, fabricated-membership-and-approval → forbidden_claim_present
  v2-n-15 template-example-bibliography, in-text-citation-without-target → forbidden_claim_present
  v2-n-16 placeholder-appendix-included, container-replaces-outline-leaves → forbidden_claim_present
  v2-n-16-x1 ecog-appendix-without-assessment → forbidden_claim_present
  v2-n-16-x2 nyha-appendix-unverified-version, nyha-appendix-without-assessment → forbidden_claim_present
  v2-n-16-x3 template-example-supplier → forbidden_fact_present; blank-provider-fields → missing_required_fact; invented-provider-content → forbidden_claim_present
- Bare booleans bare true/false; synthetic markers present in every non-boolean fact value and every claim statement; checker ignores supplied self-reported verdicts (v2_n_15 positive carries supplied_passed=false and still passes, asserted).

SEMANTIC_NOTES
- CtQ anchoring (v2_n_14_1): facts critical_to_quality_factors / associated_risks / proportionate_controls / control_responsibility / decision_and_data_review_linkage plus the closed chain claim; CtQ item anchors facts+claim; forbidden template_example_plan_name and ctq_generic_slogan_without_anchors negatives; conditional risk-plan rule.
- Responsibility separation (v2_n_14_2/_3/_4): disjoint fact namespaces asserted; banned inferences of completed training / signed acceptance; monitoring matches the proportionate approach with no universal 100%-SDV promise and no copied company name.
- Audit/inspection vs deviations (v2_n_14_5/_6): distinct processes with records/impact assessment/communication; real important/general/urgent-hazard definitions; urgent-hazard blanket waiver forbidden; TP-MA-15 declared "待验证 / provenance pending" in both (test-asserted), never validated.
- Safety oversight (v2_n_14_7): actual body type/composition/roles/information/review/escalation; DSMB vs sponsor-involved SMC vs endpoint IRC non-interchangeable; fabricated membership/charter and universal semiannual cadence forbidden; charter duties only via conditional rule.
- References (v2_n_15): generated from actually used sources (used_source_register, complete metadata, resolvable in-text targets); two independent evidence floors (bibliography vs resolvability); template-example bibliography, unresolved citation and unused references forbidden; foreign-style conditional.
- Appendix container vs outline leaves (v2_n_16 vs x1/x2/x3): heading_only_aggregation container aggregates actual applicable attachments and cannot replace outline-leaf obligations (disjoint fact paths asserted); x1/x2 bind caption headings 973/977 and their owned tables 974/978; x3 (981–995) has no own heading style, so its Word obligation is its two bookmarks.
- Conditional score appendices (x1/x2): required applicability-decision record; version/source/reproduction/table/claim only required when active; active and conditional-inactive positive fixtures both pass; no-assessment/unverified-version negatives fail exactly as designed.
- Laboratory/provider example separation (x3): genuine lab + destruction provider names/identifiers/roles with two separate evidence floors; template example rows forbidden; blank/invented negatives.
- word_rules populated from node_tree for all 12 (required_styles + required_bookmarks; x3 styles empty by node_tree, bookmarks only); ownership declarations for quality.*/references.*/appendix.* roots present and test-asserted; closed vocabularies and conditional-path declaration precedent (batch6 D1) enforced.

DEFERRED
- Runtime conditional-rule evaluation (checker defers conditional_applicability rules); fixtures exercise both active/inactive paths deterministically only.
- Positive QC rules, CtQ questions, skeleton-risk rules and project-specific elements remain unexecuted judgment obligations (returned as deferred_qc_obligations).
- TP-MA-15 content integration deliberately not validated (provenance pending, per spec).
- Native Word rendering, clinical/legal/regulatory suitability, and real project facts (all fixture values synthetic).

LIMITS_AND_NEXT
- No acceptance claim: the ZCode main owner owns verification and acceptance; this report is execution evidence only.
- The 0-missing/111 full-mode result holds only while all eight batch slice files remain as assembled; any later edit to another batch invalidates it.
- Suggested main-owner next steps: review the 25-file diff, rerun the batch8 suite plus the cross-batch acceptance lint, and only then close 3R.3; publication/activation and clinical release remain outside this pass.