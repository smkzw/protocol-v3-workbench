Delegated mode. Same-session bounded repair, not a new independent reviewer.
Agent/provider/model: zcode / zcode / GLM-5.3-Flash, effort max.

Hard boundaries:
- Existing execution-context boundaries remain. Edit only the nine new graph,
  facade and test files originally allowed; evidence only under
  runs/mw_protocol_v3_2r1_typed_facade_20260905/. No existing storage/contracts/
  runtime-reservations/main/legacy/frontend edits, no historical evidence rewrite.
- No services, real models/network/OCR/translation, install, live/monitoring,
  global configuration, cleanup or recursive delegation. Tests use fresh temporary
  SQLite and kill only their own synthetic children. Use apply_patch for edits.
- Runner-managed report path: `runs/execution/mw_protocol_v3_2r1_typed_facade_20260905/worker_01_followup.md`.
  Never write this report with tools; return the report for runner persistence.

Initial read set:
- `context/mw_protocol_v3_2r1_typed_facade_20260905_execution_context.md`
- `reviews/mw_protocol_v3_2r1_codex_findings_20260905.md`
- `runs/conference/mw_protocol_v3_2r1_fresh_20260905/general_single_object.md`

Task:
Your first pass was not accepted. Repair the concrete functional defects in one
coherent minimal pass, red-first. Do not argue that existing green tests prove
these paths: Codex four probes actually fail, reviewer independently reproduced
double decision commit and unusable receipt recovery.

Required fixes and Codex decisions:
1. Decision and start-run checks must be atomic with append in the existing UoW
   transaction (no new schema/platform). Conflicting decisions return typed
   GraphDecisionConflictError, identical decisions reuse exactly once. Concurrent
   start must not append two starts or silently rebind roots; sequential changed
   root facts must raise an explicit typed binding error. Use existing ports.
2. Replace sequential subprocess.run race harnesses in BOTH product recovery
   tests and THREE-case facade tests with actually overlapping Popen lifetimes.
   Require rendezvous success; no timeout-then-proceed. No broad exception counted
   as semantic conflict. Add deterministic stale-precheck interleaving as well;
   unforced races alone can miss the bug. Keep prior evidence, no xfail.
3. Receipt recovery is intended to restore USABLE content. Accept genuine output
   payload plus declared hash, verify equality, persist the same typed result and
   contract/input provenance, converge the existing reservation with no dispatch.
   Preserve call compatibility where possible, but hash-only receipt is NOT
   completed usable content. It must remain recoverable with an explicit blocked
   reason, never certify completion or wedge in an untyped exception. Do not
   auto-retry unknown work. Test downstream and terminal-node receipt recovery.
4. Decision output_sha256 must hash the exact persisted output consumed downstream;
   retain a separate value hash for decision dedup if needed. Add regression.
5. If all node results are durable but run completion event was lost, reopen/advance
   must append completion without dispatch. Add bounded + real own-process death
   test of this exact window, and the result-event-before-reservation-terminal
   window. run_to_completion must not busy-loop forever on no-progress state.
6. Translate contended reservation errors into graph-typed retriable/wait status,
   without converting unknown into permission to dispatch. Verify actual overlap,
   single physical dispatch and eventual convergence.
7. QC evidence: human actor vs writer PID is NOT Agent4 fresh-context proof.
   Demonstrate independent injected QC invocation/context over declared inputs,
   separate from writer-private context and user confirmation. Use minimal existing
   typed contracts/service boundary, not a new agent framework. Explicitly label
   this offline orchestration evidence, not actual-model context/clinical acceptance.
   If existing allowed interfaces cannot support it, report exact minimal need;
   do not silently scope away the 2R acceptance requirement.

Repros to read/run (read-only originals; port equivalent tests to allowed suite):
- runs/mw_protocol_v3_2r1_typed_facade_20260905/test_codex_concurrency_probe.py
  (PYTHONPATH additionally tests/protocol_v3), codex_four_probes_red.xml.
- runs/mw_protocol_v3_2r1_fresh_20260905/{cas_proof,receipt_zombie_repro,true_race_driver}.py.
Do not modify their original evidence. A changed transaction boundary may require
porting the interleaving hook to the same semantic precheck window; retain original
failing proof and explain the regression's new hook rather than relaxing assertion.

Environment correction: existing /Users/smkzw/.local/bin/node v22.22.3 matches
manifest, bundled Node does not. Tests use env -i
PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false and a fresh explicit WORKBENCH_RUNTIME_DIR.
Python runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python.
pytest -q -p no:cacheprovider --tb=short with NEW XML paths; run full
tests/protocol_v3 + pocs/protocol_v3/orchestrator/tests after focused checks.
Prior corrected baseline1649passed66.64s excludes Codex four failing probes.

Output schema:
# Execution Output: mw_protocol_v3_2r1_typed_facade_20260905 - worker_01_followup
## Boundary Check
## Repairs And Exact Evidence
## Verification Results
## Remaining Limitations
## Next Step

No task closure. Return concrete commands/results and per-finding disposition;
Codex and the existing fresh reviewer will verify the changed artifact.
