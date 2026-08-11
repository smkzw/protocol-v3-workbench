All four repairs are complete and verified. Here is the final report.

---

# Execution Output: mw_protocol_v3_phase1_task17_20260811 - worker_02_recovery_02

## Boundary And Context Check

**Workspace root:** `.` (`protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313`). Work confined to assigned boundaries.

**Read set consumed (authorized initial set):**
- `AGENTS.md`, `context/mw_protocol_v3_phase1_task17_20260811_context.md`
- `runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_02_recovery_01.md`
- `services/api/app/protocol_workflow/runtime/harness.py` (pre-repair)
- `services/api/app/protocol_workflow/runtime/adapters/direct_api.py` (pre-repair)
- `services/api/app/protocol_workflow/runtime/adapters/local_omlx.py` (pre-repair)
- `tests/protocol_v3/test_harness_policy.py` (pre-repair)

No additional reads beyond the initial set were required.

**Boundary verification (post-work):** `git diff` shows zero tracked file changes. `git status` shows only authorized artifacts as untracked. No canonical contract modified. No registry/loader modified. No worker_03 adapter modified. No shared gate modified. No medical-monitoring diff. Plan hash unchanged (`fa99fbd…d54914`). No production path, no service started, no provider/model/OCR/translation/gate-database invoked, no credential handled.

**Files written (all authorized):** `runtime/harness.py`, `runtime/adapters/direct_api.py`, `runtime/adapters/local_omlx.py`, `tests/protocol_v3/test_harness_policy.py`.

## Work Performed

Repaired four confirmed P1 functional-contract bypasses using fail-first methodology.

**Fail-first observations (before repair, 10 of 11 new tests failed):**
- Gap 1: adapter without `preflight()` dispatched successfully (bypass)
- Gap 1: non-callable preflight treated as `preflight_exception` not `preflight_missing`
- Gap 1: preflight returning `str` caused `AttributeError` (not caught)
- Gap 2: missing `observed_provider` silently defaulted → `success=True`
- Gap 2: missing `output_schema_ref` silently defaulted → `success=True`
- Gap 2: missing `observed_model` silently defaulted → `success=True`
- Gap 3: rogue `observed_provider` in receipt → `success=True`
- Gap 3: rogue `observed_model` in receipt → `success=True`
- Gap 3: rogue `observed_model` in gated receipt → `success=True`
- Gap 4: directly constructed request dispatched successfully → `success=True`

**Repairs applied:**

1. **Missing preflight must fail closed (gap 1).** Removed the `getattr` backward-compatibility bypass. The dispatcher now requires `adapter.preflight` to be callable — missing/non-callable returns `preflight_missing` with `dispatched=False`, zero probe calls, zero transport calls. A preflight result that is not `AdapterOutcome` returns `preflight_invalid_result`. Worker_03's `CodexAppAdapter`/`OmpCliAdapter` now correctly fail with `preflight_missing` until they add the method.

2. **No fabricated receipt fields (gap 2).** `DirectApiAdapter.dispatch()` and `LocalOmlxAdapter.dispatch()` now require all six receipt fields (`provider_session_id`, `output_sha256`, `observed_provider`, `observed_model`, `output_artifact_ref`, `output_schema_ref`) to be present and non-blank in the physical transport mapping. Missing/blank fields raise `ValueError` (surfaces as `dispatch_exception` with `dispatched=True`). Removed all `.get(…, self._provider)` / `.get(…, request.output_schema_ref)` defaults. Removed the duplicate Direct API dispatch docstring.

3. **Observed identity mismatch is not success (gap 3).** `_validate_receipt()` now accepts `expected_provider` and `expected_model` and compares them against `receipt.observed_provider` / `receipt.observed_model`. A mismatch returns `receipt_identity_mismatch` with `dispatched=True` and `success=False`. The receipt is runtime authority — it must agree with the validated request.

