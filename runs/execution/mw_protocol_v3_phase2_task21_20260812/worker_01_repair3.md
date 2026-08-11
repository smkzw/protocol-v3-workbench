# Execution Output: mw_protocol_v3_phase2_task21_20260812 - worker_01 (repair3, same-session)

## Boundary And Context Check

- Role: first-line executor `worker_01`; effective route `opencode-go/deepseek-v4-flash` authoritative per session override; no provider/model change attempted.
- Repair3 constraints honored: initial read set limited to `AGENTS.md`, execution context, execution plan, `pocs/protocol_v3/orchestrator/__init__.py`, and the three case modules as read-only fixtures. Exact write ownership respected: **only `pocs/protocol_v3/orchestrator/__init__.py` modified**. Fakes, case definitions, `tests/test_case_contracts.py`, product source, medical-monitoring, services, databases, and security files were not touched. No packages installed; only stdlib + already-pinned Pydantic.
- Both Codex-reproduced helper defects (parallel-edge over-decrement in `topological_order`; duplicate IDs from parallel edges in `node_dependencies`) were fixed at the source; determinism/tie-break and all prior contract semantics preserved.

## Work Performed

1. **Defect 1 — `CaseGraph.topological_order()` prematurely released targets on parallel typed edges** (`__init__.py`): the old Kahn implementation counted indegree by *distinct* upstream nodes (`incoming` as sets of source ids) but decremented per *typed edge* when popping a source — a DATA+GATE pair from the same source to the same target decremented twice, pulling indegree from 2 to 0 before the second upstream node was processed. Replaced the per-edge decrement loop with a precomputed `successors` map (source → distinct targets); each completed source decrements each distinct target exactly once. The `indegree[target] > 0` guard became structurally dead and was removed. `ready` list remains sorted, popped from the front, and re-sorted after each append — node_id deterministic tie-break unchanged.
2. **Defect 2 — `CaseGraph.node_dependencies()` returned duplicate dependency IDs** (`__init__.py`): the old implementation sorted the raw generator of incoming edges, so DATA+GATE parallel edges yielded the same source id twice. Now deduplicates via a set comprehension before sorting, returning deterministic sorted distinct source ids that match the node's declared `depends_on` exactly.
3. Docstring updated on both helpers to state the distinct-source contract.

## Artifacts And Evidence

Changed file (only worker-01-owned):
- `pocs/protocol_v3/orchestrator/__init__.py` — `topological_order()` distinct-target decrement; `node_dependencies()` distinct-source dedup; docstrings.

Evidence (all observed in this session):
- Compile: `python3 -m py_compile` (3.9.6) and `/opt/homebrew/bin/python3.12 -m py_compile` (3.12.13) on `__init__.py` → PASS both.
- In-kernel verification (no files written; all three case modules loaded via `iter_case_graphs()`):
  - Three real graphs: `topological_order()` complete (all nodes, no missing/extra), every edge's source strictly precedes its target, and `node_dependencies(node_id) == tuple(sorted(node.depends_on))` for every node on every graph — all True.
  - Sample-size ordering: `('define_hypothesis_and_targets', 'define_statistical_assumptions', 'derive_sample_size', 'statistical_review', 'sample_size_decision_lock', 'finalize_sample_size')`; `statistical_review` precedes `sample_size_decision_lock` → True.
  - Eligibility order `('draft_eligibility_criteria', 'bind_criterion_evidence', 'cross_criterion_consistency', 'qc_review_criteria', 'eligibility_decision_lock', 'finalize_eligibility_criteria')`; objective order `('define_objectives', 'define_estimand_attributes', 'define_endpoint', 'cross_objective_consistency', 'qc_review_objective_chain', 'objective_chain_decision_lock', 'finalize_objective_chain')`.
  - Parallel-edge repro graph (a_node→b_node DATA+GATE, c_node→b_node DATA): order `('a_node', 'c_node', 'b_node')` — b_node strictly after both upstreams (old code would emit `('a_node', 'b_node', 'c_node')`); `node_dependencies('b_node') == ('a_node', 'c_node')` with no duplicates; deterministic across equivalent construction → all True.
  - Cycle graph → `CC_CYCLE` fail closed at construction; `node_dependencies('ghost_node')` → `CC_NODE_UNKNOWN`; hash stability across shuffled equivalent construction (nodes/edges/injections/schemas/root_inputs all reversed) → identical `material_sha256` → all True.

## Commands And Observations

- `python3 -m py_compile pocs/protocol_v3/orchestrator/__init__.py` and same under `/opt/homebrew/bin/python3.12` → both OK.
- In-kernel verification suite (one cell + one result print cell): all assertions passed on the first run after the edits; no probe corrections were needed this pass.

## Blockers Or Missing Environment

None. Both runtimes available; pure import/compile/inline checks were sufficient per worker-01 boundary. The integrated `tests/test_case_contracts.py` (worker-03-owned) was read-only observed as present in the directory listing but was not executed by this worker — running it belongs to Codex acceptance or a fresh verifier.

## Rerun Requests Or Next Step

- No rerun requested; deliverable complete with acceptance evidence above.
- Next step for Codex: run the worker-03 integrated `tests/test_case_contracts.py` (now present at `pocs/protocol_v3/orchestrator/tests/test_case_contracts.py`) against the repaired helpers for final Task 2.1 acceptance; the helper contract (complete order, edge order, distinct deps matching `depends_on`, deterministic tie-break) is now satisfied on all three real graphs.
