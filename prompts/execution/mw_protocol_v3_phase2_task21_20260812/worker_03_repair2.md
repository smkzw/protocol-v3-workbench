# Worker 03 同会话验收回归补强

Hard boundaries:
- Work only inside the current workspace root (`.`).
- Initial read set: `AGENTS.md`, Task 2.1 execution context/plan, current shared contracts/fakes, three case modules, and `pocs/protocol_v3/orchestrator/tests/test_case_contracts.py`.
- Exact write ownership: only `pocs/protocol_v3/orchestrator/tests/test_case_contracts.py`.
- Do not edit shared files/cases, product source, medical-monitoring, services, databases or security files. Install nothing; start no service.
- Runner-managed report path: `runs/execution/mw_protocol_v3_phase2_task21_20260812/worker_03_repair2.md`. Never write it via tools.

Continue the original Worker 03 session after Worker 01 repair4. Add focused regressions for the independently reproduced acceptance defects:

1. Minimal three-node cycle hidden behind a DATA+GATE parallel pair must raise `CC_CYCLE`.
2. Real eligibility graph mutation adding `finalize_eligibility_criteria -> eligibility_decision_lock` with matching `depends_on` must raise `CC_CYCLE`.
3. A deliberately unvalidated cyclic `CaseGraph` instance passed to `topological_order()` must fail `CC_CYCLE`, never return a partial order.
4. Direct `ArtifactRef` and `DecisionRecord` construction with mutable nested payload/value must reject `CC_INPUT_MUTABLE`; `freeze_input` equivalents must construct and reject later mutation.

Keep existing 71 tests and pinned graph hashes. Run focused tests, compile, the existing Protocol v3 functional regression without security tests, and protected-path diff. Return exact counts/results and residual issues; do not broaden scope.
