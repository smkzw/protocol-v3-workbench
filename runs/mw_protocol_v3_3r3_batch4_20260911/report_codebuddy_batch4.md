# Execution report: 3R.3 batch4 (codebuddy/deepseek-v4.1-flash:max)

Saved by dispatching ZCode main owner from the runner stream.
Route identity: codebuddy/deepseek-v4.1-flash, modelUsage echo deepseek-v4.1-flash,
duration 447158ms, 241 turns, is_error false. Dispatch: dispatch.json in this directory.

---

STATUS: COMPLETED

FILES_CREATED
- `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json` — **16** (v2_n_6_1_1 … v2_n_8_3), ChapterContractV2, frozen, template sha256 `018d28d3…3756`.
- `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json` — **16** ChapterSkillManifest (node-specific Chinese prompts; no provider/model keys; schema refs bound to ChapterSkillInput/Output).
- `tests/fixtures/protocol_v3/chapter_content_v2/batch4.json` — 1 (106 fact / 28 claim closed vocabularies, 16 coverage_roles, 72 fixtures).
- `tests/protocol_v3/test_chapter_batch4.py` — 1 (29 tests).
- Diagnostics under `runs/mw_protocol_v3_3r3_batch4_20260911/`: `red_preimplementation_20260911.xml`, `green_iter1..4_20260911.xml`, `green_final_20260911.xml`, `green_final_accepted_20260911.xml`, `assembled_batch4_registry.json`, `lint_partial_batch4.txt`.

RED_EVIDENCE
- `runs/mw_protocol_v3_3r3_batch4_20260911/red_preimplementation_20260911.xml` — **15 failed, 1 passed, 13 errors** before any batch4 artifact existed; root cause `AssemblyInputError: cannot read …/chapter_content_v2/batch4.json: No such file or directory` (assembly fixture not found) plus missing contract/skill files. Iterations 1–3 (`green_iter1`: 7F, `green_iter2`: 5F, `green_iter3`: 3F) are preserved as repair evidence; no assertion was weakened, no negative fixture deleted, no xfail used.

GREEN_EVIDENCE
- Exact command: `env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_chapter_batch4.py -q -p no:cacheprovider --tb=short`
- Tail: `29 passed in 2.92s`; XML: `runs/mw_protocol_v3_3r3_batch4_20260911/green_final_20260911.xml` (tests=29 failures=0 errors=0). Final exact-command rerun: `green_final_accepted_20260911.xml`, 29 passed.
- Partial lint CLI: exit 0, `mode: partial`, `INCOMPLETE`, zero error findings (`lint_partial_batch4.txt`). Cross-check: accepted `tests/protocol_v3/test_chapter_batch1.py` still **17 passed** with batch4 files present.

FIXTURES
- Total **72**; families: positive 16, missing_control 20, missing_claim 4, wrong_source 16, skeleton 16. Every node has ≥4 families (positive + missing_claim OR missing_control + wrong_source + skeleton) — floor 64 exceeded. All positives pass with no error findings; all negatives fail.
- Source-specific negatives (spec 夹具义务): `v2-n-6-1-2:conflicting-drug-facts`, `v2-n-6-2-2:copied-grade-threshold`, `v2-n-6-2-3:empty-storage-condition`, `v2-n-6-3:adherence-denominator-omitted`, `v2-n-6-4-3:rescue-estimand-inconsistent`, `v2-n-8-2:followup-silent-last-dose`, `v2-n-8-1:individual-equals-trial-stop`, `v2-n-7-3:invented-approval-receipt` — each fails for its named reason (exact error codes asserted).

SEMANTIC_NOTES
- Individual-vs-trial-level separation: `v2_n_8_1` types individual hold, individual permanent stop, and trial suspension/termination separately, with `discontinuation.trial_stop_decision_logic`/`_authority`; forbids `individual_equals_trial_stop` and `single_pivotal_trial_stop_rule`; `v2_n_8_2` (individual) declares no trial-level facts (asserted). Source 496–511 conflation is not replicated.
- Rescue/estimand agreement: `v2_n_6_4_3` requires `rescue_estimand_alignment` + separate evidence group and forbids `rescue_estimand_inconsistency`/`unqualified_rescue_outcome_claim`; the negative omits the linkage so it fails structurally.
- Withdrawal semantics: reason recording requested-not-compulsory; forbids `followup_terminates_at_last_dose`, `silent_erase_prior_data`, `treatment_stop_equals_consent_withdrawal`; replacement policy anchored via CtQ to sample-size/analysis.
- Example-vs-project separation: forbidden example paths per node (e.g. `intervention.template_example_hold_threshold`, `…interval`, `…three_calls`, `…stop_rule`), bare `true/false` trigger facts, conspicuous `【合成夹具】` markers.
- Evidence-group separation: separate `EvidenceSourceRequirement` groups per independently required claim on `v2_n_6_1_1`, `v2_n_6_1_2`, `v2_n_6_2_2`, `v2_n_6_3`, `v2_n_6_4_3`, `v2_n_7_3`, `v2_n_8_1`, `v2_n_8_2`, `v2_n_8_3`; every group carries context window + quality floor ≥0.9.
- Isolation: only batch4 files were written. batch2/batch3 mutable files and the core template were not read or written. Other batches' recent mtimes (21:33–21:46) are concurrent workers, not this session.

DEFERRED
- Runtime conditional evaluation, drafting activation, medical/clinical review, and native Word rendering (styles/bookmarks/field refresh) — the checker reports them as `deferred_qc_obligations` by design.
- Source-authority fact binding for `project_primary` (IB/product authority documents) is declared as an obligation, not resolved — only the `project_primary` role is used because batch4 facts are project-owned.

LIMITS_AND_NEXT
- No acceptance claim: this is a batch slice; full-mode lint still reports 95 missing carriers and 111 expected.
- `batch4.json` fact paths use `intervention.*`/`procedure.*`/`discontinuation.*`/`lost_to_followup.*` namespaces deliberately disjoint from batch1–3 so batches validate independently; final cross-batch vocabulary reconciliation remains with the main owner.
- Awaiting: independent review of the authored contracts against the content spec, then ZCode main-owner acceptance.