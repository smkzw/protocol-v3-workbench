# Protocol v3 P0-CORE Functional Closure Candidate

Date: 2026-08-12
Status: `P0_CORE_FUNCTIONAL_READY`
Scope: non-security H0–H6, dual manifests and permanent failure corpus only

## Authority and interpretation

- Frozen plan SHA-256: `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`.
- Accepted Task 0.2 inventory remains immutable at `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-snapshots/mw_protocol_v3_phase0_20260809_111313-task02-r3/repository_hygiene_inventory.json`.
- Inventory bytes SHA-256 `29321ad4595dd5093e1477449568ce93b3ffe9fb52dc6a0483db4404fbfd6621`; inventory fingerprint `38b7684664274949a1f53598d9fa420e2858e304d9df05a2a3e4ac901045339e`. Both exactly match `tests/fixtures/protocol_v3/immutable_protected_assets.json`.
- The original inventory's `occupancy=not_checked_task_0_2_read_only` is not rewritten. This record supplements it with current occupancy evidence bound to the immutable inventory. Occupancy is evaluated over the exact authorized mutation target set, not all 51,035 protected/read-only files.
- No Task 1.11 or other security test is part of this closure.

## H0 — inventory and occupancy

- 51,035 inventory entries; seven declared classifications; 14 declared owners.
- `unknown_owner_count=0`.
- `mutation_eligible_count=0`.
- Current pure eligibility computation against the accepted protected manifest returns `authorized_target_count=0`, `blocked_count=51035`, `skipped_count=0`, `quarantine_approved_field_present=false`.
- Current built-in occupancy checker on the exact authorized target set (`[]`) returns zero blockers and no declared hygiene-port listener. No file handle check is needed for a nonexistent target.
- Disposition: no repository mutation is authorized; H0 cannot be used as deletion authority.

## H1 — protected authority

- Protected manifest SHA-256 `f4b385d444d4cf922f20b9934e87f6b72c0ad932fc767b5c86045b7e8c0ace7f`.
- 5,992 protected assets; `ownerless=0`, `unresolved=0`, `unknown_current_path=0`, `symlink_escape=0`.
- The 12 inventory-stale missing paths are the explicit frozen allowlist already asserted by the manifest contract; they are not silently ignored.
- Current clean-manifest, exact-authority-hash and deterministic-rebuild checks pass.

## H2/H4/H5/H6 and permanent corpus

- Source closure was repaired in commit `6afb9cb`; current positive closure/manifest round-trip checks pass.
- Frozen toolchain and one-lock authority remain hash-valid; current positive toolchain manifest/lock checks pass.
- Task 1.10 Codex final run collected and passed all 1,226 Protocol v3 tests. The focused P1 gate audit independently collected the same 1,226 tests and passed 798 non-security P1 tests.
- Task 0.3 accepted H4–H6 rebuild/test-discovery/no-import-side-effect evidence remains retained; current manifest checks show no drift.
- Permanent eight-class failure corpus and its deterministic builder currently pass all selected positive identity/provenance checks.

## H3 — recoverable hygiene

- Actual authorized mutation set is empty. Therefore the real Task 0.5 apply set, moved-file set and direct-delete set are all empty; no live object is fabricated or moved merely to produce evidence.
- The two inactive pnpm files under `quarantine/protocol_v3/task03/frontend/` predate Task 0.5 (commits `05b7d5b`/`2a4837e`) and are frozen toolchain inputs, not an unrecorded Task 0.5 mutator output.
- Current functional rehearsal in pytest-owned temporary directories: 6/6 passed for pure restore plan, no-occupancy apply, replay-safe apply, idempotent restore, byte-identical apply→restore round-trip and PATH_MAP/eligible-set equality.
- H3 interpretation: every actual Task 0.5 move is recoverable because the actual move set is empty; the mutator's recovery contract is separately exercised without changing the repository.

## Candidate disposition

`P0-CORE_FUNCTIONAL_READY`. Same Luna session `019ff2a4-2a79-7921-9d01-6c0ef07273f1` independently accepted the additive H0 occupancy record and zero-target H3 interpretation. This does not authorize cleanup, deletion, security testing, product release, live migration or product storage activation.
