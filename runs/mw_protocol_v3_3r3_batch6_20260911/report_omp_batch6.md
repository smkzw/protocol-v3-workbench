# Execution report: 3R.3 batch6 (omp/pi openai-codex/gpt-5.6-luna:xhigh)

Saved by dispatching ZCode main owner from the runner stream.
Route identity: pi/openai-codex/gpt-5.6-luna, xhigh, probe echoed.

---

STATUS: COMPLETED

FILES_CREATED:
- 13 chapter contracts under `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/`:
  - `v2_n_11_1`
  - `v2_n_11_2`
  - `v2_n_11_3`
  - `v2_n_11_4_1`
  - `v2_n_11_4_2`
  - `v2_n_11_4_3_1`
  - `v2_n_11_4_3_2`
  - `v2_n_11_4_4`
  - `v2_n_11_4_5`
  - `v2_n_11_4_6`
  - `v2_n_11_4_7`
  - `v2_n_11_4_8`
  - `v2_n_11_4_9`
- 13 dedicated skill manifests under `chapter_skills/`
- `tests/fixtures/protocol_v3/chapter_content_v2/batch6.json`
- `tests/protocol_v3/test_chapter_batch6.py`
- 10 diagnostics under `runs/mw_protocol_v3_3r3_batch6_20260911/`

RED_EVIDENCE:
- `runs/mw_protocol_v3_3r3_batch6_20260911/red_preimplementation.xml`
  - Test file absent; pytest exited 4.
- `runs/mw_protocol_v3_3r3_batch6_20260911/red_contracts_missing.xml`
  - Test file present but fixture corpus absent; 1 failure and 7 errors.

GREEN_EVIDENCE:
```text
env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw \
TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 \
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
PYTHONPATH=tests/protocol_v3:services/api:packages:. \
runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest \
tests/protocol_v3/test_chapter_batch6.py -q -p no:cacheprovider --tb=short \
--junitxml=runs/mw_protocol_v3_3r3_batch6_20260911/pytest_batch6_final.xml
```

Tail summary:
```text
8 passed in 1.53s
```

XML:
`runs/mw_protocol_v3_3r3_batch6_20260911/pytest_batch6_final.xml`

FIXTURES:
- Total: 61
- `positive`: 13
- `missing_control`: 18
  - 9 base negatives
  - 9 source-specific negatives
- `missing_claim`: 4
- `wrong_source`: 13
- `skeleton`: 13

Source-specific negatives:
- `v2-n-11-1:wrong-assumed-effect`
- `v2-n-11-1:n-without-reproducible-inputs`
- `v2-n-11-1:missing-sidedness`
- `v2-n-11-1:missing-allocation`
- `v2-n-11-2:mislabeled-analysis-set`
- `v2-n-11-4-3-2:placeholder-sensitivity-table`
- `v2-n-11-4-3-1:rescue-estimand-inconsistent`
- `v2-n-11-4-8:named-method-without-family`
- `v2-n-11-4-9:interim-timing-alpha-mismatch`

SEMANTIC_NOTES:
- Sample size:
  - Typed endpoint, hypothesis, test model, sidedness, alpha, power, assumptions, evidence, allocation, attrition, method, software version, and reproducible result.
  - Interim adjustment and design-effect obligations remain conditional.
  - Uses shared `picos.primary_endpoint`, `framing.structured_design.hypothesis`, and `framing.structured_design.allocation_ratio` authorities.
- Analysis sets:
  - Randomized, treated, and available-assessment populations are separate.
  - Inclusion, grouping, handling, and rescue-treated rules are explicit.
  - Rescue-treated participants are not discarded without estimand-consistent justification.
- Multiplicity:
  - Requires study-specific family, ordering, alpha allocation, dependencies, procedure, applicability, and disposition.
  - Named Holm/Hochberg methods do not satisfy the contract without a bound family.
- Interim and alpha:
  - Requires timing, information fraction, purpose, decision rules, responsibility, final-analysis impact, efficacy-alpha handling, and safety separation.
  - IDMC and endpoint IRC responsibilities are distinguished.
- PK-PD-ER inheritance:
  - `v2_n_11_4_6` carries inherited `v2_n_11_4` obligations, including source marker `@783`.
  - Exploratory PK/PD/ER use remains exploratory; confirmatory use must link to primary or secondary objectives and cannot be relabeled as exploratory.
- SAP versus protocol:
  - `v2_n_11_3` carries SAP status, timing, revisions, and unblinding.
  - `v2_n_11_1` and `v2_n_11_4_3_1` explicitly preserve protocol endpoint, estimand, primary-method, and sample-size obligations even when SAP timing differs.

DEFERRED:
- Parent nodes remain non-carriers by design; no parent contract or skill files were created.
- Core schema, assembler, registry, lint, and cross-contract checker changes were not made because they are outside the authorized file boundary.
- Full project-wide acceptance, clinical/statistical validity review, native Word rendering, and live model/provider activation remain deferred to the main owner.
- No acceptance claim is made for the broader 3R.3 batch or protocol.

LIMITS_AND_NEXT:
- Main owner must perform the broader cross-contract vocabulary lint, semantic closure review, registry integration, and project acceptance.
- Verification here covers the thirteen batch-six carriers, their manifests, the 61-fixture corpus, and the targeted eight-test suite only.