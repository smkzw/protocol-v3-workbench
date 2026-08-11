# Execution Output: mw_protocol_v3_phase2_task21_20260812 - worker_01 (same-session repair pass)

## Boundary And Context Check

- Role: first-line executor `worker_01`, task `mw_protocol_v3_phase2_task21_20260812`; effective route `opencode-go/deepseek-v4-flash` treated as authoritative per session override.
- Initial read set honored: `AGENTS.md`, `context/mw_protocol_v3_phase2_task21_20260812_execution_context.md`, `plans/codex_execution_mw_protocol_v3_phase2_task21_20260812.md`, `context/mw_protocol_v3_phase2_task21_20260812_context.md`, frozen plan Task 2.1 section (`.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md:838-983`), accepted Phase 1 contracts (`packages/contracts/workbench_contracts/protocol_v3.py`), design doc gate/owner vocabulary, storage PoC decision, word_receipt error-style convention, and `runtime/idempotency.py` hashing discipline — all read-only evidence.
- Write ownership respected: only `pocs/protocol_v3/orchestrator/__init__.py` and `pocs/protocol_v3/orchestrator/fakes.py` modified (both owned by worker 01). `cases/__init__.py` had no defect and was left untouched. No tests created; no case definition, product source, medical-monitoring, service, database, or security files touched. No packages installed; only stdlib + already-pinned Pydantic used.
- Repair pass constraints followed: four Codex counterexamples addressed exactly; no route/provider change, no ownership change.

## Work Performed

1. **Defect 1 — `CC_SCHEMA_DUPLICATE` never fired** (`__init__.py`): `_assert_closed_vocabulary()` previously built `schema_names = list(self._schema_names())` where `_schema_names()` returned a `frozenset`, deduplicating before the check. Rewrote to read the raw `self.schemas` sequence (`raw_schema_names = [schema.name for schema in self.schemas]`), check duplicates on the list, then derive the frozenset for membership tests. Stable error code `CC_SCHEMA_DUPLICATE` unchanged.
2. **Defect 2 — `FakeContractError` claimed but did not inherit `CaseContractError`** (`fakes.py`): was `class FakeContractError(ValueError)` with a duplicated `__init__`. Now `class FakeContractError(CaseContractError)` with no own `__init__`; `code`/`path`/`message` and the `"<code> at <path>: <message>"` formatting come from the base class. Import list gained `CaseContractError`.
3. **Defect 3 — duplicate `root_inputs` now fails closed** (`__init__.py`): added uniqueness check on the raw `root_inputs` sequence with new stable code `CC_ROOT_INPUT_DUPLICATE`, placed in `_assert_closed_vocabulary()`.
4. **Defect 4 — duplicate `InjectionKind` declarations now fail closed** (`__init__.py`): `_assert_injections()` counts the raw declared list per kind and raises `CC_INJECTION_KIND_DUPLICATE` before the existing `CC_INJECTION_KIND_MISSING` check. Each case now has exactly one definition per injection kind.
5. Docstrings updated for the new rejection semantics (`CaseGraph` constructor contract; `InjectionKind` exactly-once rule).

## Artifacts And Evidence

Changed files (only worker-01-owned paths):
- `pocs/protocol_v3/orchestrator/__init__.py` — raw-sequence duplicate checks for schemas and root inputs; injection-kind duplicate check; docstring updates.
- `pocs/protocol_v3/orchestrator/fakes.py` — `FakeContractError(CaseContractError)` true inheritance.

Evidence (all observed in this session):
- Compile: `python3 -m py_compile` (3.9.6, pydantic 2.13.3) and `/opt/homebrew/bin/python3.12 -m py_compile` (3.12.13, pydantic 2.13.4) on all three owned files → PASS both.
- Import smoke on both interpreters: `FakeContractError.__mro__[1] is CaseContractError` → True; `orchestrator`, `cases`, `fakes` import cleanly.
- Four counterexamples (each rejects):
  - duplicate `SchemaDecl.name` → `CC_SCHEMA_DUPLICATE`
  - duplicate `root_inputs` → `CC_ROOT_INPUT_DUPLICATE`
  - two `kill_before` `InjectionPoint`s → `CC_INJECTION_KIND_DUPLICATE`
  - `FakeContractError` is a genuine `CaseContractError`; fields `code="FK_TEST"`, `path="path/x"`, `message="message y"`, `str(err) == "FK_TEST at path/x: message y"` → all True
- Regression (all pass): positive graph construction; 64-hex material SHA-256 bound to `case_id/project_id/branch_id/schema_version/graph_version`; hash stable across shuffled equivalent construction; frozen-model mutation rejected; mutable nested dict/list → `CC_INPUT_MUTABLE`; `freeze_input` deep-immutable containers locked; same-binding artifact write OK, cross-branch write and `assert_case_graph_binding` mismatch → `CC_BINDING_MISMATCH`; artifact/decision/reservation idempotency by logical key (conflicts → `FK_IDEMPOTENCY_CONFLICT`); concurrent claim → `FK_CONCURRENT_DECISION`; unknown-outcome resume → `FK_UNKNOWN_OUTCOME`; deterministic IDs across two identical `FakeRuntime` instances; branch-namespaced IDs differ.

## Commands And Observations

- `python3 -m py_compile pocs/protocol_v3/orchestrator/{__init__.py,fakes.py,cases/__init__.py}` and same under `/opt/homebrew/bin/python3.12` → both OK.
- Two import smoke commands (one per interpreter) → OK, `FakeContractError.__mro__[1]` shows `CaseContractError`.
- In-kernel verification suite (no files written): positive/hash-stability/immutability/isolation/idempotency + four counterexamples; one harness fix was required mid-run — the first schema-duplicate probe used node id `"n1"` which violates `StableId` min_length=3, and one isolation probe passed a `branch_main` graph to a `branch_feature_x` store (correctly rejected by `CC_BINDING_MISMATCH`). Both were probe-construction errors, not product defects; corrected probes re-ran green.
- No blockers observed; no environment gap.

## Blockers Or Missing Environment

None. Both runtimes available and sufficient for pure import/compile/inline checks. Full `pytest` runs were not executed per worker-01 boundary (the integrated `test_case_contracts.py` is owned by worker 03 and does not exist yet).

## Rerun Requests Or Next Step

- No rerun requested; deliverable complete and accepted evidence is above.
- Next step for Codex: shared-contract review of the repaired vocabulary, then dispatch Worker 02 (`cases/eligibility.py`, `cases/objective_estimand_endpoint.py`) against the stable error codes (`CC_SCHEMA_DUPLICATE`, `CC_ROOT_INPUT_DUPLICATE`, `CC_INJECTION_KIND_DUPLICATE`, `CC_INJECTION_KIND_MISSING`, …) — the registry in `cases/__init__.py` is ready to consume.
