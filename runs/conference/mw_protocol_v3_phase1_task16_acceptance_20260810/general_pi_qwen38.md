All probes resolved. Two reproducible defects plus one verified probe artifact. Assembling the final report.

# Conference Participant Output: mw_protocol_v3_phase1_task16_acceptance_20260810 - general_pi_qwen38

## Boundary Check

- Workspace root `.` only; no production paths touched. Read-only throughout: zero files written or edited; all probes ran in-process via the eval kernel (no test files created, no cache writes — `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`).
- Source packet limited to the declared set: frozen plan Task 1.6 (`.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md:651-671`), design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md` §17.2/§18 (lines 710-789), `packages/contracts/workbench_contracts/protocol_v3.py`, `services/api/app/protocol_workflow/runtime/{reservations,idempotency,__init__}.py`, `ports/repositories.py` (reservation port + typed errors), `storage/memory.py` (`InMemoryExecutionReservationRepository`), the two named test files, plus the in-scope dependency `canonical/hashing.py::canonical_json`.
- Did not read worker/manager/prior-review/metrics/run/raw-log outputs, other participant outputs, or AGENTS-adjacent review artifacts. Did not run directory-wide Protocol v3 tests, security/hygiene/source-baseline tests, services, or live AI.
- Executed exactly the permitted commands: `tests/protocol_v3/test_execution_reservations.py`, `tests/protocol_v3/test_repository_contract.py`, and narrower deterministic functional probes (in-memory, no network, deterministic timestamps).
- Report returned as text for runner persistence; `runs/conference/.../general_pi_qwen38.md` not written by me.

## Independent Work Product

### Baseline verification (executed, not assumed)

| Check | Result |
|---|---|
| Frozen plan SHA-256 | `fa99fbd3…d54914` — matches declared anchor exactly |
| `test_execution_reservations.py` | 35 passed (0.82 s) |
| `test_repository_contract.py` | 72 passed (0.38 s) |
| `PYTHONPATH` | repo root + `services/api` required; bare root fails collection (`ModuleNotFoundError: app`) |

Environment: `/usr/bin/python3` 3.9.6, pytest 8.4.2, pydantic 2.13.3. No venv in workspace.

### Claim-by-claim falsification attempt (objective → evidence)

1. **预留先行 (persist-before-preflight, atomic RUNNING before dispatch)** — could not falsify. Probes reproduce the pinned ordering observation at repo level: shell persisted RESERVED/0 before `preflight`; `transition(RESERVED→RUNNING)` is the only path that increments `transport_attempts` (repo enforces `+1` exactly on that edge, `memory.py:990-1002`); preflight exception → FAILED with `transport_attempts=0` and zero dispatches (probe G5). Two-coordinator race: one dispatch, loser fails closed (pinned test + H1).
2. **终态不确定恢复 (terminal-unknown recovery)** — could not falsify the core. Timeout/exception/no-receipt/non-dict-receipt all classify `UNKNOWN_OUTCOME` with an error code and no output sha (G3, G4, pinned §3). Same-session recovery completes the same id/attempt with zero dispatch; double-recovery rejected (`RUNNING→COMPLETED`/`COMPLETED→COMPLETED` not legal, probe B3b); wrong provider session on UNKNOWN→COMPLETED rejected at repo layer (`memory.py:1015-1025`, B1); invalid recovered sha revalidated by full `model_validate` and rejected, row unchanged (B3); crash-window RUNNING row (terminal persist failure) reconcilable via `recover_unknown` with zero new dispatch (B7) — exactly the success criterion. `find_unresolved` returns RESERVED+RUNNING+UNKNOWN, project-scoped (pinned + probe A6).
3. **显式 retry decision 追加谱系** — could not falsify the pinned surface. Duplicate decision id idempotent (same row, one dispatch; verified even across distinct coordinator instances after winner reaches terminal — I3); distinct decisions append attempts 2, 3 with identical `input_sha256` and immutable attempt 1 (pinned + C4); concurrent distinct decisions on two coordinators allocate distinct attempts (C4); retry without prior attempt rejected (C2); blank reason/decision rejected (C3); replay of an in-flight decision row fails closed (instrumented rerun — see corrected probe below).
4. **fallback 最小重打包** — partially falsified. Forbidden fragments never forwarded (params-only, key-at-any-depth, deep list nesting D7 rejected, value-mention correctly allowed D6); defensive deep copy confirmed (D8); authorization is allowlist membership only, no string heuristics. **But finding F1 below contradicts the documented RESTRICTED policy.**
5. **Contract transitions closed and revalidated** — could not falsify. Repo state machine is closed (`RESERVED→{RUNNING,FAILED}`, `RUNNING→{COMPLETED,FAILED,UNKNOWN}`, `UNKNOWN→{COMPLETED}`, terminals absorbing, `memory.py:955-970`); every transition re-runs full pydantic `model_validate` on the merged record before commit (`memory.py:1026-1041`), so invalid terminal data cannot persist (B3, pinned revalidation test); `transport_attempts` can never decrease (`memory.py:983-989`).

**Verdict:** no P0/P1. Two P3 findings (one doc-vs-code divergence with a dead-end recovery state; one documented-vs-implemented policy gap on RESTRICTED fallback) and three P4/informational items. Per the stated rule "READY requires no open P0-P4", I do **not** return READY; I return the counterexamples and minimal repairs below. If Codex reclassifies the P4s as informational (my recommendation), closure depends only on the two P3s.

### Findings

**F1 — P3 — `rebuild_fallback_payload` does not fail closed for RESTRICTED content without an explicit target (docstring/code contradiction; executable counterexample).**
`idempotency.py:204-208` documents: "RESTRICTED content requires the target provider/region to be present in the allowlist; if no target is declared or the target is outside the allowlist, the re-builder fails closed." `_enforce_safety_policy` (lines 273-305) only rejects empty allowlists for non-PUBLIC tiers and explicit targets outside the allowlist — tier is otherwise unused. Counterexample (executed):
```python
rebuild_fallback_payload(
    canonical_source={"prompt": "generate", "source_text": "restricted IB content"},
    sensitivity_tier=SensitivityTier.RESTRICTED,
    allowed_providers=("deepseek",), allowed_regions=("cn",),
)   # -> returns {"prompt": ..., "source_text": ...}; docstring promises FallbackSafetyViolation
```
Also verified: RESTRICTED with only `target_provider` set (region omitted) likewise returns a payload (D2). The pinned suite only covers explicit-target-outside-allowlist (`test_fallback_fails_closed_on_unmovable_forbidden_material`), so this gap is unguarded. Significance: success criterion 4 requires fallback targets authorized "only through explicit provider/region allowlists"; with no target declared, a RESTRICTED payload is handed back for dispatch to whatever implicit target the (not-yet-existing) fallback orchestrator picks — policy decision delegated to the caller instead of enforced. Minimal repair (matches documented policy, ~6 lines in `_enforce_safety_policy`):
```python
if sensitivity_tier is SensitivityTier.RESTRICTED:
    if target_provider is None or target_region is None:
        raise FallbackSafetyViolation(
            "restricted content requires an explicit target provider and region")
