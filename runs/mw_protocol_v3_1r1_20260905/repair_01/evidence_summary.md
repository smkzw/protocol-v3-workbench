# Task 1R.1 repair_01 evidence — worker_01 follow-up (zcode / GLM-5.3-Flash:max)

Targeted repair of the REVISE-d initial candidate. Same four files; additive
evidence only in this directory. Prior evidence untouched.

## Red-first

`red_repair_evidence.txt` — 11 new tests failed against the pre-repair
candidate, exactly on the acceptance blockers:

- ForeignSchemaAdoption ×6 (fake version 0/1, duplicate history, zero-prefixed
  history, missing owned column, unrelated table beside owned schema)
- VolatilePathRejection ×1 (`:memory:` accepted)
- PreEntryMutationRejection ×1 (unentered-UoW write persisted)
- SqlFailureAtomicity ×2 (half batch committed; replace cleared old projection)
- TimestampSerialization ×1 (naive datetime silently shifted)

`test_empty_version_history_is_rejected` passed pre-repair (pin only: the old
code already rejected empty history). Restructured chain-violation cases
(true first violations) and `test_batch_prefix_rolls_back_to_committed_head_on_later_violation`
passed pre-repair (test-correctness fix + already-correct validation path).

## Green (post-repair)

| Command (env: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:. /opt/homebrew/bin/python3.12 -m pytest -p no:cacheprovider) | Result |
|---|---|
| `tests/protocol_v3/test_repository_backends.py -q` | **76 passed** |
| `tests/protocol_v3/test_sqlite_product_storage.py -q` | **45 passed** |
| both files `-q` | **121 passed** |
| `runs/mw_protocol_v3_1r1_codex_20260905/test_acceptance_probes.py -q` (read-only) | **5 passed** (all Codex probes) |
| `tests/protocol_v3 -q` | **1361 passed, 101 subtests passed, 0 failed** |

(Initial pass actuals were 104 focused = 74 shared + 30 product; repair adds
+2 shared / +15 product → 121. Full suite 1344 → 1361.)

## Fixes per acceptance blocker

1. **Foreign/unknown DB adoption**: `_bootstrap` now runs a READ-ONLY preflight
   (`_open_readonly`, `file:...?mode=ro`) for any existing non-empty file
   BEFORE opening any read-write connection. `_validate_migration_history`
   requires exactly 1..N integer rows, each once, no zero/negative, duplicate,
   gapped, unknown or future entries (MAX() alone is insufficient). Adoption
   additionally requires the EXACT owned table set (no missing, no unrelated
   tables) and per-table column fingerprints recorded per migration version.
   Rejection never opens a read-write connection, so no checkpoint/rewrite of
   the unknown DB (main file byte-identical, hash-verified in tests; SQLite's
   ro open may leave EMPTY runtime -wal sidecars — documented in
   `_open_readonly`, test asserts newly-left -wal is 0 bytes). No speculative
   migration framework added; no foreign rows adopted.
2. **Unentered-UoW autocommit hole**: `_Guard.ensure_active()` now requires an
   open transaction scope (`with uow:`) for ALL 13 mutator sites (CAS save,
   event append, outbox enqueue/claim/complete/fail, inbox record/consume,
   reservation reserve/transition, read-model replace×2/upsert). Reads and
   diagnostics (`connection_pragmas`, getters) stay allowed pre-entry via
   `ensure_open`. Closed/nested semantics unchanged; `commit()` at depth 0
   mirrors memory's no-op close instead of a driver error. Ports/memory NOT
   changed. Tests prove zero durable changes after rejected pre-entry
   mutations (fresh-factory reopen asserts empty) plus positive entered/nested
   behavior.
3. **Compound-write partial persistence**: `append_events` and both
   `replace_*` projections now wrap their writes in a SAVEPOINT (smallest
   SQLite atomic boundary): on any failure the whole compound write rolls back
   while the caller's larger transaction (unrelated successful work) stays
   intact. Driver exception (trigger RAISE(FAIL) → sqlite3.IntegrityError)
   propagates unchanged. Injected-SQL-failure tests cover the event batch
   (second-row trigger failure → zero events committed, sibling CAS work
   committed) and the read-model DELETE+INSERT replacement (previous
   projection fully intact, nothing partially updated). Shared suite adds a
   validation-side whole-batch rollback case (batch prefix discarded, stream
   stays at committed head, stream still usable in the same transaction).
