# Task 1.7 Worker 02 Same-Session Repair 02

Codex verified recovery 01 with 144 focused tests and 814 full Protocol v3 tests, then found four remaining P1 functional-contract bypasses. Resume the same Worker 02 session for one final consolidated repair. This is not security testing. Do not start services or make live model/OCR/translation calls.

Hard boundaries:
- Work only inside the runner-provided workspace root `.`.
- Write only `services/api/app/protocol_workflow/runtime/harness.py`, `runtime/adapters/direct_api.py`, `runtime/adapters/local_omlx.py`, and `tests/protocol_v3/test_harness_policy.py`.
- Do not modify canonical contracts, registries, Worker 03 adapters, shared gate, frontend, legacy code, medical-monitoring or production paths.
- Runner-managed report path: `runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_02_recovery_02.md`. Never create/edit this report with tools; return the complete report for the runner.

Read first:
- `AGENTS.md`
- `context/mw_protocol_v3_phase1_task17_20260811_context.md`
- `runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_02_recovery_01.md`
- the four owned source/test files above

Write failing tests first, prove each failure, then implement the smallest coherent repair:

1. **Missing preflight must fail closed.** `HarnessDispatcher.dispatch()` currently treats an adapter without `preflight()` as ready. Remove that compatibility bypass. A missing/non-callable preflight or a preflight result that is not `AdapterOutcome` must return a stable pre-dispatch error with `dispatched=False`, zero probe calls and zero transport calls. Worker 03 will add the required method to both CLI adapters afterward.

2. **Do not fabricate runtime receipt fields.** Direct API and local oMLX currently default missing `observed_provider`, `observed_model`, or `output_schema_ref` from registry/request text. Require the physical transport mapping to contain all receipt fields explicitly: `provider_session_id`, `output_sha256`, `observed_provider`, `observed_model`, `output_artifact_ref`, `output_schema_ref`. Missing/blank fields must fail after the single transport boundary with `dispatched=True`; no relabel/default is allowed. Remove the duplicate Direct API dispatch docstring while touching that method.

3. **Observed identity mismatch is not success.** The receipt is runtime authority, so the Harness must compare its explicit observed provider/model with the validated request. A mismatch must return a stable typed failure such as `receipt_identity_mismatch`, retain `dispatched=True`, and never return `success=True`. Add provider and model mismatch tests for direct and gated paths.

4. **A request must prove it passed binding validation.** `HarnessDispatchRequest` is currently directly constructible, so a caller can bypass `build_request()` and its RoleEntry/Skill/artifact/region checks. Close this application-contract bypass without changing the canonical models: make normal construction unavailable and provide a module-private validated construction path used only by `build_request()`, or an equivalently deterministic mechanism. `HarnessDispatcher` must reject any unvalidated/forged request before preflight/probe/transport. Add a test proving direct construction cannot yield a dispatchable request and a test proving the valid builder path still works. Keep the public adapter input type usable for type checking.

Also remove `_null_lease` if it remains unused. Preserve exact artifact/hash/schema binding, selected-region/sensitivity policy, unified workload gate, real lease, same-session forwarding, fallback rebuild, no repository handle, and no `max_turns=1`.

Run:
- focused Task 1.7 pair;
- full `tests/protocol_v3` suite;
- Ruff on owned files;
- Python 3.12 compile checks;
- plan-hash and zero medical-monitoring-diff checks.

Return exact fail-first observations, final counts, changed paths, and remaining Worker 03 interface work. Do not claim final READY.

Output schema:
1. `# Execution Output: mw_protocol_v3_phase1_task17_20260811 - worker_02_recovery_02`
2. `## Boundary And Context Check`
3. `## Work Performed`
4. `## Artifacts And Evidence`
5. `## Commands And Observations`
6. `## Blockers Or Missing Environment`
7. `## Rerun Requests Or Next Step`