```
plus one regression test (RESTRICTED, non-empty allowlists, no target → `FallbackSafetyViolation`). Alternative if the implicit-target design (docstring lines 226-229) is the intended one: correct lines 204-208 and pin "allowlist-as-authority" with a test instead — but for RESTRICTED-tier clinical source material, fail-closed is the safer reading of design §17.2 ("策略不允许时 fail closed"). **Decision point for Codex — see Q2.**

**F2 — P3 — dangling RESERVED shell: docstring promises a transition the code never performs, and no API can dispose the shell afterward.**
`ReservationCoordinator.reserve_or_reuse` docstring (`reservations.py:217-219`): "RESERVED → a crash interrupted a persist-first dispatch. Transition the dangling shell to UNKNOWN_OUTCOME and fail closed." Executed counterexample: persist a RESERVED shell (crash between `reserve` and preflight), then call `reserve_or_reuse` from a second coordinator → raises `UnknownOutcomeConflictError` (fail-closed observable is correct) but the shell **remains `reserved`** (A2). Consequences verified:
- `recover_unknown` on the shell raises `RepositoryStateTransitionError` (RESERVED→COMPLETED not a legal edge, A3);
- `retry_explicit` succeeds (attempt 2 dispatched and completed) but **leaves the shell `reserved` forever** (A4/A5); it stays in `find_unresolved` permanently (A6, I2: `['reserved']`);
- the repo state machine itself permits `RESERVED→FAILED` (`memory.py:956-959`, probe: legal at repo layer), yet no coordinator API uses it.
So the recovery loop ("发现→处置") has a hole for exactly the crash window persist-first is designed to create: discoverable via `find_unresolved`, but undismissable. Minimal repair options: (a) implement the documented transition — on observing a RESERVED existing row in `reserve_or_reuse`, `transition(→UNKNOWN_OUTCOME, error_code="dispatch_never_proven", ...)` before raising; note the repo currently disallows RESERVED→UNKNOWN, so option (a) also needs that edge; or (b) add a `fail_closed_reserved` disposition using the existing RESERVED→FAILED edge. Either way the docstring and code must agree, and a pinned test must assert the shell's post-disposition status. **Decision point for Codex — see Q1.**

**F3 — P4 — recovery session guard asymmetric: RUNNING→COMPLETED accepts a different provider session; UNKNOWN→COMPLETED rejects it.** Executed: a crash-window RUNNING row reconciled with `provider_session_id="sess:DIFFERENT"` completes (G1), while the same payload against an UNKNOWN row raises (B1). Both behaviors are defensible (receipt session supersedes the harness-minted session on first completion; UNKNOWN locks to the dispatched session), but the asymmetry is undocumented and untested. Fix: document in `transition`'s docstring or unify; one regression test either way.

**F4 — P4 — cross-coordinator concurrent duplicate retry fails closed instead of returning the winner's row.** Single-coordinator duplicates are idempotent (pinned); two distinct `ReservationCoordinator` instances racing the same decision produce one dispatch + one `UnknownOutcomeConflictError` to the loser (H1: `results=1 errors=['UnknownOutcomeConflictError'] dispatches=1`). Fail-closed is safe and the loser converges on a subsequent call (I3), but the test docstring "the loser observes the winner's outcome" holds only for one coordinator instance because `_retry_lock` is per-instance (`reservations.py:191`). Fix: state the single-instance serialization contract in the class docstring, or key the lock in the repository.

**F5 — P4/informational — after an explicit retry resolves the lineage, `reserve_or_reuse` on the ORIGINAL idempotency key stays blocked forever** (I1: `UnknownOutcomeConflictError`), because attempt 1 is immutable UNKNOWN by design. Probably correct for Task 1.6 (reuse is per-key, lineage-level resolution is Task 1.8/1.9 territory), but the LangGraph layer must never re-enter the node with the original key after an explicit retry — flag for the integration tasks.

**F6 — informational —** payloads whose keys are all `_`-prefixed hash equal to the empty payload (G7, by-design metadata stripping); `retry_explicit` allocation loop is bounded at 32 iterations (`reservations.py:321`, `RuntimeError` on non-convergence) — fine for realistic concurrency, noted for the record.

### Corrected probe artifact (self-audit)
One earlier probe (H2 "replay of in-flight decision returned") was a bug in my own probe (wrong idempotency-key variable → lookup missed the seeded row). Instrumented rerun with the exact decision key: `find_by_logical_call(decision_key)` returns the RUNNING row and `retry_explicit` raises `UnknownOutcomeConflictError` — correct fail-closed behavior. Recorded here so Codex's reproduction does not chase a phantom.

## Evidence And Assumptions

**Evidence (all executed this pass):**
- 107/107 named-suite pass with per-file split 35/72, matching the loop-log anchors in the conference context.
- Frozen plan hash verified: `shasum -a 256` → `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`.
- Probe matrix A/B/C/D/G/H/I (in-memory, deterministic, `datetime(2026,1,1,tzinfo=utc)` fixtures, fake transports only) — results quoted inline above.
- Source anchors: `reservations.py:197-256` (reserve_or_reuse), `:258-284` (recover_unknown), `:286-367` (retry_explicit), `:381-526` (_dispatch_and_persist), `:552-577` (_outcome_for_existing); `idempotency.py:179-305`; `memory.py:852-1107`; `protocol_v3.py:912-964`.

**Assumptions:**
- The in-memory adapter is the acceptance reference implementation (Task 1.8 storage selection is future work); repo-layer semantics here bind the future SQLite/Postgres adapters via the contract suite.
- `provider_session_id` minted by the coordinator (`sess:<reservation_id>`) is the harness-side session identity; provider receipts may carry their own session.
- "No security testing" honored: all probes are functional state-transition/identity probes; no adversarial input, path, or permission testing.
- Python 3.9.6 system interpreter is the intended runner (matches `verify_toolchain_rebuild.py`'s Xcode Python 3.9 environment).

## Risks, Gaps, And Verification Needs

- **Highest-impact defect:** F1. It is the only finding that weakens a stated acceptance criterion (criterion 4) rather than documentation: RESTRICTED-tier clinical source material can be repackaged for fallback dispatch without any explicit target authorization, contradicting the module's own contract. A downstream adapter written against the docstring will fail; one written against the code will forward restricted content.
- **Recovery-loop hole:** F2. Persist-first is the core Task 1.6 discipline, and its canonical crash artifact (RESERVED shell) currently has no disposition path; `find_unresolved` will report it on every restart until manually edited — which the closed state machine deliberately makes hard.
- **Test-suite blind spots to pin regardless of disposition decisions:** (1) RESTRICTED-no-target; (2) dangling-RESERVED lifecycle end-to-end (observe → dispose → absent from `find_unresolved`); (3) RUNNING-vs-UNKNOWN session-guard asymmetry; (4) cross-coordinator duplicate-retry contract. All four are deterministic, in-memory, and cheap.
- **Not verified (out of scope):** real harness adapters, LangGraph wiring, non-memory repositories, lease/heartbeat behavior, and anything in Tasks 1.7+.
- **Risk if findings are waived:** F1 waived → silent policy contradiction frozen into Phase 1 acceptance; F2 waived → operators get an undismissable recovery alarm class.

**Bounded questions for Codex:**
1. **Q1 (blocks F2 disposition):** Is the RESERVED-shell transition promised by `reserve_or_reuse`'s docstring a Task 1.6 requirement? Safe provisional path: implement it (RESERVED→UNKNOWN with a stable error code, or RESERVED→FAILED via the existing legal edge) + one pinned test; if deferred to Task 1.8/1.9, correct the docstring now and record the orphan lifecycle as an accepted limitation. Either way doc and code must match before READY.
2. **Q2 (blocks F1 disposition):** For RESTRICTED content with non-empty allowlists and **no** explicit target, is the required behavior fail-closed (docstring lines 204-208; my recommendation, matches design §17.2 fail-closed stance) or implicit-first-allowlist-target (docstring lines 226-229)? One sentence from Codex selects the 6-line fix vs. the docstring correction; both are trivially testable.
3. **Q3 (closure rule):** The prompt's "no P0-P4 remains" conflicts with treating F3-F5 as informational. Does Codex accept reclassifying F3-F5 as documented informational items (leaving only F1/F2 as closure blockers), or does it want pinned tests for all six?

## Recommended Next Step

Codex reproduces F1 and F2 exactly as written (both are 3-line executable counterexamples against the current filesystem), chooses the disposition for Q1/Q2, applies the minimal repairs above (estimated ≤ 30 lines total including tests), reruns only `test_execution_reservations.py` + `test_repository_contract.py`, then re-requests this session for a recheck pass. If Codex waives F3-F5 as informational with docstring corrections, the recheck can return READY after the two P3 fixes verify. No other participant output was consulted; this pass is independently reproducible from the probe descriptions above.