4. **Volatile `:memory:`**: rejected in `_validate_config` before any I/O
   (str and Path forms); ordinary relative/absolute file paths still work
   (regression test builds a relative-path DB in a tmp cwd).
5. **Masked chain-violation tests**: batches now contain only the violating
   event(s), so gap / prev_mismatch / duplicate_event_id / duplicate_sequence
   (in-batch) / wrong_stream each fire as the FIRST violation on both
   backends. No existing fixture or assertion removed or weakened; the
   duplicate-of-stored case is still covered. Immutable old negative tests
   untouched.
6. **Naive datetime**: `_dt_to_iso` raises `ValueError` on naive timestamps at
   the serialization boundary (no silent local-time reinterpretation); focused
   tests pin naive rejection, aware-UTC roundtrip, aware +08:00 roundtrip and
   instant equality across offsets.
7. **Empty-version-row regression** pinned (`schema_version` table with no
   rows → reject, bytes untouched). Obsolete narrow WAL-defect comments
   corrected in BOTH `sqlite.py` and `selected.py` (defect fixed in 3.51.3+;
   official docs note it may affect earlier versions too; gate unchanged at
   ≥3.51.3). Default no-builder negative tests unchanged and passing; the
   `StorageNotReadyError` message was reworded (F6) while preserving the
   asserted substrings ("sqlite.py", "pocs", "Codex follow-up") and now points
   to `create_product_unit_of_work_factory`.

## Final hashes (sha256)

```
abdb01078c78e06aeac3bdbfea0f02db9a45c2f9b79989ee7a1c99478c780d8f  services/api/app/protocol_workflow/storage/sqlite.py
153fc687d1414ca41218daec7b1777a73e98dbf8476491ba926a91c3d9d7a6d3  services/api/app/protocol_workflow/storage/selected.py
0b1dd33b2b551fb6b144d3df1bff652d886e51edf76b82bff94420d6c1d044f5  tests/protocol_v3/test_repository_backends.py
5f721f415fcbc30c8a7abddf1fd59856a5f14caaf76c37979acb45dbb3ac65e6  tests/protocol_v3/test_sqlite_product_storage.py
```

## Scope diff

Worker-touched paths only: `storage/sqlite.py` (new), `storage/selected.py`
(tracked diff vs Phase R state), the two new test files, `repair_01/` evidence.
Other tracked modifications (`scripts/qc/*`, `tests/fixtures/*`,
`test_frozen_authority_manifest.py`, `test_repository_hygiene_mutator.py`)
pre-date this task. No ports/memory/PoC/main/frontend/monitoring edits; no
services, network, packages, commits.

## Compliance notes

- `apply_patch` located at `/Users/smkzw/.codex/tmp/arg0/codex-arg0hCMeRK/apply_patch`
  and used for all edits EXCEPT one content append to
  `test_sqlite_product_storage.py` (new test classes) that was applied via a
  `cat >>` heredoc before the first apply_patch call in that sequence;
  disclosed here rather than silently claimed. All subsequent changes used
  apply_patch.
- Mandatory rereads done in full: plan v2 (all 481 lines), review amendment,
  Codex probes, conference evidence.

## Out-of-scope pending (reported, not edited)

- Driver-level exception translation for `sqlite3.Error`/`SqliteStorageError`
  in `application/service.py` (`_EXCEPTION_MAP`) and the CAS/outbox steps of
  `events/unit_of_work.py` — mandatory 1R.3 work outside this task's four
  files (conference finding F2; remains fail-closed today: raw driver
  exception propagates and the with-block rolls back).
- 1R.2 main composition-root switch remains the product activation gate; the
  explicit `create_product_unit_of_work_factory` function route does not
  supersede it.
- Worker does not claim task closure or product acceptance; Codex and the
  independent verifier own done.
