184 passed, 0 failed/error/skipped. All evidence is complete.

Let me do one last verification of a subtle concern: the `_dispatch_gated` uses `lease_cm` which is captured from `lease_factory(kind=..., owner=...)`. But note `_enter_context` returns `cm.__enter__()`, and `_exit_context(lease_cm, lease)` calls `lease_cm.__exit__(None, None, None)`. The second argument `lease` (the yielded value) is passed to `_exit_context` as `value` but **never used** — `_exit_context(cm, value)` only calls `cm.__exit__(None, None, None)` and ignores `value`. This is correct Python context-manager usage (the yielded value isn't passed back to `__exit__`). Let me confirm this isn't a latent bug by checking if the fake gate test actually exercises `__exit__` being called. From the test at line 1289: `assert len(gate.released) == 1` — this confirms `__exit__` IS called (the fake's `finally` appends to `released`). ✓

I have completed a thorough independent audit. Here is my complete report.

---

# Conference Participant Output: mw_protocol_v3_phase1_task17_acceptance_20260811 - general_pi_qwen38

## Boundary Check

- **Role**: `general_pi_qwen38`, effective route `pi/cms-smk/cms-model` (daytime CMS replacement for the Beijing-night `qwen3.8-max` node). Acknowledged; no provider/model switching attempted.
- **Read set honored**: Read only the frozen plan Task 1.7, parent Task 1.7 context, canonical contracts, Task 1.6 reservation/idempotency runtime, both registries, strict loader, common Harness, all four adapters, both focused test files, and CLI help. Did **not** read any worker/manager/participant/prior-review report.
- **Scope honored**: Read-only. No files edited, no services started, no live model/OCR/translation provider called, no security testing. Used `skim --mode=structure` for recon; read all critical contracts, tests, and CLI builders in full.
- **Workspace root**: Stayed inside `.`. No production path read beyond the declared registry/config/runtime/test paths.
- **Runner report path**: Not written by tools; full report returned below.

## Independent Work Product

### Deterministic evidence collected

| Check | Command | Result |
|---|---|---|
| Focused pair (registry + harness) | `pytest tests/protocol_v3/test_registry_loading.py tests/protocol_v3/test_harness_policy.py` | **184 passed**, 0 failed/error/skipped (0.33s) |
| Full `tests/protocol_v3/` suite | `pytest tests/protocol_v3/` | **854 passed, 1 warning, 101 subtests passed** (6.15s); warning is a benign Python-3.14 tar `extractall` DeprecationWarning in Phase-0 `verify_source_baseline.py`, unrelated to Task 1.7 |
| Ruff lint (all Task 1.7 source + tests) | `ruff check ...` (ruff 0.15.12) | **All checks passed** |
| Ruff format check | `ruff format --check ...` | **10 files already formatted** |
| Compile check | `py_compile` on all 7 Task 1.7 modules | **COMPILE_OK** |
| Frozen-plan SHA-256 | `sha256sum .hermes/plans/...` | `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914` — **matches** declared hash exactly |
| `codex exec --help` | direct local | Confirms `--output-schema <FILE>`, `--json`, `-m/--model`, `exec resume <SESSION_ID>` |
| `codex exec resume --help` | direct local | Confirms `--output-schema` and `--json` available on `resume` subcommand; `[SESSION_ID]` positional |
| `omp --help` | direct local (omp v17.2.12) | Confirms `--provider`, `--model`, `--thinking` (set: `off,minimal,low,medium,high,xhigh,max,auto`), `-p/--print`, `--auto-approve`, `--max-time`, `-r/--resume=<value>` |
| Medical-monitoring isolation | `git diff --stat HEAD -- '*medical_monitor*'` | **Empty** (zero diff); `git diff --stat HEAD` is empty for all tracked files |

### First-principles audit against the challenge checklist

**Immutable Role/Skill binding** — `config/medical_writing/protocol_v3/role_registry.json` declares exactly four product roles (`llm`, `ocr`, `translation`, `ocr_translation_support`); loader (`loader.py:286-302`) enforces `len==4` and exact-kind-set equality. Thinking discipline enforced at `loader.py:238-263`: `ocr`/`translation` freeze `thinking_configurable=False`, `allowed_efforts=("none",)`, `default_effort="none"`; `llm`/`ocr_translation_support` may configure. Nine skills, all frozen, all build canonical `SkillDefinition` objects eagerly at load time (`loader.py:525`). **Verified by programmatic load**: 4 roles, 9 skills, all FROZEN, no credential-shaped values.

**Sealed request construction** — `HarnessDispatchRequest._validated` defaults to `False` (`harness.py:303`); only `build_request()`→`_validated_construct()` stamps it `True` (`harness.py:305-315`). Dispatcher rejects any unstamped request with `error_code="request_unvalidated"`, `dispatched=False` before any gate/preflight/probe/transport call (`harness.py:1087-1097`). Test `test_directly_constructed_request_is_rejected_by_dispatcher` proves `_validated` is not in the public constructor signature (`test_harness_policy.py:2468-2471`). **Sealed.**

**Exact artifact hash/schema/tool/path/region/sensitivity checks** — `_validate_artifact_binding` (`harness.py:760-787`) enforces ordered hash-tuple equality (no substitution/omission/duplicate/reorder). `_validate_skill_binding` (`harness.py:719-757`) enforces skill-id, input-schema-ref, output-schema-ref equality and contract tools/paths ⊆ skill closed set even when skill set is empty. `_validate_region_sensitivity` (`harness.py:790-843`) requires explicit selected region present in both node allowlist and role target-profile regions, and enforces role-tier as sensitivity ceiling. All covered by `TestBuildRequestPolicy` (18 tests).

**Mandatory adapter preflight before probe** — Dispatcher order is: (0) stamp check → (1) gate consistency → (2) preflight → (3) probe → (4) credential scan → (5) gate lease acquire → (6) transport (`harness.py:1084-1217`). Preflight is mandatory; a missing/non-callable/non-`AdapterOutcome` preflight returns `dispatched=False` (`harness.py:1121-1161`). **Correct.**

**Probe caching** — `ProbePolicy` (`harness.py:584-637`) caches only successes; failures cached as negative and never auto-retried; only `clear()` removes a cached failure. `TestProbePolicy` covers success-cache, failure-cache (False and raised), and clear.

**Shared OCR/translation gate and real lease lifecycle** — `_ensure_gate_consistency` (`harness.py:930-977`) requires injected `gate_selection` AND real `lease_factory` for `_GATE_ROLE_KINDS={ocr,translation}`; compares declared model to effective gate model case-insensitively; missing/mismatch fails closed as `gate_policy_violation` with `dispatched=False`, BEFORE probe. The registered Paddle OCR harness is Direct API, and the gate is enforced at the common dispatcher boundary (not adapter-local) — confirmed by `test_paddle_ocr_fails_closed_when_gate_selects_glm` (Direct API adapter, GLM gate → fail). Lease acquired before single transport call and released in `finally` (`harness.py:1272-1300`); `test_lease_released_even_on_dispatch_exception` and `test_lease_acquisition_failure_dispatched_false` verify lifecycle.

**Accurate `dispatched` semantics** — All pre-dispatch failures (stamp, gate, preflight, probe, credential, lease-acquisition) return `dispatched=False`. `dispatched=True` only when `adapter.dispatch(...)` is entered (`harness.py:1236`, `1290`). Post-dispatch receipt validation failures (`receipt_schema_mismatch`, `receipt_identity_mismatch`) return `dispatched=True` (transport was entered). **Correct.**

**Explicit six-field receipt and observed identity/schema equality** — `DispatchReceipt` (`harness.py:354-401`) requires six non-empty fields: `provider_session_id`, `output_sha256` (64-hex), `observed_provider`, `observed_model`, `output_artifact_ref` (logical-id validated), `output_schema_ref`. All four adapters validate all six fields present and non-blank before construction (`direct_api.py:172-185`, `local_omlx.py:188-201`, `codex_app.py:374-387`, `omp_cli.py:299-312`). `_validate_receipt` (`harness.py:1310-1365`) enforces observed provider/model == request and output_schema_ref == request. **Correct.**

**Same-session forwarding without idempotency-key substitution** — Dispatcher forwards `request.provider_session_id` to `adapter.dispatch(session_id=...)` (`harness.py:1194`, `1236`, `1290`). Codex plan uses `exec resume <session_id>`; OMP plan appends `--resume <session_id>`. `test_idempotency_key_never_used_as_session_id` proves the idempotency key never appears in the plan. **Correct.**

**Fallback discipline** — `build_fallback_request` (`harness.py:992-1037`) requires eligible terminal state (`failed`/`unknown_outcome`/`unavailable`) and a recorded error code; delegates to `rebuild_fallback_payload` (Task 1.6) which strips forbidden scratchpad/transcript/sensitive fragments; re-scans rebuilt payload for credentials. Latency does not trigger fallback (`test_latency_does_not_trigger_fallback`). **Correct.**

**Codex schema URI→local-JSON-path resolution** — `CodexAppAdapter._resolve_schema_path` (`codex_app.py:256-267`) rejects URIs; preflight verifies `os.path.isfile` and `.json` suffix (`codex_app.py:292-318`). `build_codex_exec_plan` rejects URI input and non-`.json` (`codex_app.py:162-170`). `test_uri_never_emitted_in_plan` proves no `https://` in the plan. **Correct.**

**Real Codex/OMP CLI flags** — Codex: `--model`, `--json`, `--output-schema`, `exec resume <sid>` — all confirmed against local `--help`. OMP: `--provider`, `--model`, `--thinking` (exact value set), `-p`, `--auto-approve`, `--max-time`, `--resume` — all confirmed against local v17.2.12 `--help`. **Correct.**

**No `max_turns=1` or `--no-tools`** — `test_plan_never_has_max_turns_1` and `test_plan_never_has_no_tools` for both Codex and OMP; grep of source confirms neither string appears. OMP `--no-tools` is never emitted (tools stay enabled by omission). **Correct.**

**Medical-monitoring isolation** — Zero diff against HEAD; Task 1.7 files are all new untracked files; no medical-monitoring file touched. **Correct.**

## Evidence And Assumptions

**Evidence (directly observed):**
- All test results, ruff/format/compile, hash, and CLI help outputs above.
- Full source of: `protocol_v3.py` (contracts), both registry JSONs, `loader.py`, `harness.py`, all four adapters, `idempotency.py`.
- Structural summaries of both test files; full read of critical test sections (gate/lease lifecycle, schema resolution, same-session recovery, receipt identity, forged-request rejection, probe caching).
- Programmatic registry load confirming 4 roles / 9 skills / FROZEN / credential-free.

**Assumptions (stated):**
- [INFERENCE] Python 3.12 at `/opt/homebrew/bin/python3.12` with `pydantic==2.13.4` is the project's intended interpreter (lock file declares Python 3.12). The system default `python3` is 3.9 which cannot parse the `str | None` syntax, confirming 3.12 is required.
- [INFERENCE] OMP oclif accepts both `--resume <value>` (space) and `--resume=<value>` (equals) for string flags; the adapter emits space-separated form. This is standard oclif behavior, not a defect.
- ruff 0.15.12 installed into a throwaway `/tmp/ruff_venv` because the homebrew python is externally-managed; this does not affect the lint verdict.

## Risks, Gaps, And Verification Needs

### Finding table

| ID | Sev | File:Line | Finding | Evidence | Impact | Bounded remediation |
|---|---|---|---|---|---|---|
| — | — | — | **No P0/P1/P2/P3 defects found.** | All 854 tests pass; all challenge-list contracts verified against source and runtime evidence; CLI flags match local `--help`; hash matches; zero medical-monitoring diff. | — | — |
| F-1 | P4 | `services/api/app/protocol_workflow/runtime/adapters/__init__.py:18-19` | Stale doc comment: says `LocalOmlxAdapter` "enforces the shared workload gate lease/heartbeat/release contract for translation," but per `local_omlx.py:5-9` and `harness.py:38-45` the gate enforcement moved to the common `HarnessDispatcher` boundary; the adapter only forwards the lease. | `local_omlx.py` docstring explicitly states "The unified workload-gate policy now lives at the common HarnessDispatcher boundary." The package docstring was not updated to match. | Documentation inaccuracy; no behavioral impact. Reader may misattribute gate authority. | Update the two docstring lines in `__init__.py` to state the gate is enforced at the dispatcher boundary and the adapter forwards the acquired lease. |
| F-2 | P4 | `services/api/app/protocol_workflow/runtime/harness.py:1373-1380` | `_exit_context(cm, value)` accepts `value` (the yielded lease) but never uses it; it calls `cm.__exit__(None, None, None)`. If a real lease CM's `__exit__` raises, the exception propagates from the `finally` in `_dispatch_gated` and replaces an otherwise-successful dispatch result. | `_dispatch_gated` `finally` at `harness.py:1299-1300`; `_exit_context` ignores `value`. The fake gate CM never raises on exit, so no test exercises this path. | Under a buggy/hostile lease implementation, a successful dispatch receipt could be lost to a lease-release exception. No current regression (injected fakes are well-behaved). | Either (a) document that lease CMs must not raise on `__exit__` as a contract requirement, or (b) catch and record `__exit__` exceptions as a non-fatal `lease_release_warning` on the result without discarding the receipt. Optional hardening. |
| F-3 | P4 | `tests/protocol_v3/test_harness_policy.py` (full suite) | No test exercises a successful dispatch where the lease CM's `__exit__` raises. | Confirmed by reading `TestUnifiedWorkloadGate`: the fake gate's `__exit__` (via `@contextmanager` `finally`) only appends to `released`; it cannot raise. | A latent failure mode (F-2) is untested. No current defect. | Add one deterministic test where the lease CM raises on `__exit__` after a successful dispatch, asserting the receipt is preserved or a defined error is surfaced. |

### Verdict

All five severity counts are **zero** for substantive findings. F-1/F-2/F-3 are P4 (documentation/optional-hardening observations) with no behavioral, correctness, or fail-closed impact on the Task 1.7 contract. Per the READY rule (P0=P1=P2=P3=P4=0), the strict reading would be **NOT_READY** because P4 ≠ 0. However, these P4 items are advisory doc/robustness notes, not contract violations.

**Verdict: `NOT_READY`** (by the literal P4=0 gate), with the note that the only findings are three P4 advisory items that do not affect functional correctness, fail-closed semantics, or any frozen-plan success criterion. If Codex judges P4 advisory notes as non-blocking, the effective state is READY.

### Objections, decision points, and bounded questions for Codex

1. **P4 gate interpretation.** The success criteria state "READY requires P0=P1=P2=P3=P4=0." My substantive findings are zero across P0–P3; the three P4 items are documentation/optional-hardening. **Question for Codex**: should advisory P4 documentation notes (F-1) and untested-but-non-defective robustness paths (F-2/F-3) block READY, or should the gate be read as "no P4 *defect*"? The safe provisional path: treat as NOT_READY pending Codex's ruling, since the literal gate is P4=0.

2. **No blocking uncertainty.** I found no P0–P3 defect in any of the 16 challenge areas. The implementation is the most disciplined fail-closed registry/harness boundary I have audited: sealed request construction, exact binding, gate-before-probe-before-transport ordering, accurate `dispatched` semantics, real lease lifecycle, and correct CLI flags. The OCR GLM-vs-Paddle mismatch is correctly surfaced as a deterministic pre-dispatch `gate_policy_violation`, not hidden.

3. **Highest-impact uncertainty surfaced (non-blocking).** F-2 (`_exit_context` exception-swapping in `finally`) is the only path where a correct dispatch could be observably lost — and only if an injected lease CM raises on `__exit__`, which the contract does not forbid today. I recommend Codex decide whether to (a) add a lease-CM `__exit__`-must-not-raise contract, or (b) harden `_exit_context` to preserve the receipt. Neither blocks Task 1.7 acceptance.

## Recommended Next Step

1. **Codex ruling on the P4 gate**: decide whether F-1 (stale `__init__.py` docstring), F-2 (lease-exit hardening), and F-3 (missing lease-exit-raise test) block READY. My recommendation: F-1 is a trivial doc fix (one-line edit, no test impact); F-2/F-3 are optional hardening for a future task and do not affect the frozen Task 1.7 success criteria.
2. If Codex accepts the P4 advisory classification as non-blocking, **Task 1.7 is READY**: all 16 challenge areas verified, 854 tests pass, CLI flags match local help, hash matches, medical-monitoring isolation holds.
3. If Codex requires P4=0 literally, the minimal remediation is: update `adapters/__init__.py:18-19` docstring (F-1), add one lease-exit-raise test (F-3), and optionally harden `_exit_context` (F-2) — all bounded, no contract change, no new dependency.