4. **Request must prove binding validation (gap 4).** `HarnessDispatchRequest` now has a `_validated: bool = False` field. Direct construction leaves it `False`. Only `build_request()` calls the module-private `_validated_construct()` classmethod which stamps it `True`. The dispatcher checks `request._validated` at the top of `dispatch()` — unvalidated requests return `request_unvalidated` with `dispatched=False`, zero probe/preflight/transport calls.

5. **Removed `_null_lease`** (unused dead code).

## Artifacts And Evidence

| Artifact | Lines (before → after) | Changes |
|---|---|---|
| `services/api/app/protocol_workflow/runtime/harness.py` | 1310 → 1399 | Removed preflight bypass; added `_validated` stamp + `_validated_construct` classmethod + dispatcher check; added observed identity mismatch to `_validate_receipt`; propagated `expected_provider`/`expected_model`; removed `_null_lease` |
| `services/api/app/protocol_workflow/runtime/adapters/direct_api.py` | 183 → 192 | Removed all receipt field defaults; require explicit physical transport fields; removed duplicate docstring |
| `services/api/app/protocol_workflow/runtime/adapters/local_omlx.py` | 195 → 211 | Removed all receipt field defaults; require explicit physical transport fields |
| `tests/protocol_v3/test_harness_policy.py` | 1994 → 2297 | Added 11 fail-first tests (4 test classes); updated 9 worker_03-dispatch tests to assert `preflight_missing` |

## Commands And Observations

| Command | Observation |
|---|---|
| Fail-first: 11 new tests before repair | **10 failed, 1 passed** — all four bypasses proven |
| `PYTHONPATH="services/api:packages/contracts:." python3 -m pytest tests/protocol_v3/test_harness_policy.py -q` | **124 passed** in 0.47s |
| `PYTHONPATH="services/api:packages/contracts:." python3 -m pytest tests/protocol_v3/test_harness_policy.py tests/protocol_v3/test_registry_loading.py -q` (focused pair) | **155 passed** in 0.47s |
| `PYTHONPATH="services/api:packages/contracts:." python3 -m pytest tests/protocol_v3/ -q` (full suite) | **825 passed** in 7.51s — no regressions |
| `uv tool run ruff check --fix <owned files>` | 3 auto-fixed, **0 remaining** |
| `python3 -m py_compile <owned files>` | OK (Python 3.9.6) |
| `python3.12 -m py_compile <owned files>` | OK (Python 3.12.13) |
| `git diff --name-only` | Zero tracked file changes |
| `sha256sum .hermes/plans/…md` | `fa99fbd…d54914` — unchanged |
| Medical-monitoring diff | NONE |

## Blockers Or Missing Environment

**No blocker.** Same environment notes as prior recoveries (Ruff via `uv tool run ruff`; `PYTHONPATH` required for test invocation).

## Rerun Requests Or Next Step

**Worker_02 recovery 02 is complete and verified. No rerun needed for owned files.**

**Remaining worker_03 interface work (NOT my files — documented, not modified):**

1. **`CodexAppAdapter` and `OmpCliAdapter` must implement `preflight(request) -> AdapterOutcome`.** Without it, the dispatcher now correctly rejects all dispatch through those adapters with `preflight_missing` (`dispatched=False`, zero transport calls). Nine tests document this expected failure. Once worker_03 adds `preflight()`, those tests should be updated to assert the real dispatch/probe outcomes.

2. **`CodexAppAdapter.dispatch()` and `OmpCliAdapter.dispatch()` must construct `DispatchReceipt` with all six explicit fields** from the physical transport mapping (no defaults). The adapters must also accept `lease=None` for protocol uniformity.

3. **`CodexAppAdapter.dispatch()` and `OmpCliAdapter.dispatch()` must accept `session_id=None` and `lease=None` kwargs** for protocol coherence with the updated `TransportAdapter` protocol.

**For Codex acceptance:** verify the `_validated` stamp mechanism is acceptable (it uses a private classmethod + `object.__setattr__` on a frozen dataclass, which is the standard Python pattern for sealed construction without changing canonical models); confirm that worker_03's CLI adapters are blocked until preflight is added (this is intentional — gap 1 requires every adapter to expose preflight); do NOT claim final READY (per instructions).
