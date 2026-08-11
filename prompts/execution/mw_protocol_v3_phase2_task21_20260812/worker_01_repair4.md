# Worker 01 同会话验收反例修复

Hard boundaries:
- Work only inside the current workspace root (`.`).
- Initial read set: `AGENTS.md`, Task 2.1 execution context/plan, `pocs/protocol_v3/orchestrator/__init__.py`, `pocs/protocol_v3/orchestrator/fakes.py`, and the three case modules read-only.
- Exact write ownership: only `pocs/protocol_v3/orchestrator/__init__.py` and `pocs/protocol_v3/orchestrator/fakes.py`.
- Do not edit case modules/tests, product source, medical-monitoring, services, databases or security files. Install nothing; start no service.
- Runner-managed report path: `runs/execution/mw_protocol_v3_phase2_task21_20260812/worker_01_repair4.md`. Never write it via tools.

Fresh verifier Qwen found and Codex independently reproduced two shared-contract defects. Continue the original Worker 01 session; do not change route or scope.

## Required repair

1. `CaseGraph._assert_edges_and_acyclicity()` counts indegree by distinct sources but decrements per typed edge. A DATA+GATE pair can release a target twice and hide a real cycle. Replace the validator's Kahn loop with distinct-source/distinct-target bookkeeping, preferably a shared private deterministic Kahn core used by both validation and `topological_order()` so they cannot drift again. Cyclic construction must raise stable `CC_CYCLE`.
2. `topological_order()` must fail closed with `CC_CYCLE` if a malformed/bypassed graph cannot produce all nodes; never return a partial order.
3. Direct construction of `ArtifactRef(payload={"x":[1]})` and `DecisionRecord(value={"x":[1]})` currently accepts mutable nested state, contradicting immutable-artifact/read contracts. Add model validation that calls the established deep-immutability guard and rejects mutable nested payload/value. Do not silently freeze caller input; callers may explicitly use `freeze_input`. Preserve store/board happy paths.

## Proof required

- Real eligibility back-edge `finalize_eligibility_criteria -> eligibility_decision_lock`, with matching dependency and existing lock->finalize edge, rejects `CC_CYCLE` despite parallel DATA/GATE edges.
- A minimal three-node parallel-edge hidden cycle rejects `CC_CYCLE`; acyclic parallel-edge graph remains valid and topologically ordered.
- `topological_order()` on a deliberately unvalidated malformed cyclic instance fails `CC_CYCLE`, not partial output.
- Direct mutable `ArtifactRef` and `DecisionRecord` reject `CC_INPUT_MUTABLE`; explicitly frozen equivalents pass and remain non-mutable.
- All three current graph hashes remain unchanged; prior copy validation, idempotency, binding, unknown-node/schema, terminal-state and helper fixes remain green.

Return a compact report with exact changes, error codes, counterexamples, hash impact and residual issues.
