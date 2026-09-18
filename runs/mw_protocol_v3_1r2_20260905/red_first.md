# 1R.2 red-first record — 2026-09-05 (worker_01)

New test file: `tests/protocol_v3/test_protocol_v3_1r2_mount.py` (29 tests).

## Red run (before implementation)

Command:

```sh
PYTHONPATH=services/api:packages: /opt/homebrew/bin/python3.12 -m pytest \
  tests/protocol_v3/test_protocol_v3_1r2_mount.py -x -q --no-header -p no:cacheprovider
```

Result: `1 failed ... stopping after 1 failures`

```text
E       ModuleNotFoundError: No module named 'app.protocol_workflow.api.composition'
tests/protocol_v3/test_protocol_v3_1r2_mount.py:136: ModuleNotFoundError
```

The first test (`TestMountConfig::test_default_off_when_flag_absent`) failed
on the missing composition module; all composition/storage/router symbols
under test (`mount_protocol_workflow_router`,
`protocol_workflow_config_from_env`, `admit_project`, `is_project_admitted`,
`protocol_workflow_not_found_envelope`, schema v2) were absent at that point.

## Green run (after minimal implementation)

- `focused_1r2_mount.xml`: 28 passed, 1 skipped (real-main entrypoint;
  skip reason names the missing Main-owned dep `fitz(PyMuPDF)`).
- `full_protocol_v3.xml`: 1400 passed, 1 skipped, 101 subtests passed.

## Schema-version drift vs the 1R.1 freeze (relevant, intended)

- `storage/sqlite.py`: `18770a1c…` → `61737a8c…` (migration 2 allowlist).
- `test_sqlite_product_storage.py`: `6710dd96…` → `a755d8ce…` (v2 pins).
- Unchanged: `storage/selected.py` (`153fc687…`),
  `test_repository_backends.py` (`0b1dd33b…`).
