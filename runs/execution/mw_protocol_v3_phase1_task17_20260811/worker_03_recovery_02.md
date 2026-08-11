All work complete and verified. Here is the final report.

---

# Execution Output: mw_protocol_v3_phase1_task17_20260811 - worker_03_recovery_02

## Boundary And Context Check

**Read set consumed:**
- `AGENTS.md` — operating principles
- `context/mw_protocol_v3_phase1_task17_20260811_context.md` — parent Task 1.7 scope
- `runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_02_recovery_02.md` — the tightened common Harness interface (preflight, 6-field receipt, `_validated` stamp, observed identity check, mandatory probe)
- `services/api/app/protocol_workflow/runtime/harness.py` — full updated Harness (1400 lines): `AdapterOutcome`, `DispatchReceipt` (6 fields), `TransportAdapter` protocol (`preflight`, `probe`, `dispatch(session_id, lease)`), `HarnessDispatcher.dispatch()` (gate → preflight → probe → credential scan → lease → dispatch → receipt validation)
- `services/api/app/protocol_workflow/runtime/adapters/direct_api.py` — worker 02's reference pattern (mandatory probe, preflight, 6-field receipt, no defaults)
- My owned files: `codex_app.py`, `omp_cli.py`, `tests/protocol_v3/test_harness_policy.py`
- `packages/contracts/workbench_contracts/protocol_v3.py` — `NodeExecutionContract.provider_session_id` confirmed

**CLI evidence re-read directly (required):**
- `codex exec --help`: `--json` (JSONL), `--output-schema <FILE>` (filesystem path), `--model`, `resume` subcommand
- `codex exec resume --help`: `codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]`, `--json`, `--output-schema`, `--model`
- `omp --help` (v17.2.9): `-p`/`--print`, `--auto-approve`, `--thinking` accepts `off|minimal|low|medium|high|xhigh|max|auto`, `--max-time`, `-r`/`--resume=<value>`, `--provider`, `--model`

