# Batch1 verification evidence — mw_protocol_v3_3r3_batch1_20260906

Z Code bounded executor (GLM-5.3-Flash / max), 2026-09-06. All commands run
from the repo root with the mandated isolated venv:
`runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python` under
`env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin
HOME=/Users/smkzw LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1
PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.`

## Red-first (before artifacts existed)

- Command: `pytest -q -p no:cacheprovider tests/protocol_v3/test_chapter_batch1.py`
- Observed: 2 failed + 6 errors — `FileNotFoundError: .../chapter_contracts`
  (artifacts absent). Captured in `red_first_run.txt`.

## Green run (after authoring)

- `pytest -q -p no:cacheprovider tests/protocol_v3/test_chapter_batch1.py`
  → **8 passed in 1.07s**.
- Whole directory `pytest -q -p no:cacheprovider tests/protocol_v3`
  → 1663 passed, 1 failed
  (`test_repository_hygiene_mutator.py::TestIntegrityFollowup4::test_raw_tempfile_var_alias_path_accepted`).
  Failure cause is environmental, not artifact-caused: the test asserts
  `tempfile.TemporaryDirectory` resolves under `/var`; the mandated `env -i`
  environment has no `TMPDIR`, so Python picks `/tmp`. Re-run with
  `TMPDIR=/var/tmp` → **1 passed**. That test file and its subject script were
  already modified in the working tree before this task (git status snapshot);
  no test was modified or diluted.

## CLI evidence (reads only; stdout only)

- `scripts/qc/protocol_v3/assemble_chapter_registry.py --contracts-dir
  .../chapter_contracts --skills-dir .../chapter_skills --batch
  tests/fixtures/protocol_v3/chapter_content_v2/batch1.json`
  → exit 0, 184,954 bytes registry JSON on stdout
  (`assembled_batch1_registry.json`).
- `scripts/qc/protocol_v3/lint_chapter_registry.py --registry ... --template-dir
  .../tp_ma_07_v2 --partial` → exit 0; `mode: partial`,
  `status: incomplete`, 99 missing carriers enumerated,
  `partial_mode_not_full_acceptance` info
  (`lint_partial.txt`).
- Same without `--partial` (full mode) → exit 1; `expected=111 covered=12
  leaf_union=110 cover=v2_front_block`; exactly **99** `missing_coverage`
  errors, none on the twelve batch carriers (`lint_full.txt`).

## Coverage truth (derived from node_tree.json, not hardcoded)

- heading leaves (`is_leaf_heading` in both trees): 106; outline leaves
  (`is_leaf`): 109; union 110 + unheaded cover = 111 expected carriers.
- Batch1 roles: `v2_front_block` = cover (front_block present, zero-based
  body-child 0–44); `v2_n_front_5` = outline_only_leaf (Normal local outline,
  no heading style); other ten = heading_leaf (style 2/3 nodes, leaf in both
  trees).

## Authoring source anchors used (zero-based body-child indices)

From reviews/mw_protocol_v3_3r3_batch1_content_spec_20260906.md and the
template registry: cover 23/25/28–36/40–42; front_1 44–46+table[46] 4×5;
front_2 49/51/54/56/58; front_3 66/67/70/72/74/77; front_4 84/87–93+tables
[89]2×3/[91]4×6/[93]3×5; front_5 94–96+table[96] 3×50; front_6 99–231;
front_7 232–234; front_8 236; n_1_1 240–243+table[242] 2×17+1 nested;
n_1_2 245–258; n_1_3 259–265+table[265] 6×33; SOA landscape section =
sections[ordinal 6] (sectPr ends at body-child 266). Word style IDs from
style_properties (2=heading 1, 3=heading 2, 1=Normal, 16=footer, 17=header,
18=toc 1, 21=table of figures, 25=Title, 28=Table Grid).

## Fixture families (48 total; content values conspicuously synthetic)

positive (passes, QC judgment deferred) + one missing-family
(missing_control ×9 / missing_claim ×3) + wrong_source (company_style_only
evidence → wrong_source_role) + skeleton (empty → skeleton_content) per node.
Named negatives per content spec: cover dropped confidentiality/header-footer
facts; front_1 blank change-rationale cell + wrong version source;
front_2 dropped institution; front_3 wrong (old/template) sponsor source;
front_4 blanked role/address cells + dropped PI fact; front_5 dropped
glossary_expansion claim; front_6 cached-static source; front_7 dropped
caption inventory + objects; front_8 dropped claim; n_1_1 wrong source
(template-style values); n_1_2 wrong source (template timeline); n_1_3
cell IDs present but values empty.
