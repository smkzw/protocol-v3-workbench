All work is complete and verified. Here is the full report.

---

# Execution Output: mw_protocol_v3_phase1_task17_20260811 - worker_02

## Boundary And Context Check

**Workspace root:** `.` (`protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313`). Work confined to assigned boundaries.

**Read set consumed (authorized):**
- `AGENTS.md`, `context/mw_protocol_v3_phase1_task17_20260811_execution_context.md`, `plans/codex_execution_mw_protocol_v3_phase1_task17_20260811.md`
- Parent Task 1.7 context: `context/mw_protocol_v3_phase1_task17_20260811_context.md`
- Approved design §17/§18: `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md:710-805`
- Accepted Task 1.6 runtime: `services/api/app/protocol_workflow/runtime/{idempotency,reservations,__init__}.py`
- Worker 01's artifacts: `services/api/app/protocol_workflow/registries/{loader,__init__}.py`, `config/medical_writing/protocol_v3/{role_registry,skill_registry}.json`
- Shared gate contract: `services/api/app/omlx_workload_gate_client.py`
- Canonical contract: `packages/contracts/workbench_contracts/protocol_v3.py` (`NodeExecutionContract`, `SkillDefinition`, `ReasoningEffort`, `SensitivityTier`, `SideEffectKind`, `ProtocolV3Model`)
- Worker 01 report: `runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_01.md`
- Convention reference: `tests/protocol_v3/test_registry_loading.py`, `test_execution_reservations.py`

**Boundary verification (post-work):** `git status` shows only my 5 authorized artifacts as untracked. `git diff` shows zero tracked file changes. No medical-monitoring diff. No production path, no service started, no provider/model/OCR/translation/gate-database invoked, no credential handled.

## Work Performed

Implemented Work Item 2: the Harness policy boundary plus Direct API and local oMLX adapters with deterministic fake-backed policy tests.

**Key design decisions (evidence-backed):**

1. **Typed immutable artifact contracts.** `ArtifactRef` (content-addressed ref + sha256 + bounded snippet ≤8192 chars), `HarnessDispatchRequest` (policy-validated minimal input), `DispatchReceipt` (typed receipt owning observed identity), `HarnessResult` (terminal classification with `dispatched` flag), and `FallbackInput` (recorded evidence for fallback authorization). All are frozen dataclasses with structural validation in `__post_init__`. The harness never accepts repositories, credentials, raw previous-provider scratchpads, session transcripts or arbitrary filesystem paths.

2. **Policy-before-dispatch.** `build_request()` validates artifact-only input + credential scan → role/skill/schema/thinking consistency → provider/region/sensitivity allowlist → allowed tools/paths subset-of-skill. A policy violation raises `HarnessPolicyError` and produces **zero** adapter invocations. The `HarnessDispatcher.dispatch()` adds a defence-in-depth credential scan on the final payload.

3. **Probe-once-per-identity.** `ProbePolicy` caches only a successful probe; a failed probe is recorded as a negative result and never retried automatically. Only `ProbePolicy.clear()` (explicit policy reconciliation) removes a cached failure. This matches the accepted contract: "Require a first-use connectivity probe per adapter identity; cache only a successful probe."

4. **No latency re-dispatch, no `max_turns=1`.** The harness dispatches exactly once per validated request. Fallback requires a recorded eligible terminal/unavailable result (`failed`/`unknown_outcome`/`unavailable`) plus an error code, and re-builds minimal input from canonical artifact refs via the Task 1.6 `rebuild_fallback_payload` (forbidden fragments discarded). Neither adapter sets `max_turns=1`.

5. **Direct API adapter.** Injected deterministic callable (`dispatch_fn` + optional `probe_fn`). Defence-in-depth routing check: refuses a request whose declared provider/model doesn't match the adapter identity. The receipt owns observed identity (runtime authority, never registry text).

6. **Local oMLX adapter + gate lease.** Translation work acquires the shared workload-gate lease before the injected callable runs (injected `lease_factory` context manager; deterministic fake when no factory supplied). The lease is released in a `finally` even on dispatch exception. Lease kind is derived from the role (`ocr` vs `translation` bucket).

7. **PaddleOCR fail-closed.** `_ensure_ocr_role_gate_consistency()` compares the gate's current OCR model against the declared role model *before invocation*. When the gate selects `GLM-OCR-bf16` and the declared model is `PaddleOCR-VL-1.6`, the adapter raises `OcrRoleGateMismatchError` (a stable `HarnessPolicyError` subclass) — no GLM output is ever labeled Paddle. The adapter never edits the shared gate.

8. **Credential scanner alignment.** The harness `_CREDENTIAL_VALUE_RE` mirrors the accepted registry loader pattern exactly (Bearer, PEM headers, `sk-` prefix, `AKIA` AWS keys). It deliberately does NOT match arbitrary hex strings so legitimate sha256 content hashes are not false-positives.

9. **Reservation composition, not duplication.** The harness composes with Task 1.6 `ReservationCoordinator` via the injected transport boundary; it does not re-implement the reservation state machine. `build_fallback_request()` delegates to `runtime.idempotency.rebuild_fallback_payload` and wraps `FallbackSafetyViolation` as `HarnessFallbackError`.

## Artifacts And Evidence

