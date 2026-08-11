# Task 1.7 Worker 03 Same-Session Repair 02

Resume the same Worker 03 session. The common Harness has been tightened and the focused pair is now 156 passed / full Protocol v3 826 passed. Adapt only the Codex and OMP CLI adapters to that accepted common interface and close the schema URI-to-local-file defect. No live CLI/model/provider call and no service startup.

Hard boundaries:
- Work only inside the runner-provided workspace root `.`.
- Write only `services/api/app/protocol_workflow/runtime/adapters/codex_app.py`, `runtime/adapters/omp_cli.py`, `runtime/adapters/__init__.py` if exports need coherence, and the Codex/OMP portions of `tests/protocol_v3/test_harness_policy.py`.
- Do not modify common Harness, canonical contracts, registries, shared gate, frontend, legacy code, medical-monitoring or production paths.
- Runner-managed report path: `runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_03_recovery_02.md`. Never create/edit this report with tools; return the complete report for the runner.

Read first:
- `AGENTS.md`
- `context/mw_protocol_v3_phase1_task17_20260811_context.md`
- `runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_02_recovery_02.md`
- `services/api/app/protocol_workflow/runtime/harness.py`
- your two adapter files and their tests

Write failing tests first, then implement the smallest coherent repair:

1. Both adapters must require an explicit non-null `probe_fn`; remove all default `lambda: True` behavior. Implement pure `preflight(request) -> AdapterOutcome` that checks provider/model identity before probe. Missing/malformed constructor dependencies fail closed.

2. Both `dispatch()` methods must accept `session_id=None, lease=None` and construct `DispatchReceipt` from all six explicit physical transport fields only: provider session id, output hash, observed provider, observed model, logical output artifact ref, output schema ref. Do not default or relabel any receipt field. The common Harness will verify runtime identity and schema.

3. Preserve exact same-session behavior already proven: Codex uses `codex exec resume SESSION_ID`; OMP uses `--resume SESSION_ID`; no idempotency key substitution; no `--max-turns=1`; tools remain enabled; OMP uses `-p`, `--auto-approve`, exact thinking effort, and long wait.

4. **Codex schema URI must resolve to a real local JSON Schema file path.** `NodeExecutionContract`/Skill carry refs such as `https://protocol-v3.local/schemas/chapter-draft-output.v1.json`, while `codex --output-schema` accepts a filesystem path. Do not pass the URI to the CLI and do not create schema files in this task. Inject a deterministic schema-path resolver or closed mapping into `CodexAppAdapter`. Preflight must resolve the exact request schema ref to an existing regular local JSON file, reject missing/unmapped/non-file/URI results with stable errors and `dispatched=False`, and command planning must use the resolved local path. Tests must create a temporary schema file and prove both new and resumed plans use that file path; add a negative test proving the URI itself is never emitted as the CLI path. Keep the standalone pure plan builder explicit about accepting a local schema path rather than a schema ref.

5. Update the nine temporary `preflight_missing` expectations introduced by Worker 02 into real success or precise policy/receipt outcomes. Add tests for mandatory probe, preflight provider/model mismatch before probe, six-field receipt enforcement, schema resolver failure before probe, common dispatcher session forwarding, and no duplicate invocation.

Run the focused pair, full `tests/protocol_v3`, Ruff/format on owned files, Python 3.12 compile, direct local `codex exec --help`, `codex exec resume --help`, and `omp --help` syntax evidence only, plus plan-hash and zero medical-monitoring-diff checks. Do not make a real model call and do not claim final READY.

Output schema:
1. `# Execution Output: mw_protocol_v3_phase1_task17_20260811 - worker_03_recovery_02`
2. `## Boundary And Context Check`
3. `## Work Performed`
4. `## Artifacts And Evidence`
5. `## Commands And Observations`
6. `## Blockers Or Missing Environment`
7. `## Rerun Requests Or Next Step`
