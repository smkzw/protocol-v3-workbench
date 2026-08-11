The full gated dispatch lifecycle works end-to-end: gate consistency check passes, lease is acquired and forwarded, dispatch_fn receives the lease, receipt is validated. All correct.

---

# Execution Output: mw_protocol_v3_phase1_task17_20260811 - worker_02_recovery_01

## Boundary And Context Check

**Workspace root:** `.` (`protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313`). Work confined to assigned boundaries.

**Read set consumed (authorized initial set + permitted expansions):**
- `AGENTS.md`, `context/mw_protocol_v3_phase1_task17_20260811_context.md`
- `services/api/app/protocol_workflow/registries/loader.py` (RoleEntry, _TargetProfile)
- `services/api/app/protocol_workflow/runtime/harness.py` (pre-repair)
- `services/api/app/protocol_workflow/runtime/adapters/{direct_api,local_omlx,codex_app,omp_cli}.py`
- `tests/protocol_v3/test_harness_policy.py` (pre-repair)
- `packages/contracts/workbench_contracts/protocol_v3.py` (`NodeExecutionContract`, `SensitivityTier`, `SkillDefinition`) — canonical contract reference, read-only, NOT modified
- `services/api/app/protocol_workflow/runtime/{reservations,idempotency}.py` — Task 1.6 reference, read-only, NOT modified
- Worker_03 adapters (`codex_app.py`, `omp_cli.py`) — read-only for coherence verification, NOT modified

**Boundary verification (post-work):** `git diff` shows zero tracked file changes. `git status` shows only authorized artifacts as untracked. No canonical contract modified. No registry/loader modified. No medical-monitoring diff. No production path, no service started, no provider/model/OCR/translation/gate-database invoked, no credential handled.

**Files written (all authorized):** `runtime/harness.py`, `runtime/adapters/direct_api.py`, `runtime/adapters/local_omlx.py`, `tests/protocol_v3/test_harness_policy.py`. Worker_03's `codex_app.py` and `omp_cli.py` were NOT modified.

## Work Performed

Repaired all 10 confirmed P1 contract gaps in the common Harness boundary.

**Gap-by-gap repair:**

1. **Registry-bound role policy (gap 1).** Removed `role_allows_thinking: bool`. `build_request()` now requires the immutable `RoleEntry` from the loaded registry and validates exact `role_id`, role kind, target-profile provider/model/harness match, allowed efforts, and thinking discipline. `_validate_role_binding()` is the sole authority — no caller boolean escape hatch.

2. **Full node/skill/artifact binding (gap 2).** `_validate_skill_binding()` enforces `skill_definition_id` equality, input/output schema ref equality, and contract tools/paths as subsets of the skill's closed set **always** (even when the skill set is empty → contract must also be empty). `_validate_artifact_binding()` enforces exact ordered hash-tuple equality (`passed_hashes == node_contract.input_artifact_hashes`) — no substitution, omission, duplicate or reordering. `prompt_sha256` and `provider_session_id` carried into the typed request.

3. **Selected region and sensitivity (gap 3).** `selected_region` is now a required parameter. `_validate_region_sensitivity()` checks it against both the node allowlist and the Role target-profile regions. The Role target-profile sensitivity tier is the maximum permitted (`_SENSITIVITY_RANK`); a more sensitive request fails closed. Provider allowlist preserved.

4. **Logical artifact refs only (gap 4).** `ArtifactRef.__post_init__` now enforces a closed logical URI pattern (`_ARTIFACT_REF_RE`: lowercase alphanumerics, `/_:-` separators). `_PATH_ESCAPE_RE` rejects absolute paths, `~`, `..`, backslash. Positive test for namespaced refs (`chapter-1/draft`); negative tests for absolute, home, traversal, uppercase.

