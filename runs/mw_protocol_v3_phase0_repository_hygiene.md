# MW Protocol v3 Phase 0 repository hygiene inventory

Status: `TASK_0_2_IMPLEMENTED_AWAITING_FRESH_REVIEW`
Task ID: `mw_protocol_v3_phase0_20260809_111313`
Authority inventory: `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-snapshots/mw_protocol_v3_phase0_20260809_111313-task02-r3/repository_hygiene_inventory.json`
Inventory fingerprint: `38b7684664274949a1f53598d9fa420e2858e304d9df05a2a3e4ac901045339e`

## Outcome

The live workbench was scanned read-only. All 51,035 files/symlinks have a SHA-256, size, mode, mtime, owner, rule, current/cold label, static production/test/checkpoint reference signals, and exactly one of the seven approved dispositions. Unknown or unowned paths are zero. Static lack of reference is never deletion authority and every entry remains `mutation_eligible=false`.

| Disposition | Files | Bytes | Meaning |
|---|---:|---:|---|
| `reuse` | 421 | 39,090,609 | Active shared source/toolchain usable by the clean build |
| `migrate_then_retire` | 82 | 5,294,976 | Existing medical-writing behavior to extract behind Protocol v3 contracts before retirement |
| `authority_regression` | 392 | 86,351,722 | Approved design, clinical corpus and regression evidence retained read-only |
| `historical_archive` | 27,088 | 13,143,605,387 | Early process/acceptance history, indexed but excluded from active build |
| `regenerable` | 14,989 | 603,672,745 | Cache/build/dependency products; candidate only after Task 0.3–0.5 gates |
| `quarantine` | 70 | 8,748,010 | Blocked candidates requiring locator/hash/occupancy resolution |
| `protected_out_of_scope` | 7,993 | 17,396,760,367 | Medical monitoring, runtime databases/logs and harness state; deny-mutation |

Historical evidence is split into 14,899 current files (10,086,040,123 bytes) and 12,189 cold files (3,057,565,264 bytes). This is an index, not deletion approval.

## What remains directly useful

- Shared contracts, API/frontend source, tests, build/QC scripts and declared toolchain files remain available in the isolated source baseline.
- Existing medical-writing exporter, durable export jobs, Word-verification repository, TipTap/ProseMirror editing baseline, structured-table editor, cross-reference mark, source mapping and durable job state are migration inputs, not proof that design-v1.2 is complete.
- Approved design-v1.2, D001–D017 decisions, r17/D017 regression records, Word release evidence, regulatory/clinical research, protocol corpus and current corpus/glossary assets remain read-only authority/regression inputs.

## What is early process material

- `runs/`, `records/`, `logs/`, most `evidence/`, `context/`, `reviews/`, `metrics/`, `prompts/`, and superseded `plans/` are `historical_archive` unless a higher-priority authority or medical-monitoring rule applies.
- `.superpowers/`, `artifacts/`, `output/`, `frontend/output/`, loose worker reports and early visual explorations are historical design/visual process material.
- They are excluded from the clean implementation workspace but remain in place and hash-indexed. Task 0.2 did not move or delete them.

## What may eventually be cleaned

- 14,989 regenerable files (about 604 MB) include `frontend/.npm-cache`, `frontend/node_modules`, `.venv`, `frontend/dist`, `.pytest_cache`, `.playwright-cli`, bytecode and OpenXML Release/obj output.
- No item is currently eligible for mutation. Task 0.3 must first reproduce the Python/frontend toolchain; Task 0.4 must freeze protected owners; Task 0.5 then uses copy-hash-PATH_MAP/restore rehearsal or deterministic cache deletion as allowed by the plan.

## Quarantine findings

- The nested `implementation/workbench/` contains 68 files (8,732,818 bytes): 18 match canonical content, 13 conflict with a canonical path, and 37 have no canonical counterpart. All remain `quarantine_blocked`; none was merged, moved or deleted.
- `frontend/.npmrc` is a protected local toolchain configuration and remains blocked until Task 0.3 proves a clean rebuild without it.
- The loose `--indications` file is an orphan CLI-process artifact but remains blocked until locator and occupancy checks approve quarantine.
- 2,583 basename/hash conflict groups and 3,938 checkpoint-reference blockers are recorded. They are conservative mutator gates, not claims that every same basename is an error.

## Verification

- TDD red: the focused test initially failed because the classifier modules did not exist.
- First fresh review rejected r2 on case-sensitive monitoring ownership, incomplete generic WAL/SHM coverage and substring-based added-path attribution. New tests failed before remediation.
- TDD green after remediation: the focused suite passed 5/5 and `python3 -m pytest tests/protocol_v3 -q` passed 16 tests.
- Immediate 51,035-entry rehash verification returned zero blocked drift. Explicitly tolerated owners were only `medical_monitoring`, `harness_runtime`, and `toolchain_cache`; observed drift was limited to one monitoring prompt and `.pytest_cache` metadata/content.
- New-path drift now runs through the same case-insensitive, explicitly scoped rule engine. An arbitrary path whose filename merely contains `medical_monitoring` remains unresolved and blocks verification.
- Task 0.1 source baseline was reverified after inventory generation: all 1,017 entries and strict metadata matched fingerprint `a9ece82faffde0106dcda2ff2dab29bc79ba1ec6bed94fca87e19606dc64b8f2`.
- No live service, model, download, OCR, translation, Word automation or mutator ran.

## Gate position

Task 0.2 implementation is ready for fresh review. H0/H1/H3 are not declared complete: process/file occupancy remains explicitly `not_checked_task_0_2_read_only`, the protected dependency/SQLite logical manifest belongs to Task 0.4, and every mutator remains locked until Tasks 0.3–0.5 satisfy their gates.
