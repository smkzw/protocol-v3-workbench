# Execution report: 3R.3 batch3 (omp/pi openai-codex/gpt-5.6-luna:xhigh)

Saved by dispatching ZCode main owner from the runner stream.
Route identity: pi/openai-codex/gpt-5.6-luna, xhigh thinking flag, probe echoed provider/model.
Dispatch: dispatch.json in this directory.

---

STATUS: COMPLETED

FILES_CREATED:
- 10 ChapterContractV2 files:
  - `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/v2_n_4_1.json` through `v2_n_4_5.json`
  - `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/v2_n_5_1.json` through `v2_n_5_5.json`
- 10 dedicated Chinese chapter-skill manifests under `chapter_skills/`
- `tests/fixtures/protocol_v3/chapter_content_v2/batch3.json`
- `tests/protocol_v3/test_chapter_batch3.py`
- Diagnostics:
  - `runs/mw_protocol_v3_3r3_batch3_20260911/red_preimplementation.xml`
  - `runs/mw_protocol_v3_3r3_batch3_20260911/green_attempt1.xml`
  - `runs/mw_protocol_v3_3r3_batch3_20260911/green_attempt2.xml`
  - `runs/mw_protocol_v3_3r3_batch3_20260911/green_final.xml`

RED_EVIDENCE:
- `runs/mw_protocol_v3_3r3_batch3_20260911/red_preimplementation.xml`
- Preimplementation run failed with 20 tests because batch3 fixture and contract files were absent.

GREEN_EVIDENCE:
- Exact command:
  `env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_chapter_batch3.py -q -p no:cacheprovider --tb=short --junitxml=runs/mw_protocol_v3_3r3_batch3_20260911/green_final.xml`
- Tail summary: `20 passed in 0.79s`
- XML: `runs/mw_protocol_v3_3r3_batch3_20260911/green_final.xml`
- Partial lint: `incomplete`, zero error findings, 10 covered carriers.
- Full lint: intentionally `incomplete`, reports 101 missing carriers.

FIXTURES:
- Total: 48
- Positive: 10
- Missing claim: 10
- Missing control: 5
- Wrong source: 13
- Skeleton: 10
- Source-specific negatives:
  - `fixture:batch3:v2-n-4-1:wrong-comparator-ratio`
  - `fixture:batch3:v2-n-4-2:stale-numbered-reference`
  - `fixture:batch3:v2-n-4-3:dose-other-regimen`
  - `fixture:batch3:v2-n-4-4:end-of-treatment-as-follow-up`
  - `fixture:batch3:v2-n-5-1:threshold-contradiction`
  - `fixture:batch3:v2-n-5-3:copied-contraception-duration`
  - `fixture:batch3:v2-n-5-4:nonspecific-per-protocol`
  - `fixture:batch3:v2-n-5-5:phantom-completed-approval`

SEMANTIC_NOTES:
- Parent `v2_n_5` body 372–379 population framing is assigned to inclusion carrier `v2_n_5_1`; exclusion carrier `v2_n_5_2` references the framing without copying inverse criteria or creating a fabricated parent leaf.
- Inclusion and exclusion contracts use distinct typed paths for logic, criteria, parameters, windows, and exceptions, with explicit `all-applicable-criteria` and `any-applicable-criterion` predicates.
- Design high-risk choices remain project-instance human decisions. Contracts prohibit template defaults, copied example values, inferred allocation ratios, and inferred randomization systems.
- Completion, follow-up, and overall study end are separate obligations. Screen failure, rescreening, and consented-but-not-randomized status are separately represented.
- Independently required evidence groups are separated for all ten nodes. Registry consistency obligations are present for `v2_n_5_1` and `v2_n_5_2`.

DEFERRED:
- Medical coherence, clinical validity, and positive QC/CtQ judgment.
- Runtime conditional applicability execution.
- Actual admitted project provenance and source approval.
- Native Word rendering and visual acceptance.
- Final regulated wording against applicable GCP source text.

LIMITS_AND_NEXT:
- Batch3 is a partial authored slice only; no acceptance or runtime activation claim.
- Main owner must combine this slice with the other accepted/reviewed batches, run final cross-contract vocabulary and semantic-closure checks, reconcile M11/E6(R3) anchors, and perform final acceptance.