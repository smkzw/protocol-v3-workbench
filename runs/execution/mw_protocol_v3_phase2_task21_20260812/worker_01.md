# Execution Output: mw_protocol_v3_phase2_task21_20260812 - worker_01

## Boundary And Context Check

Worked only inside the workspace root. Wrote exactly the three assigned files; created no tests, no case files, no sibling artifacts. No product module imported (verified: importing the package loads zero `app`/`main` modules).

Read (all read-only): `AGENTS.md`, execution context, Codex plan, full task context, frozen plan Task 2.1 section (`.hermes/plans/…md:838-983`), accepted contracts `packages/contracts/workbench_contracts/protocol_v3.py` (aliases, `ProtocolV3Model.material_sha256`, `NodeExecutionContract`/`ExecutionReservation`/`ReservationStatus`/`WorkflowRun`/`SkillDefinition.agent_role`/`SideEffectKind`), design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md` (Gates D1/Q1, Agent②/④/⑤ boundaries, unknown-outcome no-auto-redispatch), PoC conventions from `pocs/protocol_v3/storage/decision.md` and `word_receipt/contract.py`, runtime `idempotency.py` + `agent5/run_manifest.py` (logical-key/hash discipline). No scheduler, storage, provider or product write touched.

## Work Performed

**`pocs/protocol_v3/orchestrator/__init__.py`** — closed immutable vocabulary, `CASE_CONTRACT_SCHEMA_VERSION = "mw_protocol_v3_orchestrator_case_contract_v1"`:
- Closed enums: `CaseId` (3 cases), `GateKind` (D1, Q1, `user_decision`), `OwnerRole` (mirrors product `agent_role` literals + `user` + `system`), `NodeKind` (work/check/calculation/decision), `EdgeKind` (data/decision/gate), `SideEffectKind` (product names + `decision_record`), `InjectionKind` (all five), `FailurePolicy` (fail_closed/bounded_retry).
- Immutable frozen models (`extra="forbid"`): `SchemaDecl`, `NodeContract` (node_id, kind, owner, gate, typed input schemas, output schema, depends_on, side-effect key template + kind, failure policy/attempts), `Edge`, `InjectionPoint` (kind, target, logical_key, expectation, `old_graph_version` for migration), `CaseGraph` (case_id, project_id, branch_id, schema_version, graph_version, description, schemas, root_inputs, nodes, edges, injections).
- Fail-closed at construction: duplicate/unknown nodes, unknown/self/duplicate edges, edges↔`depends_on` exact-match, cycles (Kahn), unknown output/input schema, uncovered/dangling inputs, all-five injection kinds per case, unknown injection targets, migration-only `old_graph_version`, side-effect key discipline, failure-policy attempts, invalid Gate/Owner/CaseId/schema_version. `revalidate_instances="always"` closes the `model_copy` smuggling bypass (found in verification).
- Deterministic material SHA-256 bound to identity + sorted structure; models carry no timestamps/run-ids/counters, so runtime/scheduler-private state cannot enter the hash and equivalent construction (shuffled order) hashes identically.
- Helpers: `freeze_input`/`assert_deep_immutable` (mutable nested input → `CC_INPUT_MUTABLE`), `assert_case_graph_binding` (`CC_BINDING_MISMATCH`), `canonical_json`, `topological_order`, `node_dependencies`. Typed `CaseContractError(code, path, message)`; construction raises `pydantic.ValidationError` wrapping it (repo convention).

**`pocs/protocol_v3/orchestrator/fakes.py`** — deterministic, project/branch-bound, I/O-free fakes: `FakeClock` (fixed epoch + step), `FakeIdFactory` (namespace+project+branch+kind+key digest), `FakeArtifactStore` (idempotent by logical key, conflict on divergence, rejects mutable payloads, frozen refs), `FakeDecisionBoard` (idempotent records + `claim`/pending representing concurrent-decision → `FK_CONCURRENT_DECISION`), `FakeReservationLedger` (mirrors product reservation semantics; duplicate resume idempotent; `unknown_outcome` resume → `FK_UNKNOWN_OUTCOME` fail-closed; terminal transitions validated), `FakeRuntime` bundle. `FakeContractError` subclasses `CaseContractError`.

**`pocs/protocol_v3/orchestrator/cases/__init__.py`** — re-exports vocabulary (single import surface), immutable `CASE_MODULES` registry (CaseId → module name), lazy `load_case`/`iter_case_graphs` (case modules must export `GRAPH: CaseGraph` with matching `case_id`), `case_graph()` validated builder, `assert_registry_closed`.

## Artifacts And Evidence

- `pocs/protocol_v3/orchestrator/__init__.py` (35.5 KB, 28-name `__all__`)
- `pocs/protocol_v3/orchestrator/fakes.py` (23.4 KB, 12-name `__all__`)
- `pocs/protocol_v3/orchestrator/cases/__init__.py` (5.0 KB)

Verification (inline pure checks, no test files created): **42/42 assertions pass** on Python 3.9.6 / pydantic 2.13.3, covering hash order-stability/branch-case sensitivity, topological validity, all-five injection kinds, 20 fail-closed rejections (incl. smuggled Gate/Owner via `model_copy`), binding mismatch, artifact idempotency + conflict, mutable-payload rejection, payload mutation rejection, decision idempotency/concurrent-claim/record-over-claim, reservation idempotency/resume-completed/unknown-outcome/failed/terminal-transition, cross-instance determinism. Scaffolding checks: `case_graph()` builder, `CC_CASE_REGISTRY_OPEN` on open registry, `ModuleNotFoundError` from `iter_case_graphs` (expected until worker 02/03 modules exist), nested-mutable-in-tuple rejection. Both Python 3.9.6 and 3.12.13 (pydantic 2.13.4) compile and import all three files. `__pycache__` cleaned.

Defects found and fixed during verification: (1) `material_metadata_fields` was an instance field (would leak into material serialization) → `ClassVar`; (2) fakes silently froze mutable payloads instead of rejecting per required behavior → `put`/`record` now fail closed `CC_INPUT_MUTABLE`; (3) `model_copy` could smuggle invalid Gate/Owner into a graph → `revalidate_instances="always"`.

## Commands And Observations

| Command | Observation |
|---|---|
| `python3 -m py_compile …` + `python3.12 -m py_compile …` | Both runtimes OK (twice: after initial write, after edits) |
| `python3 -c "import pocs.protocol_v3.orchestrator[.fakes][.cases]"` | Imports OK; product modules loaded: none; namespace package works from repo root |
| `python3 -c "…"` inline check suite (eval kernel, reset) | 42/42 PASS; scaffolding checks PASS |
| `grep 'import (app\|services\|medical_writing\|frontend)'` on orchestrator dir | No matches |

## Blockers Or Missing Environment

None. Remaining-by-design gaps to state explicitly: `iter_case_graphs()`/`load_case()` raise `ModuleNotFoundError` until worker 02/03 write `eligibility.py`, `objective_estimand_endpoint.py`, `sample_size.py`; the all-five-injections-per-case requirement means each case must declare all five `InjectionKind` points. `pytest` was not run (no test files allowed for this worker).

## Rerun Requests Or Next Step

Ready for Codex shared-contract review, then worker 02. Contract for workers 02/03: each case module exports `GRAPH: CaseGraph` with `case_id` matching the `CASE_MODULES` registry key, declares `schemas`/`root_inputs`, nodes with `depends_on` exactly matching edge sources, and injection points for all five kinds (migration point graph-level with `old_graph_version`; others name a target node). Suggested graph_version pattern: `mw_protocol_v3_case_<case>_graph_v1`. Worker 03's integrated test can assert registry closure via `cases.assert_registry_closed(cases.iter_case_graphs())` and reuse the fakes (`FakeRuntime`) for the kill/duplicate/concurrent/migration matrix.
