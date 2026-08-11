# Task 1.7 Worker 02 Same-Session Repair 01

Codex final-authority review found additional deterministic P1 contract gaps. Resume this same session and repair the common Harness boundary. This is one consolidated same-session recovery pass; do not start services or make any live model/OCR/translation call.

Hard boundaries:
- Work only inside the runner-provided workspace root `.`.
- Write only `services/api/app/protocol_workflow/runtime/harness.py`, `runtime/adapters/direct_api.py`, `runtime/adapters/local_omlx.py`, adapter protocol/exports needed for coherence, and `tests/protocol_v3/test_harness_policy.py`.
- Do not modify canonical contracts, registries, global/shared gate, frontend, legacy code, medical-monitoring or production paths.
- Runner-managed report path: `runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_02_recovery_01.md`. Never create/edit this report with tools; return the complete report for the runner.

Read these files only as the initial set:
- `AGENTS.md`
- `context/mw_protocol_v3_phase1_task17_20260811_context.md`
- `services/api/app/protocol_workflow/registries/loader.py`
- `services/api/app/protocol_workflow/runtime/harness.py`
- `services/api/app/protocol_workflow/runtime/adapters/direct_api.py`
- `services/api/app/protocol_workflow/runtime/adapters/local_omlx.py`
- `tests/protocol_v3/test_harness_policy.py`

The initial set may be expanded only to the frozen Task 1.7 section, canonical `NodeExecutionContract`/`SkillDefinition`, and Task 1.6 reservation/idempotency code directly needed for this repair. Record additions.

Confirmed gaps and required repair:

1. **Registry-bound role policy, not a caller boolean.** `build_request()` currently accepts `role_allows_thinking: bool`, so a caller can mark OCR/translation as thinking-capable. Require the immutable `RoleEntry` from the loaded registry and verify exact `role_id`, role kind, target provider/model/harness, allowed effort and thinking discipline. Remove the trustable boolean escape hatch.

2. **Full node/skill/artifact binding.** Fail closed unless `node_contract.skill_definition_id == skill.skill_definition_id`, node input/output schema refs equal the Skill refs, and the exact passed artifact hash tuple equals `node_contract.input_artifact_hashes` (no substitution, omission, duplicate or reordering ambiguity). Always enforce contract tools/paths as subsets even when the Skill set is empty. Carry `prompt_sha256` and `provider_session_id` into the typed Harness request as control metadata.

3. **Selected region and sensitivity.** Require an explicit selected target region. It must be in both the node allowlist and the Role target-profile regions. Treat the Role target-profile sensitivity tier as the maximum permitted tier and reject a more sensitive request. Preserve provider allowlist validation.

4. **Logical artifact refs only.** `ArtifactRef.ref` must be a closed logical artifact URI/ID, not an absolute path, home path, traversal, control string or arbitrary filesystem path. Add positive/negative tests.

5. **Unified workload gate for both OCR and translation.** The registered Paddle OCR harness is Direct API, so enforcing gate consistency only in `LocalOmlxAdapter` is bypassable. Move the workload policy to the common Harness boundary: for role kinds `ocr` and `translation`, require injected read-only effective model selection plus a real injected lease context factory; compare declared model to the effective model before probe/dispatch, fail closed on missing/mismatch, and hold the correct `ocr`/`translation` lease around the single transport call. This must apply to Paddle Direct API and local oMLX equally. No fake/no-op lease default. Current `GLM-OCR-bf16` vs Paddle remains a deterministic pre-dispatch failure; translation succeeds only when effective Hy-MT2 identity matches. Do not edit the shared gate.

6. **Mandatory real probe injection.** Direct API and local oMLX constructors must reject missing `probe_fn`; never default to `lambda: True`. Update the common adapter protocol so every adapter exposes provider/model and a pure preflight. Identity/provider/model/gate/preflight failures occur before probe and return stable policy errors with `dispatched=False` and zero transport calls.

7. **Same-session path through the Harness.** Add `provider_session_id` to `HarnessDispatchRequest` from `NodeExecutionContract`; update `TransportAdapter.dispatch(request, *, session_id=None)` and make `HarnessDispatcher` forward exactly that value. Do not use `idempotency_key` as a session id. Direct/local adapters may explicitly reject or deterministically ignore an unsupported session only in preflight, but the common dispatcher must not force callers to bypass probe/policy for recovery.

8. **Typed output receipt.** Extend `DispatchReceipt` with a logical `output_artifact_ref` and `output_schema_ref`; validate both and require the adapter receipt schema to equal the request's declared output schema. Hash alone is not typed artifact proof. Update deterministic fakes/tests.

9. **Accurate dispatched semantics.** Preflight/policy/probe/gate/lease-acquisition failures must report `dispatched=False`; set `dispatched=True` only when entering the injected physical transport boundary. Use a small typed adapter outcome/error signal if needed rather than guessing from exception type.

10. Preserve fallback rebuild, credential-free payload, no repository handle, no `max_turns=1`, no security testing, no monitoring changes. Do not broaden to Task 1.8.

Run the focused Task 1.7 pair, the full Protocol v3 suite, Ruff/format and compile checks. Return exact counts, changed paths, remaining interface work for worker 3, and uncertainty. Do not claim final READY.

Output schema:
1. `# Execution Output: mw_protocol_v3_phase1_task17_20260811 - worker_02_recovery_01`
2. `## Boundary And Context Check`
3. `## Work Performed`
4. `## Artifacts And Evidence`
5. `## Commands And Observations`
6. `## Blockers Or Missing Environment`
7. `## Rerun Requests Or Next Step`
