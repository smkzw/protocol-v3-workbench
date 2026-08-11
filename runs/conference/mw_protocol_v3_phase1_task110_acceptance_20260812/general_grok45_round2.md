# Execution Output:
mw_protocol_v3_phase1_task110_acceptance_20260812 — general_grok45 (Grok Build / grok-4.5), same-session completion after interrupted prior pass

## Boundary And Context Check

- **Role in this deliverable:** independent read-only acceptance / execution-evidence report for Task 1.10 (v2→v3 dry-run migration, quarantine, idempotent lineage, unidirectional cutover, legacy mutation guard). No product edits; no security tests; no service start; no live/runtime DB; no external network; no worker/manager/other-participant reports used as authority.
- **Workspace boundary:** only current workbench root `.`. Did not write runner report paths (`runs/conference/...`); this response is the complete deliverable for the runner to persist.
- **Source of truth used:** frozen plan Task 1.10 (`.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`); conference success criteria; live artifacts under `services/api/app/protocol_workflow/legacy/`, `config/medical_writing/protocol_v3/v2_v3_mapping.json`, and the four focused tests.
- **Env constraint discovered:** full `tests/protocol_v3/` and `app.*` imports require `PYTHONPATH=services/api`. Without it, collection fails with `ModuleNotFoundError: No module named 'app'` (environment, not product defect).
- **Scope confirmation:** synthetic 3,878-row denominator only; standalone contracts (not production-mounted). Explicitly out of scope: Task 1.11 security matrix, live cutover, browser/visual, AI/OCR.

## Work Performed

1. Independently hashed the frozen plan and mapping file; opened Task 1.10 plan micro-steps and all seven legacy modules + mapping JSON + four tests.
2. Ran the four focused Task 1.10 pytest files (twice: bare and with `PYTHONPATH=services/api`).
3. Ran full `tests/protocol_v3/` with `PYTHONPATH=services/api`.
4. Ran API-isolation selector on `test_protocol_v3_api_contract.py` (`SharedSurfaceIsolation or main_py_does_not_reference`).
5. Ran bounded counterexample probes in-process (seven families, 3878 accounting, hash determinism/permutation stability, cutover skip/reverse/unknown-mid/conflict/idempotent, brochure dual-layer block, full no-bypass sweep, drift clean, read-parity freeze, protected-path porcelain).
6. Ran a precision subset (lineage + brochure + skip/reverse + no-bypass + rollback + read-parity): 37 passed.
7. Challenged the “blocked in production” assumption: confirmed `main.py` does **not** import legacy guard (standalone contract — expected for Task 1.10, not a code fail).

**Independent acceptance verdict for Task 1.10 material criteria: READY.**

## Artifacts And Evidence

| Artifact | Independent observation |
|---|---|
| `legacy/{__init__,migration_inventory,quarantine}.py` | Seven families closed; inventory invariant `source = records + quarantine + dedup`; deep-frozen payloads |
| `legacy/migration_map.py` + `v2_v3_mapping.json` | Spec schema `mw_v2_v3_mapping_v1`; version `mw-v2-v3-mapping.2026.08.12-task110`; 7 families / 20 types; `verify_mapping_spec_contracts` → `verified=True`, 0 issues; type dispositions: direct 4 / derived 1 / preserved_legacy_only 6 / quarantine 9 |
| `legacy/cutover_state.py` | Ladder exactly `legacy_active → shadow_read_only → new_canonical`; skip/reverse/unknown-project-reuse/conflicting-replay fail closed; idempotent replay does not double-apply |
| `legacy/mutation_route_inventory.py` | Routes 133 (legacy_write 101 / excluded 28 / read_only 4); services 195 (legacy_write 94 / excluded 83 / read_only 18); drift `ok=True`, findings 0; 0 project-bound `/medical-writing` excluded |
| `legacy/mutation_guard.py` | Dual-layer `legacy_mutation_blocked`; unclassified → `MutationGuardConfigurationError`; `RollbackHelper` only disables v3 command attachment / retains events — cannot reverse cutover or re-enable legacy writes |
| Brochure targets | Route `route.register_medical_writing_investigator_brochure` path contains `/medical-writing/sources/investigator-brochure`; service `service.source_intake.SourceRegistryService.register_medical_writing_document`; both `legacy_write`; ALLOWED only in `LEGACY_ACTIVE`; BLOCKED in SHADOW and NEW_CANONICAL at route **and** service layers |
| Synthetic 3878 dry-run | `source_count=3878`, `mapped=3418`, `unmapped=quarantined=460`, `len(outcomes)=3878`, `len(lineage_entries)=3418`; no silent drop |
| Wiring / protected paths | `main.py` does not import `protocol_workflow.legacy` (standalone); brochure path string exists in `main.py`; `register_medical_writing_document` exists in `source_intake.py`; git porcelain: no main/source_intake/monitoring deltas |

**Hashes (computed this session)**