**Boundary compliance:**
- Wrote only: `codex_app.py`, `omp_cli.py`, `tests/protocol_v3/test_harness_policy.py` (CLI portions + one Ruff fix in worker 02's section). `__init__.py` unchanged (exports already coherent).
- No canonical contract, registry, shared gate, frontend, legacy, medical-monitoring, or production path modified.
- No live model/CLI/service calls — only `--help` reads for syntax evidence.
- Plan hash unchanged: `fa99fbd…d54914`. Medical-monitoring diff: **0**.

## Work Performed

### 1. `codex_app.py` — full rewrite with 5 repairs

- **Mandatory `probe_fn`**: Constructor rejects `probe_fn=None` with `ValueError`. No `lambda: True` default.
- **`preflight(request) -> AdapterOutcome`**: Pure check rejecting provider/model mismatch (`adapter_provider_mismatch` / `adapter_model_mismatch`) and schema-resolution failures (`schema_ref_unmapped` / `schema_file_missing`) before probe.
- **`dispatch(session_id=None, lease=None)`**: Accepts both kwargs for protocol uniformity. Constructs `DispatchReceipt` from all 6 explicit transport fields; raises `ValueError` on missing/blank fields (no defaults).
- **Schema URI → local file resolver**: `schema_path_resolver` is a mandatory injected `Callable[[str], str | None]`. Preflight resolves the request `output_schema_ref` URI to a real local file path and verifies `os.path.isfile`. Command planning uses the resolved path. The URI never appears in the plan.
- **`build_codex_exec_plan`**: Now takes `output_schema_path` (local path, not URI). Standalone pure builder.

### 2. `omp_cli.py` — full rewrite with 3 repairs

- **Mandatory `probe_fn`**: Constructor rejects `probe_fn=None`.
- **`preflight(request) -> AdapterOutcome`**: Pure provider/model mismatch check.
- **`dispatch(session_id=None, lease=None)`**: 6-field receipt, no defaults.
- Same-session (`--resume`), `-p`, `--auto-approve`, exact thinking values, long `--max-time` all preserved.

### 3. Tests — 9 `preflight_missing` → real outcomes + 25+ new tests

**Updated 9 expectations** (from `preflight_missing` to real success/policy outcomes):
- `TestCodexDispatch`: 2 `preflight_missing` tests → `test_valid_dispatch_produces_typed_receipt` (success), `test_probe_failure_prevents_dispatch` (`probe_failed`), plus `test_preflight_provider_mismatch_before_probe`, `test_preflight_model_mismatch_before_probe`, `test_six_field_receipt_enforced`
- `TestOmpDispatch`: 2 `preflight_missing` → valid receipt + probe failure + preflight mismatch + 6-field enforcement
- `TestCrossProductProbeOnce`: 2 `preflight_missing` → `probe_failed` + `probe_failed`; counting probe test → `probe_count == 1`
- `TestCrossProductSchemaMismatch`: `test_codex_plan_binds_request_output_schema` → `test_codex_plan_binds_resolved_schema_path_not_uri`
- `TestCrossProductSameSessionRecovery`: comment fixes; new `test_dispatcher_forwards_provider_session_id_codex` and `test_dispatcher_forwards_provider_session_id_omp`

**New test classes (25+ tests):**
- `TestCliAdapterMandatoryProbe` (5): missing `probe_fn`, `schema_path_resolver`, `transport` all rejected at construction
- `TestCliAdapterPreflight` (4): ok outcomes + provider/model mismatch
- `TestCodexSchemaResolver` (5): unmapped ref, nonexistent file, resolved path in plan, URI never emitted, resumed plan uses resolved path
- `TestCliNoDuplicateDispatch` (2): preflight/probe failure → zero invocations
- `TestCliAdapterProtocolConformance` (4): protocol members present, `lease` kwarg accepted

## Artifacts And Evidence

| File | Change | Size | Verification |
|---|---|---|---|
| `adapters/codex_app.py` | Full rewrite | ~15KB | Ruff OK, format OK, 3.12 compile OK |
| `adapters/omp_cli.py` | Full rewrite | ~12KB | Ruff OK, format OK, 3.12 compile OK |
| `tests/protocol_v3/test_harness_policy.py` | CLI portions repaired + new tests | 2637 lines | Ruff OK, format OK, 3.12 compile OK |

## Commands And Observations

| Command | Observation |
|---|---|
| `pytest test_harness_policy.py -q` | **151 passed** in 0.48s |
| `pytest test_harness_policy.py test_registry_loading.py -q` (focused pair) | **182 passed** in 0.49s |
| `pytest tests/protocol_v3/ -q` (full suite) | **852 passed** in 6.08s |
| `python3 -m ruff check <owned files>` | **All checks passed!** |
| `python3 -m ruff format --check <owned files>` | **4 files already formatted** |
| `python3.12 -m py_compile <owned files>` | **compile OK (3.12.13)** |
| `shasum -a 256 .hermes/plans/…md` | `fa99fbd…d54914` — unchanged |
| `git status --porcelain \| grep -ic monitoring` | **0** |
| `codex exec --help` | `--json`, `--output-schema <FILE>`, `--model`, `resume` subcommand confirmed |
| `codex exec resume --help` | `exec resume [OPTIONS] [SESSION_ID]` confirmed |
| `omp --help` | `-p`, `--auto-approve`, `--thinking off\|minimal\|low\|medium\|high\|xhigh\|max\|auto`, `--max-time`, `--resume` confirmed |

## Blockers Or Missing Environment

None. All tools available: `python3` (3.9.6), `python3.12` (3.12.13), `pytest`, `ruff`, bundled `codex`, local `omp` v17.2.9. PYTHONPATH set to `services/api:packages/contracts:.` (existing convention).

## Rerun Requests Or Next Step

**Worker 03 recovery 02 is complete and verified.** All 5 required repairs delivered:

1. Both adapters require mandatory `probe_fn` (no default); pure `preflight() -> AdapterOutcome` checks identity before probe
2. Both `dispatch()` accept `session_id=None, lease=None`; 6-field receipt from explicit transport fields only
3. Same-session behavior preserved (Codex `exec resume`, OMP `--resume`, no idempotency-key substitution, no `--max-turns=1`, tools enabled, OMP uses `-p`/`--auto-approve`/exact thinking/long wait)
4. Codex schema URI resolves to real local JSON file via injected resolver; URI never emitted in plan; unmapped/missing file fails closed in preflight before probe
5. All 9 temporary `preflight_missing` expectations updated to real success/policy/receipt outcomes; new tests for mandatory probe, preflight mismatch, 6-field receipt, schema resolver failure, dispatcher session forwarding, no duplicate invocation

182 focused pair passed; 852 full Protocol v3 passed; Ruff clean; Python 3.12 compile clean; plan hash unchanged; zero medical-monitoring diff. Do not claim final READY — Codex and the independent verifier own acceptance.
