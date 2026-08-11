# Task 1.7 Worker 03 Same-Session Repair 01

Codex final-authority review found deterministic P1 contract defects in your completed adapter work. Resume this same session and repair only your owned files. Do not start a real model/CLI/service call.

Hard boundaries:
- Work only inside the runner-provided workspace root `.`.
- Write only `services/api/app/protocol_workflow/runtime/adapters/codex_app.py`, `services/api/app/protocol_workflow/runtime/adapters/omp_cli.py`, additive CLI adapter exports/docs, and additive CLI portions of `tests/protocol_v3/test_harness_policy.py`.
- Do not modify canonical contracts, registries, shared gate, frontend, legacy code, medical-monitoring or production paths.
- Runner-managed report path: `runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_03_recovery_01.md`. Never create or edit this report with tools; return the complete report in your final response for the runner to persist.

Read these files only as the initial set:
- `AGENTS.md`
- `context/mw_protocol_v3_phase1_task17_20260811_context.md`
- `services/api/app/protocol_workflow/runtime/adapters/codex_app.py`
- `services/api/app/protocol_workflow/runtime/adapters/omp_cli.py`
- `tests/protocol_v3/test_harness_policy.py`

The initial read set does not prohibit the three local help commands or directly dependent Task 1.7 files needed to implement and test this repair. Record every additional source used.

Authoritative local capability evidence must be re-read directly now using the bundled Codex executable identified in the parent context and the local `omp` executable:
- bundled Codex `exec --help`
- bundled Codex `exec resume --help`
- `omp --help`

Confirmed counterexamples to the current implementation:
1. Codex emits JSONL with `--json`, not the nonexistent `--jsonl`.
2. Codex same-session syntax is the `exec resume` subcommand: `codex exec resume [OPTIONS] SESSION_ID`; there is no `--resume` flag on `codex exec`.
3. OMP non-interactive mode is `-p`/`--print`, and automatic tool approval is `--auto-approve`; there is no `--yes` flag.
4. OMP `--thinking` accepts `off|minimal|low|medium|high|xhigh|max|auto`; `on` is invalid. Preserve the exact requested effort (`none` maps to `off`; the supported non-none effort maps to itself) and reject unsupported effort values.
5. Do not use the idempotency key as a provider session id. A new dispatch has no resume token; same-session recovery uses only `NodeExecutionContract.provider_session_id`. Make session identity an explicit nullable input to plan construction/dispatch rather than silently substituting `idempotency_key`.

Required repair:
- Correct `runtime/adapters/codex_app.py`, `runtime/adapters/omp_cli.py`, their exports/docs if needed, and only the additive CLI portions of `tests/protocol_v3/test_harness_policy.py`.
- For Codex, build two closed plan shapes: new `exec` and resumed `exec resume`; both use `--json`, `--output-schema`, explicit model, tools enabled, and no `--max-turns 1`.
- For OMP, use `-p`, `--auto-approve`, explicit provider/model, exact valid thinking value, long `--max-time`, and optional `--resume SESSION_ID`; never `--no-tools`/`--max-turns 1`.
- Add deterministic tests that compare generated flags/subcommand ordering to the observed local help contract and prove the idempotency key is never used as a session id.
- Preserve probe/fallback/minimal-artifact and medical-monitoring boundaries. Do not broaden into Task 1.8 or security testing.
- Run the focused Task 1.7 pair and Ruff/format checks. Return the full execution report schema with exact changed paths, command counts and residual uncertainty. Do not claim final READY.

Output schema:
1. `# Execution Output: mw_protocol_v3_phase1_task17_20260811 - worker_03_recovery_01`
2. `## Boundary And Context Check`
3. `## Work Performed`
4. `## Artifacts And Evidence`
5. `## Commands And Observations`
6. `## Blockers Or Missing Environment`
7. `## Rerun Requests Or Next Step`