5. **Unified workload gate for OCR and translation (gap 5).** Gate policy moved to the common `HarnessDispatcher` boundary via `_ensure_gate_consistency()`. For role kinds `ocr` and `translation`, requires injected `gate_selection` + `lease_factory`; compares declared model to effective model before probe/dispatch; fails closed on missing/mismatch with `WorkloadGateError`. The correct `ocr`/`translation` lease is held around the single transport call via `_dispatch_gated()`. Applies to Paddle Direct API and local oMLX equally — Paddle OCR via Direct API now correctly fail-closed when gate selects GLM. No fake/no-op lease default.

6. **Mandatory real probe injection (gap 6).** `DirectApiAdapter` and `LocalOmlxAdapter` constructors reject missing `probe_fn` with `ValueError` (no `lambda: True` default). Both expose `provider`, `model`, and pure `preflight()` returning `AdapterOutcome`. The dispatcher calls preflight before probe; identity/provider/model/gate/preflight failures return stable policy errors with `dispatched=False` and zero transport calls.

7. **Same-session path through the Harness (gap 7).** `provider_session_id` added to `HarnessDispatchRequest` from `NodeExecutionContract`. `TransportAdapter.dispatch(request, *, session_id=None, lease=None)` protocol updated. `HarnessDispatcher` forwards `request.provider_session_id` as `session_id`. `idempotency_key` is never used as a session id.

8. **Typed output receipt (gap 8).** `DispatchReceipt` extended with `output_artifact_ref` (validated as closed logical id) and `output_schema_ref`. `_validate_receipt()` enforces receipt schema equals request output schema. Hash alone is no longer typed artifact proof.

9. **Accurate dispatched semantics (gap 9).** `AdapterOutcome` typed signal replaces exception-type guessing. Preflight/policy/probe/gate/lease-acquisition failures → `dispatched=False`. Only entering `adapter.dispatch()` sets `dispatched=True`. Lease acquisition failure → `dispatched=False` with `gate_lease_acquisition_failed`.

10. **Preserved invariants (gap 10).** Fallback rebuild via `build_fallback_request()` unchanged (wraps `rebuild_fallback_payload`). Credential-free payload scan preserved. No repository handle. No `max_turns=1`.

## Artifacts And Evidence

| Artifact | Lines | Changes from pre-repair |
|---|---|---|
| `services/api/app/protocol_workflow/runtime/harness.py` | 1309 (was 731) | Rewritten: registry-bound role policy, full node/skill/artifact binding, selected region + sensitivity ceiling, logical artifact ref validation, unified workload gate at common boundary, AdapterOutcome typed signal, preflight protocol, session_id/lease forwarding, typed output receipt validation, accurate dispatched semantics |
| `services/api/app/protocol_workflow/runtime/adapters/direct_api.py` | 183 (was 141) | Mandatory `probe_fn`, pure `preflight()`, `dispatch(request, *, session_id, lease)`, typed receipt with `output_artifact_ref`/`output_schema_ref` |
| `services/api/app/protocol_workflow/runtime/adapters/local_omlx.py` | 195 (was 308) | Simplified: gate policy moved to harness; mandatory `probe_fn`, pure `preflight()`, lease forwarding from dispatcher, typed receipt. `OcrRoleGateMismatchError` retained as deprecated import-compat alias |
| `tests/protocol_v3/test_harness_policy.py` | 1993 (was 2109) | Rewritten: all `build_request` calls use `role_entry` + `selected_region`; all fakes return `output_artifact_ref`/`output_schema_ref`; 113 tests covering all 10 gaps |

## Commands And Observations