| Object | SHA-256 |
|---|---|
| Frozen plan | `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914` |
| Mapping file bytes | `8ee8ac78b98aa4ed836679f309a2695ca2c10d8dce65dd1fee153a88da1e6806` |
| Loaded `MappingSpec.spec_sha256` | `34db4b34d5b94114f88c171c125c817d61962cfac3ad2329c1dd63b76b1bdfa2` |
| Mutation inventory `inventory_sha256` | `2e44f83a1992b7b2da8497a761666bf77905827291f99dda38247bedb2ae9df0` |
| 3878 dry-run `run_sha256` | `080a1bb14c9350ab0858f1f5bd07ca20f524efbd7b95c756313db2fbf567b52d` (stable under input reverse) |

**Falsification matrix (independent probes)**

| Claim to falsify | Result |
|---|---|
| Silent drop of unmapped rows | Fail to falsify product: `3418+460=3878` |
| Source/payload mutation after inventory | Inventory/result hashes stable; frozen payloads raise `TypeError` |
| Non-deterministic inventory/map hashes | Identical `run_sha256` on replay and reversed input |
| Lineage overwrite on conflict / same-rev | Covered by green `TestIdempotentLineage` (conflict fail-closed; child retains parent; no overwrite) |
| Cutover reverse / skip / mid-start | `reverse`, `skip`, `unknown_project_reuse` |
| Unclassified mutator bypass | Configuration error fail-closed |
| Brochure / legacy_write bypass in read-only | 101×2 route + 94×2 service checks all blocked |
| Live production wiring claimed | Explicitly **not** wired; do not over-claim |

**Non-blocking residual:** Dry-run report dispositions are coarse (`mapped`/`quarantined`) while type-level mapping uses `direct`/`derived`/`preserved_legacy_only`/`quarantine`. Accounting still closes; document for human readers only.

## Commands And Observations

| Command | Observation |
|---|---|
| `shasum -a 256` plan + mapping | Plan `fa99fbd3…`; mapping file `8ee8ac78…` |
| `python3 -m pytest` four Task 1.10 files `-q` | **220 passed** in 6.43s / 6.50s |
| `PYTHONPATH=services/api python3 -m pytest tests/protocol_v3/ -q` | **1221 passed** in 14.02s |
| `PYTHONPATH=services/api python3 -m pytest tests/protocol_v3/test_protocol_v3_api_contract.py -k "SharedSurfaceIsolation or main_py_does_not_reference" -q` | **3 passed, 29 deselected** in 0.49s |
| Precision subset (lineage / brochure / skip / reverse / no-bypass / rollback / read-parity) | **37 passed** in 3.04s |
| Bare `pytest tests/protocol_v3/` without `PYTHONPATH` | **11 collection errors** (`No module named 'app'`) — env only |
| In-process probes (`build_inventory`, `run_mapping_dry_run`, `CutoverStateRegistry.apply`, `MutationGuard`, `verify_inventory_drift`) | All material checks PASS (see Artifacts) |
| `git status --porcelain` filtered to main/source_intake/monitoring | **none** |

Tools used: filesystem read/list, ripgrep, shell (hash, pytest, pure-Python probes). No browser, no web, no DB, no service, no file writes.

## Blockers Or Missing Environment

- **None blocking Task 1.10 acceptance** when `PYTHONPATH=services/api` is set.
- Notes only:
  - Full suite / API isolation **require** `PYTHONPATH=services/api`.
  - Company-corpus live asset is absent/not used by design; denominator is synthetic `_build_3878_corpus()`.
  - Prior conference turn was interrupted before a complete report; this same-session completion closes that gap only.
  - Runtime HTTP mounting of `MutationGuard` is **out of Task 1.10 scope** (standalone contract). It is an integration gate for later cutover tasks, not a present code defect.

## Rerun Requests Or Next Step

**No worker/participant reruns required for Task 1.10 code.**

**READY** — every material conference success criterion is independently grounded (tests + hashes + counterexamples). No exact product reproducer remains for a `NOT_READY` on Task 1.10 scope.

**What Codex must do next**

1. Accept Task 1.10 as **standalone dry-run / quarantine / lineage / cutover-state / mutation-inventory / dual-layer guard contract complete**, with explicit language that evidence is synthetic and **not** production-mounted.
2. Optionally record acceptance hashes above in the Codex acceptance/commit note (plan `fa99fbd3…`, spec `34db4b34…`, inventory `2e44f83a…`).
3. Do **not** open a Task 1.10 repair work item for missing `main.py` import of the guard; schedule runtime attachment under the later cutover/integration task (plan Task 8.x class) before any real project enters `SHADOW_READ_ONLY` / `NEW_CANONICAL`.
4. Proceed to commit/archive or the next phase task (e.g. Task 1.11 security matrix) only after Codex’s own final authority pass; this report is advisory evidence, not final clinical/regulatory/production authority.