| Artifact | Lines | Purpose |
|---|---|---|
| `services/api/app/protocol_workflow/runtime/harness.py` | 733 | Harness policy boundary: typed immutable contracts, `build_request()`, `build_fallback_request()`, `ProbePolicy`, `HarnessDispatcher`, credential scanner |
| `services/api/app/protocol_workflow/runtime/adapters/__init__.py` | 33 | Adapters package public surface re-export |
| `services/api/app/protocol_workflow/runtime/adapters/direct_api.py` | 141 | Direct API adapter (injected deterministic callable, first-use probe, defence-in-depth routing) |
| `services/api/app/protocol_workflow/runtime/adapters/local_omlx.py` | 308 | Local oMLX adapter (gate lease/heartbeat/release, PaddleOCR fail-closed before invocation, no relabel) |
| `tests/protocol_v3/test_harness_policy.py` | 1001 | 45 deterministic offline tests (direct/oMLX portions) |

**Test coverage (45 tests):**
- `TestArtifactRef` (5): valid ref, empty ref, malformed sha, control char, oversized snippet.
- `TestDispatchReceipt` (3): valid receipt, empty session, malformed output sha.
- `TestBuildRequestPolicy` (10): valid build, provider outside allowlist, thinking-frozen role with effort, credential key/value in snippet, credential bearer in snippet, contract tool/path outside skill closed set, empty artifacts, duplicate refs, payload credential-free.
- `TestProbePolicy` (4): first-use success cached, failed probe cached, raising probe cached, clear removes cached failure.
- `TestDirectApiDispatch` (5): valid typed receipt, probe failure prevents dispatch, credential in payload prevents dispatch, dispatch exception, provider mismatch.
- `TestLocalOmlxDispatch` (8): valid translation lease acquire/release, PaddleOCR fail-closed when gate=GLM, OCR no-gate-model fail-closed, OCR succeeds when gate matches, mismatch error is stable policy error, fake lease without factory, provider mismatch, lease released on exception.
- `TestFallback` (6): valid rebuild discards forbidden fragments, ineligible terminal state, no error code, restricted without target, target outside allowlist, credential in rebuilt payload.
- `TestNoDuplicateDispatch` (2): policy failure zero dispatches, probe failure no retry.
- `TestReceiptIdentity` (2): direct API observed identity, oMLX observed identity not registry text.

## Commands And Observations

| Command | Observation |
|---|---|
| `PYTHONPATH="services/api:packages/contracts:." python3 -m pytest tests/protocol_v3/test_harness_policy.py -v` | **45 passed** in 0.38s |
| `PYTHONPATH="services/api:packages/contracts:." python3 -m pytest tests/protocol_v3/ -q` (full suite regression) | **746 passed** in 5.92s — no regressions (701 from worker_01 baseline + 45 new) |
| `uv tool run ruff check --fix <owned files>` | 24 auto-fixes applied; then **All checks passed!** after 2 manual fixes (SIM102 nested-if, F841 unused var) |
| `python3.12 -m py_compile <owned .py files>` | `py_compile OK` — all 5 files compile under Python 3.12.13 |
| `git diff --name-only` | Zero tracked file changes |
| `git status --porcelain` | Only authorized artifacts untracked; no tracked file modified; no medical-monitoring diff |

**Test invocation note:** `PYTHONPATH="services/api:packages/contracts:."` is required, matching the accepted convention used by all sibling tests (worker_01 confirmed the same requirement).

## Blockers Or Missing Environment

**No blocker for this work item.** Two environment notes for Codex:

1. **Ruff is not installed in the system Python.** I ran ruff 0.16.2 via `uv tool run ruff` (`/Users/smkzw/.local/bin/uv`), same as worker_01. There is no `ruff.toml`/`[tool.ruff]` config in the repo.

2. **Test invocation requires `PYTHONPATH="services/api:packages/contracts:."`.** This is a pre-existing condition documented by worker_01; my tests follow the accepted convention.

3. **`test_harness_policy.py` is shared with worker_03.** Worker 03 owns the Codex/OMP CLI adapter contract portions and will append their tests to this file. My helpers/fakes (`_FakeDirectApi`, `_FakeOmlxGate`, `_FakeOmlxDispatch`, `_node_contract`, `_skill`, `_artifact`) are kept generic and documented for reuse. Worker 03 should not modify my test classes.

## Rerun Requests Or Next Step

**Work item 2 is complete and verified.** No rerun needed.

**For Codex acceptance:**
- Verify the PaddleOCR fail-closed policy matches the intended gate reconciliation semantics (the adapter fails closed *before invocation* when gate OCR model ≠ declared model; this is a deterministic policy error, not an unconditional block — when the gate reconciles to Paddle, the OCR role proceeds).
- Confirm the `HarnessDispatcher` is the correct integration point for the Task 1.6 `ReservationCoordinator` (the harness validates and builds the request; the coordinator owns the reservation state machine; the adapter is the injected transport). A future task may wire them together via an `ExecutionTransport` shim that wraps `HarnessDispatcher.dispatch`.
- Decide whether `test_harness_policy.py` should be split into separate files for worker_02 (direct/oMLX) and worker_03 (Codex/OMP), or kept as one file with shared helpers. The current design uses one file per the assignment ("the direct/oMLX portions of `tests/protocol_v3/test_harness_policy.py`").

**Adjacent work (other workers, not mine):** worker_03 owns Codex/OMP CLI adapter contracts and adversarial integration tests. My adapters and harness are dependency-ready: `TransportAdapter` is a `Protocol` any adapter can implement, and `ProbePolicy`/`HarnessDispatcher` work with any adapter identity.