| Command | Observation |
|---|---|
| `PYTHONPATH="services/api:packages/contracts:." python3 -m pytest tests/protocol_v3/test_harness_policy.py -q` | **113 passed** in 0.40s |
| `PYTHONPATH="services/api:packages/contracts:." python3 -m pytest tests/protocol_v3/ -q` (full suite) | **814 passed** in 7.53s — no regressions |
| `uv tool run ruff check <owned files>` | **All checks passed!** (4 auto-fix + 4 manual BLE001 noqa) |
| `python3 -m py_compile <owned files>` | OK (Python 3.9.6) |
| `python3.12 -m py_compile <owned files>` | OK (Python 3.12.13) |
| `git diff --name-only` | Zero tracked file changes |
| End-to-end gated dispatch verification (manual) | Translation succeeds when gate matches Hy-MT2; lease forwarded to dispatch_fn; receipt validated |

**Test coverage highlights (113 tests):**
- `TestArtifactRef` (10): valid, empty, malformed sha, control char, oversized, absolute path, home path, traversal, uppercase, namespaced.
- `TestDispatchReceipt` (5): valid, empty session, malformed sha, empty artifact ref, empty schema ref.
- `TestBuildRequestPolicy` (18): valid, role_id mismatch, provider/model mismatch with target profile, thinking-frozen, skill_id mismatch, input/output schema mismatch, artifact hash substitution/omission, tool outside skill (incl. empty skill), credential in snippet, selected region required/outside node/outside role, sensitivity exceeds ceiling, payload credential-free, provider_session_id carried.
- `TestProbePolicy` (4): success cached, failure cached, raising cached, clear.
- `TestDirectApiDispatch` (5): valid typed receipt, probe failure, preflight mismatch, dispatch exception, receipt schema mismatch.
- `TestUnifiedWorkloadGate` (10): translation succeeds with matching gate, Paddle OCR fails with GLM gate, OCR no-gate-model fails, OCR succeeds when matched, gate required for translation, lease factory required for OCR, lease released on exception, lease acquisition failure dispatched=False, LLM no gate required, WorkloadGateError is policy error.
- `TestFallback` (5), `TestNoDuplicateDispatch` (2), `TestReceiptIdentity` (2).
- Codex/Omp command plan + dispatch (15), cross-product adversarial (20), mandatory probe injection (2).

## Blockers Or Missing Environment

**No blocker for this repair.** Two environment notes (same as baseline):
1. **Ruff** via `uv tool run ruff` (`/Users/smkzw/.local/bin/uv`). Not a CI gate.
2. **Test invocation** requires `PYTHONPATH="services/api:packages/contracts:."`.

## Rerun Requests Or Next Step

**Worker_02 recovery is complete and verified. No rerun needed for owned files.**

**Remaining interface work for worker_03 (NOT my files — documented, not modified):**

1. **`CodexAppAdapter` and `OmpCliAdapter` must add `preflight()`.** The dispatcher now uses `getattr(adapter, 'preflight', None)` for backward compatibility, but gap 6 requires every adapter to expose a pure preflight. Without it, identity/provider/model mismatches are caught only at dispatch time (`dispatch_exception` with `dispatched=True`) instead of pre-probe (`dispatched=False`).

2. **`CodexAppAdapter.dispatch()` and `OmpCliAdapter.dispatch()` must construct `DispatchReceipt` with `output_artifact_ref` and `output_schema_ref`** (gap 8). Currently their receipt construction raises `TypeError` because the two new required fields are missing. This surfaces as `dispatch_exception`. The transport fakes already return these fields; only the adapter receipt construction needs updating.

3. **`CodexAppAdapter.dispatch()` and `OmpCliAdapter.dispatch()` should accept `lease=None`** kwarg for protocol uniformity (currently they accept only `session_id`). Not strictly necessary since LLM/support roles are non-gated, but protocol coherence requires it.

**For Codex acceptance:** verify the registry-bound role policy matches the intended authority flow (RoleEntry from loader is the sole thinking/effort/sensitivity authority); confirm the unified gate policy at the harness boundary is the correct integration point (not adapter-local); decide whether `_dispatch_gated` holding the lease via `_enter_context`/`_exit_context` is sufficient or whether a full `with` block is preferred (current approach is equivalent and avoids try/except nesting); do NOT claim final READY (per instructions).
