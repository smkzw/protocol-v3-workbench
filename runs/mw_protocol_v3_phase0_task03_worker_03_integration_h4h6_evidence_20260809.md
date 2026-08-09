# Protocol v3 Phase 0 Task 0.3 — Integration worker (worker 3) H4-H6 evidence

Date: 2026-08-09
Task: `mw_protocol_v3_phase0_task03_20260809_111313`
Worker: `worker_03` (manifest-only wrappers, side-effect checks, H4-H6 evidence)
Scope: isolated worktree only. No live-workbench or medical-monitoring source was modified.

## Boundary reconciliation

Worker 1 and worker 2 produced disjoint Python and frontend artifacts. Worker 3
did not overwrite peer work. The Codex clean-rebuild record resolved the
worker-local child-sandbox registry blockers in the controlling isolated
environment; this worker treats the generated Python lock, npm lock and the
on-disk files as the newer evidence and did not repeat clean dependency
downloads.

On-disk hash verification (computed 2026-08-09, matches Codex evidence exactly):

| File | SHA-256 |
|---|---|
| `services/api/requirements-protocol-v3.in` | `9fd153ebb36125d68d575383ce15334f15ca294eff4ed6d50af72cdc58495045` |
| `services/api/requirements-protocol-v3.lock` | `1e771c8f4f3a90410714f94107cecd42662574fa560eb72ce9ee89e6e5921698` |
| `frontend/package.json` | `94309d8be12133712b2a6d4a9ac3be34dbbb2d730533d34deb9f7adc20d2abdd` |
| `frontend/package-lock.json` | `83378e52cc1fdf764ea5d34c418aa0e7da2c4bdf1b099ec85e8feaadca1b2134` |
| `frontend/tests/protocol_v3_test_inventory.mjs` | `f04e933dfcdd228ea26544c142cac29946c1e0714ece1b6719b20dd8d1e24442` |
| `scripts/qc/protocol_v3/verify_toolchain_rebuild.py` | recomputed by manifest pre-check after integration |
| `frontend/pnpm-lock.yaml` (frozen, unchanged) | `3f101b4e9c833a5154af12f250644cfe60ada682d351c9f028484159d038fba8` |
| `frontend/pnpm-workspace.yaml` (frozen, unchanged) | `d6d0c24446d91ef762d37c6ba801bb516e65d7055aa9f8027fcd457409a97ce1` |

## Artifacts added by worker 3

- `config/medical_writing/protocol_v3/toolchain_manifest.json` — frozen
  toolchain manifest (schema `protocol-v3-toolchain.v1`). Single execution
  authority: pins npm as the unique package manager, the package/lock/inventory
  hashes, Python 3.12 + pip-tools 7.6.0 compiler command, the lock hashes, the
  dual-runner scripts, the clean-install/import-probe recipe, and the side-effect
  contract. No CLI override is accepted.
- `scripts/qc/protocol_v3/run_frontend_checks.py` — manifest-only frontend
  wrapper. Performs the hash pre-check, then dispatches to the frozen inventory
  script for H4/H5; starts no service and imports no `main.py` (H6). Exposes no
  `--package-manager`/`--script`/`--lock` override; argparse accepts only
  `--repo-root/--manifest/--check/--run-unit/--build/--json`.
- `tests/protocol_v3/test_toolchain_manifest.py` — 7 focused tests: schema,
  hash-on-disk match, Python-lock-from-manifest, fail-closed on wrong schema,
  fail-closed on stale lock hash, fail-closed on non-hex digest, fail-closed on
  missing referenced file.
- `tests/protocol_v3/test_frontend_check_wrapper.py` — 7 focused tests: no
  package-manager/script override, hash pre-check matches disk, inventory counts
  match manifest, fail-closed on stale count, plus three side-effect-safety
  tests (no `main.py` import, modules importable without side effects, import
  probe reports zero changed paths on the real source tree).

## Changes to `verify_toolchain_rebuild.py` (worker 1 integration)

Additive only; worker 1's direct `validate_hash_lock`/`clean_python_rebuild`
contract and its 5 tests are unchanged and still pass. Added:
- `ManifestError`, `MANIFEST_SCHEMA`, `MANIFEST_PATH`, `SHA256_RE`.
- `load_manifest`, `validate_manifest_hashes` (7 hash pre-checks), and
  `python_lock_validation_from_manifest`.
- CLI `--manifest` mode (manifest-only authority) with the direct mode retained.

## Commands and observations

```
# Full protocol_v3 suite (worker 1 + 2 + 3 tests, plus Task 0.1/0.2 hygiene/baseline)
python3.12 -m unittest discover -s tests/protocol_v3 -p 'test_*.py'
# Ran 35 tests in 0.396s — OK

# Frontend inventory self-check (worker 2)
node tests/protocol_v3_test_inventory.mjs --check
# protocol-v3-test-inventory: 47 tests discovered (vitest/jsdom: 3, node --test: 44)

# Manifest-only Python verification
python3.12 scripts/qc/protocol_v3/verify_toolchain_rebuild.py --manifest config/medical_writing/protocol_v3/toolchain_manifest.json
# mode=manifest; 7/7 hash checks ok; lock_sha256=1e771c8f…; entries=38; direct=15

# Manifest-only frontend check (hash + inventory)
python3.12 scripts/qc/protocol_v3/run_frontend_checks.py --check
# mode=frontend; package_manager=npm; 7/7 hash checks ok; counts {node:44,total:47,vitest:3}

# Manifest-only frontend unit run (this worktree has no node_modules)
python3.12 scripts/qc/protocol_v3/run_frontend_checks.py --run-unit  # exit 1 (expected)
```

Environment: Python 3.12.13, Node 22.22.3, npm 10.9.8. No node_modules in the
isolated worktree, so `--run-unit`/`--build` fail by design here; the Codex
clean-rebuild record (rebuilds C and D) is the authoritative H4/H5 execution
proof and is not re-run by this worker.

## Gate disposition (worker 3 contribution)

- **H4 (dependency rebuild):** frozen. The manifest pins both locks and the
  pip-tools/npm versions; the manifest hash pre-check (7/7 ok) proves the frozen
  artifacts match disk. Codex rebuilds A/B (Python) and C/D (frontend) are the
  authoritative execution proof and remain valid.
- **H5 (test discovery):** frozen. The manifest pins the inventory script hash,
  ignored directories, suffix→runner map, expected counts (47 total / 3 vitest /
  44 node), and the 3 vitest paths. The wrapper's `check_inventory` fails closed
  if live counts diverge from the manifest; observed `{vitest:3, node:44,
  total:47}` matches exactly.
- **H6 (side effects):** covered. New tool imports do not write to disk, create
  DB/directories, or start workers: the manifest-gated import probe on
  `verify_toolchain_rebuild` + `run_frontend_checks` reports `changed_paths: []`
  on the real source tree. Neither wrapper imports legacy `services/api/app/main.py`
  (asserted by a focused test).

## Remaining verification needs (for Codex/verifier)

- Independent verifier should execute two fresh clean rebuilds through the frozen
  manifest wrapper end-to-end (Python 3.12 venv install/import + npm ci/Vitest/
  Node/Vite build) to reconfirm H4/H5 independently of the Codex record.
- No final visual/PPT/PDF/clinical/regulatory acceptance is claimed by this worker.
